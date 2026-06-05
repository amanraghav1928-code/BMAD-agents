"""
core/validator.py
────────────────────────────────────────────────────────────────────────────────
Deterministic static analysis validator — NO LLM needed.
Adapted from Saanvi's validator to support all BMAD languages:
  - Python (Streamlit / FastAPI)
  - Java / Spring Boot
  - HTML / React

Runs after Developer, before Mock Tester.
Returns (passed: bool, error_message: str)
────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from typing import Any


# ─── PYTHON / STREAMLIT VALIDATION ───────────────────────────────────────────

_PYTHON_DISALLOWED = [
    "Jinja2Templates", "from jinja2",
    "import chromadb", "from chromadb",
    "import pinecone", "from pinecone",
]

_STUB_PATTERNS = [
    "pass  # TODO", "# TODO:", "raise NotImplementedError",
    "pass  # implement", "# placeholder", "pass  # stub",
]


def validate_python(code: str) -> tuple[bool, str]:
    """Validate Python code — syntax, compile, no stubs, no disallowed libs."""

    # 1. AST syntax check
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError on line {e.lineno}: {e.msg}\n  >> {e.text}"

    # 2. py_compile check
    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", tmp.name],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            err = result.stderr.strip().replace(tmp.name, "generated_app.py")
            return False, f"Compile error:\n{err}"
    except subprocess.TimeoutExpired:
        return False, "Compile check timed out."
    finally:
        os.unlink(tmp.name)

    # 3. No stub implementations
    found = [p for p in _STUB_PATTERNS if p in code]
    if found:
        return False, f"Incomplete implementation: {found[0]!r}. Fully implement all functions."

    # 4. No disallowed libraries
    found_bad = [d for d in _PYTHON_DISALLOWED if d in code]
    if found_bad:
        return False, f"Disallowed libraries: {', '.join(found_bad)}"

    # 5. No duplicate imports
    lines = code.split("\n")
    imports = [l.strip() for l in lines if l.strip().startswith(("import ", "from "))]
    seen = set()
    for imp in imports:
        if imp in seen:
            return False, f"Duplicate import: '{imp}'. Each module must be imported exactly once."
        seen.add(imp)

    return True, "Python validation passed."


# ─── SPRING BOOT / JAVA VALIDATION ───────────────────────────────────────────

def validate_springboot(code: str) -> tuple[bool, str]:
    """Validate Spring Boot multi-file output."""

    # 1. Must use === FILE: === delimiters
    if "=== FILE:" not in code and "=== file:" not in code.lower():
        return False, (
            "Spring Boot output missing === FILE: path === delimiters. "
            "Developer must output multi-file format."
        )

    # 2. Must have pom.xml
    if "pom.xml" not in code:
        return False, "Missing pom.xml in Spring Boot output."

    # 3. Must have Application.java
    if "Application.java" not in code and "application" not in code.lower():
        return False, "Missing main Application.java entry point."

    # 4. Must have spring-boot-starter-web dependency
    if "spring-boot-starter-web" not in code:
        return False, "Missing spring-boot-starter-web dependency in pom.xml."

    # 5. No stub implementations
    found = [p for p in _STUB_PATTERNS if p in code]
    if found:
        return False, f"Incomplete implementation: {found[0]!r}. Fully implement all methods."

    # 6. Must have at least one @RestController
    if "@RestController" not in code:
        return False, "Missing @RestController — no REST endpoints defined."

    return True, "Spring Boot validation passed."


def validate_java(code: str) -> tuple[bool, str]:
    """Validate plain Java code."""
    if "public class" not in code:
        return False, "Missing public class definition."
    if "public static void main" not in code:
        return False, "Missing main() entry point."
    found = [p for p in _STUB_PATTERNS if p in code]
    if found:
        return False, f"Incomplete implementation: {found[0]!r}."
    return True, "Java validation passed."


# ─── HTML / REACT VALIDATION ─────────────────────────────────────────────────

def validate_html(code: str) -> tuple[bool, str]:
    """Validate HTML/React output."""
    lower = code.lower()
    if "<!doctype html" not in lower and "<html" not in lower:
        return False, "Missing <!DOCTYPE html> or <html> tag."
    if "<body" not in lower:
        return False, "Missing <body> tag."
    if "TODO" in code or "placeholder" in code.lower():
        return False, "Placeholder content found — implement all sections fully."
    return True, "HTML validation passed."


# ─── MAIN VALIDATOR ───────────────────────────────────────────────────────────

def validate(code: str, language: str) -> tuple[bool, str]:
    """Route to correct validator based on detected language."""
    if not code or not code.strip():
        return False, "Empty code output — developer produced nothing."

    if language == "springboot":
        return validate_springboot(code)
    elif language == "java":
        return validate_java(code)
    elif language in ("html", "react"):
        return validate_html(code)
    else:  # python, streamlit, fastapi
        return validate_python(code)


def validator_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node — runs after developer_node."""
    from core.workflow import _detect_language
    code     = state.get("code", "")
    language = _detect_language(code)
    passed, message = validate(code, language)

    state["validation_passed"]  = passed
    state["validation_error"]   = None if passed else message
    state["validation_attempts"] = state.get("validation_attempts", 0) + (0 if passed else 1)

    if passed:
        print(f"\n  ✅ [Validator] PASSED ({language})")
    else:
        print(f"\n  ❌ [Validator] FAILED ({language}) — sending back to Developer")
        print(f"     Reason: {message}")

    return state


def should_fix(state: dict[str, Any]) -> str:
    """Routing: passed → continue, failed → fix (max 2 retries)."""
    if state.get("validation_passed"):
        return "passed"
    if state.get("validation_attempts", 0) > 2:
        print("\n  [Validator] Max retries reached — proceeding anyway.")
        return "max_attempts"
    return "fix"
