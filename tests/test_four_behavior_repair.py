"""Exercise v2 A1 through native commands, ledger consumers, and disposable sources."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from unittest.mock import patch

import test_i2e_team as base


runtime = base.RUNTIME
RUN = "run-1"
RUN_SCHEMA = "i2e-team-run-v2"
POLICY_SCHEMA = "i2e-team-policy-v2"
PROFILE = "i2e-team/v2"
EXECUTOR = "macos-sandbox-full-clone-v1"
ACTOR = "owner-session"
SOL_MODEL = "gpt-6.2-sol"
ASTRA_MODEL = "gpt-6.2-astra"
PYTHON = str(Path(sys.executable).resolve())
BEHAVIORS = ("A1", "A2S", "A2W", "A3")
CHECKS = dict(zip(BEHAVIORS, ("reader", "server", "display", "narrator")))
PRODUCTION = dict(zip(BEHAVIORS, ("reader.py", "server.py", "display.cjs", "narrator.py")))
SHARED_TEST = "behaviors_test.py"
WEB_TEST = "behaviors.test.cjs"
TEST_FILES = {item: WEB_TEST if item == "A2W" else SHARED_TEST for item in BEHAVIORS}
HARNESS = "proof-runner.json"
DEPENDENCIES = "proof-deps.lock"
INSTRUCTIONS = ("instructions.md", HARNESS, DEPENDENCIES)
READER_DEFECT = "fixture-reader-duplicate"

STUBS = {
    "reader.py": "def read(events):\n    return []\n",
    "server.py": "def status(method):\n    return 500\n",
    "display.cjs": "module.exports = () => 'unknown';\n",
    "narrator.py": "def caption(enabled):\n    return 'unknown'\n",
}
WORKING = {
    "reader.py": "def read(events):\n    return sorted(set(events))\n",
    "server.py": "def status(method):\n    return 405 if method == 'POST' else 200\n",
    "display.cjs": "module.exports = m => m === 'recorded' ? 'Replay' : 'No live telemetry';\n",
    "narrator.py": "def caption(enabled):\n    return 'on' if enabled else 'off'\n",
}
BROKEN_READER = "def read(events):\n    return sorted(events)\n"
REPAIRED_READER = "def read(events):\n    return sorted(dict.fromkeys(events))\n"
PYTHON_SUITE = """import unittest


class Behaviors(unittest.TestCase):
    def test_A1(self):
        from reader import read
        self.assertEqual(['a', 'b'], read(['b', 'a', 'b']))

    def test_A2S(self):
        from server import status
        self.assertEqual([200, 405], [status('GET'), status('POST')])

    def test_A2S_patch(self):
        from server import status
        self.assertEqual(405, status('PATCH'))

    def test_A3(self):
        from narrator import caption
        self.assertEqual(['off', 'on'], [caption(False), caption(True)])


if __name__ == '__main__':
    unittest.main()
"""
JS_SUITE = """const {test} = require('node:test');
const assert = require('node:assert/strict');
const label = require('./display.cjs');
test('A2W labels recorded and missing telemetry', () => {
  assert.equal(label('recorded'), 'Replay');
  assert.equal(label('unavailable'), 'No live telemetry');
});
"""


class Fixture(base.LifecycleFixture):
    """Host-shaped synthetic actors with native command and canonical case receipts."""

    consult_mapped = base.BoundaryRegressionTests.consult_mapped
    failure_intent = base.CaseTests.failure_intent

    def setUp(self):
        super().setUp()
        self.raw.write_text("SYNTHETIC_ONLY_NO_MODEL_INVOKED: local A1 fixture.\n")
        self.files = [*STUBS, SHARED_TEST, WEB_TEST]
        self.write_files({
            **STUBS,
            HARNESS: '{"python":"unittest","javascript":"node:test"}\n',
            DEPENDENCIES: "stdlib and node builtin tests\n",
        })
        self.git("init", "-q", "--initial-branch=fixture", "--template=")
        self.git("add", "--", *STUBS, *INSTRUCTIONS)
        self.git("-c", "user.name=A1 fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Synthetic before-state", "--no-gpg-sign")
        self.base_commit = self.git("rev-parse", "HEAD").strip()
        self.ledger = runtime.Ledger(str(self.db))
        self.plan = None
        self.decision_revision = None
        self.mapping = {
            "findings": [], "defects": [READER_DEFECT], "scope": ["reader.py", SHARED_TEST],
            "acceptance": ["A1"], "checks": ["reader"], "case_pairs": [],
        }

    def git(self, *args):
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args], cwd=self.repo,
            env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def contract(self):
        return dict(
            super().contract(),
            schema=RUN_SCHEMA,
            profile=PROFILE,
            objective="Preserve proof for four independent synthetic behaviors.",
            parent_request="Verify the current synthetic candidate.",
            tickets=[{"id": "fixture-ticket", "acceptance": list(BEHAVIORS)}],
            scope=self.files,
            test_scope=[SHARED_TEST, WEB_TEST],
            instructions=list(INSTRUCTIONS),
            write_boundary={"test": [SHARED_TEST, WEB_TEST], "production": list(STUBS), "excluded": ["app.py"]},
            contributors=[ACTOR, "lead-session"],
            policy={
                "schema": POLICY_SCHEMA, "queue_priority": "P2", "technical_risk": "Medium",
                "execution_lane": "Standard", "significant_architecture": False,
                "triggers": base.ordinary_policy()["triggers"], "direct_eligible": False,
                "reproducible_acceptance": True, "specialists": [], "tier_policy": "require_match",
            },
            source={"base": self.base_commit, "harness": [HARNESS], "dependencies": [DEPENDENCIES]},
            executor_mode=EXECUTOR,
            synthetic=True,
        )

    def initialize(self):
        self.ledger.init_run(self.contract())
        self.ensure_cases()
        self.push("route", "observation", {
            "kind": "ROUTING",
            "owner": self.actor(ACTOR),
            "probe": self.actor("probe-session"),
            "lead": self.actor("lead-session"),
        })

    def session_log(self, session, model, effort="max"):
        path = self.root / "synthetic-host-logs" / ("rollout-2026-11-03T00-00-00-" + session + ".jsonl")
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            rows = [
                {"type": "session_meta", "payload": {"id": session, "synthetic": True}},
                {"type": "turn_context", "payload": {
                    "model": model, "effort": effort,
                    "service_tier": "Standard" if model == ASTRA_MODEL else "Fast",
                    "context": {"fixture": True},
                }},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def actor(self, session, model=SOL_MODEL):
        tier = "Standard" if model == ASTRA_MODEL else "Fast"
        return {
            "session": session, "model": model, "effort": "max", "evidence": self.identity(session, model),
            "requested_tier": tier, "observed_tier": tier,
        }

    def reviewer(self, session, model):
        reviewer = super().reviewer(session, model)
        reviewer["excluded"] = sorted(set(reviewer["excluded"]) | {"lead-session"})
        return reviewer

    def push(self, event_id, kind, data):
        return self.ledger.append(RUN, {"id": event_id, "type": kind, "data": data}, self.history()["seq"])

    def cli(self, command, operation=None, *, request=None, run=RUN):
        argv = [PYTHON, "-B", str(base.SCRIPT), command]
        if operation:
            argv.append(operation)
        argv.extend(["--db", str(self.db)])
        if (command, operation) != ("run", "init"):
            argv.extend(["--run", run, "--expect", str(self.ledger.show(run)["seq"])])
        if request is not None:
            argv.extend(["--input", "-"])
        result = subprocess.run(
            argv, cwd=self.repo, input=json.dumps(request) if request is not None else None,
            capture_output=True, text=True, timeout=40, check=False,
        )
        return result, json.loads(result.stdout)

    def current(self):
        return runtime._v2().snapshot(self.history())

    def history(self):
        return self.ledger.show(RUN)

    def event(self, event_id, state=None):
        return next(e for e in (self.history() if state is None else state)["events"] if e["id"] == event_id)

    def write_files(self, files):
        for path, body in files.items():
            (self.repo / path).write_text(body)

    def plan_content(self, *, predeclared=True):
        return {
            "artifact": runtime.reference(self.raw),
            "scope": self.files,
            "test_scope": [SHARED_TEST, WEB_TEST],
            "acceptance": [{"id": item, "behavior": True} for item in BEHAVIORS],
            "checks": [*CHECKS.values(), "full", "unrelated", "verify-local"],
            "required_checks": [*CHECKS.values(), "full"],
            "result_map": {
                item: {"check": CHECKS[item], "production": [PRODUCTION[item]], "test": [TEST_FILES[item]]}
                for item in BEHAVIORS
            },
            "aggregate_checks": {"full": list(BEHAVIORS)},
            "decisions": [],
            "decision_reason": "Preserve exact native test and plan witnesses.",
            "contributors": [ACTOR, "lead-session"],
            "policy": self.contract()["policy"],
            "remediations": [self.mapping] if predeclared else [],
        }

    def publish_plan(self, name, content, *, approve=True, consultation=None):
        if consultation is None:
            lookup = self.consult_mapped(name + "-consult", "plan", name)
            consultation = lookup["consultation"]["id"]
        previous = self.plan
        self.plan = runtime.digest(content)
        self.content = copy.deepcopy(content)
        event = self.push(name, "plan", {
            "revision": self.plan, "content": content, "consultation": consultation, "supersedes": previous,
        })
        if approve:
            self.review(name + "-review", "plan_review", name + "-planner", ASTRA_MODEL)
        return event

    def decision(self, name, choice, *, behavior="A2S", strategy="REVIEW"):
        data = {
            "lineage": "status-contract", "kind": "ordinary", "strategy": strategy,
            "contributors": [ACTOR, "lead-session"], "artifact": runtime.reference(self.raw),
            "acceptance": [behavior], "choice": choice, "alternatives": [],
            "tradeoff": "Fixture status contract.", "supersedes": self.decision_revision,
        }
        self.decision_revision = runtime.digest(data)
        self.push(name, "decision", dict(data, revision=self.decision_revision))
        if strategy == "REVIEW":
            self.support(name + "-review")

    def support(self, name, verdict="SUPPORTED"):
        return self.push(name, "doubt_review", {
            "decision": "status-contract", "revision": self.decision_revision, "verdict": verdict,
            "reviewer": self.reviewer(name + "-reviewer", SOL_MODEL), "findings": [],
        })

    def retire(self, target, kind="withdrawal"):
        return self.push(kind + "-" + target, kind, {
            "target": target, "reason": "Retire this exact synthetic record.",
            "source": runtime.reference(self.raw),
        })

    def open_phase(self, name, mode, ids, *, bounded=False, expected="PASS"):
        request = {"id": name, "acceptance": list(ids)}
        if bounded:
            request["remediation"] = dict(self.mapping, before=self.current()["sha256"], reason="Repair reader only.")
        result = self.ledger.preflight(RUN, mode, self.history()["seq"], request)
        self.assertEqual(expected, result["state"], result)
        if expected == "PASS":
            write_scope = result["start"]["data"]["write_scope"]
            owned = set() if mode == "VERIFY" else {
                (TEST_FILES if mode == "TEST_ONLY" else PRODUCTION)[item] for item in ids
            }
            self.assertEqual(owned, set(write_scope), result)
        return result

    def selected_command(self, behavior, alternate=False):
        selection = behavior + ("_patch" if alternate else "")
        path = TEST_FILES[behavior]
        if behavior == "A2W":
            node = shutil.which("node")
            self.assertIsNotNone(node, "Node is required for the JavaScript behavior")
            return [str(Path(node).resolve()), "--test", path], "A2W labels recorded and missing telemetry"
        selector = "Behaviors.test_" + selection
        return [PYTHON, "-B", path, selector, "-v"], selector

    def request_proof(self, label, behavior, start, *, passing=True, alternate=False, **overrides):
        command, selection = self.selected_command(behavior, alternate)
        request = {
            "id": label, "phase": "GREEN" if passing else "RED", "check": CHECKS[behavior],
            "start": start, "command": command, "actor": ACTOR, "acceptance": behavior,
            "test_id": selection, "test_path": TEST_FILES[behavior],
        }
        if not passing:
            request["failure_kind"] = "ASSERTION"
        return self.ledger.prove(RUN, self.history()["seq"], dict(request, **overrides))

    def proof(self, label, behavior, start, *, passing=True, alternate=False):
        before = self.current()
        result = self.request_proof(label, behavior, start, passing=passing, alternate=alternate)
        self.assertEqual("PASS", result["state"], result)
        self.assertEqual(before, self.current())
        proof = result["proof"]
        data = proof["data"]
        receipt, raw = self.read_receipt(data["output"])
        expected_argv, selection = self.selected_command(behavior, alternate)
        self.assertEqual(expected_argv, receipt["argv"])
        self.assertEqual((before["sha256"], behavior, selection, CHECKS[behavior], start),
                         (data["candidate"], data["acceptance"], data["test_id"], data["check"], data["start"]))
        self.assertEqual(passing, receipt["exit"] == 0)
        self.assertEqual(receipt["exit"], data["exit"])
        self.assertIn(b"A2W labels" if behavior == "A2W" else b"Ran 1 test", raw)
        if not passing:
            self.assertIn(b"ERR_ASSERTION" if behavior == "A2W" else b"AssertionError", raw)
        return proof

    def read_receipt(self, ref):
        runtime.verify_reference(ref)
        receipt = json.loads(Path(ref["path"]).read_bytes())
        for stream in ("stdout", "stderr"):
            runtime.verify_reference(receipt[stream])
        output = Path(receipt["stdout"]["path"]).read_bytes() + Path(receipt["stderr"]["path"]).read_bytes()
        return receipt, output

    def command_check(self, name, start, check, command, **overrides):
        request = {"id": name, "phase": "CHECK", "check": check, "start": start, "actor": ACTOR, "command": command}
        return self.ledger.prove(RUN, self.history()["seq"], dict(request, **overrides))

    def coverage(self, name, start, proofs=None, **overrides):
        chosen = self.final_proofs if proofs is None else proofs
        request = {
            "id": name, "phase": "CHECK", "check": "full", "start": start, "actor": ACTOR,
            "results": [{"acceptance": item, "proof": proof["id"]} for item, proof in chosen.items()],
        }
        return self.ledger.prove(RUN, self.history()["seq"], dict(request, **overrides))

    def refuse(self, result, event_id, *, mentions=()):
        self.assertIn(result["state"], {"BLOCK", "HOLD"}, result)
        self.assertTrue(result["errors"], result)
        if mentions:
            self.assertTrue(any(word.casefold() in " ".join(result["errors"]).casefold() for word in mentions), result)
        self.assertFalse(any(e["id"] == event_id and e["type"] == "proof" for e in self.history()["events"]))

    def cycle(self, name, ids, *, before_green=None, submit=None, omit_green=()):
        submit = self.proof if submit is None else submit
        test, production = name + "-test", name + "-production"
        self.open_phase(test, "TEST_ONLY", ids)
        if not (self.repo / SHARED_TEST).exists() and any(TEST_FILES[item] == SHARED_TEST for item in ids):
            self.write_files({SHARED_TEST: PYTHON_SUITE})
        if "A2W" in ids and not (self.repo / WEB_TEST).exists():
            self.write_files({WEB_TEST: JS_SUITE})
        for item in ids:
            submit(name + "-red-" + item, item, test, passing=False)
        if before_green:
            before_green()
        self.open_phase(production, "PRODUCTION", ids)
        self.write_files({PRODUCTION[item]: WORKING[PRODUCTION[item]] for item in ids})
        for item in ids:
            if item not in omit_green:
                submit(name + "-green-" + item, item, production, passing=True)

    def initial_cycle(self, *, predeclared=True, decision=False, before_test=None, before_green=None,
                      submit=None, omit_green=(), break_reader=True):
        self.initialize()
        self.publish_plan("original-plan", self.plan_content(predeclared=predeclared))
        if decision:
            self.decision("d1", "GET and POST statuses")
        if before_test:
            before_test()
        self.cycle("original", BEHAVIORS, before_green=before_green, submit=submit, omit_green=omit_green)
        if break_reader:
            self.write_files({"reader.py": BROKEN_READER})

    def actual_failure(self, label, behavior):
        command, _ = self.selected_command(behavior)
        before = self.current()
        result = subprocess.run(command, cwd=self.repo, capture_output=True, timeout=15, check=False)
        self.assertEqual(before, self.current())
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(b"AssertionError", result.stderr)
        output = self.root / (label + "-failure.log")
        output.write_bytes(result.stdout + b"\n" + result.stderr)
        test_bytes = (self.repo / TEST_FILES[behavior]).read_bytes()
        preserved_test = self.root / ("failure-test-" + hashlib.sha256(test_bytes).hexdigest())
        if not preserved_test.exists():
            preserved_test.write_bytes(test_bytes)
        self.assertEqual(test_bytes, preserved_test.read_bytes())
        return {
            "command": command, "exit": result.returncode, "output": runtime.reference(output),
            "test": runtime.reference(preserved_test),
        }

    def capture_failure(self, name, behavior="A1", *, run=RUN, defect=READER_DEFECT):
        failed = self.actual_failure(name, behavior)
        failure_id = name + "-failure"
        broken = self.current()
        self.ledger.append(run, {"id": failure_id, "type": "failure", "data": {
            "defect": defect, "broken": broken, "command": failed["command"],
            "exit": failed["exit"], "output": failed["output"],
        }}, self.ledger.show(run)["seq"])
        request = self.failure_intent()
        request.update(id=name, defect=defect)
        request["failure"].update(command=failed["command"], output=failed["output"], inputs=[failed["test"]])
        case = request["case"]
        case.update(title="Synthetic " + CHECKS[behavior] + " failure", check_id=CHECKS[behavior])
        case["origin"].update(task_id=run, failure_id=failure_id)
        case["evidence_refs"][0]["sha256"] = failed["output"]["sha256"]
        result = self.ledger.capture(run, self.ledger.show(run)["seq"], request)
        self.assertEqual("PASS", result["state"], result)
        return result

    def repair_reader(self, *, late=False, change_shared_test=False, captured=False,
                      consulted=False, renew_start=False):
        if not captured:
            self.capture_failure("broken-reader")
        if late:
            self.publish_plan("repair-plan", dict(self.content, remediations=[self.mapping]))
        if not consulted:
            self.consult_mapped("repair-lookup", "repair", self.current()["sha256"])
        self.open_phase("repair-test", "TEST_ONLY", ["A1"], bounded=True)
        if change_shared_test:
            self.write_files({SHARED_TEST: PYTHON_SUITE + "\n# New shared Python test bytes.\n"})
            self.capture_failure("broken-after-test-edit")
            self.consult_mapped("repair-after-test-lookup", "repair", self.current()["sha256"])
        self.open_phase("too-early", "PRODUCTION", ["A1"], bounded=True, expected="BLOCK")
        self.proof("repair-red-A1", "A1", "repair-test", passing=False)
        self.open_phase("too-wide", "PRODUCTION", BEHAVIORS, bounded=True, expected="BLOCK")
        self.open_phase("repair-verify", "VERIFY", ["A1"], bounded=True)
        partial = self.command_check("repair-only-as-full", "repair-verify", "full", [PYTHON, "-B", "-c", "pass"])
        self.refuse(partial, "repair-only-as-full")
        if renew_start:
            self.open_phase("retired-repair", "PRODUCTION", ["A1"], bounded=True)
            self.retire("retired-repair", "supersession")
            self.open_phase("renewed-repair-test", "TEST_ONLY", ["A1"], bounded=True)
            self.proof("renewed-repair-red", "A1", "renewed-repair-test", passing=False)
            self.capture_failure("still-broken-reader")
            self.consult_mapped("renewed-repair-lookup", "repair", self.current()["sha256"])
        self.open_phase("repair-production", "PRODUCTION", ["A1"], bounded=True)
        before = self.current()
        self.write_files({"reader.py": REPAIRED_READER})
        after = self.current()
        changed = [p for p in self.files if before["files"][p] != after["files"][p]]
        self.assertEqual(["reader.py"], changed)
        green = self.proof("repair-green-A1", "A1", "repair-production")
        self.push("repaired", "repair", {
            "defect": READER_DEFECT, "outcome": "PASS", "before": before["sha256"], "after": after["sha256"],
            "output": green["data"]["output"], "start": "repair-production",
        })
        return green

    def rerun(self, *, start="repair-production", keep=None, reject=(), alternate_server=False, prefix="fresh-"):
        self.final_proofs = dict(keep or {})
        for item in BEHAVIORS:
            if item in self.final_proofs:
                continue
            label = prefix + item
            alternate = alternate_server and item == "A2S"
            if item in reject:
                self.refuse(self.request_proof(label, item, start, alternate=alternate), label)
            else:
                self.final_proofs[item] = self.proof(label, item, start, alternate=alternate)
        return self.final_proofs

    def proof_errors(self, proof, mode="PASS", state=None):
        state = self.history() if state is None else state
        return runtime._proof_errors(state, proof, mode, proof["data"]["candidate"], self.plan)

    def audit_execution(self, label, proofs):
        candidate = self.current()
        executed = []
        inspected = set()
        for item, proof in sorted(proofs.items()):
            data = proof["data"]
            self.assertEqual(candidate["sha256"], data["candidate"])
            command = data["command"]
            result = subprocess.run(command, cwd=self.repo, capture_output=True, timeout=15, check=False)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            streams = {}
            for stream in ("stdout", "stderr"):
                output = self.root / f"{label}-{item}-{stream}"
                with output.open("xb") as handle:
                    handle.write(getattr(result, stream))
                streams[stream] = runtime.reference(output)
            evidence = {"check": data["check"], "argv": command, "exit": result.returncode,
                        "candidate": candidate["sha256"], **streams}
            executed.append(evidence)
            print(json.dumps({"fixture_audit": label, "cwd": str(self.repo), "evidence": evidence,
                              "stdout": result.stdout.decode("utf-8"), "stderr": result.stderr.decode("utf-8")},
                             sort_keys=True), flush=True)
            inspected.update((PRODUCTION[item], data["test_path"]))
        self.assertEqual(candidate, self.current())
        return executed, sorted(inspected)

    def close(self, *, start="repair-production", prefix="final-"):
        aggregate = self.coverage(prefix + "full", start)
        self.assertEqual("PASS", aggregate["state"], aggregate)
        proof = aggregate["proof"]
        self.assertEqual({row["proof"] for row in proof["data"]["results"]},
                         {p["id"] for p in self.final_proofs.values()})
        candidate = self.current()["sha256"]
        for kind in ("code", "security", "tests"):
            label = prefix + "audit-" + kind
            executed, inspected = self.audit_execution(label, self.final_proofs)
            self.push(label, "audit", {
                "kind": kind, "plan": self.plan, "candidate": candidate, "verdict": "APPROVE",
                "reviewer": self.reviewer(prefix + kind + "-auditor", SOL_MODEL), "findings": [],
                "executed": executed, "inspected": inspected,
            })
        self.consult_mapped(prefix + "consult", "final", candidate)
        ready = self.ledger.check(RUN)
        self.assertTrue(ready["ready"], ready)
        self.push(prefix + "done", "observation", {
            "status": "COMPLETED", "summary": "Synthetic native checks passed.", "candidate": candidate,
        })
        self.push(prefix + "brief", "teaching", {
            "report": prefix + "done", "plan": self.plan, "candidate": candidate,
            "problem": "Keep current evidence for independent behaviors.", "path": "RED to own GREEN to current proof.",
            "decisions": [], "alternatives": [], "tradeoffs": [], "proofs": [proof["id"]],
            "sources": [proof["data"]["output"]], "principle": "Rerun each mapped behavior after source changes.",
            "example": "The reader repair leaves the server's test and write scope independent.",
            "limits": "Synthetic identities and local commands.",
        })
        done = self.ledger.check(RUN)
        self.assertEqual("PASS", done["state"], done)
        return proof

    def separate_fixture(self):
        fixture = Fixture()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def archived_case(self, check):
        case = self.failure_intent()["case"]
        case.update(check_id=check, title="Synthetic historical " + check + " regression")
        case["origin"]["task_id"] = "archived-run"
        path = self.root / (check + "-archived-case.json")
        path.write_text(json.dumps(case))
        result = subprocess.run(
            [PYTHON, "-B", str(base.CASE_HELPER), "capture", "--store", str(self.root / "cases"),
             "--kind", "case", "--input", str(path)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("CAPTURED_LOCAL", payload["state"], payload)
        return payload["digest"]

    def reopen_server(self, *, production=False, finish=False):
        self.open_phase("server-test", "TEST_ONLY", ["A2S"])
        self.proof("server-red", "A2S", "server-test", passing=False, alternate=True)
        if production:
            self.open_phase("server-production", "PRODUCTION", ["A2S"])
        if finish:
            self.write_files({"server.py": "def status(method):\n    return 200 if method == 'GET' else 405\n"})
            return self.proof("server-own-green", "A2S", "server-production", alternate=True)
        return None

    def finding(self, event, check):
        self.review(event, "audit", event + "-auditor", SOL_MODEL, audit_kind="code",
                    verdict="REVISE", findings=[{
                        "id": "coverage", "actionable": True, "material": False, "severity": "Medium",
                        "requirement": check, "evidence": runtime.reference(self.raw),
                        "consequence": "The required check has no current proof.",
                        "correction": "Execute the mapped current checks.", "validation": check,
                        "text": "Establish current executed coverage.",
                    }])

    def disposition(self, review, proof, *, action="NOT_APPLICABLE"):
        data = {
            "review": review, "finding": "coverage", "action": action,
            "reason": "Current native results resolve this fixture concern.",
            "evidence": proof["data"]["output"], "recheck": proof["id"],
        }
        if action == "FIXED":
            recheck = self.push("recheck-" + proof["id"], "recheck", {
                "plan": self.plan, "candidate": self.current()["sha256"], "verdict": "APPROVE",
                "proof": proof["id"], "reviewer": self.reviewer("independent-" + proof["id"], SOL_MODEL),
                "findings": [],
            })
            data["review_recheck"] = recheck["id"]
        self.push("resolve-" + proof["id"], "disposition", data)


class RetainedFixture:
    """Keep the native receipts and disposable source for an independent readback."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory
        register_cleanup = self.addCleanup

        def register(callback, *args, **kwargs):
            directory = getattr(self, "temp", None)
            if directory is None or callback != directory.cleanup:
                register_cleanup(callback, *args, **kwargs)

        with (
            patch.object(tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary(delete=False, **kw)),
            patch.object(self, "addCleanup", side_effect=register),
        ):
            super().setUp()
        print("retained synthetic proof fixture", self.root, flush=True)


class PublicBoundaryTests(Fixture):
    def test_public_run_initializes_explicit_v2(self):
        completed, result = self.cli("run", "init", request=self.contract())
        self.assertEqual(
            0, completed.returncode,
            f"The existing run init command must admit the valid explicit v2 contract. Response: {result}",
        )
        self.assertEqual(RUN_SCHEMA, result["contract"]["schema"])
        self.assertEqual(PROFILE, result["contract"]["profile"])
        self.assertEqual(self.base_commit, result["contract"]["source"]["base"])
        _, replay = self.cli("run", "show")
        self.assertEqual((0, result["sha256"]), (replay["seq"], replay["sha256"]))

    def test_public_run_keeps_v1_schema_and_digest(self):
        contract = base.LifecycleFixture.contract(self)
        contract["run_id"] = "v1-fixture"
        completed, result = self.cli("run", "init", request=contract)
        self.assertEqual(0, completed.returncode, result)
        _, replay = self.cli("run", "show", run=contract["run_id"])
        self.assertEqual(contract, replay["contract"])
        self.assertEqual(result["sha256"], replay["sha256"])


class FourBehaviorRepairTests(Fixture):
    def test_predeclared_and_late_approved_repairs_finish_all_four(self):
        for late in (False, True):
            with self.subTest(late=late):
                f = self.separate_fixture()
                f.initial_cycle(predeclared=not late)
                green = f.repair_reader(late=late)
                self.assertFalse(f.ledger.check(RUN)["ready"])
                f.rerun(keep={"A1": green})
                f.close()

    def test_ordinary_sequential_cycles_verify_prior_behavior_without_write_ownership(self):
        self.initialize()
        self.publish_plan("original-plan", self.plan_content(predeclared=False))
        self.cycle("reader", ["A1"])
        old = self.event("reader-green-A1")
        self.cycle("later", ["A2S", "A2W", "A3"])
        start = self.event("later-production")
        self.assertNotIn("A1", start["data"]["acceptance"])
        self.assertNotIn("reader.py", start["data"]["write_scope"])
        self.assertNotEqual(old["data"]["candidate"], self.current()["sha256"])
        self.rerun(start=start["id"], keep={item: self.event("later-green-" + item) for item in BEHAVIORS[1:]})
        actual = self.final_proofs["A1"]
        self.assertEqual(old["data"]["command"], actual["data"]["command"])
        self.assertEqual(self.current()["sha256"], actual["data"]["candidate"])
        self.assertGreater(actual["seq"], start["seq"])
        self.close(start=start["id"])

    def test_unfinished_own_test_or_production_cycle_cannot_be_carried(self):
        for production in (False, True):
            with self.subTest(production=production):
                f = self.separate_fixture()
                f.initial_cycle()
                f.reopen_server(production=production)
                green = f.repair_reader()
                f.rerun(keep={"A1": green}, reject=("A2S",))
                self.assertFalse(f.ledger.check(RUN)["ready"])

    def test_most_recent_completed_own_cycle_can_supply_the_pair(self):
        self.initial_cycle()
        own = self.reopen_server(production=True, finish=True)
        green = self.repair_reader()
        self.refuse(self.request_proof("stale-selection", "A2S", "repair-production"), "stale-selection")
        self.rerun(keep={"A1": green}, alternate_server=True)
        self.assertEqual(own["data"]["command"], self.final_proofs["A2S"]["data"]["command"])
        self.close()

    def test_changed_shared_test_invalidates_affected_behaviors_only(self):
        self.initial_cycle()
        green = self.repair_reader(change_shared_test=True)
        self.rerun(keep={"A1": green}, reject=("A2S", "A3"))
        self.assertEqual([], self.proof_errors(self.final_proofs["A2W"]))
        self.assertFalse(self.ledger.check(RUN)["ready"])

    def test_fresh_pass_cannot_replace_missing_prior_own_green(self):
        self.initial_cycle(omit_green=("A2W",))
        green = self.repair_reader()
        self.rerun(keep={"A1": green}, reject=("A2W",))
        self.assertFalse(self.ledger.check(RUN)["ready"])

    def test_validation_rechecks_test_command_source_and_profile_identity(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        original = self.final_proofs["A2S"]
        self.assertEqual([], self.proof_errors(original))
        other = self.final_proofs["A2W"]
        for field, value in (
            ("test", other["data"]["test"]), ("test_path", WEB_TEST), ("test_id", "unknown-selection"),
            ("check", "reader"), ("command", [PYTHON, "-V"]), ("candidate", "0" * 64),
        ):
            with self.subTest(field=field):
                altered = copy.deepcopy(original)
                altered["data"][field] = value
                for mode in ("GREEN", "PASS"):
                    self.assertTrue(self.proof_errors(altered, mode))
        altered = dict(original, observed_profile={"sha256": "0" * 64})
        self.assertTrue(self.proof_errors(altered))

    def test_missing_original_red_stream_blocks_current_proof(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        self.close()
        red = self.event("original-red-A2S")
        receipt, _ = self.read_receipt(red["data"]["output"])
        Path(receipt["stderr"]["path"]).write_bytes(b"Tampered original assertion output.\n")
        self.assertTrue(self.proof_errors(self.final_proofs["A2S"]))
        self.assertFalse(self.ledger.check(RUN)["ready"])

    def test_material_change_and_unapproved_intermediate_plan_do_not_revive_carry(self):
        for material in (False, True):
            with self.subTest(material=material):
                f = self.separate_fixture()
                f.initial_cycle(predeclared=False)
                original = copy.deepcopy(f.content)
                if material:
                    f.publish_plan("changed", dict(original, decision_reason="Different acceptance contract."))
                    f.publish_plan("restored", original)
                    green = f.repair_reader(late=True)
                else:
                    other = dict(f.mapping, defects=["other-fixture-defect"])
                    f.publish_plan("unapproved", dict(original, remediations=[other]), approve=False)
                    f.capture_failure("broken-reader")
                    f.publish_plan("approved", dict(original, remediations=[other, f.mapping]))
                    f.consult_mapped("repair-lookup", "repair", f.current()["sha256"])
                    green = f.repair_reader(captured=True, consulted=True)
                f.rerun(keep={"A1": green}, reject=BEHAVIORS[1:])
                self.assertFalse(f.ledger.check(RUN)["ready"])

    def test_relevant_decision_change_and_restoration_do_not_revive_carry(self):
        for before_production in (False, True):
            with self.subTest(before_production=before_production):
                f = self.separate_fixture()
                changed = lambda: f.decision("d2", "GET, POST and PATCH statuses")
                f.initial_cycle(decision=True, before_green=changed if before_production else None)
                if not before_production:
                    changed()
                    f.decision("d3", "GET and POST statuses")
                green = f.repair_reader()
                f.rerun(keep={"A1": green}, reject=("A2S",))
                self.assertFalse(f.ledger.check(RUN)["ready"])

    def test_old_decision_support_cannot_be_restored_retroactively(self):
        self.initial_cycle(decision=True)
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        current = self.final_proofs["A2S"]
        self.assertEqual([], self.proof_errors(current))
        self.support("rejected-support", "REVISE")
        self.support("restored-support")
        self.assertTrue(self.proof_errors(current))
        self.refuse(self.request_proof("replayed-support", "A2S", "repair-production"), "replayed-support")

    def test_new_decision_invalidates_subsequent_case_and_finding_consumption(self):
        self.initial_cycle(decision=True)
        green = self.repair_reader()
        self.archived_case("server")
        self.finding("server-review", "server")
        self.rerun(keep={"A1": green})
        server = self.final_proofs["A2S"]
        self.disposition("server-review", server, action="FIXED")
        self.close()
        self.decision("later-d2", "Changed GET and POST statuses")
        for restoring in (False, True):
            if restoring:
                self.decision("restored-d3", "GET and POST statuses")
            with self.subTest(restoring=restoring):
                issues = self.ledger.check(RUN)["errors"]
                self.assertTrue(self.proof_errors(server))
                self.assertIn("carried case regression proof missing: server", issues)
                self.assertIn("unresolved actionable finding server-review/coverage", issues)

    def test_unrelated_real_failure_stays_blocking_and_preserves_command_output(self):
        self.initial_cycle()
        self.write_files({"server.py": STUBS["server.py"]})
        green = self.repair_reader()
        self.rerun(keep={"A1": green}, reject=("A2S",))
        failed = self.actual_failure("server-not-fixed", "A2S")
        self.assertIn(b"AssertionError", Path(failed["output"]["path"]).read_bytes())
        self.assertFalse(self.ledger.check(RUN)["ready"])

    def test_rerun_does_not_authorize_production_edit_of_another_behavior(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        self.write_files({"server.py": "# Out of the reader repair scope.\n" + WORKING["server.py"]})
        issues = self.ledger.check(RUN)["errors"]
        self.assertTrue(any("scope" in message for message in issues), issues)

    def test_same_digest_needs_timely_approval_for_each_original_proof(self):
        for selected in ("original-red-A2S", "original-green-A2S"):
            with self.subTest(selected=selected):
                f = self.separate_fixture()

                def issue(label, behavior, start, *, passing=True):
                    if label != selected:
                        return f.proof(label, behavior, start, passing=passing)
                    original = f.plan
                    f.publish_plan("repeated-plan", copy.deepcopy(f.content), approve=False)
                    self.assertEqual(original, f.plan)
                    blocked = f.request_proof(label, behavior, start, passing=passing)
                    f.refuse(blocked, label, mentions=("approv", "review", "plan"))
                    f.review("timely-for-new-execution", "plan_review", "later-planner", ASTRA_MODEL)
                    f.refuse(f.request_proof(label + "-bad-actor", behavior, start, passing=passing,
                                             actor="unknown-session"), label + "-bad-actor")
                    return f.proof(label + "-lawfully-reissued", behavior, start, passing=passing)

                f.initial_cycle(submit=issue)
                self.assertFalse(any(e["id"] == selected for e in f.history()["events"]))
                green = f.repair_reader()
                f.rerun(keep={"A1": green})
                f.close()

    def test_carry_cannot_be_issued_during_a_repeated_plan_approval_gap(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        self.archived_case("server")
        self.publish_plan("repeated-plan", copy.deepcopy(self.content), approve=False)
        self.finding("server-review", "server")
        result = self.request_proof("server-before-approval", "A2S", "repair-production")
        self.refuse(result, "server-before-approval", mentions=("approv", "review", "plan"))
        self.review("late-plan-review", "plan_review", "late-planner", ASTRA_MODEL)
        self.assertFalse(any(e["id"] == "server-before-approval" for e in self.history()["events"]))
        repaired = self.proof("server-after-approval", "A2S", "repair-production")
        self.final_proofs["A2S"] = repaired
        self.disposition("server-review", repaired)
        self.close()

    def test_each_selected_dependency_remains_live_through_current_consumption(self):
        targets = (
            "original-plan", "original-revision", "original-plan-review", "d1", "decision-revision",
            "d1-review", "original-test", "original-red-A2S", "original-production", "original-green-A2S",
            "repair-plan", "repair-plan-review", "repair-production", "fresh-A2S",
        )
        for target in targets:
            with self.subTest(target=target):
                f = self.separate_fixture()
                f.initial_cycle(predeclared=False, decision=True)
                original = f.plan
                green = f.repair_reader(late=True)
                f.archived_case("server")
                f.finding("server-review", "server")
                f.rerun(keep={"A1": green})
                proof = f.final_proofs["A2S"]
                f.disposition("server-review", proof)
                f.close()
                self.assertEqual([], f.proof_errors(proof))
                identity = {"original-revision": original, "decision-revision": f.decision_revision}.get(target, target)
                f.retire(identity, "supersession" if target.endswith("revision") else "withdrawal")
                issues = f.ledger.check(RUN)["errors"]
                self.assertTrue(f.proof_errors(proof), target)
                self.assertIn("carried case regression proof missing: server", issues)
                self.assertIn("unresolved actionable finding server-review/coverage", issues)

    def test_original_boundary_rejects_selected_withdrawal_before_start(self):
        for target in ("original-plan", "original-plan-review", "d1", "d1-review"):
            with self.subTest(target=target):
                f = self.separate_fixture()
                f.initialize()
                f.publish_plan("original-plan", f.plan_content())
                f.decision("d1", "GET and POST statuses")
                f.retire(target, "supersession")
                f.open_phase("withdrawn-original-start", "TEST_ONLY", BEHAVIORS, expected="BLOCK")
                self.assertFalse(any(e["id"] == "withdrawn-original-start" for e in f.history()["events"]))

    def test_withdrawn_result_can_be_reissued_but_old_disposition_stays_open(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.archived_case("server")
        self.finding("server-review", "server")
        self.rerun(keep={"A1": green})
        original = self.final_proofs["A2S"]
        self.disposition("server-review", original, action="FIXED")
        self.close()
        self.retire(original["id"])
        self.assertTrue(self.proof_errors(original))
        new = self.proof("replacement-server-result", "A2S", "repair-production")
        self.final_proofs["A2S"] = new
        self.assertEqual([], self.proof_errors(new))
        self.assertIn("unresolved actionable finding server-review/coverage", self.ledger.check(RUN)["errors"])
        self.disposition("server-review", new, action="FIXED")
        self.close(prefix="reverified-")

    def test_unqualified_plan_review_after_issuance_blocks_later_consumption(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        proof = self.final_proofs["A2S"]
        self.close()
        original = self.history()
        reviewer = dict(self.reviewer("unqualified-planner", ASTRA_MODEL), fresh=False)
        self.push("unqualified-approval", "plan_review", {
            "plan": self.plan, "verdict": "APPROVE", "reviewer": reviewer, "findings": [],
        })
        self.review("qualified-again", "plan_review", "restoring-planner", ASTRA_MODEL)
        self.assertEqual([], self.proof_errors(proof, state=original))
        self.assertTrue(self.proof_errors(proof))
        self.assertFalse(self.ledger.check(RUN)["ready"])

    def test_later_support_does_not_retire_an_issuance_witness(self):
        for kind, selected in (("plan", "original-plan-review"), ("decision", "d1-review")):
            with self.subTest(kind=kind):
                f = self.separate_fixture()
                f.initial_cycle(decision=True)
                green = f.repair_reader()
                f.rerun(keep={"A1": green})
                f.close()
                if kind == "plan":
                    f.review("replacement", "plan_review", "replacement-planner", ASTRA_MODEL)
                else:
                    f.support("replacement")
                self.assertTrue(f.ledger.check(RUN)["ready"])
                f.retire(selected)
                self.assertTrue(f.proof_errors(f.final_proofs["A2S"]))
                self.assertFalse(f.ledger.check(RUN)["ready"])

    def test_real_new_bounded_cycle_recovers_after_retired_start(self):
        self.initial_cycle()
        green = self.repair_reader(renew_start=True)
        self.rerun(keep={"A1": green})
        self.close()

    def test_withdrawn_start_cannot_authorize_a_rerun(self):
        self.initial_cycle()
        self.repair_reader()
        self.retire("repair-production", "supersession")
        self.refuse(self.request_proof("retired-start-result", "A2S", "repair-production"),
                    "retired-start-result", mentions=("start", "withdraw", "supersed"))

    def test_fresh_cycle_recovers_after_old_support_is_withdrawn(self):
        self.initial_cycle(decision=True)
        self.support("temporary")
        self.retire("temporary")
        self.support("replacement")
        self.reopen_server(production=True, finish=True)
        green = self.repair_reader()
        self.rerun(keep={"A1": green}, alternate_server=True)
        self.close()

    def test_retired_unrelated_and_future_witnesses_do_not_poison_a_lawful_pair(self):
        def support():
            self.support("current-support")
            self.retire("d1-review")
            self.retire("unrelated")
            self.retire("fresh-A2S")

        self.initial_cycle(decision=True, before_test=support)
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        self.close()

    def test_tdd_red_deferral_and_preselection_decision_reassignment(self):
        for reassign in (False, True):
            with self.subTest(reassign=reassign):
                f = self.separate_fixture()

                def before():
                    if reassign:
                        f.decision("historical-server", "Originally applies to the server")
                        f.decision("current-narrator", "Now applies only to narrator", behavior="A3")
                    else:
                        f.decision("tdd-only", "Resolve via the intended server assertion", strategy="TDD_RED")

                f.initial_cycle(before_test=before)
                if reassign:
                    f.decision("new-narrator", "Changed narrator choice", behavior="A3")
                green = f.repair_reader()
                f.rerun(keep={"A1": green}, reject=("A3",) if reassign else ())
                self.assertEqual([], f.proof_errors(f.final_proofs["A2S"]))
                if not reassign:
                    f.close()

    def test_effective_support_loss_differs_from_retirement_of_old_support(self):
        for lane in ("plan", "decision"):
            for kind in ("withdrawal", "supersession"):
                for selected in (False, True):
                    with self.subTest(lane=lane, kind=kind, selected=selected):
                        f = self.separate_fixture()
                        f.initial_cycle(decision=True)
                        green = f.repair_reader()
                        f.rerun(keep={"A1": green})
                        f.close()
                        proof = f.final_proofs["A2S"]

                        def support(name):
                            if lane == "plan":
                                f.review(name, "plan_review", name + "-planner", ASTRA_MODEL)
                            else:
                                f.support(name)

                        support("first-support")
                        support("current-support")
                        self.assertEqual([], f.proof_errors(proof))
                        f.retire("current-support" if selected else "first-support", kind)
                        support("replacement-support")
                        self.assertEqual(selected, bool(f.proof_errors(proof)))
                        self.assertEqual(not selected, f.ledger.check(RUN)["ready"])

    def test_support_loss_between_original_and_rerun_boundaries_is_not_laundered(self):
        for lane in ("plan", "decision"):
            for selected in ("original-red-A2S", "original-green-A2S", "fresh-A2S"):
                for position in ("before", "after"):
                    with self.subTest(lane=lane, selected=selected, position=position):
                        f = self.separate_fixture()

                        def interrupt():
                            if lane == "plan":
                                f.review("temporary", "plan_review", "temp-planner", ASTRA_MODEL)
                            else:
                                f.support("temporary")
                            f.retire("temporary", "supersession")
                            if lane == "plan":
                                f.review("restored", "plan_review", "restored-planner", ASTRA_MODEL)
                            else:
                                f.support("restored")

                        def issue(label, behavior, start, *, passing=True):
                            if label == selected and position == "before":
                                interrupt()
                            proof = f.proof(label, behavior, start, passing=passing)
                            if label == selected and position == "after":
                                interrupt()
                            return proof

                        f.initial_cycle(decision=True, submit=issue)
                        green = f.repair_reader()
                        if (selected, position) == ("fresh-A2S", "after"):
                            f.rerun(keep={"A1": green})
                            interrupt()
                            self.assertTrue(f.proof_errors(f.final_proofs["A2S"]))
                        else:
                            if selected == "fresh-A2S":
                                interrupt()
                            f.refuse(f.request_proof("after-gap", "A2S", "repair-production"), "after-gap")
                        self.assertFalse(f.ledger.check(RUN)["ready"])

    def test_retired_plan_review_and_other_behavior_support_stay_scoped(self):
        self.initial_cycle(predeclared=False, before_test=lambda: self.decision(
            "narrator", "Narrator choice", behavior="A3"))
        previous = self.plan
        green = self.repair_reader(late=True)
        self.push("retired-plan-review", "plan_review", {
            "plan": previous, "verdict": "REVISE",
            "reviewer": self.reviewer("retired-plan-planner", ASTRA_MODEL), "findings": [],
        })
        self.rerun(keep={"A1": green})
        self.close()
        self.retire("retired-plan-review")
        self.assertTrue(self.ledger.check(RUN)["ready"])
        self.support("temporary-narrator")
        self.retire("temporary-narrator")
        self.support("replacement-narrator")
        self.assertEqual([], self.proof_errors(self.final_proofs["A2S"]))
        self.assertTrue(self.proof_errors(self.final_proofs["A3"]))

    def test_bad_plan_lookup_cannot_be_reused_or_replaced_after_issuance(self):
        for bad in ("reused", "wrong-target", "late-applicability", "stale-cases"):
            with self.subTest(bad=bad):
                f = self.separate_fixture()
                f.initial_cycle(predeclared=False)
                if bad == "stale-cases":
                    early = f.consult_mapped("stale-plan-lookup", "plan", "repair-plan")["consultation"]
                f.capture_failure("broken-reader")
                if bad == "reused":
                    chosen = f.event("original-plan-consult")
                elif bad == "wrong-target":
                    chosen = f.consult_mapped("different-lookup", "plan", "different-plan")["consultation"]
                elif bad == "late-applicability":
                    chosen = f.consultation("unclassified-lookup", "plan", "repair-plan",
                                             classify=False)["consultation"]
                else:
                    chosen = early
                f.publish_plan("repair-plan", dict(f.content, remediations=[f.mapping]), consultation=chosen["id"])
                if bad == "late-applicability":
                    for index, digest in enumerate(chosen["data"]["known"]):
                        f.push("late-case-" + str(index), "case_decision", {
                            "consultation": chosen["id"], "digest": digest, "applicability": "APPLIES",
                            "reason": "Classified after the plan was issued.", "checks": ["reader"],
                        })
                f.consult_mapped("repair-lookup", "repair", f.current()["sha256"])
                f.open_phase("bad-plan-start", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")
                f.consult_mapped("belated-plan-lookup", "plan", "repair-plan")
                f.open_phase("still-bad-plan-start", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")

    def test_plan_lookup_preserves_historical_knowledge_boundary(self):
        self.initial_cycle(predeclared=False)
        green = self.repair_reader(late=True)
        later = self.archived_case("server")
        self.rerun(keep={"A1": green})
        self.close()
        plan = self.event("repair-plan")
        original_lookup = self.event(plan["data"]["consultation"])
        self.assertEqual("repair-plan", original_lookup["data"]["target"])
        self.assertNotIn(later, original_lookup["data"]["known"])
        self.assertIn(later, self.event("final-consult")["data"]["shown"])

    def test_timely_lookup_recovery_qualifies_exact_same_target(self):
        self.initial_cycle(predeclared=False)
        self.capture_failure("broken-reader")
        request = {"id": "failed-plan-lookup", "stage": "plan", "target": "repair-plan",
                   "query": "synthetic assignment"}
        store, offline = self.root / "cases", self.root / "offline-cases"
        store.rename(offline)
        try:
            blocked = self.ledger.consult(RUN, self.history()["seq"], request)
            self.assertEqual("BLOCK", blocked["state"], blocked)
        finally:
            offline.rename(store)
        lookup = self.consultation("recovered-plan-lookup", "plan", "repair-plan", classify=False,
                                   recovery_for=request["id"], recovery_reason="Restore the fixture's private store.")
        event = lookup["consultation"]
        for index, (digest, reference) in enumerate(event["data"]["shown"].items()):
            check = json.loads(Path(reference["path"]).read_bytes())["record"]["check_id"]
            self.push("recovered-case-" + str(index), "case_decision", {
                "consultation": event["id"], "digest": digest, "applicability": "APPLIES",
                "reason": "The recovered exact-target lookup showed this case.", "checks": [check],
            })
        self.publish_plan("repair-plan", dict(self.content, remediations=[self.mapping]), consultation=event["id"])
        green = self.repair_reader(captured=True)
        self.rerun(keep={"A1": green})
        self.close()


class CoverageTests(Fixture):
    def test_native_producer_refuses_partial_duplicate_stale_and_misattributed_coverage(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        full = [{"acceptance": item, "proof": proof["id"]} for item, proof in self.final_proofs.items()]
        substitutions = {
            "partial": full[:1],
            "duplicate": full + [full[0]],
            "misattributed": [dict(row, proof=full[0]["proof"]) for row in full],
            "extra": full + [{"acceptance": "unknown", "proof": full[0]["proof"]}],
            "stale": [dict(row, proof="original-green-A2S") if row["acceptance"] == "A2S" else row for row in full],
            "opaque": [{"acceptance": "A1", "proof": self.raw.as_posix()}],
        }
        for name, rows in substitutions.items():
            with self.subTest(name=name):
                label = "bad-full-" + name
                before = self.history()["sha256"]
                self.refuse(self.coverage(label, "repair-production", results=rows), label)
                self.assertEqual(before, self.history()["sha256"])
        ordinary = self.command_check("generic-check", "repair-production", "verify-local",
                                      [PYTHON, "-B", "-c", "print('one named check')"])
        self.assertEqual("PASS", ordinary["state"], ordinary)
        self.assertEqual("verify-local", ordinary["proof"]["data"]["check"])
        self.assertFalse(self.ledger.check(RUN)["ready"])
        self.close()

    def test_aggregate_rechecks_native_command_and_stream_receipts(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.rerun(keep={"A1": green})
        proof = self.close()
        receipt, _ = self.read_receipt(self.final_proofs["A2S"]["data"]["output"])
        stream = Path(receipt["stderr"]["path"])
        actual = stream.read_bytes()
        try:
            stream.write_bytes(actual + b"synthetic tampering\n")
            self.refuse(self.coverage("after-receipt-drift", "repair-production"), "after-receipt-drift")
            self.assertTrue(self.proof_errors(proof))
            self.assertFalse(self.ledger.check(RUN)["ready"])
        finally:
            stream.write_bytes(actual)

    def test_withdrawn_native_subresult_blocks_aggregate_case_and_finding_consumers(self):
        self.initial_cycle()
        green = self.repair_reader()
        self.archived_case("full")
        self.finding("coverage-review", "full")
        self.rerun(keep={"A1": green})
        result = self.coverage("covered-finding", "repair-production")
        self.assertEqual("PASS", result["state"], result)
        aggregate = result["proof"]
        self.disposition("coverage-review", aggregate)
        self.close()
        self.retire(self.final_proofs["A2S"]["id"])
        self.refuse(self.coverage("withdrawn-subresult", "repair-production"), "withdrawn-subresult")
        issues = self.ledger.check(RUN)["errors"]
        self.assertTrue(self.proof_errors(aggregate))
        self.assertIn("carried case regression proof missing: full", issues)
        self.assertIn("unresolved actionable finding coverage-review/coverage", issues)


class InheritedCaseTests(Fixture):
    def bind_fixture_parent(self):
        prior_run = "earlier-reader-run"
        self.ledger.init_run(dict(self.contract(), run_id=prior_run))
        parent = self.capture_failure("prior-reader-capture", run=prior_run)
        child = self.capture_failure("broken-reader")
        self.mapping = dict(self.mapping, case_pairs=[{"digest": parent["digest"], "check": "reader"}])
        self.publish_plan("repair-plan", dict(self.content, remediations=[self.mapping]))
        consultation = self.consult_mapped("repair-lookup", "repair", self.current()["sha256"])["consultation"]
        request = {
            "id": "bind-inherited-reader", "digest": parent["digest"], "check": "reader",
            "defect": READER_DEFECT, "failure": "broken-reader-failure", "case_link": child["link"]["id"],
            "consultation": consultation["id"], "before": self.current()["sha256"], "plan": self.plan,
            "prior_run": prior_run, "prior_prefix": self.ledger.show(prior_run)["sha256"],
            "relation": {"source": runtime.reference(self.raw), "reason": "Both actual runs reproduce the same duplicate."},
        }
        return parent, child, request

    def test_exact_inherited_binding_unblocks_only_bounded_repair_and_retains_original_origin(self):
        self.initial_cycle(predeclared=False)
        parent, child, request = self.bind_fixture_parent()
        blocked = self.open_phase("no-binding", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")
        self.assertTrue(any("reader" in message for message in blocked["errors"]), blocked)
        for field, wrong in (("check", "server"), ("prior_prefix", "0" * 64), ("before", "1" * 64)):
            with self.subTest(field=field):
                completed, rejected = self.cli("case", "bind", request=dict(request, **{field: wrong}))
                self.assertNotEqual(0, completed.returncode, rejected)
                self.assertIn(rejected["state"], {"BLOCK", "HOLD"}, rejected)
        completed, bound = self.cli("case", "bind", request=request)
        self.assertEqual(0, completed.returncode, bound)
        self.assertEqual("PASS", bound["state"], bound)
        self.open_phase("ordinary-still-blocked", "TEST_ONLY", ["A2S"], expected="BLOCK")
        self.assertFalse(self.ledger.check(RUN)["ready"])
        green = self.repair_reader(captured=True, consulted=True)
        self.rerun(keep={"A1": green})
        self.close()
        final = self.event("final-consult")["data"]
        self.assertIn(parent["digest"], final["known"])
        self.assertIn(child["digest"], final["known"])
        origin = json.loads(Path(final["shown"][parent["digest"]]["path"]).read_bytes())["record"]["origin"]
        self.assertEqual("earlier-reader-run", origin["task_id"])
        current_links = {e["data"]["digest"] for e in self.history()["events"] if e["type"] == "case_link"}
        self.assertEqual({child["digest"]}, current_links)

    def test_binding_cannot_defer_unrelated_applicable_check(self):
        self.initial_cycle(predeclared=False)
        self.archived_case("unrelated")
        _, _, request = self.bind_fixture_parent()
        completed, bound = self.cli("case", "bind", request=request)
        self.assertEqual(0, completed.returncode, bound)
        blocked = self.open_phase("unrelated-still-due", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")
        self.assertIn("carried case regression proof missing: unrelated", blocked["errors"])


class ProofExecutorTests(Fixture):

    def test_invalid_start_actor_and_unsupported_host_never_launch_proof_argv(self):
        self.initial_cycle(break_reader=False)
        self.open_phase("contained-verify", "VERIFY", BEHAVIORS)
        marker = "A1-proof-command-must-not-launch"
        command = [PYTHON, "-B", "-c", "print(" + repr(marker) + ")"]
        with patch("subprocess.Popen", wraps=subprocess.Popen) as launched:
            for label, start, actor in (("bad-start", "missing-start", ACTOR),
                                        ("bad-actor", "contained-verify", "wrong-session")):
                self.refuse(self.command_check(label, start, "verify-local", command, actor=actor), label)
            with patch.object(sys, "platform", "linux"):
                self.refuse(self.command_check("unsupported-host", "contained-verify", "verify-local", command),
                            "unsupported-host")
        self.assertFalse(any(marker in repr(call) for call in launched.call_args_list))

    def test_proof_refuses_changed_harness_before_starting_command(self):
        self.initial_cycle(break_reader=False)
        self.open_phase("before-harness-drift", "VERIFY", BEHAVIORS)
        self.write_files({HARNESS: '{"python":"different harness"}\n'})
        marker = "A1-proof-drift-command-must-not-launch"
        command = [PYTHON, "-B", "-c", "print(" + repr(marker) + ")"]
        with patch("subprocess.Popen", wraps=subprocess.Popen) as launched:
            refused = self.command_check("drifted-proof", "before-harness-drift", "verify-local", command)
        self.refuse(refused, "drifted-proof", mentions=("harness", "source", "candidate", "identity"))
        self.assertFalse(any(marker in repr(call) for call in launched.call_args_list))

    def test_setup_failure_cannot_be_red_and_retains_native_streams(self):
        self.initialize()
        self.publish_plan("original-plan", self.plan_content())
        self.open_phase("test-start", "TEST_ONLY", ["A1"])
        self.write_files({SHARED_TEST: PYTHON_SUITE})
        command = [PYTHON, "-B", "-c", "import fixture_module_that_does_not_exist"]
        failed = self.request_proof("setup-is-not-red", "A1", "test-start", passing=False, command=command)
        self.refuse(failed, "setup-is-not-red")
        receipt, raw = self.read_receipt(failed["receipt"])
        self.assertEqual(command, receipt["argv"])
        self.assertNotEqual(0, receipt["exit"])
        self.assertIn(b"ModuleNotFoundError", raw)
        self.open_phase("production-is-still-blocked", "PRODUCTION", ["A1"], expected="BLOCK")

    def test_timeout_preserves_actual_streams_and_does_not_admit_check(self):
        self.initial_cycle(break_reader=False)
        self.open_phase("timeout-verify", "VERIFY", BEHAVIORS)
        command = [PYTHON, "-B", "-c", "import time; print('started timeout fixture', flush=True); time.sleep(20)"]
        failed = self.command_check("timed-out", "timeout-verify", "verify-local", command, timeout_seconds=1)
        self.refuse(failed, "timed-out")
        receipt, raw = self.read_receipt(failed["receipt"])
        self.assertEqual(command, receipt["argv"])
        self.assertTrue(receipt["timed_out"])
        self.assertIn(b"started timeout fixture", raw)


class CarryModeTests(RetainedFixture, Fixture):
    def test_carry_requires_unchanged_original_test_and_harness_modes(self):
        for change in ("unchanged", "live-test", "restored-test", "live-harness"):
            with self.subTest(change=change):
                fixture = type(self)()
                self.addCleanup(fixture.doCleanups)
                fixture.setUp()
                fixture.initialize()
                fixture.publish_plan("original-plan", fixture.plan_content(predeclared=False))
                fixture.cycle("reader", ["A1"])
                original = fixture.event("reader-green-A1")
                fixture.cycle("display", ["A2W"])
                fixture.open_phase("server-test", "TEST_ONLY", ["A2S"])
                target = fixture.repo / (HARNESS if change == "live-harness" else SHARED_TEST)
                before = target.read_bytes()
                mode = stat.S_IMODE(target.stat().st_mode)
                if change in ("live-test", "restored-test"):
                    target.chmod(mode ^ stat.S_IXUSR)
                    self.assertNotEqual(mode, stat.S_IMODE(target.stat().st_mode))
                    recorded = fixture.proof("mode-drift-red", "A2S", "server-test", passing=False)
                    self.assertEqual(before, target.read_bytes())
                    if change == "restored-test":
                        target.chmod(mode)
                        self.assertEqual(mode, stat.S_IMODE(target.stat().st_mode))
                        self.assertEqual(recorded, fixture.event(recorded["id"]))
                        fixture.proof("server-red", "A2S", "server-test", passing=False)
                else:
                    fixture.proof("server-red", "A2S", "server-test", passing=False)

                fixture.open_phase("server-production", "PRODUCTION", ["A2S"])
                fixture.write_files({"server.py": WORKING["server.py"]})
                fixture.proof("server-green", "A2S", "server-production")
                if change == "live-harness":
                    target.chmod(mode ^ stat.S_IXUSR)
                    self.assertNotEqual(mode, stat.S_IMODE(target.stat().st_mode))
                self.assertEqual(before, target.read_bytes())
                result = fixture.request_proof("carried-reader", "A1", "server-production")
                print(json.dumps({"change": change, "original": original["id"], "result": result},
                                 sort_keys=True), flush=True)
                with self.subTest(boundary="unchanged original carry inputs"):
                    if change == "unchanged":
                        self.assertEqual("PASS", result["state"], result)
                        self.assertEqual([], fixture.proof_errors(result["proof"], "GREEN"))
                    else:
                        fixture.refuse(result, "carried-reader")
                        self.assertNotIn("receipt", result)
                if change == "live-harness":
                    target.chmod(mode)
                independent = fixture.proof("unaffected-display", "A2W", "server-production")
                self.assertEqual([], fixture.proof_errors(independent, "GREEN"))
