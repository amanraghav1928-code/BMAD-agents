"""
Tests for orchestrator/state.py
---------------------------------
Covers: BMADState TypedDict structure, field types,
        default values used in main.py, state spreading.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.state import BMADState


class TestBMADStateFields(unittest.TestCase):
    """All required fields are present in the TypedDict."""

    REQUIRED_FIELDS = [
        "user_request",
        "project_brief",
        "functional_spec",
        "solution_design",
        "stories",
        "code",
        "test_plan",
        "execution_result",
        "execution_error",
        "debug_iterations",
        "status",
    ]

    def _make_state(self) -> BMADState:
        return {
            "user_request": "Build a to-do app",
            "project_brief": "",
            "functional_spec": "",
            "solution_design": "",
            "stories": "",
            "code": "",
            "test_plan": "",
            "execution_result": "",
            "execution_error": "",
            "debug_iterations": 0,
            "status": "pending",
        }

    def test_all_fields_present(self):
        state = self._make_state()
        for field in self.REQUIRED_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, state)

    def test_field_count(self):
        state = self._make_state()
        self.assertEqual(len(state), len(self.REQUIRED_FIELDS))

    def test_string_fields(self):
        state = self._make_state()
        string_fields = [f for f in self.REQUIRED_FIELDS if f != "debug_iterations"]
        for field in string_fields:
            with self.subTest(field=field):
                self.assertIsInstance(state[field], str)

    def test_debug_iterations_is_int(self):
        state = self._make_state()
        self.assertIsInstance(state["debug_iterations"], int)

    def test_status_default_is_pending(self):
        state = self._make_state()
        self.assertEqual(state["status"], "pending")

    def test_debug_iterations_default_is_zero(self):
        state = self._make_state()
        self.assertEqual(state["debug_iterations"], 0)


class TestBMADStateSpread(unittest.TestCase):
    """Agents update state immutably using {**state, key: value} pattern."""

    def _make_state(self, **overrides) -> BMADState:
        base = {
            "user_request": "Build a dashboard",
            "project_brief": "",
            "functional_spec": "",
            "solution_design": "",
            "stories": "",
            "code": "",
            "test_plan": "",
            "execution_result": "",
            "execution_error": "",
            "debug_iterations": 0,
            "status": "pending",
        }
        return {**base, **overrides}

    def test_spread_preserves_other_fields(self):
        state = self._make_state()
        updated = {**state, "project_brief": "A dashboard for sales", "status": "analysed"}
        self.assertEqual(updated["user_request"], "Build a dashboard")
        self.assertEqual(updated["project_brief"], "A dashboard for sales")
        self.assertEqual(updated["status"], "analysed")

    def test_spread_does_not_mutate_original(self):
        state = self._make_state()
        _ = {**state, "status": "analysed"}
        self.assertEqual(state["status"], "pending")

    def test_debug_iterations_increment(self):
        state = self._make_state(debug_iterations=1)
        updated = {**state, "debug_iterations": state["debug_iterations"] + 1}
        self.assertEqual(updated["debug_iterations"], 2)
        self.assertEqual(state["debug_iterations"], 1)  # original unchanged

    def test_status_transitions(self):
        transitions = [
            "pending",
            "analysed",
            "spec_written",
            "designed",
            "stories_created",
            "developed",
            "executed",
            "passed",
        ]
        state = self._make_state()
        for status in transitions:
            with self.subTest(status=status):
                updated = {**state, "status": status}
                self.assertEqual(updated["status"], status)


class TestBMADStateAnnotations(unittest.TestCase):
    """Verify TypedDict annotations are correctly defined."""

    def test_annotations_exist(self):
        annotations = BMADState.__annotations__
        self.assertIsNotNone(annotations)

    def test_string_annotations(self):
        annotations = BMADState.__annotations__
        string_fields = [
            "user_request", "project_brief", "functional_spec",
            "solution_design", "stories", "code", "test_plan",
            "execution_result", "execution_error", "status",
        ]
        for field in string_fields:
            with self.subTest(field=field):
                self.assertIn(field, annotations)
                self.assertEqual(annotations[field], str)

    def test_int_annotation(self):
        annotations = BMADState.__annotations__
        self.assertIn("debug_iterations", annotations)
        self.assertEqual(annotations["debug_iterations"], int)


if __name__ == "__main__":
    unittest.main()
