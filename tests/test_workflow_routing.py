"""
Tests for orchestrator/workflow.py
------------------------------------
Covers: _sanitize, _is_ui, _syntax_check,
        _route_executor, _route_qa node routing logic.
"""

import os
import sys
import unittest
from langgraph.graph import END

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflow import _sanitize, _is_ui, _syntax_check, _route_executor, _route_qa

# ---------------------------------------------------------------------------
# _sanitize
# ---------------------------------------------------------------------------

class TestSanitize(unittest.TestCase):
    def test_strips_python_fence(self):
        raw = "```python\nimport streamlit as st\nst.title('Hi')\n```"
        result = _sanitize(raw)
        self.assertNotIn("```", result)
        self.assertIn("import streamlit", result)

    def test_strips_plain_fence(self):
        raw = "Here is your code:\n```\nimport os\nprint(os.getcwd())\n```"
        result = _sanitize(raw)
        self.assertNotIn("```", result)
        self.assertIn("import os", result)

    def test_strips_shell_commands(self):
        raw = "import streamlit as st\nstreamlit run app.py\nst.write('hello')"
        result = _sanitize(raw)
        self.assertNotIn("streamlit run", result)
        self.assertIn("import streamlit", result)

    def test_strips_pip_install(self):
        raw = "import pandas as pd\npip install pandas\ndf = pd.DataFrame()"
        result = _sanitize(raw)
        self.assertNotIn("pip install", result)
        self.assertIn("import pandas", result)

    def test_strips_dollar_prompt(self):
        raw = "import os\n$ python app.py\nprint('done')"
        result = _sanitize(raw)
        self.assertNotIn("$ python", result)

    def test_strips_preamble_prose(self):
        raw = "Sure! Here is the code:\nHere you go:\nimport streamlit as st\nst.write('hi')"
        result = _sanitize(raw)
        self.assertFalse(result.startswith("Sure"))
        self.assertTrue(result.startswith("import"))

    def test_clean_code_unchanged(self):
        code = "import streamlit as st\n\nst.title('App')\nst.write('Hello world')"
        result = _sanitize(code)
        self.assertEqual(result.strip(), code.strip())

    def test_empty_string(self):
        result = _sanitize("")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _is_ui
# ---------------------------------------------------------------------------

class TestIsUi(unittest.TestCase):
    def test_detects_streamlit(self):
        code = "import streamlit as st\nst.title('App')"
        self.assertTrue(_is_ui(code))

    def test_detects_gradio(self):
        code = "import gradio as gr\napp = gr.Interface(fn=fn, inputs='text', outputs='text')"
        self.assertTrue(_is_ui(code))

    def test_detects_dash(self):
        code = "import dash\nfrom dash import dcc, html"
        self.assertTrue(_is_ui(code))

    def test_detects_flask(self):
        code = "from flask import Flask\napp = Flask(__name__)"
        self.assertTrue(_is_ui(code))

    def test_detects_fastapi(self):
        code = "from fastapi import FastAPI\napp = FastAPI()"
        self.assertTrue(_is_ui(code))

    def test_non_ui_returns_false(self):
        code = "import math\nprint(math.pi)"
        self.assertFalse(_is_ui(code))

    def test_only_checks_first_500_chars(self):
        # UI keyword appears after 500 chars — should NOT be detected
        padding = "# " + "x" * 498 + "\n"
        code = padding + "import streamlit as st"
        self.assertFalse(_is_ui(code))


# ---------------------------------------------------------------------------
# _syntax_check
# ---------------------------------------------------------------------------

class TestSyntaxCheck(unittest.TestCase):
    def test_valid_code_returns_empty(self):
        code = "import os\nprint(os.getcwd())"
        self.assertEqual(_syntax_check(code), "")

    def test_invalid_code_returns_error(self):
        code = "def broken(\n    print('oops')"
        result = _syntax_check(code)
        self.assertNotEqual(result, "")
        self.assertIsInstance(result, str)

    def test_valid_streamlit_code_returns_empty(self):
        code = (
            "import streamlit as st\n"
            "st.title('Hello')\n"
            "st.write('World')\n"
        )
        self.assertEqual(_syntax_check(code), "")

    def test_syntax_error_message_is_descriptive(self):
        code = "x = (1 + 2"  # unclosed parenthesis
        result = _syntax_check(code)
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# _route_executor
# ---------------------------------------------------------------------------

class TestRouteExecutor(unittest.TestCase):
    def _state(self, error="", debug_iterations=0, status="executed"):
        return {
            "user_request": "build something",
            "project_brief": "",
            "functional_spec": "",
            "solution_design": "",
            "stories": "",
            "code": "",
            "test_plan": "",
            "execution_result": "",
            "execution_error": error,
            "debug_iterations": debug_iterations,
            "status": status,
        }

    def test_no_error_routes_to_qa(self):
        state = self._state(error="", status="executed")
        result = _route_executor(state)
        self.assertEqual(result, "qa")

    def test_error_first_iteration_routes_to_developer(self):
        state = self._state(error="SyntaxError: invalid syntax", debug_iterations=0)
        result = _route_executor(state)
        self.assertEqual(result, "developer")

    def test_error_second_iteration_routes_to_developer(self):
        state = self._state(error="NameError: name 'x' is not defined", debug_iterations=1)
        result = _route_executor(state)
        self.assertEqual(result, "developer")

    def test_error_max_retries_exceeded_routes_to_qa(self):
        # max_debug_retries = 2 per config/workflow.yaml
        state = self._state(error="still broken", debug_iterations=2)
        result = _route_executor(state)
        self.assertEqual(result, "qa")

    def test_empty_error_string_routes_to_qa(self):
        state = self._state(error="")
        result = _route_executor(state)
        self.assertEqual(result, "qa")


# ---------------------------------------------------------------------------
# _route_qa
# ---------------------------------------------------------------------------

class TestRouteQa(unittest.TestCase):
    def _state(self, status="passed", error="", debug_iterations=0):
        return {
            "user_request": "build something",
            "project_brief": "",
            "functional_spec": "",
            "solution_design": "",
            "stories": "",
            "code": "",
            "test_plan": "",
            "execution_result": "",
            "execution_error": error,
            "debug_iterations": debug_iterations,
            "status": status,
        }

    def test_passed_routes_to_end(self):
        state = self._state(status="passed")
        result = _route_qa(state)
        self.assertEqual(result, END)

    def test_failed_with_error_and_retries_left_routes_to_developer(self):
        state = self._state(status="failed_validation", error="some error", debug_iterations=0)
        result = _route_qa(state)
        self.assertEqual(result, "developer")

    def test_failed_with_error_max_retries_routes_to_end(self):
        state = self._state(status="failed_validation", error="still failing", debug_iterations=2)
        result = _route_qa(state)
        self.assertEqual(result, END)

    def test_failed_no_error_routes_to_end(self):
        state = self._state(status="failed_validation", error="")
        result = _route_qa(state)
        self.assertEqual(result, END)


if __name__ == "__main__":
    unittest.main()
