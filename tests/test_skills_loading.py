"""
Tests for skills/*.yaml files
--------------------------------
Verifies all 6 skill YAML files load correctly and have
the required structure: name, role, skills list, input, output.
"""

import os
import sys
import unittest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")

SKILL_FILES = {
    "analyst":         "skills/analyst.yaml",
    "product_manager": "skills/product-manager.yaml",
    "architect":       "skills/architect.yaml",
    "scrum_master":    "skills/scrum-master.yaml",
    "developer":       "skills/developer.yaml",
    "qa_engineer":     "skills/qa-engineer.yaml",
}


def _load(path: str) -> dict:
    with open(os.path.join(_ROOT, path), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestSkillFilesExist(unittest.TestCase):
    def test_all_skill_files_exist(self):
        for agent_id, rel_path in SKILL_FILES.items():
            full_path = os.path.join(_ROOT, rel_path)
            with self.subTest(agent=agent_id):
                self.assertTrue(os.path.isfile(full_path), f"Missing: {full_path}")


class TestSkillFilesLoadable(unittest.TestCase):
    def test_all_files_parse_as_valid_yaml(self):
        for agent_id, rel_path in SKILL_FILES.items():
            with self.subTest(agent=agent_id):
                data = _load(rel_path)
                self.assertIsInstance(data, dict, f"{rel_path} did not parse to a dict")


class TestSkillFileStructure(unittest.TestCase):
    """Each skills YAML must have: agent, role, skills (list), input, output."""

    REQUIRED_KEYS = ["agent", "role", "skills", "input", "output"]

    def test_required_keys_present(self):
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            for key in self.REQUIRED_KEYS:
                with self.subTest(agent=agent_id, key=key):
                    self.assertIn(key, data, f"{rel_path} missing key '{key}'")

    def test_skills_is_non_empty_list(self):
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            with self.subTest(agent=agent_id):
                self.assertIsInstance(data["skills"], list)
                self.assertGreater(len(data["skills"]), 0, f"{rel_path} has empty skills list")

    def test_agent_field_is_string(self):
        """Skills YAML uses 'agent' (not 'name') as the identifier field."""
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            with self.subTest(agent=agent_id):
                self.assertIsInstance(data["agent"], str)
                self.assertGreater(len(data["agent"]), 0)

    def test_role_is_string(self):
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            with self.subTest(agent=agent_id):
                self.assertIsInstance(data["role"], str)
                self.assertGreater(len(data["role"]), 0)

    def test_input_is_string_or_list(self):
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            with self.subTest(agent=agent_id):
                self.assertIsInstance(data["input"], (str, list))

    def test_output_is_string_or_list(self):
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            with self.subTest(agent=agent_id):
                self.assertIsInstance(data["output"], (str, list))

    def test_each_skill_has_name_and_description(self):
        """Skills entries are dicts with 'name' and 'description' keys."""
        for agent_id, rel_path in SKILL_FILES.items():
            data = _load(rel_path)
            for i, skill in enumerate(data["skills"]):
                with self.subTest(agent=agent_id, skill_index=i):
                    self.assertIsInstance(skill, dict, f"Skill #{i} in {rel_path} should be a dict")
                    self.assertIn("name", skill, f"Skill #{i} in {rel_path} missing 'name'")
                    self.assertIn("description", skill, f"Skill #{i} in {rel_path} missing 'description'")


def _skills_text(data: dict) -> str:
    """Flatten all skill names and descriptions into a single lowercase string."""
    parts = []
    for skill in data.get("skills", []):
        if isinstance(skill, dict):
            parts.append(skill.get("name", ""))
            parts.append(skill.get("description", ""))
        else:
            parts.append(str(skill))
    return " ".join(parts).lower()


class TestSkillFileContent(unittest.TestCase):
    """Spot-check specific content in each agent's skills."""

    def test_analyst_agent_field(self):
        data = _load(SKILL_FILES["analyst"])
        self.assertIn("analyst", data["agent"].lower())

    def test_developer_has_programming_skill(self):
        data = _load(SKILL_FILES["developer"])
        text = _skills_text(data)
        self.assertTrue(
            any(word in text for word in ["code", "python", "programming", "develop", "implement"]),
            "Developer skills should mention coding/programming"
        )

    def test_qa_engineer_has_testing_skill(self):
        data = _load(SKILL_FILES["qa_engineer"])
        text = _skills_text(data)
        self.assertTrue(
            any(word in text for word in ["test", "qa", "quality", "verify", "validate"]),
            "QA Engineer skills should mention testing"
        )

    def test_product_manager_output(self):
        data = _load(SKILL_FILES["product_manager"])
        output = data["output"]
        if isinstance(output, list):
            output = " ".join(str(o) for o in output)
        self.assertIsInstance(output, str)
        self.assertGreater(len(output), 0)

    def test_architect_has_design_skill(self):
        data = _load(SKILL_FILES["architect"])
        text = _skills_text(data)
        self.assertTrue(
            any(word in text for word in ["design", "architect", "system", "database", "schema"]),
            "Architect skills should mention design/system architecture"
        )

    def test_scrum_master_has_story_skill(self):
        data = _load(SKILL_FILES["scrum_master"])
        text = _skills_text(data)
        self.assertTrue(
            any(word in text for word in ["story", "agile", "backlog", "sprint", "scrum", "user"]),
            "Scrum Master skills should mention user stories/agile"
        )


class TestWorkflowYaml(unittest.TestCase):
    """Validate the main workflow config file."""

    def _load_workflow(self) -> dict:
        return _load("config/workflow.yaml")

    def test_workflow_file_exists(self):
        path = os.path.join(_ROOT, "config/workflow.yaml")
        self.assertTrue(os.path.isfile(path))

    def test_workflow_has_settings(self):
        data = self._load_workflow()
        self.assertIn("settings", data)

    def test_workflow_settings_have_model(self):
        data = self._load_workflow()
        self.assertIn("model", data["settings"])
        self.assertIsInstance(data["settings"]["model"], str)

    def test_workflow_settings_have_max_debug_retries(self):
        data = self._load_workflow()
        self.assertIn("max_debug_retries", data["settings"])
        self.assertIsInstance(data["settings"]["max_debug_retries"], int)
        self.assertGreaterEqual(data["settings"]["max_debug_retries"], 1)

    def test_workflow_settings_have_temperature(self):
        data = self._load_workflow()
        self.assertIn("temperature", data["settings"])
        temp = data["settings"]["temperature"]
        self.assertGreaterEqual(temp, 0.0)
        self.assertLessEqual(temp, 2.0)

    def test_workflow_has_agents_list(self):
        data = self._load_workflow()
        self.assertIn("agents", data)
        self.assertIsInstance(data["agents"], list)
        self.assertGreaterEqual(len(data["agents"]), 6)

    def test_workflow_has_flow(self):
        data = self._load_workflow()
        self.assertIn("flow", data)
        self.assertIsInstance(data["flow"], list)


if __name__ == "__main__":
    unittest.main()
