from typing import TypedDict, Optional


class BMADState(TypedDict):
    session_id: str
    user_request: str
    project_brief: str
    functional_spec: str
    solution_design: str
    ui_design: str
    stories: str
    code: str
    review_feedback: str
    mock_test_code: str
    mock_test_result: str
    test_strategy: str
    test_plan: str
    execution_result: str
    execution_error: str
    debug_iterations: int
    status: str
    # ── Complexity Scorer (NEW) ────────────────────────────────────────────
    complexity_score: Optional[int]
    complexity_reason: Optional[str]
    complexity_model_override: Optional[str]
    # ── Validator (NEW) ───────────────────────────────────────────────────
    validation_passed: Optional[bool]
    validation_error: Optional[str]
    validation_attempts: Optional[int]
    # ── EvalAgent (NEW) ───────────────────────────────────────────────────
    eval_scores: Optional[dict]
