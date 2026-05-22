"""
Tests for orchestrator/agent_runner.py
---------------------------------------
Covers: _load_md, _load_yaml, _extract_system_prompt,
        get_agent_skills, run_agent (mocked LLM).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.agent_runner import (
    _extract_system_prompt,
    _load_md,
    _load_yaml,
    get_agent_skills,
    run_agent,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..")

# ---------------------------------------------------------------------------
# _load_md
# ---------------------------------------------------------------------------

class TestLoadMd(unittest.TestCase):
    def test_loads_analyst_md(self):
        content = _load_md("agents/analyst.md")
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 50)

    def test_loads_all_agent_mds(self):
        files = [
            "agents/analyst.md",
            "agents/product-manager.md",
            "agents/architect.md",
            "agents/scrum-master.md",
            "agents/developer.md",
            "agents/qa-engineer.md",
        ]
        for path in files:
            with self.subTest(path=path):
                content = _load_md(path)
                self.assertGreater(len(content), 10, f"{path} appears empty")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            _load_md("agents/nonexistent.md")


# ---------------------------------------------------------------------------
# _load_yaml
# ---------------------------------------------------------------------------

class TestLoadYaml(unittest.TestCase):
    def test_loads_workflow_yaml(self):
        data = _load_yaml("config/workflow.yaml")
        self.assertIsInstance(data, dict)
        self.assertIn("settings", data)
        self.assertIn("model", data["settings"])

    def test_loads_all_skill_yamls(self):
        files = [
            "skills/analyst.yaml",
            "skills/product-manager.yaml",
            "skills/architect.yaml",
            "skills/scrum-master.yaml",
            "skills/developer.yaml",
            "skills/qa-engineer.yaml",
        ]
        for path in files:
            with self.subTest(path=path):
                data = _load_yaml(path)
                self.assertIsInstance(data, dict)


# ---------------------------------------------------------------------------
# _extract_system_prompt
# ---------------------------------------------------------------------------

class TestExtractSystemPrompt(unittest.TestCase):
    def test_extracts_section(self):
        md = "# Agent\n\n## Overview\nSome overview.\n\n## System Prompt\nYou are a helpful agent.\n\n## Other Section\nMore text."
        result = _extract_system_prompt(md)
        self.assertEqual(result, "You are a helpful agent.")

    def test_falls_back_to_full_content_when_no_section(self):
        md = "You are a helpful agent without a section header."
        result = _extract_system_prompt(md)
        self.assertEqual(result, md)

    def test_multiline_system_prompt(self):
        md = "## System Prompt\nLine 1.\nLine 2.\nLine 3.\n## Next"
        result = _extract_system_prompt(md)
        self.assertIn("Line 1.", result)
        self.assertIn("Line 2.", result)
        self.assertIn("Line 3.", result)

    def test_all_agent_mds_have_system_prompt(self):
        agents = ["analyst", "product-manager", "architect", "scrum-master", "developer", "qa-engineer"]
        for agent in agents:
            with self.subTest(agent=agent):
                content = _load_md(f"agents/{agent}.md")
                prompt = _extract_system_prompt(content)
                self.assertGreater(len(prompt), 20, f"{agent}.md system prompt is too short")


# ---------------------------------------------------------------------------
# get_agent_skills
# ---------------------------------------------------------------------------

class TestGetAgentSkills(unittest.TestCase):
    AGENT_IDS = ["analyst", "product_manager", "architect", "scrum_master", "developer", "qa_engineer"]

    def test_returns_dict_for_all_agents(self):
        for agent_id in self.AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                skills = get_agent_skills(agent_id)
                self.assertIsInstance(skills, dict)

    def test_skills_have_agent_field(self):
        """Skills YAML files use 'agent' as the identifier key (not 'name')."""
        for agent_id in self.AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                skills = get_agent_skills(agent_id)
                self.assertIn("agent", skills, f"{agent_id} skills.yaml missing 'agent' key")

    def test_skills_have_skills_list(self):
        for agent_id in self.AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                skills = get_agent_skills(agent_id)
                self.assertIn("skills", skills, f"{agent_id} skills.yaml missing 'skills' key")
                self.assertIsInstance(skills["skills"], list)
                self.assertGreater(len(skills["skills"]), 0)

    def test_invalid_agent_raises(self):
        with self.assertRaises(KeyError):
            get_agent_skills("nonexistent_agent")


# ---------------------------------------------------------------------------
# run_agent (mocked LLM)
# ---------------------------------------------------------------------------

class TestRunAgent(unittest.TestCase):
    @patch("core.agent_runner._get_llm")
    def test_run_agent_returns_string(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="  Mocked agent response.  ")
        mock_get_llm.return_value = mock_llm

        result = run_agent("analyst", "Build me a todo app")
        self.assertEqual(result, "Mocked agent response.")

    @patch("core.agent_runner._get_llm")
    def test_run_agent_passes_system_message(self, mock_get_llm):
        from langchain_core.messages import SystemMessage, HumanMessage

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="response")
        mock_get_llm.return_value = mock_llm

        run_agent("developer", "User request: build a calculator")

        call_args = mock_llm.invoke.call_args[0][0]
        self.assertIsInstance(call_args[0], SystemMessage)
        self.assertIsInstance(call_args[1], HumanMessage)
        self.assertIn("build a calculator", call_args[1].content)

    @patch("core.agent_runner._get_llm")
    def test_run_agent_all_ids(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="ok")
        mock_get_llm.return_value = mock_llm

        agent_ids = ["analyst", "product_manager", "architect", "scrum_master", "developer", "qa_engineer"]
        for agent_id in agent_ids:
            with self.subTest(agent_id=agent_id):
                result = run_agent(agent_id, "test message")
                self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
