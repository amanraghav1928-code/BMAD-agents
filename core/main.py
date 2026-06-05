import sys
import os
import time
import uuid
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflow import app
from core.state import BMADState
from core.observability import flush, log_pipeline_summary, score_pipeline
from core.memory import save_session, get_relevant_context, list_sessions
from core.guardrails import validate_input, GuardrailError, print_guardrail_error
from groq import RateLimitError

_ROOT = os.path.join(os.path.dirname(__file__), "..")

_INITIAL_STATE: BMADState = {
    "session_id": "",
    "user_request": "",
    "project_brief": "",
    "functional_spec": "",
    "solution_design": "",
    "ui_design": "",
    "stories": "",
    "code": "",
    "review_feedback": "",
    "mock_test_code":   "",
    "mock_test_result": "",
    "test_strategy": "",
    "test_plan": "",
    "execution_result": "",
    "execution_error": "",
    "debug_iterations": 0,
    "status": "pending",
    # New fields
    "complexity_score":          None,
    "complexity_reason":         None,
    "complexity_model_override": None,
    "validation_passed":         None,
    "validation_error":          None,
    "validation_attempts":       0,
    "eval_scores":               None,
}


def _save_outputs(state: BMADState, slug: str) -> str:
    out_dir = os.path.join(_ROOT, "output", slug)
    os.makedirs(out_dir, exist_ok=True)
    docs = {
        "prompt.txt":          state.get("user_request",     ""),
        "project-brief.md":    state.get("project_brief",   ""),
        "functional-spec.md":  state.get("functional_spec",  ""),
        "solution-design.md":  state.get("solution_design",  ""),
        "user-stories.md":     state.get("stories",          ""),
        "mock-tests.py":       state.get("mock_test_code",   ""),
        "mock-test-results.md":state.get("mock_test_result", ""),
        "test-strategy.md":    state.get("test_strategy",    ""),
        "test-plan.md":        state.get("test_plan",        ""),
    }
    for fname, content in docs.items():
        if content:
            with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
                f.write(content)
    return out_dir


def run(request: str) -> None:
    # ── INPUT GUARDRAIL ───────────────────────────────────────────────────────
    try:
        request = validate_input(request)
    except GuardrailError as e:
        print_guardrail_error(e)
        return

    slug       = "".join(c if c.isalnum() or c == " " else "" for c in request[:40].lower()).replace(" ", "_")
    session_id = f"bmad-{slug[:30]}-{uuid.uuid4().hex[:8]}"
    state      = {**_INITIAL_STATE, "user_request": request, "session_id": session_id}

    print("\n" + "=" * 65)
    print("  BMAD AGENT SYSTEM")
    print("  Powered by LangGraph · Groq llama-3.3-70b · Langfuse")
    print("=" * 65)
    print(f"\n  Request    : {request}")
    print(f"  Session ID : {session_id}")
    print(f"  Date       : {date.today()}")
    print("\n  [1/10] Analyst           — understanding requirements...")
    print("  [2/10] Product Manager   — writing functional spec...")
    print("  [3/10] Architect         — designing solution...")
    print("  [4/10] Designer    ┐     — creating UI design system...  ║ PARALLEL")
    print("  [4/10] Scrum Master┘     — creating user stories...      ║ PARALLEL")
    print("  [5/10] Developer         — generating code...")
    print("  [6/10] Code Reviewer     — reviewing code quality...")
    print("  [7/10] Executor          — syntax check...")
    print("  [8/10] Mock Tester       — running pytest mock tests...")
    print("  [9/10] QA Engineer       — running test plan...")
    print("\n  (check Langfuse dashboard for live traces)\n")

    # Inject memory context for developer agent
    memory_context = get_relevant_context(request)
    if memory_context:
        print("  💾 Memory: found similar past project — injecting context...\n")
        state = {**state, "user_request": request + memory_context}

    t_start = time.time()
    try:
        final = app.invoke(state)
    except GuardrailError as e:
        print_guardrail_error(e)
        return
    except RateLimitError as e:
        # Both primary + fallback models exhausted their daily quota.
        # Parse the "try again in Xh Ym" from the Groq error body and surface it
        # cleanly instead of dumping a raw traceback.
        import re
        err_str = str(e)
        m = re.search(r"try again in ([^.]+)\.", err_str)
        retry_in = m.group(1).strip() if m else "some time"
        print("\n" + "=" * 65)
        print("  ⛔  DAILY TOKEN LIMIT REACHED")
        print("=" * 65)
        print(f"\n  Both llama-3.3-70b-versatile and llama-3.1-8b-instant have")
        print(f"  exhausted their daily token quota.")
        print(f"\n  ⏰  Primary model resets in: {retry_in}")
        print(f"\n  What you can do:")
        print(f"     1. Wait {retry_in} and run again — quota resets daily.")
        print(f"     2. Upgrade your Groq plan at https://console.groq.com/settings/billing")
        print(f"     3. Add a different API key in your .env file:")
        print(f"        GROQ_API_KEY=your_new_key")
        print("=" * 65 + "\n")
        return
    total_ms = (time.time() - t_start) * 1000
    out_dir = _save_outputs(final, slug)

    # Determine the actual saved file extension (matches executor_node logic)
    from core.workflow import _detect_language
    _code_for_lang = final.get("code", "")
    _lang = _detect_language(_code_for_lang)
    _ext_map = {"streamlit": ".py", "python": ".py", "fastapi": ".py",
                "html": ".html", "react": ".html", "java": "/Main.java",
                "springboot": "/"}
    _ext = _ext_map.get(_lang, ".py")
    if _lang == "java":
        app_file = os.path.join(_ROOT, "apps", slug, "Main.java")
    elif _lang == "springboot":
        app_file = os.path.join(_ROOT, "apps", slug)   # directory path
    else:
        app_file = os.path.join(_ROOT, "apps", f"{slug}{_ext}")

    print("\n" + "=" * 65)
    print("  PROJECT BRIEF")
    print("=" * 65)
    print(final.get("project_brief", ""))

    print("\n" + "=" * 65)
    print("  FUNCTIONAL SPEC (first 30 lines)")
    print("=" * 65)
    lines = final.get("functional_spec", "").split("\n")
    print("\n".join(lines[:30]))
    if len(lines) > 30:
        print(f"  ... see {out_dir}/functional-spec.md for full document")

    print("\n" + "=" * 65)
    print("  USER STORIES (first 25 lines)")
    print("=" * 65)
    lines = final.get("stories", "").split("\n")
    print("\n".join(lines[:25]))
    if len(lines) > 25:
        print(f"  ... see {out_dir}/user-stories.md for full document")

    print("\n" + "=" * 65)
    print("  TEST PLAN")
    print("=" * 65)
    print(final.get("test_plan", ""))

    if final.get("execution_error"):
        print("\n" + "=" * 65)
        print("  ERRORS")
        print("=" * 65)
        print(final.get("execution_error", ""))

    print("\n" + "=" * 65)
    print(f"  STATUS          : {final.get('status', 'unknown')}")
    print(f"  DEBUG ITERS     : {final.get('debug_iterations', 0)}")
    print(f"  DOCS SAVED TO   : {out_dir}/")
    print(f"  APP SAVED TO    : {app_file}")
    print("=" * 65)
    print(f"\n  Documents generated:")
    print(f"    {out_dir}/project-brief.md")
    print(f"    {out_dir}/functional-spec.md")
    print(f"    {out_dir}/solution-design.md")
    print(f"    {out_dir}/user-stories.md")
    print(f"    {out_dir}/mock-tests.py")
    print(f"    {out_dir}/mock-test-results.md")
    print(f"    {out_dir}/test-strategy.md")
    print(f"    {out_dir}/test-plan.md")
    # Show the right run command based on detected language
    print(f"\n  ▶  How to run your app:")
    if _lang == "streamlit":
        print(f"     streamlit run {app_file}\n")
    elif _lang in ("html", "react"):
        print(f"     open {app_file}   (just open the file in your browser)\n")
    elif _lang == "java":
        java_dir = os.path.join(_ROOT, "apps", slug)
        print(f"     cd {java_dir} && javac Main.java && java Main\n")
    elif _lang == "springboot":
        print(f"     cd {app_file} && mvn spring-boot:run\n")
        print(f"     Then open http://localhost:8080\n")
    elif _lang == "fastapi":
        print(f"     python {app_file}   then open http://localhost:8000/docs\n")
    else:
        print(f"     python {app_file}\n")

    # Save to memory for future runs
    detected_lang = _lang  # already computed above
    save_session(
        session_id=session_id,
        user_request=request,
        status=final.get("status", "unknown"),
        output_file=app_file,
        agents_run=["analyst", "product_manager", "architect", "designer",
                    "scrum_master", "developer", "code_reviewer", "executor",
                    "mock_tester", "qa_engineer"],
        total_tokens=0,
        total_cost=0.0,
        language=detected_lang,
        debug_iterations=final.get("debug_iterations", 0),
    )

    # Log full pipeline summary to Langfuse
    log_pipeline_summary(
        session_id=session_id,
        user_request=request,
        final_status=final.get("status", "unknown"),
        debug_iterations=final.get("debug_iterations", 0),
        total_tokens=0,      # aggregated per-agent in log_agent_call
        total_cost=0.0,
        total_latency_ms=total_ms,
        agents_run=["analyst", "product_manager", "architect", "designer",
                    "scrum_master", "developer", "code_reviewer", "executor",
                    "mock_tester", "qa_engineer"],
    )

    score_pipeline(
        session_id=session_id,
        final_state=final,
        total_latency_ms=total_ms,
    )

    flush()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]))
    else:
        print("\n" + "=" * 65)
        print("  BMAD AGENT SYSTEM")
        print("  Powered by LangGraph · Groq llama-3.3-70b · Langfuse")
        print("=" * 65)
        past = list_sessions()
        if past:
            print(f"\n  💾 Memory: {len(past)} past project(s) on record:")
            for s in past[-3:]:
                print(f"     • [{s['date']}] {s['user_request'][:60]}  ({s['status']})")
            print()
        print("  What do you want to build?")
        print("  (Press Enter twice when done)\n")
        lines = []
        while True:
            line = input("  > " if not lines else "    ")
            if line == "" and lines:
                break
            lines.append(line)
        request = " ".join(lines).strip()
        if not request:
            print("  No input. Exiting.")
            sys.exit(0)
        run(request)
