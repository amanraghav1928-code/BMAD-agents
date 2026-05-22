"""
Observability — Langfuse integration
--------------------------------------
Tracks session IDs, token usage, latency, model info, and costs
for every agent run in the BMAD pipeline.
"""

import os
from langfuse import Langfuse
from langfuse.decorators import langfuse_context
from dotenv import load_dotenv

load_dotenv()

_langfuse: Langfuse | None = None

# Groq pricing per 1M tokens (as of 2025)
_COST_PER_1M = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant":    {"input": 0.05, "output": 0.08},
    "mixtral-8x7b-32768":      {"input": 0.27, "output": 0.27},
}


def _client() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _langfuse


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_1M.get(model, {"input": 0.59, "output": 0.79})
    return round(
        (input_tokens / 1_000_000) * rates["input"] +
        (output_tokens / 1_000_000) * rates["output"],
        6
    )


def update_observation(
    name: str,
    input_data: dict,
    output_data: dict,
    metadata: dict | None = None,
) -> None:
    langfuse_context.update_current_observation(
        name=name,
        input=input_data,
        output=output_data,
        metadata=metadata or {},
    )


def update_trace(
    session_id: str,
    user_request: str,
    tags: list | None = None,
    metadata: dict | None = None,
) -> None:
    langfuse_context.update_current_trace(
        session_id=session_id,
        name=f"bmad-pipeline: {user_request[:60]}",
        input={"user_request": user_request},
        tags=tags or ["bmad"],
        metadata=metadata or {},
    )


def log_agent_call(
    session_id: str,
    agent_id: str,
    agent_role: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    input_text: str,
    output_text: str,
    status: str = "success",
) -> None:
    lf = _client()
    cost = estimate_cost(model, input_tokens, output_tokens)

    trace = lf.trace(
        name=f"bmad-{agent_id}",
        session_id=session_id,
        input={"prompt": input_text[:1000]},
        output={"response": output_text[:2000]},
        tags=["bmad", agent_id, "agent-call"],
        metadata={
            "agent_id":   agent_id,
            "agent_role": agent_role,
            "model":      model,
            "status":     status,
            "latency_ms": round(latency_ms, 2),
            "cost_usd":   cost,
        },
    )

    trace.generation(
        name=f"{agent_id}-llm-call",
        model=model,
        input=[
            {"role": "system", "content": "(system prompt)"},
            {"role": "user",   "content": input_text[:500]},
        ],
        output=output_text[:2000],
        usage={
            "input":  input_tokens,
            "output": output_tokens,
            "total":  input_tokens + output_tokens,
            "unit":   "TOKENS",
        },
        metadata={
            "latency_ms": round(latency_ms, 2),
            "cost_usd":   cost,
        },
    )


def log_execution(
    session_id: str,
    code: str,
    result: str,
    error: str,
    latency_ms: float = 0.0,
) -> None:
    lf = _client()
    trace = lf.trace(
        name="bmad-executor",
        session_id=session_id,
        input={"code_length": len(code), "code_preview": code[:300]},
        output={"result": result[:2000], "error": error[:500]},
        tags=["bmad", "executor"],
        metadata={
            "code_lines": len(code.splitlines()),
            "success":    not bool(error),
            "latency_ms": round(latency_ms, 2),
        },
    )
    trace.span(
        name="code_execution",
        input={"code": code[:3000]},
        output={"stdout": result[:2000], "stderr": error[:500]},
    )


def log_pipeline_summary(
    session_id: str,
    user_request: str,
    final_status: str,
    debug_iterations: int,
    total_tokens: int,
    total_cost: float,
    total_latency_ms: float,
    agents_run: list,
) -> None:
    lf = _client()
    lf.trace(
        name="bmad-pipeline-summary",
        session_id=session_id,
        input={"user_request": user_request},
        output={"status": final_status},
        tags=["bmad", "pipeline", final_status],
        metadata={
            "final_status":     final_status,
            "debug_iterations": debug_iterations,
            "total_tokens":     total_tokens,
            "total_cost_usd":   round(total_cost, 6),
            "total_latency_ms": round(total_latency_ms, 2),
            "agents_run":       agents_run,
            "agents_count":     len(agents_run),
        },
    )


def score_pipeline(
    session_id: str,
    final_state: dict,
    total_latency_ms: float,
) -> None:
    """
    Automatic Langfuse Evals — called once after every pipeline run.
    Pushes 6 scores to Langfuse so you can track quality over time.

    Scores (all 0.0 – 1.0):
      pipeline_success    — did the pipeline pass QA?
      code_quality        — syntax valid + no execution error
      debug_efficiency    — fewer debug retries = higher score
      agent_completion    — what % of agents finished
      output_completeness — how substantial is the generated code
      qa_verdict          — did QA explicitly say PASS?
    """
    lf = _client()

    status          = final_state.get("status", "")
    code            = final_state.get("code", "")
    exec_error      = final_state.get("execution_error", "")
    exec_result     = final_state.get("execution_result", "")
    test_plan       = final_state.get("test_plan", "")
    debug_iters     = final_state.get("debug_iterations", 0)
    agents_run      = ["analyst","product_manager","architect","designer",
                       "scrum_master","developer","code_reviewer","executor",
                       "mock_tester","qa_engineer"]

    # ── Score 1: Pipeline success (binary) ────────────────────────────────────
    pipeline_success = 1.0 if status == "passed" else 0.0

    # ── Score 2: Code quality (syntax OK + no execution error) ────────────────
    has_code    = len(code.strip()) > 100
    syntax_ok   = not exec_error and has_code
    exec_ok     = any(kw in exec_result.lower() for kw in
                      ("syntax ok","compiled ok","html ok","java file saved","maven compile ok"))
    code_quality = round((0.5 if syntax_ok else 0.0) + (0.5 if exec_ok else 0.0), 2)

    # ── Score 3: Debug efficiency (0 retries = 1.0, each retry costs 0.25) ───
    debug_efficiency = max(0.0, round(1.0 - (debug_iters * 0.25), 2))

    # ── Score 4: Agent completion (% of agents that produced output) ──────────
    completed = sum(1 for key in [
        "project_brief","functional_spec","solution_design",
        "stories","code","review_feedback","test_plan",
    ] if final_state.get(key, "").strip())
    agent_completion = round(completed / 7, 2)

    # ── Score 5: Output completeness (code length proxy) ─────────────────────
    code_lines = len([l for l in code.splitlines() if l.strip()])
    output_completeness = min(1.0, round(code_lines / 200, 2))  # 200 lines = perfect

    # ── Score 6: QA verdict ───────────────────────────────────────────────────
    qa_verdict = 1.0 if "VERDICT: PASS" in test_plan.upper() else 0.0

    scores = [
        ("pipeline_success",    pipeline_success,    "Did the full pipeline pass QA?"),
        ("code_quality",        code_quality,        "Syntax valid + no execution error (0-1)"),
        ("debug_efficiency",    debug_efficiency,    "Fewer debug retries = higher score"),
        ("agent_completion",    agent_completion,    "% of agents that produced output"),
        ("output_completeness", output_completeness, "Code length as proxy for completeness"),
        ("qa_verdict",          qa_verdict,          "QA Engineer explicit PASS verdict"),
    ]

    # Find the pipeline-summary trace for this session to attach scores to
    try:
        traces = lf.get_traces(session=session_id, limit=5)
        trace_id = None
        for t in traces.data:
            if "pipeline" in (t.name or "").lower():
                trace_id = t.id
                break
        # Fallback: use the most recent trace in this session
        if not trace_id and traces.data:
            trace_id = traces.data[0].id
    except Exception:
        trace_id = None

    for name, value, comment in scores:
        try:
            if trace_id:
                lf.score(
                    trace_id=trace_id,
                    name=name,
                    value=value,
                    comment=comment,
                    data_type="NUMERIC",
                )
            else:
                # No trace found — create a standalone score trace
                lf.score(
                    name=name,
                    value=value,
                    comment=f"[session:{session_id}] {comment}",
                    data_type="NUMERIC",
                )
        except Exception:
            pass  # Never crash the pipeline over a scoring failure

    print(f"\n  📊 Langfuse Evals logged ({len(scores)} scores):")
    for name, value, _ in scores:
        bar = "█" * int(value * 10) + "░" * (10 - int(value * 10))
        print(f"     {name:<22} {bar}  {value:.2f}")


def score_faithfulness(
    session_id: str,
    question: str,
    context: str,
    answer: str,
    trace_id: str | None = None,
) -> float:
    """
    LLM-as-judge faithfulness score for RAG apps.
    Uses llama-3.1-8b to rate 0.0-1.0 how grounded the answer is in the context.
    Pushes the score to Langfuse. Returns the score value.
    """
    try:
        from groq import Groq
        import os
        groq = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        prompt = (
            f"Rate 0.0-1.0: does this answer rely ONLY on the provided context?\n"
            f"1.0=fully grounded, 0.0=hallucinated.\n"
            f"Context: {context[:800]}\nAnswer: {answer[:400]}\n"
            f"Reply with ONLY a number like 0.85"
        )
        resp = groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5, temperature=0.0,
        )
        score = float(resp.choices[0].message.content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5

    lf = _client()
    try:
        if not trace_id:
            traces = lf.get_traces(session=session_id, limit=3)
            trace_id = traces.data[0].id if traces.data else None
        if trace_id:
            lf.score(trace_id=trace_id, name="faithfulness", value=score,
                     data_type="NUMERIC",
                     comment="LLM-as-judge: answer grounded in retrieved context")
    except Exception:
        pass

    bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
    print(f"  🎯 Faithfulness  {bar}  {score:.2f}")
    return score


def score_answer_relevance(
    session_id: str,
    question: str,
    answer: str,
    trace_id: str | None = None,
) -> float:
    """
    LLM-as-judge answer relevance score for RAG apps.
    Rates 0.0-1.0 how well the answer addresses the question.
    Pushes score to Langfuse. Returns score value.
    """
    try:
        from groq import Groq
        import os
        groq = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        prompt = (
            f"Rate 0.0-1.0: does this answer directly and completely address the question?\n"
            f"1.0=fully answers, 0.0=completely off-topic.\n"
            f"Question: {question[:400]}\nAnswer: {answer[:400]}\n"
            f"Reply with ONLY a number like 0.85"
        )
        resp = groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5, temperature=0.0,
        )
        score = float(resp.choices[0].message.content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5

    lf = _client()
    try:
        if not trace_id:
            traces = lf.get_traces(session=session_id, limit=3)
            trace_id = traces.data[0].id if traces.data else None
        if trace_id:
            lf.score(trace_id=trace_id, name="answer_relevance", value=score,
                     data_type="NUMERIC",
                     comment="LLM-as-judge: answer directly addresses the question")
    except Exception:
        pass

    bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
    print(f"  📐 Answer Relevance  {bar}  {score:.2f}")
    return score


def flush() -> None:
    # Always flush via the direct client (works for both @observe and direct traces)
    _client().flush()
