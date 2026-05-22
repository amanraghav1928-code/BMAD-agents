"""
Guardrails
==========
Input and output safety checks for the BMAD pipeline.

  INPUT  GUARDRAILS  → validate what the user sends in
  OUTPUT GUARDRAILS  → validate what each agent returns

Each check raises GuardrailError on failure or returns a
(passed: bool, message: str) tuple when used as a soft check.
"""

import re


# ── Custom exception ──────────────────────────────────────────────────────────

class GuardrailError(Exception):
    """Raised when a guardrail check fails and the pipeline must stop."""
    def __init__(self, rule: str, message: str):
        self.rule    = rule
        self.message = message
        super().__init__(f"[GUARDRAIL:{rule}] {message}")


# ═══════════════════════════════════════════════════════════════════════════════
# INPUT GUARDRAILS
# ═══════════════════════════════════════════════════════════════════════════════

_HARMFUL_KEYWORDS = [
    "hack", "malware", "virus", "ransomware", "phishing",
    "ddos", "exploit", "keylogger", "rootkit", "spyware",
    "bomb", "weapon", "illegal", "porn", "nude",
]

_GREETINGS = [
    r"^hi\b", r"^hello\b", r"^hey\b", r"^what'?s up",
    r"^how are you", r"^good morning", r"^good evening",
    r"^test$", r"^ok$", r"^okay$",
]


def validate_input(user_request: str) -> str:
    """
    Run all input guardrails on the user's request.
    Returns the (possibly cleaned) request string if all checks pass.
    Raises GuardrailError if any check fails.
    """
    request = user_request.strip()

    # ── GR-I-01: Empty input ─────────────────────────────────────────────────
    if not request:
        raise GuardrailError(
            "GR-I-01",
            "Request is empty. Please describe what you want to build."
        )

    # ── GR-I-02: Too short ───────────────────────────────────────────────────
    if len(request) < 10:
        raise GuardrailError(
            "GR-I-02",
            f"Request is too short ({len(request)} chars). "
            "Please describe your project in at least a sentence."
        )

    # ── GR-I-03: Greeting / non-build input ─────────────────────────────────
    lower = request.lower()
    for pattern in _GREETINGS:
        if re.search(pattern, lower):
            raise GuardrailError(
                "GR-I-03",
                "That looks like a greeting, not a build request. "
                "Try: 'Build a to-do app with Streamlit' or 'Create a BMI calculator'."
            )

    # ── GR-I-04: Harmful content ─────────────────────────────────────────────
    for kw in _HARMFUL_KEYWORDS:
        if kw in lower:
            raise GuardrailError(
                "GR-I-04",
                f"Request contains potentially harmful content ('{kw}'). "
                "BMAD only builds legitimate software applications."
            )

    # ── GR-I-05: Too long — truncate with warning ────────────────────────────
    MAX_LEN = 2000
    if len(request) > MAX_LEN:
        print(f"\n  ⚠️  [GR-I-05] Request truncated from {len(request)} → {MAX_LEN} chars "
              f"to stay within token limits.\n")
        request = request[:MAX_LEN]

    # ── GR-I-06: Normalize natural descriptions into build requests ──────────
    # Instead of blocking, we AUTO-PREPEND "Build a " so users can describe
    # their app naturally without being forced to start with a magic keyword.
    # We only block if the input is clearly NOT an app description (handled
    # by GR-I-03 above for greetings/single words).
    build_prefixes = [
        "build", "create", "make", "develop", "write", "generate",
        "design", "implement",
    ]
    app_nouns = [
        "app", "tool", "system", "dashboard", "website", "api",
        "calculator", "tracker", "manager", "bot", "assistant", "platform",
        "portal", "service", "utility", "game", "simulator", "checker",
        "analyzer", "monitor", "viewer", "editor", "generator", "converter",
    ]
    has_prefix = any(lower.startswith(kw) or f" {kw} " in lower for kw in build_prefixes)
    has_noun   = any(kw in lower for kw in app_nouns)

    if not has_prefix and not has_noun:
        # Looks like a description without build intent — auto-wrap it
        request = f"Build a {request}"
        print(f"\n  ℹ️  [GR-I-06] Auto-normalized: prepended 'Build a ' to your request.\n")

    return request


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT GUARDRAILS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_agent_output(agent_name: str, output: str,
                           min_length: int = 50) -> str:
    """
    Generic output guardrail — checks any agent's text output.
    Returns the output if valid, raises GuardrailError otherwise.
    """

    # ── GR-O-01: Empty output ────────────────────────────────────────────────
    if not output or not output.strip():
        raise GuardrailError(
            "GR-O-01",
            f"{agent_name} returned an empty response. "
            "The LLM may have been rate-limited or the prompt was too long."
        )

    # ── GR-O-02: Output too short ────────────────────────────────────────────
    if len(output.strip()) < min_length:
        raise GuardrailError(
            "GR-O-02",
            f"{agent_name} output is suspiciously short "
            f"({len(output.strip())} chars, min {min_length}). "
            "The agent may have returned a partial response."
        )

    return output.strip()


def validate_code_output(code: str) -> str:
    """
    Output guardrail specifically for the Developer agent.
    Ensures the returned string is actual code, not empty or just comments.
    """
    code = validate_agent_output("Developer", code, min_length=100)

    # ── GR-O-03: No real code lines ──────────────────────────────────────────
    real_lines = [
        ln for ln in code.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if len(real_lines) < 5:
        raise GuardrailError(
            "GR-O-03",
            f"Developer output has only {len(real_lines)} non-comment lines. "
            "Expected real code with at least 5 executable lines."
        )

    # ── GR-O-04: Markdown fences still present ───────────────────────────────
    if "```" in code:
        raise GuardrailError(
            "GR-O-04",
            "Developer output still contains markdown code fences (```). "
            "Sanitizer may have failed — check _sanitize()."
        )

    return code


def validate_review_output(review: str) -> str:
    """
    Output guardrail for Code Reviewer agent.
    Must contain a clear APPROVED or NEEDS_FIXES verdict.
    """
    review = validate_agent_output("Code Reviewer", review, min_length=30)

    # ── GR-O-05: No verdict found ────────────────────────────────────────────
    upper = review.upper()
    if "APPROVED" not in upper and "NEEDS_FIXES" not in upper and "NEEDS FIXES" not in upper:
        # Soft warning — don't crash, just log
        print("  ⚠️  [GR-O-05] Code Reviewer didn't include APPROVED or NEEDS_FIXES. "
              "Defaulting to APPROVED.")
    return review


def validate_mock_test_output(test_code: str) -> str:
    """
    Output guardrail for Mock Tester agent.
    Ensures the output is actual pytest code.
    """
    # Mock tests are optional for non-Python — skip validation for skip messages
    if test_code.strip().startswith("# Mock tests skipped"):
        return test_code

    test_code = validate_agent_output("Mock Tester", test_code, min_length=50)

    # ── GR-O-06: No test functions found ─────────────────────────────────────
    if "def test_" not in test_code:
        raise GuardrailError(
            "GR-O-06",
            "Mock Tester output contains no test functions (def test_...). "
            "The agent did not generate valid pytest code."
        )

    # ── GR-O-07: No assert statements ────────────────────────────────────────
    if "assert" not in test_code:
        raise GuardrailError(
            "GR-O-07",
            "Mock test code has no assert statements. "
            "Tests without assertions don't actually verify anything."
        )

    return test_code


def validate_qa_output(test_plan: str) -> str:
    """
    Output guardrail for QA Engineer agent.
    Must contain a VERDICT line.
    """
    test_plan = validate_agent_output("QA Engineer", test_plan, min_length=50)

    # ── GR-O-08: No verdict ──────────────────────────────────────────────────
    if "VERDICT" not in test_plan.upper():
        print("  ⚠️  [GR-O-08] QA output missing VERDICT line. "
              "Treating as inconclusive.")
    return test_plan


# ═══════════════════════════════════════════════════════════════════════════════
# GUARDRAIL REPORT  (pretty print for terminal)
# ═══════════════════════════════════════════════════════════════════════════════

def print_guardrail_error(e: GuardrailError) -> None:
    print("\n" + "=" * 65)
    print(f"  🚫 GUARDRAIL BLOCKED  [{e.rule}]")
    print("=" * 65)
    print(f"  {e.message}")
    print("=" * 65 + "\n")
