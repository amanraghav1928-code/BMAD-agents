"""
Tests for templates/*.md files
--------------------------------
Verifies both template markdown files exist, are non-empty,
and contain all required placeholder sections.
"""

import os
import sys
import unittest
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")

TEMPLATES = {
    "functional_spec": "templates/functional_spec_template.md",
    "solution_design": "templates/solution_design_template.md",
}


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), "r", encoding="utf-8") as f:
        return f.read()


class TestTemplateFilesExist(unittest.TestCase):
    def test_functional_spec_template_exists(self):
        path = os.path.join(_ROOT, TEMPLATES["functional_spec"])
        self.assertTrue(os.path.isfile(path), f"Missing: {path}")

    def test_solution_design_template_exists(self):
        path = os.path.join(_ROOT, TEMPLATES["solution_design"])
        self.assertTrue(os.path.isfile(path), f"Missing: {path}")


class TestTemplateFilesNonEmpty(unittest.TestCase):
    def test_functional_spec_not_empty(self):
        content = _read(TEMPLATES["functional_spec"])
        self.assertGreater(len(content.strip()), 50)

    def test_solution_design_not_empty(self):
        content = _read(TEMPLATES["solution_design"])
        self.assertGreater(len(content.strip()), 50)


class TestFunctionalSpecTemplate(unittest.TestCase):
    """Functional spec template must cover all key sections."""

    REQUIRED_SECTIONS = [
        "Executive Summary",
        "Functional Requirements",
        "Scope",
        "Risks",
    ]

    def _content(self) -> str:
        return _read(TEMPLATES["functional_spec"])

    def test_is_markdown(self):
        content = self._content()
        # Should start with a heading
        self.assertTrue(content.strip().startswith("#"), "Functional spec template should start with a # heading")

    def test_required_sections_present(self):
        content = self._content()
        for section in self.REQUIRED_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, content, f"Missing section '{section}' in functional spec template")

    def test_has_placeholder_markers(self):
        content = self._content()
        # Should contain {placeholders} or [placeholder] style markers
        has_curly = bool(re.search(r"\{[^}]+\}", content))
        has_bracket = bool(re.search(r"\[[A-Z][^\]]+\]", content))
        self.assertTrue(
            has_curly or has_bracket,
            "Functional spec template should contain placeholder markers like {project_name} or [PROJECT NAME]"
        )

    def test_has_at_least_three_headings(self):
        content = self._content()
        headings = re.findall(r"^#{1,3} .+", content, re.MULTILINE)
        self.assertGreaterEqual(len(headings), 3, "Functional spec template should have at least 3 headings")


class TestSolutionDesignTemplate(unittest.TestCase):
    """Solution design template must cover architecture sections."""

    REQUIRED_SECTIONS = [
        "Architecture",
        "Tech",
        "Database",
    ]

    def _content(self) -> str:
        return _read(TEMPLATES["solution_design"])

    def test_is_markdown(self):
        content = self._content()
        self.assertTrue(content.strip().startswith("#"), "Solution design template should start with a # heading")

    def test_required_sections_present(self):
        content = self._content()
        for section in self.REQUIRED_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(
                    section, content,
                    f"Missing section '{section}' in solution design template"
                )

    def test_has_placeholder_markers(self):
        content = self._content()
        has_curly = bool(re.search(r"\{[^}]+\}", content))
        has_bracket = bool(re.search(r"\[[A-Z][^\]]+\]", content))
        self.assertTrue(
            has_curly or has_bracket,
            "Solution design template should contain placeholder markers"
        )

    def test_has_at_least_three_headings(self):
        content = self._content()
        headings = re.findall(r"^#{1,3} .+", content, re.MULTILINE)
        self.assertGreaterEqual(len(headings), 3, "Solution design template should have at least 3 headings")


class TestAgentPersonaFiles(unittest.TestCase):
    """All agent .md persona files must have a ## System Prompt section."""

    AGENT_FILES = {
        "analyst":         "agents/analyst.md",
        "product_manager": "agents/product-manager.md",
        "architect":       "agents/architect.md",
        "scrum_master":    "agents/scrum-master.md",
        "developer":       "agents/developer.md",
        "qa_engineer":     "agents/qa-engineer.md",
    }

    def test_all_persona_files_exist(self):
        for agent_id, rel_path in self.AGENT_FILES.items():
            with self.subTest(agent=agent_id):
                full_path = os.path.join(_ROOT, rel_path)
                self.assertTrue(os.path.isfile(full_path), f"Missing persona file: {full_path}")

    def test_all_persona_files_have_system_prompt_section(self):
        for agent_id, rel_path in self.AGENT_FILES.items():
            with self.subTest(agent=agent_id):
                content = _read(rel_path)
                self.assertIn(
                    "## System Prompt", content,
                    f"{rel_path} is missing '## System Prompt' section"
                )

    def test_all_persona_files_are_markdown(self):
        for agent_id, rel_path in self.AGENT_FILES.items():
            with self.subTest(agent=agent_id):
                content = _read(rel_path)
                has_heading = bool(re.search(r"^#{1,3} .+", content, re.MULTILINE))
                self.assertTrue(has_heading, f"{rel_path} has no markdown headings")

    def test_persona_files_min_length(self):
        for agent_id, rel_path in self.AGENT_FILES.items():
            with self.subTest(agent=agent_id):
                content = _read(rel_path)
                self.assertGreater(len(content.strip()), 100, f"{rel_path} seems too short")

    def test_system_prompts_are_non_trivial(self):
        """The extracted system prompt for each agent should be longer than 50 chars."""
        import re as _re
        for agent_id, rel_path in self.AGENT_FILES.items():
            with self.subTest(agent=agent_id):
                content = _read(rel_path)
                match = _re.search(r"## System Prompt\n(.*?)(?=\n## |\Z)", content, _re.DOTALL)
                if match:
                    prompt = match.group(1).strip()
                    self.assertGreater(len(prompt), 50, f"{rel_path} system prompt is too short: '{prompt}'")


if __name__ == "__main__":
    unittest.main()
