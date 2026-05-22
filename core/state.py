from typing import TypedDict


class BMADState(TypedDict):
    session_id: str
    user_request: str
    project_brief: str
    functional_spec: str
    solution_design: str
    ui_design: str          # ← Designer Agent output
    stories: str
    code: str
    review_feedback: str    # ← Code Reviewer output
    mock_test_code:   str    # ← Mock Tester: actual pytest code with mocks
    mock_test_result: str    # ← Mock Tester: pytest run output (PASSED/FAILED)
    test_strategy: str       # ← QA Engineer: HOW we test (written first)
    test_plan: str           # ← QA Engineer: WHAT we tested (written after)
    execution_result: str
    execution_error: str
    debug_iterations: int
    status: str
