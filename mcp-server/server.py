"""
BMAD Langfuse Intelligence MCP Server
======================================
A smart MCP server that combines:
  - Langfuse (your pipeline trace data)
  - LiteLLM proxy (routes to Groq/Cerebras for intelligent answers)

Instead of just returning raw data, the LLM processes it
and gives you intelligent, human-readable answers.
"""

import os
import sys
import logging
import requests
import litellm
from dotenv import load_dotenv

# Use the official Anthropic MCP SDK — no banner, clean stdio
from mcp.server.fastmcp import FastMCP

# Silence all logs so MCP stdio protocol isn't disrupted
logging.disable(logging.CRITICAL)
litellm.suppress_debug_info = True

# ── Load environment variables from .env ──────────────────────────────────────
_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_PATH)

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_BASE_URL   = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# ── LiteLLM proxy config ───────────────────────────────────────────────────────
_USE_LITELLM  = os.getenv("USE_LITELLM", "false").lower() == "true"
_LITELLM_URL  = os.getenv("LITELLM_PROXY_URL", "http://localhost:4000")
_LITELLM_KEY  = os.getenv("LITELLM_MASTER_KEY", "bmad-litellm-key-2025")
_GROQ_KEY     = os.getenv("GROQ_API_KEY", "")
_MCP_MODEL    = "bmad-primary" if _USE_LITELLM else "groq/llama-3.3-70b-versatile"

# ── Create the MCP server ─────────────────────────────────────────────────────
mcp = FastMCP(
    name="BMAD Langfuse Intelligence",
    instructions=(
        "You are a smart analytics assistant for the BMAD AI pipeline. "
        "You have access to Langfuse trace data and use LiteLLM (routed to Groq) "
        "to give intelligent, concise answers about agent performance, "
        "model usage, recent activity, and pipeline health."
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _langfuse_get(endpoint: str, params: dict = None) -> dict:
    """
    Make an authenticated GET request to the Langfuse REST API.
    Returns the JSON response as a Python dict.
    """
    url      = f"{LANGFUSE_BASE_URL}/api/public/{endpoint}"
    response = requests.get(
        url,
        auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY),
        params=params or {},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _ask_litellm(question: str, context: str) -> str:
    """
    Send data context + user question to LiteLLM proxy (Groq/Cerebras).
    LiteLLM acts as the 'brain' that reads raw Langfuse data
    and returns a smart, human-readable answer.
    Routes through LiteLLM proxy when USE_LITELLM=true, otherwise calls Groq directly.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""You are a data analyst for a BMAD AI agent pipeline system.
You have been given real data from Langfuse (an AI observability tool).

IMPORTANT CONTEXT:
- Today's date is: {today}
- Current time is: {now}
- "Today" means any timestamp starting with "{today}"
- "Yesterday" means any timestamp starting with the day before {today}

=== LANGFUSE DATA ===
{context}
====================

Answer this question based ONLY on the data above:
{question}

Rules:
- Be concise and specific
- Use numbers from the data
- When counting "today", only include timestamps starting with "{today}"
- If data is insufficient, say so
- Format nicely with bullet points or tables where helpful
"""
    if _USE_LITELLM:
        # Route through LiteLLM proxy — proxy handles fallbacks automatically
        response = litellm.completion(
            model=f"openai/{_MCP_MODEL}",   # "openai/" prefix tells litellm it's an OpenAI-compatible endpoint
            messages=[{"role": "user", "content": prompt}],
            api_key=_LITELLM_KEY,
            api_base=_LITELLM_URL,
            max_tokens=2048,
            temperature=0.1,
        )
    else:
        # Direct Groq call (no proxy needed)
        response = litellm.completion(
            model="groq/llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            api_key=_GROQ_KEY,
            max_tokens=2048,
            temperature=0.1,
        )
    return response.choices[0].message.content


def _format_traces(traces: list) -> str:
    """
    Convert raw trace list into a readable text block for Ollama to process.
    """
    lines = []
    for t in traces:
        ts      = t.get("timestamp", "")[:16].replace("T", " ")
        name    = t.get("name", "unknown")
        latency = t.get("latency", 0) or 0
        session = t.get("sessionId", "N/A") or "N/A"
        tags    = ", ".join(t.get("tags", [])) or "none"
        cost    = t.get("totalCost", 0) or 0
        lines.append(
            f"[{ts}] {name} | latency={latency:.2f}s | "
            f"session={session[:40]} | tags={tags} | cost=${cost:.6f}"
        )
    return "\n".join(lines) if lines else "No trace data available."


# ═══════════════════════════════════════════════════════════════════════════════
# MCP TOOLS — These are the functions Claude can call
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def ask_pipeline(question: str) -> str:
    """
    Ask ANY question about your BMAD pipeline in plain English.
    LiteLLM (Groq) reads the latest Langfuse traces and gives a smart answer.

    Examples:
      - "Which agent is slowest?"
      - "How many times did the developer agent run?"
      - "What was built yesterday?"
      - "Are there any failed pipelines?"
    """
    from datetime import datetime, timezone, timedelta

    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    q_lower = question.lower()
    params  = {"limit": 100, "orderBy": "timestamp.desc"}

    # Smart pre-filter: if question is about today/yesterday, filter at API level
    # so Ollama only sees the relevant subset (avoids context overflow & confusion)
    if "today" in q_lower:
        params["fromTimestamp"] = f"{today}T00:00:00Z"
    elif "yesterday" in q_lower:
        params["fromTimestamp"] = f"{yesterday}T00:00:00Z"
        params["toTimestamp"]   = f"{today}T00:00:00Z"

    data   = _langfuse_get("traces", params)
    traces = data.get("data", [])

    if not traces:
        return f"No trace data found for your query (checked from {params.get('fromTimestamp', 'all time')})."

    context = _format_traces(traces)
    return _ask_litellm(question, context)


@mcp.tool()
def get_agent_performance(agent_name: str = "") -> str:
    """
    Get smart performance stats for a specific agent or all agents.
    LiteLLM (Groq) calculates averages, spots patterns, and summarises clearly.

    Args:
        agent_name: e.g. "analyst", "developer", "qa" — leave blank for ALL agents
    """
    params = {"limit": 100, "orderBy": "timestamp.desc"}
    if agent_name:
        params["name"] = f"bmad-{agent_name.lower().replace('bmad-', '')}"

    data   = _langfuse_get("traces", params)
    traces = data.get("data", [])

    if not traces:
        return f"No traces found for agent: {agent_name or 'any'}"

    context  = _format_traces(traces)
    question = (
        f"Give a full performance report for "
        f"{'agent: ' + agent_name if agent_name else 'ALL agents'}.\n"
        f"Include: number of runs, average latency, min latency, max latency, "
        f"and any performance issues or patterns you notice."
    )
    return _ask_litellm(question, context)


@mcp.tool()
def get_model_usage(model_name: str = "") -> str:
    """
    Find out how many traces a specific model has generated,
    or get a breakdown of all model usage across your pipeline.

    Args:
        model_name: e.g. "llama-3.3-70b-versatile" — leave blank for ALL models
    """
    data   = _langfuse_get("traces", {"limit": 100, "orderBy": "timestamp.desc"})
    traces = data.get("data", [])

    if not traces:
        return "No trace data available."

    context  = _format_traces(traces)
    question = (
        f"Count and report model usage. "
        f"{'Focus on model: ' + model_name if model_name else 'Show all models and their trace counts.'}\n"
        f"Group by agent name and count how many traces each agent/model combination has."
    )
    return _ask_litellm(question, context)


@mcp.tool()
def get_recent_activity(limit: int = 10) -> str:
    """
    Get a smart summary of the most recent pipeline runs.
    Always fetches the newest entries, never old ones.

    Args:
        limit: how many recent traces to look at (default 10)
    """
    # Force newest first — solves the "picks old entries" problem
    data   = _langfuse_get("traces", {
        "limit": min(limit, 50),
        "orderBy": "timestamp.desc",  # always newest first
    })
    traces = data.get("data", [])

    if not traces:
        return "No recent activity found."

    context  = _format_traces(traces)
    question = (
        f"Summarise the {len(traces)} most recent pipeline activities.\n"
        f"What projects were built? When? How fast did each agent run? "
        f"Were there any failures or retries? Give a clear timeline summary."
    )
    return _ask_litellm(question, context)


@mcp.tool()
def compare_agents(agent1: str, agent2: str) -> str:
    """
    Compare performance between two agents side by side.
    LiteLLM (Groq) analyses both and tells you which is faster and more consistent.

    Args:
        agent1: first agent name e.g. "analyst"
        agent2: second agent name e.g. "developer"
    """
    data   = _langfuse_get("traces", {"limit": 100, "orderBy": "timestamp.desc"})
    traces = data.get("data", [])

    # Filter only relevant traces for both agents
    relevant = [
        t for t in traces
        if agent1.lower() in t.get("name", "").lower()
        or agent2.lower() in t.get("name", "").lower()
    ]

    if not relevant:
        return f"No traces found for agents: {agent1} or {agent2}"

    context  = _format_traces(relevant)
    question = (
        f"Compare performance between '{agent1}' and '{agent2}'.\n"
        f"Show: number of runs each, average latency each, fastest run each, "
        f"slowest run each, and a final verdict on who performs better overall."
    )
    return _ask_litellm(question, context)


@mcp.tool()
def get_pipeline_health() -> str:
    """
    Get an overall health report of your entire BMAD pipeline.
    Checks for failures, slow agents, retry patterns, and overall success rate.
    """
    data   = _langfuse_get("traces", {"limit": 100, "orderBy": "timestamp.desc"})
    traces = data.get("data", [])

    if not traces:
        return "No trace data available for health check."

    # Also fetch pipeline summary traces specifically
    summary_data   = _langfuse_get("traces", {
        "limit": 20,
        "name": "bmad-pipeline-summary",
        "orderBy": "timestamp.desc",
    })
    summaries = summary_data.get("data", [])

    context = (
        f"=== ALL RECENT TRACES ===\n{_format_traces(traces)}\n\n"
        f"=== PIPELINE SUMMARIES ===\n{_format_traces(summaries)}"
    )
    question = (
        "Give a complete pipeline health report:\n"
        "1. Overall success rate (passed vs failed)\n"
        "2. Which agents are slowest / causing bottlenecks\n"
        "3. How many debug/retry iterations happened\n"
        "4. Any error patterns\n"
        "5. Overall health score out of 10 with reasoning"
    )
    return _ask_litellm(question, context)


@mcp.tool()
def search_sessions(keyword: str) -> str:
    """
    Search for pipeline sessions by project keyword.
    Finds all runs related to a specific project or topic.

    Args:
        keyword: e.g. "stock", "navigation", "inventory"
    """
    data   = _langfuse_get("traces", {"limit": 100, "orderBy": "timestamp.desc"})
    traces = data.get("data", [])

    # Filter by keyword in session ID or tags
    relevant = [
        t for t in traces
        if keyword.lower() in (t.get("sessionId") or "").lower()
        or any(keyword.lower() in tag.lower() for tag in t.get("tags", []))
    ]

    if not relevant:
        return f"No sessions found matching keyword: '{keyword}'"

    context  = _format_traces(relevant)
    question = (
        f"Summarise all pipeline sessions related to '{keyword}'.\n"
        f"What was built? How many agents ran? What was the outcome? "
        f"How long did it take total?"
    )
    return _ask_litellm(question, context)


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
