#!/usr/bin/env python3
"""Run the staged label pilot on macOS in a new private output directory."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
RUNNER = "pilot/scripts/verify_labels.py"
CATALOG = "pilot/references/label-verification.json"
FEATURE = "labels.normalize"
MODEL_BOUNDARY = "Synthetic actors and verdicts in the v8 ledger. Real local processes, API results and Git admissions."
IMPLEMENTATION = "def read(events):\n    return [' '.join(event.split()) for event in events]\n"
CONTRACT = """SYNTHETIC_ONLY_NO_MODEL_INVOKED
Direct label task A1. Normalize whitespace in list[str]. Preserve order, multiplicity,
non-whitespace text, length and the caller's input. Reapplication must be idempotent.
Run the pinned labels.normalize E2E, properties and scoped rules. Only behaviors_test.py
is writable in TEST_ONLY. Only reader.py is writable in PRODUCTION. Local evaluation.
"""
TEST_SOURCE = '''import json
from pathlib import Path
import subprocess
import sys
import unittest


class Behaviors(unittest.TestCase):
    def test_A1(self):
        root = Path(__file__).resolve().parent
        command = [sys.executable, "-IB", str(root / "pilot/scripts/verify_labels.py"),
                   "--repo", str(root), "--feature", "labels.normalize"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if result.returncode not in (0, 1):
            raise RuntimeError(f"Verification setup failed: {result.stdout} {result.stderr}")
        report = json.loads(result.stdout)
        if (report["state"], result.returncode) not in (("PASS", 0), ("FAIL", 1)):
            raise RuntimeError(f"Inconsistent verification result: {report}")
        print("LABEL_VERIFICATION=" + json.dumps(report, sort_keys=True))
        self.assertEqual("PASS", report["state"], report)


if __name__ == "__main__":
    unittest.main()
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, body):
    with path.open("x") as stream:
        json.dump(body, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run(args, output):
    skill = args.skill.resolve(strict=True)
    script = skill / "scripts/i2e.py"
    sys.path.insert(0, str(ROOT / "tests"))
    import test_i2e_team as base
    base.CASE_HELPER = args.case_helper.expanduser().resolve(strict=True)
    base.SCRIPT = script
    spec = importlib.util.spec_from_file_location("pilot_i2e_runtime", script)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    base.RUNTIME = runtime
    import test_four_behavior_repair as fixture
    from test_i2e_v2_worker import COMMIT_PROGRAM, WorkerV2Tests

    assert fixture.runtime is runtime
    fixture_dir = output / "fixtures"
    fixture_dir.mkdir()
    tempfile.tempdir = str(fixture_dir)

    class LabelTask(WorkerV2Tests):
        def configure(self, lane="Direct", **options):
            super().configure(lane, **options)

        def prepare_plan(self, **options):
            self.raw.write_text(CONTRACT)
            for relative in (RUNNER, CATALOG):
                dest = self.repo / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(skill / relative.removeprefix("pilot/"), dest)
            self.git("add", "--", RUNNER, CATALOG)
            self.git("-c", "user.name=I2E fixture", "-c", "user.email=fixture@example.invalid",
                     "commit", "-qm", "Pin the selected verification harness", "--no-gpg-sign")
            self.base_commit = self.git("rev-parse", "HEAD").strip()
            self.contract_extras.update(
                authority={"actions": ["edit", "worker"], "evidence": runtime.reference(self.raw)},
                objective="Normalize label whitespace while preserving content and list behavior.",
                parent_request="Pilot portable verification in the Direct label fixture.",
                instructions=[*fixture.INSTRUCTIONS, RUNNER, CATALOG],
                source={"base": self.base_commit, "harness": [fixture.HARNESS, RUNNER, CATALOG],
                        "dependencies": [fixture.DEPENDENCIES]},
            )
            command = [fixture.PYTHON, "-B", "-c", "from reader import read; assert read([]) == []"]
            baseline = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, timeout=15)
            write_json(output / "baseline.json", {"argv": command, "exit": baseline.returncode,
                                                  "stdout": baseline.stdout, "stderr": baseline.stderr})
            baseline.check_returncode()
            self.policy_value["assurance"]["checks"]["baseline"]["reason"] = (
                "Observed empty-list baseline " + digest(output / "baseline.json"))
            self.plan_extras.update(verification_map=self.verification_map(["A1"]),
                                    decision_reason="A1 requires the pinned public API journey, properties and scoped rules.")
            super().prepare_plan(**options)

    task = LabelTask()
    task.setUp()
    write_json(output / "fixture.json", {"repo": str(task.repo), "db": str(task.db), "run": fixture.RUN,
                                         "base": task.base_commit, "skill": str(skill), "actors": MODEL_BOUNDARY})
    program = ("from pathlib import Path\nimport subprocess, sys\n" + COMMIT_PROGRAM
               + "\nPath(sys.argv[1]).write_text(sys.argv[2])\ncommit(sys.argv[1])\n")
    def admit(phase, attempt, path, source, predecessor):
        task.open_phase(phase, "TEST_ONLY" if path == fixture.SHARED_TEST else "PRODUCTION", ["A1"])
        prepared = task.prepare_attempt(attempt, phase, predecessor=predecessor)
        task.run_script(attempt, program, path, source)
        commit = task.commit_from(prepared)
        submission = task.submit(attempt, commit)
        result = task.worker("admit", "admit-" + attempt, attempt=attempt, submission=submission["id"])
        assert result["outcome"] == "INTENDED", result
        task.worker("revoke", "retire-" + attempt, attempt=attempt, reason="Local handoff is complete.")
        return commit

    def pack_result(proof):
        receipt, raw = task.read_receipt(proof["data"]["output"])
        lines = [line for line in raw.decode().splitlines() if line.startswith("LABEL_VERIFICATION=")]
        assert len(lines) == 1, raw
        return {"id": proof["id"], "exit": receipt["exit"], "command": receipt["argv"],
                "source": proof["data"]["candidate"], "test": proof["data"]["test"],
                "results": json.loads(lines[0].split("=", 1)[1])}

    refused = task.open_phase("before-red", "PRODUCTION", ["A1"], expected="BLOCK")
    assert refused["start"] is None
    test_commit = admit("pilot-test", "label-tests", fixture.SHARED_TEST, TEST_SOURCE, task.base_commit)
    red = pack_result(task.proof("label-red", "A1", "pilot-test", passing=False))
    write_json(output / "red.json", red)
    assert red["results"]["state"] == "FAIL" and red["exit"] == 1

    implementation = IMPLEMENTATION
    if args.seeded_composition:
        implementation = ("import unicodedata\n\ndef read(events):\n"
                          "    return [unicodedata.normalize('NFC', ' '.join(s.split())) for s in events]\n")
    prod_commit = admit("pilot-production", "label-production", "reader.py", implementation, test_commit)
    green_attempt = task.request_proof("label-green", "A1", "pilot-production")
    write_json(output / "green-attempt.json", green_attempt)
    if green_attempt["state"] != "PASS":
        if not args.seeded_composition:
            raise RuntimeError(f"Required GREEN failed: {green_attempt}")
        command, _ = task.selected_command("A1")
        native, raw = task.read_receipt(green_attempt["receipt"])
        lines = [line for line in raw.decode().splitlines() if line.startswith("LABEL_VERIFICATION=")]
        assert green_attempt["state"] == "BLOCK" and native["exit"] == 1 and native["argv"] == command, native
        assert len(lines) == 1 and b"AssertionError" in raw, raw
        native_report = json.loads(lines[0].split("=", 1)[1])
        rerun = subprocess.run(command, cwd=task.repo, capture_output=True, text=True, timeout=20)
        matches = [line for line in rerun.stdout.splitlines() if line.startswith("LABEL_VERIFICATION=")]
        assert rerun.returncode == 1 and len(matches) == 1, (rerun.stdout, rerun.stderr)
        receipt = json.loads(matches[0].split("=", 1)[1])
        assert receipt == native_report and all(row["state"] == "PASS" for row in receipt["checks"]), receipt
        assert receipt["state"] == "FAIL" and any(row["would_fail"] and row["status"] == "pilot_enforced"
                                                  for row in receipt["rules"]), receipt
        cli = [fixture.PYTHON, "-B", str(script), "check", "--db", str(task.db), "--run", fixture.RUN]
        checked = subprocess.run(cli, cwd=task.repo, capture_output=True, text=True, timeout=30)
        held = json.loads(checked.stdout)
        assert held["state"] == "BLOCK" and not held["ready"] and not held["parent_complete"], held
        write_json(output / "replay.json", {"argv": cli, "exit": checked.returncode, "result": held})
        write_json(output / "ledger.json", task.history())
        result = {"state": "HELD_SEEDED_FAULT", "lane": "Direct", "actors": MODEL_BOUNDARY,
                  "production_commit": prod_commit, "native_green_state": green_attempt["state"],
                  "rerun_exit": rerun.returncode, "results": receipt, "parent_complete": held["parent_complete"]}
        write_json(output / "summary.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0
    proof = green_attempt["proof"]
    green = pack_result(proof)
    write_json(output / "green.json", green)
    assert (green["results"]["state"], green["exit"], green["test"]) == ("PASS", 0, red["test"])
    task.final_proofs = {"A1": proof}
    done = task.finish_workflow(start="pilot-production", prefix="local-")
    assert done["state"] == "PASS" and done["lifecycle"] == "ACCEPTED_LOCAL" and done["parent_complete"]

    cmd = [fixture.PYTHON, "-B", str(script), "check", "--db", str(task.db), "--run", fixture.RUN]
    replay = subprocess.run(cmd, cwd=task.repo, capture_output=True, text=True, timeout=30, check=True)
    observed = json.loads(replay.stdout)
    assert observed["state"] == "PASS" and observed["parent_complete"] and observed["lifecycle"] == "ACCEPTED_LOCAL"
    write_json(output / "replay.json", {"argv": cmd, "exit": replay.returncode, "result": observed})
    history = task.history()
    write_json(output / "ledger.json", history)
    kinds = [e["data"]["kind"] for e in history["events"] if e["type"] == "audit"]
    assert kinds == ["combined"] and not any(e["type"] in ("plan_review", "final_review") for e in history["events"])
    result = {"state": "MISSED_SEEDED_FAULT" if args.seeded_composition else "PASS",
              "lane": "Direct", "feature": FEATURE, "lifecycle": observed["lifecycle"],
              "candidate": task.current()["sha256"], "actors": MODEL_BOUNDARY, "audits": kinds,
              "seeded_composition": args.seeded_composition,
              "test_commit": test_commit, "production_commit": prod_commit, "native_red_exit": red["exit"],
              "native_green_exit": green["exit"], "tests_unchanged": True, "parent_complete": True,
              "harness_sha256": digest(task.repo / RUNNER), "catalog_sha256": digest(task.repo / CATALOG)}
    write_json(output / "summary.json", result)
    print(json.dumps(result, sort_keys=True))
    return 1 if args.seeded_composition else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="a new private evidence directory")
    parser.add_argument("--skill", type=Path, default=ROOT / "skills/i2e-team",
                        help="staged skill checkout or extracted i2e-team directory")
    parser.add_argument("--seeded-composition", action="store_true",
                        help="check that v8 refuses a deliberate Unicode composition fault; a miss exits 1")
    parser.add_argument("--case-helper", type=Path, default=Path("~/.codex/skills/i2e-failure-cases/scripts/shared_cases.py"),
                        help="existing canonical I2E failure-case helper")
    args = parser.parse_args()
    if sys.platform != "darwin" or sys.version_info < (3, 12):
        parser.error("The staged v8 synthetic worker fixture requires macOS and Python 3.12 or newer.")
    os.umask(0o077)
    sys.dont_write_bytecode = True
    output = args.output.resolve()
    output.mkdir()
    try:
        return run(args, output)
    except Exception:
        (output / "first-failure.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
