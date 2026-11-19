"""Exercise the normal Critical CLI with local project checks and fixture host records."""

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
import uuid


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/i2e-team/scripts"
PLANNER_ARGV = runpy.run_path(str(SCRIPTS / "critical_speckit.py"))["planner_argv"]
SOL = "gpt-6.2-sol"
ASTRA = "gpt-6.2-astra"

PROJECT_CHECKS = '''
import ast
from pathlib import Path
import subprocess
import sys

argv = sys.argv
if argv[1] == "lint":
    ast.parse(Path("app.py").read_text())
    print("parsed app.py")
    if len(argv) == 3:
        Path("app.py").write_text('print("changed during lint")\\n')
elif argv[1] == "e2e":
    process = subprocess.run([sys.executable, "app.py"], capture_output=True, text=True)
    print(process.stdout.strip())
    assert process.returncode == 0 and process.stdout == "ready\\n", "actual CLI output was incorrect"
else:
    raise SystemExit("unknown check")
'''


class CriticalFlowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.private = self.root / "private"
        self.private.mkdir()
        self.state = self.private / "run.json"
        self.sidecar = self.state.with_name("run.json.d")
        self.host = self.private / "host"
        (self.host / "sessions").mkdir(parents=True)
        self.github_call = self.private / "unexpected-gh-call"
        gh_tripwire = self.root / "gh"
        gh_tripwire.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(self.github_call)!r}).touch()\nraise SystemExit(1)\n",
        )
        gh_tripwire.chmod(0o755)
        self.env = os.environ | {
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "CODEX_HOME": str(self.host),
        }
        self.env.pop("CODEX_THREAD_ID", None)
        self.git("init", "-q")
        self.app = self.repo / "app.py"
        self.app.write_text('print("broken")\n')
        (self.repo / "checks.py").write_text(PROJECT_CHECKS)
        self.git("add", "app.py", "checks.py")
        self.git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "commit", "-qm", "base")
        self.workspace = self.private / "planning"
        self.marker = self.workspace / ".specify/init-options.json"
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text(json.dumps({"integration": "codex", "speckit_version": "1.4.3"}))
        for skill in ("speckit-specify", "speckit-plan", "speckit-tasks"):
            entry = self.workspace / ".agents/skills" / skill / "SKILL.md"
            entry.parent.mkdir(parents=True)
            entry.write_text("Fixture Spec Kit skill entrypoint.\n")
        feature = self.workspace / "specs/001-fixture"
        feature.mkdir(parents=True)
        self.spec = feature / "spec.md"
        self.spec.write_text(
            "## Measurable Outcomes\n\n"
            "- **SC-001**: The project CLI prints ready.\n"
            "- **SC-002**: An incorrect CLI result makes the E2E command fail.\n"
        )
        self.plan = feature / "plan.md"
        self.plan.write_text("Use the project CLI entrypoint and assert its output.\n")
        self.tasks = feature / "tasks.md"
        self.tasks.write_text("- [ ] T001 Fix the CLI output in app.py\n- [ ] T002 Verify the project CLI in checks.py\n")
        self.evidence = self.private / "handoff.md"
        self.evidence.write_text("Inspected project sources and exercised the implementation entrypoint.\n")
        self.probe_actor = self.rollout(SOL)
        self.planner_actor = self.rollout(ASTRA, tier=None, cwd=self.workspace)
        self.worker_actor = self.rollout(SOL)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def rollout(self, model, *, tier="priority", source="exec", effort="max", cwd=None, sandbox=None, **metadata):
        session = str(uuid.uuid4())
        path = self.host / "sessions" / f"rollout-fixture-{session}.jsonl"
        checkout = str(cwd or self.repo)
        meta = {"id": session, "originator": "codex_exec", "source": source,
                "timestamp": datetime.now(timezone.utc).isoformat(), "cwd": checkout} | metadata
        context = {"model": model, "effort": effort, "cwd": checkout}
        if tier is not None:
            context["service_tier"] = tier
        if sandbox is not None:
            context["sandbox_policy"] = sandbox
        path.write_text("\n".join(json.dumps(item) for item in (
            {"type": "session_meta", "payload": meta}, {"type": "turn_context", "payload": context},
        )) + "\n")
        return session, path

    def cli(self, *args, actor=None, live=True, code=0, state=None):
        arguments = [str(item) for item in args]
        env = self.env.copy()
        if actor:
            session, rollout = actor
            arguments += ["--rollout", str(rollout)]
            if live:
                env["CODEX_THREAD_ID"] = session
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "i2e.py"), "critical", "--state", str(state or self.state), *arguments],
            cwd=self.repo, env=env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(code, result.returncode, result.stderr or result.stdout)
        return result.stderr if code == 2 else json.loads(result.stdout)

    def init_and_probe(self):
        self.cli("init", "--repo", self.repo)
        self.cli("probe", "--evidence", self.evidence, actor=self.probe_actor)

    def propose_plan(self, *flags, code=0, dispatch=True, dispatch_argv=None, lint_extra=None):
        arguments = ["plan", "--spec", self.spec, "--plan", self.plan, "--tasks", self.tasks,
                     "--lint-argv", json.dumps([sys.executable, "checks.py", "lint", *(lint_extra or [])]),
                     "--e2e-argv", json.dumps([sys.executable, "checks.py", "e2e"]), *flags]
        if dispatch:
            captured = self.private / "dispatch.json"
            captured.write_text(json.dumps({"session": self.planner_actor[0],
                                            "argv": dispatch_argv or PLANNER_ARGV(self.workspace)}))
            arguments.extend(["--dispatch", captured])
        return self.cli(*arguments, actor=self.planner_actor, code=code)

    def handoff(self, *, fix=True):
        self.init_and_probe()
        self.propose_plan()
        if fix:
            self.app.write_text('print("ready")\n')
        return self.cli("implement", "--evidence", self.evidence, actor=self.worker_actor)

    def acceptance(self, current, verdicts=("PASS", "PASS")):
        evidence = {key: current[key] for key in ("plan_sha256", "candidate_sha256", "verification_sha256")}
        evidence["cases"] = [
            {"id": key, "verdict": verdict, "check": "e2e", "observation": observation}
            for key, verdict, observation in zip(current["criteria"], verdicts, (
                "The attached E2E output contains the expected ready line from app.py.",
                "An incorrect output exits through the assertion in checks.py.",
            ))
        ]
        path = self.private / "acceptance.json"
        path.write_text(json.dumps(evidence))
        return path

    def test_four_rounds_retain_actual_failure_then_repair_and_recheck(self):
        before = self.handoff(fix=False)
        bad_verifier = self.rollout(SOL)
        failed = self.cli("verify", actor=bad_verifier, code=1)
        self.assertEqual("repair", failed["phase"])
        self.assertEqual("PASS", failed["checks"]["lint"]["result"])
        self.assertEqual(1, failed["checks"]["e2e"]["exit_code"])
        error = Path(failed["checks"]["e2e"]["stderr"]["path"])
        self.assertIn("actual CLI output was incorrect", error.read_text())
        self.assertEqual(before["candidate_sha256"], failed["candidate_sha256"])

        self.app.write_text('print("ready")\n')
        self.tasks.write_text(self.tasks.read_text().replace("[ ]", "[x]"))
        repaired = self.cli("implement", "--evidence", self.evidence, actor=self.worker_actor)
        self.assertEqual(failed["verification_sha256"], repaired["rounds"][-1]["repair_of"])
        self.assertNotEqual(before["candidate_sha256"], repaired["candidate_sha256"])
        self.assertIn("fresh standalone", self.cli("verify", actor=bad_verifier, code=2))
        self.assertIn("fresh standalone", self.cli("verify", actor=self.worker_actor, code=2))
        good_verifier = self.rollout(SOL)
        checked = self.cli("verify", actor=good_verifier)
        self.assertEqual("assess", checked["phase"])
        self.assertEqual({"PASS"}, {value["result"] for value in checked["checks"].values()})
        self.assertIn("same independent verifier", self.cli(
            "accept", "--acceptance", self.acceptance(checked), actor=self.rollout(SOL), code=2,
        ))
        completed = self.cli("accept", "--acceptance", self.acceptance(checked), actor=good_verifier)
        self.assertEqual("complete", completed["phase"])
        self.assertTrue(completed["acceptance_current"])
        self.assertTrue(error.is_file())
        self.assertEqual(["probe", "plan", "implement", "verify", "implement", "verify"],
                         [item["role"] for item in completed["rounds"]])
        self.assertEqual({"UNKNOWN"}, {item["actor"]["effective_service_tier"] for item in completed["rounds"]})
        self.assertEqual("dispatch", completed["rounds"][1]["actor"]["tier_request_evidence"])
        self.assertEqual(2, len(self.cli("tasks")))
        self.assertIn("active implementation or repair", self.cli(
            "task", "--id", "T001", "--status", "DONE", code=2,
        ))
        self.app.write_text('print("changed after acceptance")\n')
        self.assertFalse(self.cli("status")["acceptance_current"])

    def test_planning_uses_only_local_tasks_and_replans_on_changed_design(self):
        self.init_and_probe()
        self.assertIn("captured offline --dispatch", self.propose_plan(code=2, dispatch=False))
        self.app.write_text('print("changed before planning")\n')
        self.assertIn("preserve the probed checkout", self.propose_plan(code=2))
        self.app.write_text('print("broken")\n')
        original = self.propose_plan()
        self.assertEqual(["T001", "T002"], [item["task"] for item in original["tasks"]])
        for item in original["tasks"]:
            location, fragment = item["ref"].split("#")
            self.assertTrue((self.sidecar / location).is_file())
            self.assertEqual(item["task"], fragment)
        self.assertEqual(["OPEN", "OPEN"], [item["status"] for item in self.cli("tasks")])
        progress = self.cli("task", "--id", "T001", "--status", "IN_PROGRESS")
        self.assertEqual(["IN_PROGRESS", "OPEN"], [item["status"] for item in progress])
        self.assertEqual(progress, self.cli("tasks"))
        self.assertIn("changed specification or design", self.propose_plan("--replan-reason", "Cosmetic review", code=2))
        self.plan.write_text("Exercise the command from the checkout root and explicitly assert its output.\n")
        self.assertIn("approved plan.md changed", self.cli("implement", "--evidence", self.evidence,
                                                          actor=self.worker_actor, code=2))
        updated = self.propose_plan("--replan-reason", "The design now exercises the checkout root.")
        self.assertNotEqual(original["plan_sha256"], updated["plan_sha256"])
        self.assertEqual(original["tasks"], updated["tasks"])
        self.assertFalse(self.github_call.exists())

    def test_planner_requires_prepared_private_spec_kit_workspace(self):
        self.init_and_probe()
        options = self.marker.read_bytes()
        self.marker.unlink()
        self.assertIn("prepared local Codex Spec Kit workspace", self.propose_plan(code=2))
        self.assertFalse((self.sidecar / "issues").exists())
        self.marker.write_bytes(options)
        self.planner_actor = self.rollout(ASTRA, tier="default", cwd=self.root)
        self.assertIn("selected workspace", self.propose_plan(code=2))
        self.planner_actor = self.rollout(ASTRA, tier="default", cwd=self.repo)
        self.assertIn("selected workspace", self.propose_plan(code=2))
        self.planner_actor = self.rollout(ASTRA, tier="default", cwd=self.workspace)
        original = self.plan
        self.plan = self.repo / "plan.md"
        self.plan.write_text("Wrong checkout.\n")
        self.assertIn("private feature directory", self.propose_plan(code=2, dispatch=False))
        self.plan.unlink()
        self.plan = original
        result = self.propose_plan()
        self.assertEqual(str(self.workspace), result["rounds"][-1]["actor"]["cwd"])
        self.assertEqual(str(self.workspace), result["rounds"][-1]["spec_kit_workspace"])
        self.assertEqual(str(self.repo), result["repo"])

    def test_planner_refuses_widened_launch_and_accepts_private_output(self):
        self.init_and_probe()
        argv = PLANNER_ARGV(self.workspace)
        online = [arg.replace("network_access=false", "network_access=true") for arg in argv]
        widened = [*argv[:-2], "--add-dir", str(self.repo), *argv[-2:]]
        for launch in (online, widened):
            self.assertIn("canonical offline Spec Kit launch", self.propose_plan(code=2, dispatch_argv=launch))
        self.planner_actor = self.rollout(ASTRA, tier="default", cwd=self.workspace,
                                           sandbox={"type": "workspace-write", "network_access": True})
        self.assertIn("sandbox or network permissions", self.propose_plan(code=2))
        self.planner_actor = self.rollout(ASTRA, tier="default", cwd=self.workspace,
                                           sandbox={"type": "workspace-write", "network_access": False})
        output = [*argv[:-2], "-o", str(self.repo / "outside.md"), *argv[-2:]]
        self.assertIn("absolute private file", self.propose_plan(code=2, dispatch_argv=output))
        self.assertFalse((self.sidecar / "issues").exists())
        command = [str(self.root / "codex"), *argv[1:-2], "--output-last-message",
                   str(self.private / "planner-output.md"), *argv[-2:]]
        self.assertEqual("implement", self.propose_plan(dispatch_argv=command)["phase"])

    def test_verifier_binds_context_exact_acceptance_and_candidate(self):
        self.handoff()
        fork = self.rollout(SOL, forked_from_id=self.worker_actor[0])
        self.assertIn("fresh standalone", self.cli("verify", actor=fork, code=2))
        reviewer = self.rollout(SOL)
        self.assertIn("recorded Sol verifier session", self.cli("verify", actor=reviewer, live=False, code=2))
        checked = self.cli("verify", actor=reviewer)
        document = self.acceptance(checked)
        evidence = json.loads(document.read_text())
        evidence["verification_sha256"] = "stale"
        document.write_text(json.dumps(evidence))
        self.assertIn("exact verification receipt", self.cli("accept", "--acceptance", document, actor=reviewer, code=2))
        evidence["verification_sha256"] = checked["verification_sha256"]
        evidence["cases"].pop()
        document.write_text(json.dumps(evidence))
        self.assertIn("each planned success criterion", self.cli("accept", "--acceptance", document, actor=reviewer, code=2))
        self.app.write_text('print("changed after checks")\n')
        stale = self.cli("accept", "--acceptance", self.acceptance(checked), actor=reviewer, code=1)
        self.assertEqual("repair", stale["phase"])
        self.assertEqual("STALE", stale["rounds"][-1]["assessment"]["result"])

    def test_specific_failed_acceptance_case_enters_repair_even_with_green_commands(self):
        self.handoff()
        reviewer = self.rollout(SOL)
        checked = self.cli("verify", actor=reviewer)
        document = self.acceptance(checked, verdicts=("PASS", "FAIL"))
        failed = self.cli("accept", "--acceptance", document, actor=reviewer, code=1)
        self.assertEqual("repair", failed["phase"])
        self.assertEqual("FAIL", failed["rounds"][-1]["assessment"]["cases"][1]["verdict"])
        self.assertEqual({"PASS"}, {check["result"] for check in failed["checks"].values()})

    def test_candidate_mutation_suspends_remaining_check(self):
        self.init_and_probe()
        self.propose_plan(lint_extra=["mutate"])
        self.cli("implement", "--evidence", self.evidence, actor=self.worker_actor)
        result = self.cli("verify", actor=self.rollout(SOL), code=1)
        self.assertEqual("repair", result["phase"])
        self.assertFalse(result["checks"]["lint"]["candidate_unchanged"])
        self.assertEqual("NOT_RUN", result["checks"]["e2e"]["result"])

    def test_private_single_writer_and_probe_is_read_only(self):
        args = ("init", "--repo", self.repo)
        self.assertIn("outside the checkout", self.cli(*args, state=self.repo / "unsafe.json", code=2))
        self.assertFalse((self.repo / "unsafe.json.d").exists())
        self.cli(*args)
        self.assertEqual(0o600, self.state.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.sidecar.stat().st_mode & 0o777)
        with (self.sidecar / "state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertIn("Critical run is busy", self.cli("status", code=2))
        self.app.write_text('print("changed before probing")\n')
        self.assertIn("preserve the initial checkout", self.cli("probe", "--evidence", self.evidence,
                                                               actor=self.probe_actor, code=2))
        self.assertEqual("probe", self.cli("status")["phase"])


if __name__ == "__main__":
    unittest.main()
