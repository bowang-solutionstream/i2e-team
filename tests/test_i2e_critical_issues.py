"""Exercise session-local issue management without a network, GitHub CLI or Git remote."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/i2e-astra-sol/scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


issues = module("critical_issues")
speckit = module("critical_speckit")


class LocalIssueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.tasks = self.root / "tasks.md"
        self.tasks.write_text("# Tasks\n- [ ] T001 [US1] Show balance\n  Acceptance: SC-001\n"
                              "- [x] T002 Test the user journey\n```text\n- [ ] T003 Ignore example\n```\n")
        self.side = self.root / "run.json.d"

    def test_offline_issue_lifecycle_and_replay(self):
        with patch("subprocess.Popen", side_effect=AssertionError("external CLI")), patch(
            "socket.socket", side_effect=AssertionError("external network")
        ):
            rows = issues.sync_tasks(self.tasks, self.side)
            self.assertEqual(["T001", "T002"], [row["task"] for row in rows])
            before = issues.task_board(rows, self.side)
            self.assertEqual(["OPEN", "DONE"], [x["status"] for x in before])
            self.assertEqual(["Acceptance: SC-001"], before[0]["details"])
            self.assertEqual("IN_PROGRESS", issues.task_board(rows, self.side, "T001", "IN_PROGRESS")[0]["status"])
            self.assertEqual(rows, issues.sync_tasks(self.tasks, self.side))
            self.assertEqual("IN_PROGRESS", issues.task_board(rows, self.side)[0]["status"])
            independent = self.root / "another-run.json.d"
            self.assertEqual("OPEN", issues.task_board(issues.sync_tasks(self.tasks, independent), independent)[0]["status"])
            self.assertEqual("DONE", issues.task_board(rows, self.side, "T001", "DONE")[0]["status"])
            self.tasks.write_text(self.tasks.read_text().replace("Show balance", "Show available balance"))
            revised = issues.sync_tasks(self.tasks, self.side)
            self.assertNotEqual(rows, revised)
            self.assertEqual("OPEN", issues.task_board(revised, self.side)[0]["status"])
            self.assertEqual("DONE", issues.task_board(rows, self.side)[0]["status"])

    def test_invalid_or_tampered_issues(self):
        rows = issues.sync_tasks(self.tasks, self.side)
        with self.assertRaises(ValueError):
            issues.task_board(rows, self.side, "T888", "DONE")
        with self.assertRaises(ValueError):
            issues.task_board(rows, self.side, "T001", "made-up")
        with self.assertRaises(ValueError):
            issues.task_board(rows[::-1], self.side)
        with self.assertRaises(ValueError):
            issues.task_board([{"task": "T001", "ref": "../elsewhere"}], self.side)
        (self.side / rows[0]["ref"].split("#")[0]).write_text("{}")
        with self.assertRaises(ValueError):
            issues.task_board(rows, self.side)
        self.tasks.write_text("- [ ] T001 First\n- [ ] T001 Second\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            issues.sync_tasks(self.tasks, self.side)

    def test_setup_requires_local_only_official_planning_skills(self):
        workspace = self.root / "planning"
        (workspace / ".specify").mkdir(parents=True)
        (workspace / ".specify/init-options.json").write_text(json.dumps(
            {"integration": "codex", "speckit_version": speckit.VERSION}))
        for name in speckit.SKILLS:
            path = workspace / ".agents/skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("fixture")
        with patch("subprocess.Popen", side_effect=AssertionError("unexpected bootstrap")):
            self.assertEqual("READY", speckit.prepare(workspace)["state"])
            (workspace / ".specify/extensions/github").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "GitHub extension"):
                speckit.prepare(workspace)
            self.assertTrue((workspace / ".specify/extensions/github").is_dir())


if __name__ == "__main__":
    unittest.main()
