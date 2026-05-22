"""
Agent Runner
------------
Reads agent personas from .md files and skills from .yaml files,
then calls the LLM and logs token usage + latency to Langfuse
via the @observe decorator context.
"""

import os
import re
import time
import yaml
import litellm
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI   # used for Cerebras (OpenAI-compatible API)
from langfuse.decorators import observe, langfuse_context
from dotenv import load_dotenv
from groq import RateLimitError, APIStatusError

# ── LiteLLM setup ─────────────────────────────────────────────────────────────
litellm.drop_params = True   # silently ignore unknown params
_USE_LITELLM = os.getenv("USE_LITELLM", "false").lower() == "true"
_LITELLM_URL = os.getenv("LITELLM_PROXY_URL", "http://localhost:4000")
_LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "bmad-litellm-key-2025")

# ── Model fallback chain ───────────────────────────────────────────────────────
# Tier 1 (primary):  Groq llama-3.3-70b-versatile  — best quality, 100K TPD
# Tier 2 (fallback): Groq llama-3.1-8b-instant     — separate quota, 6K TPM cap
#                    ⚠️  Skipped for large-output agents (developer, reviewer,
#                        mock_tester, qa_engineer) — 8b's 1800 token output cap
#                        produces truncated code. These go straight to Tier 3.
# Tier 3 (final):    Cerebras qwen-3-235b           — free, no daily cap, 8K output
#
# Per-minute rate limits on Groq escalate to Cerebras after 1×15s retry
# (not 5×60s — that caused 5-minute stalls producing broken code).
# ─────────────────────────────────────────────────────────────────────────────
_GROQ_FALLBACK_MODEL      = "llama-3.1-8b-instant"
_GROQ_FALLBACK_MAX_TOKENS = 1800   # 8b cap: 6000 TPM − 1800 out − ~500 sys = 3700 input
_GROQ_FALLBACK_MAX_CHARS  = 12_000 # ≈ 3000 tokens — safe budget for 8b input

_CEREBRAS_MODEL      = "qwen-3-235b-a22b-instruct-2507"  # 235B params — more powerful than 70b
_CEREBRAS_BASE_URL   = "https://api.cerebras.ai/v1"
_CEREBRAS_MAX_TOKENS = 8192

load_dotenv()

_ROOT = os.path.join(os.path.dirname(__file__), "..")

_AGENT_ROLES = {
    "analyst":         "Business Analyst",
    "product_manager": "Product Manager",
    "architect":       "Solution Architect",
    "designer":        "UI/UX Designer",
    "scrum_master":    "Scrum Master",
    "developer":       "Senior Developer",
    "code_reviewer":   "Code Reviewer",
    "mock_tester":     "Mock Test Engineer",
    "qa_engineer":     "QA Engineer",
}

_AGENT_FILES = {
    "analyst":         ("agents/analyst.md",         "skills/analyst.yaml"),
    "product_manager": ("agents/product-manager.md", "skills/product-manager.yaml"),
    "architect":       ("agents/architect.md",        "skills/architect.yaml"),
    "designer":        ("agents/designer.md",         "skills/analyst.yaml"),       # reuse simple skills
    "scrum_master":    ("agents/scrum-master.md",     "skills/scrum-master.yaml"),
    "developer":       ("agents/developer.md",        "skills/developer.yaml"),
    "code_reviewer":   ("agents/code_reviewer.md",   "skills/qa-engineer.yaml"),   # reuse qa skills
    "mock_tester":     ("agents/mock-tester.md",      "skills/qa-engineer.yaml"),  # reuse qa skills
    "qa_engineer":     ("agents/qa-engineer.md",      "skills/qa-engineer.yaml"),
}

# Pricing per 1M tokens
_COST_PER_1M = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant":    {"input": 0.05, "output": 0.08},
    "qwen-3-235b-a22b-instruct-2507": {"input": 0.0, "output": 0.0},  # Cerebras free tier
}


def _make_cerebras_llm() -> ChatOpenAI:
    """Create a Cerebras LLM — via LiteLLM proxy (if enabled) or directly."""
    if _USE_LITELLM:
        return ChatOpenAI(
            model="bmad-cerebras",
            api_key=_LITELLM_KEY,
            base_url=_LITELLM_URL,
            max_tokens=_CEREBRAS_MAX_TOKENS,
            temperature=0.1,
        )
    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CEREBRAS_API_KEY not set in .env — "
            "get a free key at https://cloud.cerebras.ai"
        )
    return ChatOpenAI(
        model=_CEREBRAS_MODEL,
        api_key=api_key,
        base_url=_CEREBRAS_BASE_URL,
        max_tokens=_CEREBRAS_MAX_TOKENS,
        temperature=0.1,
    )


def _load_md(path: str) -> str:
    with open(os.path.join(_ROOT, path), "r", encoding="utf-8") as f:
        return f.read()


def _load_yaml(path: str) -> dict:
    with open(os.path.join(_ROOT, path), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_system_prompt(md_content: str) -> str:
    match = re.search(r"## System Prompt\n(.*?)(?=\n## |\Z)", md_content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return md_content


def _parse_retry_time(err_str: str) -> str:
    """Extract 'Please try again in Xh Ym Zs' from a Groq rate-limit message."""
    m = re.search(r"try again in ([^.]+)\.", err_str)
    return m.group(1).strip() if m else "some time"


def _get_llm(agent_id: str = "") -> ChatGroq:
    config = _load_yaml("config/workflow.yaml")
    settings = config["settings"]
    agent_models      = settings.get("agent_models", {})
    model_max_tokens  = settings.get("model_max_tokens", {})
    model      = agent_models.get(agent_id, settings.get("default_model", "llama-3.3-70b-versatile"))
    max_tokens = model_max_tokens.get(model, settings.get("max_tokens", 8192))

    # ── LiteLLM proxy mode ────────────────────────────────────────────────────
    # If LiteLLM proxy is running (USE_LITELLM=true), route all calls through it.
    # The proxy handles model routing, fallbacks, and observability automatically.
    if _USE_LITELLM:
        print(f"  🔀  [{agent_id}] Routing via LiteLLM proxy → {_LITELLM_URL} (model: {model})")
        return ChatOpenAI(
            model=model,           # e.g. "llama-3.3-70b-versatile" — alias defined in litellm_config.yaml
            api_key=_LITELLM_KEY,
            base_url=_LITELLM_URL,
            max_tokens=max_tokens,
            temperature=settings["temperature"],
        )

    return ChatGroq(
        model=model,
        temperature=settings["temperature"],
        api_key=os.getenv("GROQ_API_KEY"),
        max_tokens=max_tokens,
    )


def _get_model_name(agent_id: str = "") -> str:
    config = _load_yaml("config/workflow.yaml")
    settings = config["settings"]
    agent_models = settings.get("agent_models", {})
    return agent_models.get(agent_id, settings.get("default_model", "llama-3.3-70b-versatile"))


@observe(as_type="generation")
def run_agent(agent_id: str, user_message: str, session_id: str = "unknown") -> str:
    md_path, _ = _AGENT_FILES[agent_id]
    md_content  = _load_md(md_path)
    system_prompt = _extract_system_prompt(md_content)
    model = _get_model_name(agent_id)
    role  = _AGENT_ROLES.get(agent_id, agent_id)

    # Tag this observation with agent metadata
    langfuse_context.update_current_observation(
        name=f"bmad-{agent_id}",
        model=model,
        input=user_message[:500],
        metadata={
            "agent_id":   agent_id,
            "agent_role": role,
            "session_id": session_id,
        },
    )

    # Tag the parent trace with session info
    langfuse_context.update_current_trace(
        session_id=session_id,
        tags=["bmad", agent_id],
        metadata={"agent_role": role, "model": model},
    )

    llm = _get_llm(agent_id)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    # ── 3-tier model fallback helpers ─────────────────────────────────────────
    def _switch_to_groq_8b(reason: str) -> None:
        """Tier 2: Hot-swap to llama-3.1-8b and truncate input for 8b's 6k cap."""
        nonlocal llm, model, messages
        print(f"\n  ⚠️  [{agent_id}] {reason}")
        print(f"  🔄  Switching to Tier 2 → {_GROQ_FALLBACK_MODEL}...\n")
        llm = ChatGroq(
            model=_GROQ_FALLBACK_MODEL,
            temperature=0.1,
            api_key=os.getenv("GROQ_API_KEY"),
            max_tokens=_GROQ_FALLBACK_MAX_TOKENS,
        )
        model = _GROQ_FALLBACK_MODEL
        _truncate_for_8b()
        langfuse_context.update_current_observation(
            model=_GROQ_FALLBACK_MODEL,
            metadata={"fallback_tier": 2, "fallback_reason": reason},
        )

    def _switch_to_cerebras(reason: str) -> None:
        """Tier 3: Hot-swap to Cerebras llama-3.3-70b — 60K TPM, no daily cap, free."""
        nonlocal llm, model, messages
        print(f"\n  ⚠️  [{agent_id}] {reason}")
        print(f"  🔄  Switching to Tier 3 → {_CEREBRAS_MODEL} (Cerebras)...\n")
        llm   = _make_cerebras_llm()
        model = _CEREBRAS_MODEL
        langfuse_context.update_current_observation(
            model=_CEREBRAS_MODEL,
            metadata={"fallback_tier": 3, "fallback_reason": reason},
        )

    def _truncate_for_8b() -> None:
        """Truncate user_message to fit llama-3.1-8b's 6 000-token hard cap."""
        user_text = messages[1].content
        if len(user_text) > _GROQ_FALLBACK_MAX_CHARS:
            messages[1] = HumanMessage(
                content=user_text[:_GROQ_FALLBACK_MAX_CHARS]
                + "\n\n[Context truncated to fit model limits — focus on core requirements above]"
            )
            print(f"  ✂️  [{agent_id}] Truncated {len(user_text)} → "
                  f"{_GROQ_FALLBACK_MAX_CHARS} chars for 8b context window.\n")

    # Agents that need large output — skip 8b (only 1800 tokens) and go straight to Cerebras
    _LARGE_OUTPUT_AGENTS = {"developer", "code_reviewer", "mock_tester", "qa_engineer"}

    # ── Inference loop with automatic tier stepping ────────────────────────────
    t0 = time.time()
    max_attempts = 5   # covers: 70b → 8b → Cerebras → Cerebras-retry
    for attempt in range(max_attempts):
        try:
            response = llm.invoke(messages)
            break

        # ── Groq-specific errors ───────────────────────────────────────────────
        except RateLimitError as e:
            err_str = str(e)
            if "tokens per day" in err_str or "TPD" in err_str:
                retry_in = _parse_retry_time(err_str)
                if model not in (_GROQ_FALLBACK_MODEL, _CEREBRAS_MODEL):
                    # Large-output agents skip 8b and go straight to Cerebras
                    if agent_id in _LARGE_OUTPUT_AGENTS:
                        _switch_to_cerebras(f"Daily limit on {model} (resets in {retry_in}) — skipping 8b for large output agent.")
                    else:
                        # Tier 1 → Tier 2
                        _switch_to_groq_8b(f"Daily limit on {model} (resets in {retry_in}).")
                    continue
                elif model == _GROQ_FALLBACK_MODEL:
                    # Tier 2 → Tier 3
                    _switch_to_cerebras(f"8b daily limit hit (resets in {retry_in}).")
                    continue
                else:
                    raise  # Cerebras shouldn't get TPD — unexpected
            # Per-minute rate limit on Groq — switch to Cerebras after 1 short wait
            if model == _CEREBRAS_MODEL:
                raise  # Cerebras rate limits are handled below
            if attempt == 0:
                # One quick retry after a short wait before escalating
                wait = 15
                print(f"\n  ⏳ [{agent_id}] Rate limited — waiting {wait}s then switching to Cerebras...")
                time.sleep(wait)
            else:
                # Already waited once — escalate to Cerebras immediately
                _switch_to_cerebras("Groq per-minute limit — switching to Cerebras.")
                continue

        except APIStatusError as e:
            err_str = str(e)
            if e.status_code == 413 or "too large" in err_str.lower():
                # 413 Request Too Large
                if model not in (_GROQ_FALLBACK_MODEL, _CEREBRAS_MODEL):
                    _switch_to_groq_8b("Request too large for primary model (413).")
                    continue
                elif model == _GROQ_FALLBACK_MODEL:
                    # Already truncated but still too big → go to Gemini
                    _switch_to_cerebras("Request too large even for 8b — switching to Cerebras.")
                    continue
                # On Cerebras with 413 — reduce by 30% and retry
                user_text = messages[1].content
                reduced = int(len(user_text) * 0.7)
                if reduced > 500 and attempt < max_attempts - 1:
                    messages[1] = HumanMessage(
                        content=user_text[:reduced]
                        + "\n\n[Further truncated — generate from available context]"
                    )
                    print(f"  ✂️  [{agent_id}] Reduced to {reduced} chars, retrying...\n")
                    continue
            raise

        # ── Generic / Cerebras errors — one retry then fail ──────────────────────
        except Exception as e:
            err_str = str(e).lower()
            if model != _CEREBRAS_MODEL and (
                "quota" in err_str or "limit" in err_str or "429" in err_str
            ):
                _switch_to_cerebras(f"Error on {model}: {str(e)[:80]}")
                continue
            raise

    latency_ms = (time.time() - t0) * 1000
    output_text = response.content.strip()

    # Extract token usage — handles Groq dict format AND Cerebras/Gemini object format
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        rm    = getattr(response, "response_metadata", {})
        usage = rm.get("token_usage", {})

    if isinstance(usage, dict):
        input_tokens  = usage.get("input_tokens",  usage.get("prompt_tokens", 0))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    else:
        # Cerebras returns an object with input_tokens / output_tokens attributes
        input_tokens  = getattr(usage, "input_tokens",  getattr(usage, "prompt_token_count", 0))
        output_tokens = getattr(usage, "output_tokens", getattr(usage, "candidates_token_count", 0))

    rates = _COST_PER_1M.get(model, {"input": 0.59, "output": 0.79})
    cost  = round((input_tokens / 1_000_000) * rates["input"] +
                  (output_tokens / 1_000_000) * rates["output"], 6)

    # Push token + cost + latency into the Langfuse observation
    langfuse_context.update_current_observation(
        output=output_text[:2000],
        usage={
            "input":  input_tokens,
            "output": output_tokens,
            "total":  input_tokens + output_tokens,
            "unit":   "TOKENS",
        },
        metadata={
            "agent_id":    agent_id,
            "agent_role":  role,
            "model":       model,
            "session_id":  session_id,
            "latency_ms":  round(latency_ms, 2),
            "cost_usd":    cost,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
        },
    )

    return output_text


def get_agent_skills(agent_id: str) -> dict:
    _, yaml_path = _AGENT_FILES[agent_id]
    return _load_yaml(yaml_path)
