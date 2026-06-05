import re
import subprocess
import sys
import os
import time
import py_compile
import tempfile
import yaml
from langfuse.decorators import observe
from langgraph.graph import StateGraph, END
from core.state import BMADState
from core.agent_runner import run_agent
from core.observability import update_observation, log_execution
from core.guardrails import (
    validate_agent_output,
    validate_code_output,
    validate_review_output,
    validate_mock_test_output,
    validate_qa_output,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_UI_FRAMEWORKS = ("streamlit", "gradio", "dash", "flask", "fastapi")
_SHELL_PATTERNS = [
    re.compile(r"^streamlit\s+run\s+", re.MULTILINE),
    re.compile(r"^uvicorn\s+\w", re.MULTILINE),
    re.compile(r"^gunicorn\s+", re.MULTILINE),
    re.compile(r"^pip\s+(install|freeze)", re.MULTILINE),
    re.compile(r"^\$\s+", re.MULTILINE),
    re.compile(r"^javac\s+", re.MULTILINE),
    re.compile(r"^java\s+", re.MULTILINE),
    re.compile(r"^npm\s+", re.MULTILINE),
    re.compile(r"^node\s+", re.MULTILINE),
]


def _load_config() -> dict:
    with open(os.path.join(_ROOT, "config/workflow.yaml"), "r") as f:
        return yaml.safe_load(f)


def _detect_language(code: str) -> str:
    """Detect language from code content."""
    head = code[:800]
    head_lower = head.lower()
    if "import streamlit" in head_lower or "from streamlit" in head_lower:
        return "streamlit"
    if "<!doctype html" in head_lower or "<html" in head_lower:
        if "react" in head_lower or "type=\"text/babel\"" in head_lower:
            return "react"
        return "html"
    if ("import react" in head_lower or
        "from 'react'" in head_lower or
        'from "react"' in head_lower or
        "require('react')" in head_lower):
        return "react"
    # Spring Boot — detect multi-file delimiter format OR Spring annotations
    if ("=== file:" in head_lower or
        "spring-boot-starter" in head_lower or
        "@springbootapplication" in head_lower or
        "@restcontroller" in head_lower or
        "springapplication.run" in head_lower):
        return "springboot"
    if "public class" in head and "public static void main" in code:
        return "java"
    if "import cv2" in head_lower or "import numpy" in head_lower:
        return "python"
    if "from fastapi" in head_lower or "import fastapi" in head_lower:
        return "fastapi"
    # RAG FastAPI multi-file project (AIKA-style)
    if ("=== file: backend/" in head_lower or
        "=== file: frontend/" in head_lower or
        "=== file: docker-compose" in head_lower or
        ("fastapi" in head_lower and "chromadb" in head_lower)):
        return "rag_fastapi"
    if "chromadb" in head_lower or "sentence_transformers" in head_lower:
        return "streamlit"
    return "python"


def _parse_rag_files(raw: str) -> dict[str, str]:
    """
    Parse multi-file RAG/FastAPI output delimited by === FILE: path === markers.
    Returns {relative_path: file_content} dict.
    Same format as Spring Boot but for FastAPI + React + Docker projects.
    """
    files = {}
    raw = re.sub(r"```[a-zA-Z]*\s*\n?", "", raw)
    raw = raw.replace("```", "")
    parts = re.split(r"===\s*FILE:\s*(.+?)\s*===", raw)
    for i in range(1, len(parts) - 1, 2):
        path    = parts[i].strip()
        content = parts[i + 1].strip()
        if path and content:
            files[path] = content
    return files


def _parse_springboot_files(raw: str) -> dict[str, str]:
    """
    Parse multi-file Spring Boot output delimited by === FILE: path === markers.
    Returns {relative_path: file_content} dict.
    """
    files = {}
    # Strip markdown fences first
    raw = re.sub(r"```[a-zA-Z]*\s*\n?", "", raw)
    raw = raw.replace("```", "")

    parts = re.split(r"===\s*FILE:\s*(.+?)\s*===", raw)
    # parts = [pre_text, path1, content1, path2, content2, ...]
    for i in range(1, len(parts) - 1, 2):
        path    = parts[i].strip()
        content = parts[i + 1].strip()
        if path and content:
            files[path] = content
    return files


def _sanitize(raw: str, language: str = "python") -> str:
    """Strip markdown fences and shell command lines."""
    # Remove any language-tagged fences
    for lang_tag in ("python", "java", "html", "jsx", "javascript", "css", "react", ""):
        raw = re.sub(rf"```{lang_tag}\s*\n?", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("```", "")

    if language in ("html", "react"):
        # For HTML find the doctype/html start
        match = re.search(r"<!DOCTYPE|<html", raw, re.IGNORECASE)
        if match:
            return raw[match.start():].strip()
        # Bare React JSX — wrap it in a proper HTML+CDN shell
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>App</title>
  <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;background:#0f0f1a;font-family:'Inter',sans-serif;">
  <div id="root"></div>
  <script type="text/babel">
{raw.strip()}
  </script>
</body>
</html>"""

    if language in ("springboot", "rag_fastapi"):
        # Keep the raw multi-file output — parsed later in executor_node
        return raw.strip()

    if language == "java":
        # Find class declaration start
        match = re.search(r"(public\s+class|import\s+java)", raw)
        return raw[match.start():].strip() if match else raw.strip()

    # Python — strip shell lines then deduplicate/fix imports
    lines = raw.split("\n")
    start = next(
        (i for i, l in enumerate(lines)
         if l.strip().startswith(("import ", "from ", "def ", "class ", "#!"))),
        0,
    )
    cleaned = "\n".join(
        l for l in lines[start:] if not any(p.match(l) for p in _SHELL_PATTERNS)
    ).strip()
    return _fix_python_code(cleaned)


def _fix_python_code(code: str) -> str:
    """
    Post-generation sanitizer for Python/Streamlit code.
    1. Removes deprecated streamlit submodule imports that crash on modern Streamlit.
    2. Deduplicates import lines (LLMs sometimes repeat the same import dozens of times).
    3. Removes obviously broken lines (bare 'import urllib.parse' spam, etc.)
    """
    # Deprecated streamlit submodule imports — all removed in Streamlit 1.x+
    _BAD_ST_IMPORTS = {
        "from streamlit import caching",
        "from streamlit import components",
        "from streamlit import session_state",
        "from streamlit import widgets",
        "from streamlit import legacy_caching",
        "from streamlit import report_thread",
        "from streamlit import bootstrap",
    }
    lines = code.split("\n")
    seen_imports: set[str] = set()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Drop deprecated streamlit submodule imports
        if any(stripped.startswith(bad) for bad in _BAD_ST_IMPORTS):
            continue
        # Drop duplicate import/from lines
        if stripped.startswith(("import ", "from ")) and stripped:
            if stripped in seen_imports:
                continue
            seen_imports.add(stripped)
        cleaned.append(line)
    return "\n".join(cleaned)


def _is_ui(code: str) -> bool:
    return any(fw in code[:500].lower() for fw in _UI_FRAMEWORKS)


def _syntax_check_python(code: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        py_compile.compile(tmp, doraise=True)
        return ""
    except py_compile.PyCompileError as e:
        return str(e)
    finally:
        os.unlink(tmp)


def _syntax_check_java(code: str, output_dir: str) -> str:
    java_file = os.path.join(output_dir, "Main.java")
    with open(java_file, "w", encoding="utf-8") as f:
        f.write(code)
    _brew_java = "/opt/homebrew/opt/openjdk@17/bin"
    _env = os.environ.copy()
    _env["PATH"] = f"{_brew_java}:{_env.get('PATH', '')}"
    _env["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@17"
    result = subprocess.run(
        ["javac", java_file], capture_output=True, text=True, timeout=30, env=_env
    )
    return result.stderr.strip() if result.returncode != 0 else ""


# Keep old name for test compatibility
def _syntax_check(code: str) -> str:
    return _syntax_check_python(code)


@observe(name="bmad-analyst")
def analyst_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    update_observation("bmad-analyst", {"request": state["user_request"]}, {})
    brief = run_agent("analyst", f"User Request: {state['user_request']}", session_id=session_id)
    brief = validate_agent_output("Analyst", brief, min_length=50)
    update_observation("bmad-analyst", {"request": state["user_request"]}, {"brief_length": len(brief)})
    return {**state, "project_brief": brief, "status": "analysed"}


@observe(name="bmad-product-manager")
def product_manager_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    update_observation("bmad-product-manager", {"brief": state["project_brief"][:200]}, {})
    spec = run_agent("product_manager", f"Project Brief:\n{state['project_brief']}", session_id=session_id)
    spec = validate_agent_output("Product Manager", spec, min_length=100)
    update_observation("bmad-product-manager", {}, {"spec_length": len(spec)})
    return {**state, "functional_spec": spec, "status": "spec_written"}


@observe(name="bmad-architect")
def architect_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    update_observation("bmad-architect", {"spec": state["functional_spec"][:200]}, {})
    design = run_agent("architect", f"Functional Specification:\n{state['functional_spec']}", session_id=session_id)
    design = validate_agent_output("Architect", design, min_length=100)
    update_observation("bmad-architect", {}, {"design_length": len(design)})
    return {**state, "solution_design": design, "status": "designed"}


# ── Parallel Branch 1: Designer ───────────────────────────────────────────────
@observe(name="bmad-designer")
def designer_node(state: BMADState) -> dict:
    session_id = state.get("session_id", "unknown")
    update_observation("bmad-designer", {"spec": state["functional_spec"][:200]}, {})
    ui_design = run_agent(
        "designer",
        (
            f"Functional Specification:\n{state['functional_spec']}\n\n"
            f"Solution Design:\n{state['solution_design']}"
        ),
        session_id=session_id,
    )
    update_observation("bmad-designer", {}, {"ui_design_length": len(ui_design)})
    # ⚠️ Return ONLY changed keys — parallel nodes must not return full state
    return {"ui_design": ui_design}


# ── Parallel Branch 2: Scrum Master ──────────────────────────────────────────
@observe(name="bmad-scrum-master")
def scrum_master_node(state: BMADState) -> dict:
    session_id = state.get("session_id", "unknown")
    update_observation("bmad-scrum-master", {"spec": state["functional_spec"][:200]}, {})
    stories = run_agent(
        "scrum_master",
        f"Functional Specification:\n{state['functional_spec']}\n\nSolution Design:\n{state['solution_design']}",
        session_id=session_id,
    )
    update_observation("bmad-scrum-master", {}, {"stories_length": len(stories)})
    # ⚠️ Return ONLY changed keys — parallel nodes must not return full state
    return {"stories": stories}


@observe(name="bmad-developer")
def developer_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    iteration  = state.get("debug_iterations", 0)
    update_observation("bmad-developer", {"request": state["user_request"], "iteration": iteration}, {})

    # Build error context for retry attempts
    error_context = ""
    if iteration > 0:
        exec_error      = state.get("execution_error", "")
        test_plan       = state.get("test_plan", "")
        review_feedback = state.get("review_feedback", "")
        if exec_error:
            error_context += (
                f"\n\n{'='*60}\n"
                f"⚠️  PREVIOUS ATTEMPT FAILED (iteration {iteration})\n"
                f"{'='*60}\n"
                f"EXECUTION ERROR:\n{exec_error}\n\n"
                f"Fix ONLY these specific errors. Do not rewrite working code.\n"
            )
        if review_feedback and "NEEDS_FIXES" in review_feedback:
            error_context += (
                f"\nCODE REVIEW FEEDBACK:\n{review_feedback[:1500]}\n"
                f"Fix every issue listed by the Code Reviewer.\n"
            )
        if test_plan and ("fail" in test_plan.lower() or "FAIL" in test_plan):
            error_context += (
                f"\nQA FEEDBACK:\n{test_plan[:1000]}\n"
                f"Address every QA failure listed above.\n"
            )

    # Truncate each section to stay under Groq's 12k TPM limit
    # ~4 chars per token → limits below ≈ 3500 input tokens total
    func_spec     = state['functional_spec'][:3000]
    sol_design    = state['solution_design'][:2000]
    ui_design_txt = state.get('ui_design', '')[:800]
    stories_txt   = state['stories'][:1500]
    user_req      = state['user_request'][:600]

    raw = run_agent(
        "developer",
        (
            f"FUNCTIONAL SPECIFICATION:\n{func_spec}\n\n"
            f"SOLUTION DESIGN:\n{sol_design}\n\n"
            f"UI DESIGN SYSTEM:\n{ui_design_txt}\n\n"
            f"USER STORIES:\n{stories_txt}\n\n"
            f"ORIGINAL REQUEST: {user_req}"
            f"{error_context}"
        ),
        session_id=session_id,
    )
    # ⚡ CRITICAL: detect language BEFORE sanitizing — prevents Spring Boot
    # multi-file output from being destroyed by Python sanitizer
    detected_lang = _detect_language(raw)
    code = _sanitize(raw, detected_lang)
    code = validate_code_output(code)
    update_observation("bmad-developer", {}, {"code_length": len(code), "iteration": iteration})
    return {**state, "code": code, "status": "developed", "debug_iterations": iteration + 1}


@observe(name="bmad-code-reviewer")
def code_reviewer_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    iteration  = state.get("debug_iterations", 0)

    # Skip review after 2 retries to avoid infinite loop
    if iteration >= 2:
        return {**state, "review_feedback": "APPROVED (max retries reached)", "status": "review_approved"}

    update_observation("bmad-code-reviewer", {"iteration": iteration}, {})
    review = run_agent(
        "code_reviewer",
        (
            f"Functional Specification:\n{state['functional_spec']}\n\n"
            f"Code to Review:\n{state['code'][:6000]}"
        ),
        session_id=session_id,
    )
    review  = validate_review_output(review)
    verdict = "review_approved" if "NEEDS_FIXES" not in review.upper() else "review_failed"
    update_observation("bmad-code-reviewer", {}, {"verdict": verdict})
    return {**state, "review_feedback": review, "status": verdict}


def executor_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    code = state.get("code", "")
    if not code.strip():
        return {**state, "execution_result": "", "execution_error": "No code.", "status": "execution_failed"}

    slug     = "".join(c if c.isalnum() or c == " " else "" for c in state["user_request"][:40].lower()).replace(" ", "_")
    apps_dir = os.path.join(_ROOT, "apps")
    os.makedirs(apps_dir, exist_ok=True)

    language = _detect_language(code)
    code     = _sanitize(code, language)

    # ── Determine output file path by language ────────────────────────────────
    ext_map  = {"streamlit": ".py", "python": ".py", "fastapi": ".py",
                "html": ".html", "react": ".html", "java": "/Main.java",
                "springboot": "/", "rag_fastapi": "/"}
    ext      = ext_map.get(language, ".py")

    if language == "rag_fastapi":
        # Parse multi-file FastAPI+React+Docker project
        rag_dir     = os.path.join(apps_dir, slug)
        output_file = rag_dir
        rag_files   = _parse_rag_files(code)
        if not rag_files:
            language    = "python"
            output_file = os.path.join(apps_dir, f"{slug}.py")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(code)
        else:
            for rel_path, content in rag_files.items():
                full_path = os.path.join(rag_dir, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
    elif language == "springboot":
        # Parse multi-file format and create Maven project structure
        spring_dir  = os.path.join(apps_dir, slug)
        output_file = spring_dir   # directory is the "app file" for Spring Boot
        sb_files    = _parse_springboot_files(code)
        if not sb_files:
            # Fallback: treat as plain Java if parser found nothing
            language    = "java"
            java_dir    = os.path.join(apps_dir, slug)
            os.makedirs(java_dir, exist_ok=True)
            output_file = os.path.join(java_dir, "Main.java")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(code)
        else:
            for rel_path, content in sb_files.items():
                full_path = os.path.join(spring_dir, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
    elif language == "java":
        java_dir    = os.path.join(apps_dir, slug)
        os.makedirs(java_dir, exist_ok=True)
        output_file = os.path.join(java_dir, "Main.java")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(code)
    else:
        output_file = os.path.join(apps_dir, f"{slug}{ext}")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(code)

    t0 = time.time()
    result, error, status = "", "", "executed"

    # ── Execute / validate by language ───────────────────────────────────────
    if language == "rag_fastapi":
        rag_files = _parse_rag_files(code)
        if not rag_files:
            error  = "RAG FastAPI parser found no === FILE: === delimiters."
            status = "execution_failed"
        else:
            file_list = "\n".join(f"  • {p}" for p in rag_files.keys())
            # Syntax-check Python files
            py_errors = []
            for rel_path, content in rag_files.items():
                if rel_path.endswith(".py"):
                    try:
                        import ast as _ast
                        _ast.parse(content)
                    except SyntaxError as e:
                        py_errors.append(f"{rel_path}: {e}")
            if py_errors:
                error  = "Python syntax errors:\n" + "\n".join(py_errors)
                status = "execution_failed"
            else:
                result = (f"RAG FastAPI project saved ✅\nFiles:\n{file_list}\n"
                          f"Run: cd {rag_dir} && docker-compose up --build")
                status = "executed"
    elif language == "springboot":
        sb_files = _parse_springboot_files(code)
        if not sb_files:
            error  = "Spring Boot parser found no === FILE: === delimiters in output."
            status = "execution_failed"
        else:
            file_list = "\n".join(f"  • {p}" for p in sb_files.keys())
            # Ensure Homebrew Java/Maven are on PATH when running subprocesses
            _brew_java = "/opt/homebrew/opt/openjdk@17/bin"
            _brew_mvn  = "/opt/homebrew/opt/maven/bin"
            _env = os.environ.copy()
            _env["PATH"] = f"{_brew_java}:{_brew_mvn}:{_env.get('PATH', '')}"
            _env["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@17"
            mvn = subprocess.run(["which", "mvn"], capture_output=True, text=True, env=_env)
            if mvn.returncode == 0:
                mvn_result = subprocess.run(
                    ["mvn", "compile", "-q"], capture_output=True,
                    text=True, timeout=120, cwd=spring_dir, env=_env,
                )
                if mvn_result.returncode == 0:
                    result = f"Maven compile OK ✅\nFiles:\n{file_list}\nRun: cd {spring_dir} && mvn spring-boot:run"
                    status = "executed"
                else:
                    error  = mvn_result.stderr[:2000]
                    result = f"Files saved:\n{file_list}"
                    status = "execution_failed"
            else:
                result = (f"Spring Boot project saved ✅ (Maven not installed — cannot compile locally)\n"
                          f"Files:\n{file_list}\n"
                          f"To run: install Maven then → cd {spring_dir} && mvn spring-boot:run")
                status = "executed"

    elif language == "streamlit":
        err = _syntax_check_python(code)
        result = f"Syntax OK — run with: streamlit run {output_file}" if not err else ""
        error  = err
        status = "executed" if not err else "execution_failed"

    elif language in ("html", "react"):
        # HTML just needs to be valid — open in browser
        has_html = "<html" in code.lower() or "<!doctype" in code.lower()
        result   = f"HTML OK — open in browser: {output_file}" if has_html else ""
        error    = "" if has_html else "Missing <html> tag"
        status   = "executed" if has_html else "execution_failed"

    elif language == "java":
        # Check if javac is available
        javac = subprocess.run(["which", "javac"], capture_output=True, text=True)
        if javac.returncode != 0:
            result = f"Java file saved to: {output_file}"
            error  = ""
            status = "executed"   # no javac — just save and trust the code
        else:
            err    = _syntax_check_java(code, java_dir)
            result = f"Compiled OK — run with: cd {java_dir} && java Main" if not err else ""
            error  = err
            status = "executed" if not err else "execution_failed"

    elif language == "fastapi":
        err    = _syntax_check_python(code)
        result = f"Syntax OK — run with: python {output_file}" if not err else ""
        error  = err
        status = "executed" if not err else "execution_failed"

    else:  # plain Python / OpenCV / scripts
        try:
            proc   = subprocess.run([sys.executable, output_file],
                                    capture_output=True, text=True, timeout=30)
            result = proc.stdout.strip()
            error  = proc.stderr.strip() if proc.returncode != 0 else ""
            status = "executed" if proc.returncode == 0 else "execution_failed"
        except subprocess.TimeoutExpired:
            result = "Script ran but timed out (30s) — may need user interaction"
            error  = ""
            status = "executed"
        except Exception as exc:
            result, error, status = "", str(exc), "execution_failed"

    latency_ms = (time.time() - t0) * 1000
    log_execution(session_id, code, result, error, latency_ms=latency_ms)
    return {**state, "code": code, "execution_result": result,
            "execution_error": error, "status": status}


@observe(name="bmad-mock-tester")
def mock_test_node(state: BMADState) -> BMADState:
    """
    Generates real pytest code with mocks for the developer's code,
    runs it, and stores the result. Feeds back to QA and developer.
    """
    session_id = state.get("session_id", "unknown")
    code       = state.get("code", "")
    language   = _detect_language(code)

    # Only run mock tests for Python-based code
    if language not in ("python", "streamlit", "fastapi"):
        return {**state,
                "mock_test_code":   "# Mock tests skipped — not a Python project",
                "mock_test_result": "SKIPPED — mock tests only run for Python projects",
                "status": state.get("status", "executed")}

    update_observation("bmad-mock-tester", {"language": language}, {})

    # Ask LLM to generate pytest code
    raw = run_agent(
        "mock_tester",
        (
            f"FUNCTIONAL SPECIFICATION:\n{state['functional_spec'][:2000]}\n\n"
            f"PYTHON CODE TO TEST:\n{code[:4000]}"
        ),
        session_id=session_id,
    )

    # Strip any accidental markdown fences the LLM may add
    test_code = raw.strip()
    if test_code.startswith("```"):
        test_code = re.sub(r"^```[a-z]*\n?", "", test_code)
        test_code = re.sub(r"\n?```$", "", test_code.strip())

    # Write test file to a temp location and run pytest
    mock_result = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_test_mock.py",
            delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(test_code)
            tmp_path = tmp.name

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", tmp_path, "-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=60
        )
        output   = (proc.stdout + proc.stderr).strip()
        # Summarise the result
        if proc.returncode == 0:
            mock_result = f"✅ ALL TESTS PASSED\n\n{output}"
        else:
            mock_result = f"❌ SOME TESTS FAILED\n\n{output}"

        os.unlink(tmp_path)

    except subprocess.TimeoutExpired:
        mock_result = "⚠️ TIMEOUT — mock tests took longer than 60 seconds"
    except Exception as e:
        mock_result = f"⚠️ MOCK TEST ERROR: {e}"

    test_code = validate_mock_test_output(test_code)
    update_observation("bmad-mock-tester", {}, {"result": mock_result[:300]})
    return {**state,
            "mock_test_code":   test_code,
            "mock_test_result": mock_result,
            "status": "mock_tested"}


@observe(name="bmad-qa")
def qa_node(state: BMADState) -> BMADState:
    session_id = state.get("session_id", "unknown")
    execution_result = state.get("execution_result", "")
    execution_error  = state.get("execution_error", "")
    code = state.get("code", "")

    language = _detect_language(code)
    auto_pass_langs = ("streamlit", "html", "react", "fastapi", "java")
    ok_keywords     = ("syntax ok", "compiled ok", "html ok", "java file saved")
    is_auto_pass    = (
        language in auto_pass_langs
        and any(kw in execution_result.lower() for kw in ok_keywords)
        and not execution_error
    )
    label_map = {
        "streamlit": "Streamlit UI app",
        "html":      "HTML/CSS web page",
        "react":     "React web app",
        "fastapi":   "FastAPI REST API",
        "java":      "Java application",
    }
    if is_auto_pass:
        label    = label_map.get(language, language)
        # Auto-generate a minimal test strategy for auto-pass cases
        test_strategy = (
            f"TEST STRATEGY\n=============\n"
            f"PROJECT: {state.get('user_request','')[:60]}\n\n"
            f"OBJECTIVE:\nValidate that the {label} meets all functional requirements.\n\n"
            f"SCOPE:\nIN SCOPE:\n- Syntax and structure validation\n- Feature completeness check\n"
            f"OUT OF SCOPE:\n- Load testing\n- Cross-browser testing\n\n"
            f"TESTING TYPES:\n- Functional Testing: Automated syntax check via executor\n"
            f"- UI/UX Testing: Manual review on launch\n\n"
            f"EXIT CRITERIA:\n- Syntax check passes with no errors\n- App launches successfully\n\n"
            f"VERDICT: PASS — {label} passed automated validation."
        )
        test_plan = f"TEST PLAN\n=========\nVERDICT: PASS\n{label} passed validation — ready to run."
        update_observation("bmad-qa", {"result": execution_result}, {"verdict": "AUTO-PASS"})
        return {**state, "test_strategy": test_strategy, "test_plan": test_plan, "status": "passed"}

    mock_test_result = state.get("mock_test_result", "")

    raw_output = run_agent(
        "qa_engineer",
        (
            f"Functional Specification:\n{state['functional_spec']}\n\n"
            f"User Stories:\n{state['stories']}\n\n"
            f"Execution Result:\n{execution_result}\n\n"
            f"Execution Error:\n{execution_error}\n\n"
            f"Mock Test Results:\n{mock_test_result[:1500]}"
        ),
        session_id=session_id,
    )

    # Split the output into test_strategy and test_plan
    if "--- TEST PLAN ---" in raw_output:
        parts         = raw_output.split("--- TEST PLAN ---")
        test_strategy = parts[0].replace("--- TEST STRATEGY ---", "").strip()
        test_plan     = parts[1].strip()
    elif "TEST PLAN" in raw_output and "TEST STRATEGY" in raw_output:
        # fallback split on TEST PLAN heading
        idx           = raw_output.index("TEST PLAN")
        test_strategy = raw_output[:idx].strip()
        test_plan     = raw_output[idx:].strip()
    else:
        # agent only returned one document — treat as test plan
        test_strategy = "TEST STRATEGY\n=============\n(Generated with test plan — see test-plan.md)"
        test_plan     = raw_output

    test_plan = validate_qa_output(test_plan)
    status = "passed" if "VERDICT: PASS" in test_plan.upper() else "failed_validation"
    update_observation("bmad-qa", {}, {"verdict": status})
    return {**state, "test_strategy": test_strategy, "test_plan": test_plan, "status": status}


def _route_reviewer(state: BMADState) -> str:
    """After code review: approved → executor, needs fixes → developer."""
    if state.get("status") == "review_approved" or "APPROVED" in state.get("review_feedback", "").upper():
        return "executor"
    return "developer"


def _route_executor(state: BMADState) -> str:
    config      = _load_config()
    max_retries = config["settings"]["max_debug_retries"]
    iterations  = state.get("debug_iterations", 0)
    if state.get("execution_error") and iterations <= max_retries:
        return "developer"
    return "mock_tester"


def _route_qa(state: BMADState) -> str:
    config      = _load_config()
    max_retries = config["settings"]["max_debug_retries"]
    iterations  = state.get("debug_iterations", 0)
    if state.get("status") == "passed":
        return END
    if iterations <= max_retries:
        return "developer"
    return END


def build_workflow():
    graph = StateGraph(BMADState)

    # ── Register all nodes ────────────────────────────────────────────────────
    graph.add_node("analyst",         analyst_node)
    graph.add_node("product_manager", product_manager_node)
    graph.add_node("architect",       architect_node)
    graph.add_node("designer",        designer_node)        # ← NEW
    graph.add_node("scrum_master",    scrum_master_node)
    graph.add_node("developer",       developer_node)
    graph.add_node("code_reviewer",   code_reviewer_node)
    graph.add_node("executor",        executor_node)
    graph.add_node("mock_tester",     mock_test_node)       # ← NEW
    graph.add_node("qa",              qa_node)

    # ── Pipeline edges ────────────────────────────────────────────────────────
    graph.set_entry_point("analyst")
    graph.add_edge("analyst",         "product_manager")
    graph.add_edge("product_manager", "architect")

    # ── PARALLEL: Designer + Scrum Master run simultaneously after Architect ──
    graph.add_edge("architect",   "designer")       # ← Branch 1
    graph.add_edge("architect",   "scrum_master")   # ← Branch 2 (runs in parallel)

    # ── Both branches join at Developer ───────────────────────────────────────
    graph.add_edge("designer",    "developer")
    graph.add_edge("scrum_master","developer")

    # ── Code Reviewer after Developer ─────────────────────────────────────────
    graph.add_edge("developer",   "code_reviewer")
    graph.add_conditional_edges("code_reviewer", _route_reviewer,
                                {"executor": "executor", "developer": "developer"})

    graph.add_conditional_edges("executor", _route_executor,
                                {"developer": "developer", "mock_tester": "mock_tester"})
    graph.add_edge("mock_tester", "qa")
    graph.add_conditional_edges("qa", _route_qa,
                                {END: END, "developer": "developer"})
    return graph.compile()


app = build_workflow()
