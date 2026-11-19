"""V2 lifecycle tests using the same ledger and real local proof producer."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import unicodedata
from unittest.mock import patch

import test_four_behavior_repair as a1
from test_i2e_v2_contract import assurance, policy_request


def manifest(path, ticket, role, baseline, *, unchanged=True):
    return {
        "path": path, "ticket": ticket, "role": role, "baseline": baseline,
        "impact": {"callers": ["reader.py"], "dependencies": [], "checks": ["reader"],
                   "technical_risk": "Medium", "contract_unchanged": unchanged},
    }


class ManifestBoundaryTests(a1.Fixture):
    def test_existing_preflight_admits_explicit_before_write_manifest(self):
        self.initialize()
        self.publish_plan("manifest-plan", self.plan_content(predeclared=False))
        rows = [manifest(a1.SHARED_TEST, "fixture-ticket", "test", None)]
        result = self.ledger.preflight(a1.RUN, "TEST_ONLY", self.history()["seq"], {
            "id": "manifest-test-start", "acceptance": ["A1"], "write_manifest": rows,
        })
        self.assertEqual("PASS", result["state"], result)
        self.assertEqual([a1.SHARED_TEST], result["start"]["data"]["write_scope"])
        self.assertEqual(rows, result["start"]["data"]["write_manifest"])
        self.assertFalse((self.repo / a1.SHARED_TEST).exists())


class WorkflowFixture(a1.Fixture):
    def setUp(self):
        super().setUp()
        self.configure()

    def configure(self, lane="Standard", *, ids=("A1",), tickets=None, risk=None, **policy_options):
        self.lane = lane
        self.ids = tuple(ids)
        self.tickets = tickets or [{"id": "fixture-ticket", "acceptance": list(ids)}]
        self.files = sorted({a1.PRODUCTION[item] for item in ids} | {a1.TEST_FILES[item] for item in ids})
        self.plan_extras = {}
        self.contract_extras = {}
        self.owner_model = a1.ASTRA_MODEL if lane == "Critical" else a1.SOL_MODEL
        self.lead_model = self.owner_model
        self.policy_value = policy_request(lane, risk=risk or {"Direct": "Low", "Standard": "Medium", "Critical": "High"}[lane],
                                           priority="P2", **policy_options)
        if lane == "Direct" and "assurance" not in policy_options:
            self.policy_value["assurance"] = assurance(ticket_count=len(self.tickets))
        self.observations = {}
        self.observed_paths = set()

    def current(self):
        return a1.runtime._v2().snapshot(self.history(), self.observed_paths)

    def contract(self):
        contract = super().contract()
        tests = sorted({a1.TEST_FILES[item] for item in self.ids})
        production = sorted({a1.PRODUCTION[item] for item in self.ids})
        contributors = [a1.ACTOR, "root-session"] + ([] if self.lane == "Direct" else ["lead-session"])
        contract.update(
            tickets=self.tickets, scope=self.files, test_scope=tests, contributors=contributors,
            policy=self.policy_value,
            write_boundary={"test": tests, "production": production, "excluded": ["app.py"]},
        )
        contract.update(self.contract_extras)
        return contract

    def session_log(self, session, model, effort="max"):
        path = super().session_log(session, model, effort=effort)
        if session in self.observations:
            changes = self.observations[session]
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[1]["payload"].update(changes)
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def actor(self, session, model=a1.SOL_MODEL):
        actor = super().actor(session, model)
        actor["observed_tier"] = self.observations.get(session, {}).get("service_tier", actor["observed_tier"])
        return actor

    def reviewer(self, session, model):
        result = super().reviewer(session, model)
        contributors = set(self.contract()["contributors"])
        for event in self.history()["events"]:
            if event["type"] == "plan":
                contributors.update(event["data"]["content"]["contributors"])
        result["excluded"] = sorted(set(result["excluded"]) | contributors)
        return result

    def initialize(self, *, same_roles=False, tier_selection=None):
        # Replay the preserved v2 Critical audit cases against their recorded policy.
        self.ledger.init_run(self.contract(), historical_profile=self.lane == "Critical" or getattr(self, "historical_profile", False))
        self.ensure_cases()
        route = {"kind": "ROUTING", "owner": self.actor(a1.ACTOR, self.owner_model),
                 "probe": self.actor("probe-session")}
        if self.lane != "Direct":
            route["lead"] = self.actor(a1.ACTOR if same_roles else "lead-session", self.lead_model)
        self.push("route", "observation", route)
        if tier_selection is not None:
            self.push("owner-tier-selection", "human_decision", {
                "actor": "human", "kind": "TIER_POLICY", "policy": "record_unknown",
                "source": a1.runtime.reference(self.raw), "statement": "Synthetic fixture owner selects this tier policy.",
                "alternates": tier_selection,
            })

    def plan_content(self, *, predeclared=False):
        content = super().plan_content(predeclared=predeclared)
        contract = self.contract()
        result_map = {item: content["result_map"][item] for item in self.ids}
        checks = [row["check"] for row in result_map.values()]
        content.update(
            scope=self.files, test_scope=contract["test_scope"], contributors=contract["contributors"],
            acceptance=[{"id": item, "behavior": True} for item in self.ids],
            checks=[*checks, "full", "verify-local"], required_checks=[*checks, "full"],
            result_map=result_map, aggregate_checks={"full": list(self.ids)},
        )
        content.update(self.plan_extras)
        return content

    def prepare_plan(self, *, approve=None, **options):
        self.initialize(**options)
        self.publish_plan("workflow-plan", self.plan_content(),
                          approve=(self.lane != "Direct") if approve is None else approve)

    def preflight(self, label, mode, acceptance, **fields):
        return self.ledger.preflight(a1.RUN, mode, self.history()["seq"], {
            "id": label, "acceptance": list(acceptance), **fields,
        })

    def refuse_start(self, label, mode, acceptance, **fields):
        before = self.history()
        result = self.preflight(label, mode, acceptance, **fields)
        self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
        self.assertEqual(before, self.history())
        return result

    def observe_paths(self, label, acceptance, rows):
        prior = self.current()
        result = self.preflight(label, "VERIFY", acceptance, observe_manifest=rows)
        self.assertEqual("PASS", result["state"], result)
        paths = {row["path"] for row in rows}
        start = result["start"]["data"]
        self.assertEqual((rows, [], []), (start["observe_manifest"], start["write_manifest"], start["write_scope"]))
        self.assertEqual(paths, set(start["path_identities"]))
        self.assertEqual(prior["instructions"], start["candidate"]["instructions"])
        self.observed_paths.update(paths)
        self.assertEqual(self.current(), start["candidate"])
        return result["start"]

    def feature_surface(self, *, ticket="fixture-ticket", role="production"):
        (self.repo / "features").mkdir()
        boundary = self.contract()["write_boundary"]
        boundary["surfaces"] = [{"path": "features", "kind": "directory", "role": role, "ticket": ticket}]
        boundary["excluded"].append("features/private")
        self.contract_extras["write_boundary"] = boundary

    def verification_map(self, items):
        rows = {}
        for item in items:
            command, selector = self.selected_command(item)
            with Path(command[0]).open("rb") as runner:
                checksum = hashlib.file_digest(runner, "sha256").hexdigest()
            rows[item] = {"test_path": a1.TEST_FILES[item], "test_id": selector, "command": command,
                          "runner": {"path": command[0], "sha256": checksum}}
        return rows

    def mapped_check(self, label, start, item, **overrides):
        mapping = self.content["verification_map"][item]
        request = {key: mapping[key] for key in ("test_path", "test_id", "command")}
        request.update(id=label, phase="CHECK", check=a1.CHECKS[item], start=start, actor=a1.ACTOR, acceptance=item)
        return self.ledger.prove(a1.RUN, self.history()["seq"], dict(request, **overrides))

    def native_check(self, label, start, item):
        result = self.mapped_check(label, start, item)
        self.assertEqual("PASS", result["state"], result)
        proof = result["proof"]
        body = proof["data"]
        receipt, raw = self.read_receipt(body["output"])
        self.assertEqual((start, self.current()["sha256"], 0), (receipt["start"], receipt["candidate"], receipt["exit"]))
        self.assertEqual(self.content["verification_map"][item]["runner"], receipt["runner"])
        self.assertEqual(self.selected_command(item)[0], receipt["argv"])
        self.assertEqual(self.current(), proof["observed_source"])
        self.assertEqual((self.repo / a1.TEST_FILES[item]).read_bytes(), Path(body["test"]["path"]).read_bytes())
        self.assertIn(b"A2W labels" if item == "A2W" else b"Ran 1 test", raw)
        return proof

    def aggregate(self, label, start, check, rows, *, actor=a1.ACTOR):
        request = {"id": label, "phase": "CHECK", "check": check, "start": start, "actor": actor,
                   "results": [{"acceptance": item, "proof": proof["id"]} for item, proof in rows]}
        return self.ledger.prove(a1.RUN, self.history()["seq"], request)

    def finish_workflow(self, *, start="change-production", full=True, final=False, require_ready=True,
                        prefix="workflow-", specialist_evidence=True):
        if not hasattr(self, "final_proofs"):
            self.final_proofs = {
                item: self.event("change-green-" + item) for item in self.ids
            }
        proof_ids = [row["id"] for row in self.final_proofs.values()]
        if full:
            result = self.coverage(prefix + "full", start)
            self.assertEqual("PASS", result["state"], result)
            proof_ids.append(result["proof"]["id"])
        current = self.current()["sha256"]
        audit_kinds = a1.runtime.evaluate_policy(self.content["policy"], historical=a1.runtime._historical(self.history()))["audits"]
        for kind in audit_kinds:
            executed = []
            for item in self.final_proofs:
                command, _ = self.selected_command(item)
                result = subprocess.run(command, cwd=self.repo, capture_output=True, timeout=15, check=False)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                streams = {}
                for stream in ("stdout", "stderr"):
                    file = self.root / (prefix + kind + "-" + item + "-" + stream)
                    file.write_bytes(getattr(result, stream))
                    streams[stream] = a1.runtime.reference(file)
                executed.append({"check": a1.CHECKS[item], "argv": command, "exit": result.returncode,
                                 "candidate": current, **streams})
            specialties = [kind] if specialist_evidence and kind in self.content["policy"]["specialists"] else []
            self.push(prefix + "audit-" + kind, "audit", {
                "kind": kind, "plan": self.plan, "candidate": current, "verdict": "APPROVE",
                "reviewer": self.reviewer(prefix + kind + "-auditor", a1.SOL_MODEL), "findings": [],
                "executed": executed, "inspected": [a1.PRODUCTION[item] for item in self.final_proofs],
                "specialists": specialties,
            })
        self.consult_mapped(prefix + "consult", "final", current)
        if final:
            self.review(prefix + "final-review", "final_review", prefix + "final-astra", a1.ASTRA_MODEL)
        ready = self.ledger.check(a1.RUN)
        self.assertEqual(require_ready, ready["ready"], ready)
        if not require_ready:
            return ready
        self.assertEqual("BLOCK", ready["state"], ready)
        self.push(prefix + "report", "observation", {
            "status": "COMPLETED", "summary": "Synthetic local checks passed.", "candidate": current,
        })
        self.push(prefix + "brief", "teaching", {
            "report": prefix + "report", "plan": self.plan, "candidate": current,
            "problem": "Prove the synthetic change.", "path": "Input, actual test, change, and review.",
            "decisions": [], "alternatives": [], "tradeoffs": [], "proofs": proof_ids,
            "sources": [a1.runtime.reference(self.raw)], "principle": "Verify current evidence before acceptance.",
            "example": "A new reader result needs a matching current proof.", "limits": "Local synthetic exercise.",
        })
        done = self.ledger.check(a1.RUN)
        self.assertEqual(("PASS", "ACCEPTED_LOCAL"), (done["state"], done["lifecycle"]), done)
        return done

    def candidate_commit(self):
        self.git("add", "--", *self.files)
        tree = self.git("write-tree").strip()
        return self.git("-c", "user.name=V2 fixture", "-c", "user.email=fixture@example.invalid",
                        "commit-tree", tree, "-p", self.base_commit, "-m", "Synthetic accepted candidate").strip()


class WorkflowV2Tests(WorkflowFixture):
    def test_direct_completes_through_red_green_combined_verifier_and_report(self):
        self.configure("Direct")
        self.prepare_plan()
        self.open_phase("premature", "PRODUCTION", ["A1"], expected="BLOCK")
        self.cycle("change", ["A1"])
        self.push("model-ended", "observation", {"kind": "MODEL_TURN_ENDED", "session": a1.ACTOR})
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])
        completed = self.finish_workflow()
        self.assertTrue(completed["parent_complete"])
        self.assertFalse(any(e["type"] == "plan_review" for e in self.history()["events"]))
        self.assertEqual(["combined"], [e["data"]["kind"] for e in self.history()["events"] if e["type"] == "audit"])

    def test_critical_requires_final_after_three_independent_audits(self):
        self.configure("Critical", specialists=["security"])
        self.prepare_plan()
        self.cycle("change", ["A1"])
        first = self.finish_workflow(require_ready=False, specialist_evidence=False)
        self.assertTrue(any("final" in reason.casefold() for reason in first["errors"]), first)
        self.assertTrue(any("specialist" in reason.casefold() for reason in first["errors"]), first)
        result = self.finish_workflow(prefix="with-final-", final=True)
        self.assertTrue(result["ready"])
        review_sessions = {event["data"]["reviewer"]["session"] for event in self.history()["events"]
                           if event["type"] in {"plan_review", "final_review"}}
        self.assertEqual(2, len(review_sessions))
        self.assertFalse(review_sessions & set(self.contract()["contributors"]))

    def test_standard_separates_lead_worker_and_exact_plan_approval(self):
        self.prepare_plan(approve=False)
        self.open_phase("unapproved", "TEST_ONLY", ["A1"], expected="BLOCK")
        self.observations["previous-astra"] = {"service_tier": "Standard"}
        self.review("previous-model-approval", "plan_review", "previous-astra", "gpt-6-astra")
        refused = self.refuse_start("previous-model-start", "TEST_ONLY", ["A1"])
        self.assertIn("designated model/effort", str(refused["errors"]), refused)
        self.review("current-plan-review", "plan_review", "independent-astra", a1.ASTRA_MODEL)
        self.open_phase("approved", "TEST_ONLY", ["A1"])
        self.publish_plan("amendment", dict(self.content, decision_reason="Changed meaningful review contract."), approve=False)
        self.open_phase("unapproved-revision", "TEST_ONLY", ["A1"], expected="BLOCK")
        self.review("amendment-approved", "plan_review", "another-astra", a1.ASTRA_MODEL)
        self.open_phase("amendment-start", "TEST_ONLY", ["A1"])

    def test_same_standard_actor_cannot_plan_and_implement(self):
        self.prepare_plan(same_roles=True)
        self.open_phase("shared-actor", "TEST_ONLY", ["A1"], expected="BLOCK")

    def test_routine_sol_can_write_only_the_named_paths(self):
        self.configure("Direct", routine_worker={"model": a1.SOL_MODEL, "bounded": True, "paths": [a1.SHARED_TEST]})
        self.prepare_plan()
        start = self.open_phase("routine-test", "TEST_ONLY", ["A1"])["start"]
        self.assertEqual([a1.SHARED_TEST], start["data"]["write_scope"])
        self.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
        self.proof("routine-red", "A1", start["id"], passing=False)
        blocked = self.refuse_start("routine-production", "PRODUCTION", ["A1"])
        self.assertIn("bounded routine worker assignment", str(blocked["errors"]), blocked)

    def test_previous_worker_models_do_not_qualify_for_new_direct_work(self):
        for model in ("gpt-6.1-sol", "gpt-6.1-terra"):
            with self.subTest(model=model):
                fixture = WorkflowFixture()
                self.addCleanup(fixture.doCleanups)
                fixture.setUp()
                fixture.configure("Direct")
                fixture.owner_model = model
                fixture.prepare_plan()
                blocked = fixture.refuse_start("previous-worker", "TEST_ONLY", ["A1"])
                self.assertIn("observed actor differs from the requested model", str(blocked["errors"]), blocked)

    def test_default_unknown_tier_holds_and_explicit_owner_choice_only_waives_tier(self):
        trials = (
            ("require_match", {"service_tier": None}, None, "BLOCK"),
            ("record_unknown", {"service_tier": None}, None, "BLOCK"),
            ("record_unknown", {"service_tier": None}, {}, "PASS"),
            ("record_unknown", {"service_tier": "Standard"}, {}, "BLOCK"),
            ("record_unknown", {"service_tier": "Standard"}, {a1.ACTOR: "Standard"}, "PASS"),
            ("record_unknown", {"service_tier": None, "effort": "high"}, {}, "BLOCK"),
            ("record_unknown", {"service_tier": None, "model": "gpt-6-luna"}, {}, "BLOCK"),
        )
        for tier, observations, owner_selection, expected in trials:
            with self.subTest(tier=tier, observations=observations, owner_selection=owner_selection):
                f = WorkflowFixture()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.configure(tier_policy=tier)
                f.observations[a1.ACTOR] = observations
                f.prepare_plan(tier_selection=owner_selection)
                f.open_phase("tier-start", "TEST_ONLY", ["A1"], expected=expected)
                recorded = f.event("route")["data"]["owner"]
                self.assertEqual("Fast", recorded["requested_tier"])
                self.assertEqual(observations["service_tier"], recorded["observed_tier"])

    def test_new_actual_paths_need_admitted_surface_role_and_unchanged_impact(self):
        self.feature_surface()
        self.prepare_plan()
        self.open_phase("manifest-red", "TEST_ONLY", ["A1"])
        self.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
        original_red = self.proof("manifest-red-proof", "A1", "manifest-red", passing=False)
        reader = manifest("reader.py", "fixture-ticket", "production", self.current()["files"]["reader.py"])
        new = manifest("features/part.py", "fixture-ticket", "production", None)
        wrong_rows = [
            dict(new, path="features/private/keep.py"), dict(new, path="features/../app.py"),
            dict(new, role="test"), dict(new, ticket="another-ticket"),
            dict(new, impact=dict(new["impact"], contract_unchanged=False)),
        ]
        outside = self.root / "protected-source"
        outside.write_text("preserve\n")
        (self.repo / "features" / "link.py").symlink_to(outside)
        wrong_rows.append(dict(new, path="features/link.py"))
        for index, row in enumerate(wrong_rows):
            result = self.ledger.preflight(a1.RUN, "PRODUCTION", self.history()["seq"], {
                "id": "bad-manifest-" + str(index), "acceptance": ["A1"], "write_manifest": [reader, row],
            })
            self.assertEqual("BLOCK", result["state"], result)
        self.refuse_start("unobserved-addition", "PRODUCTION", ["A1"], write_manifest=[reader, new])
        observation = self.observe_paths("observe-addition", ["A1"], [new])
        self.assertIsNone(observation["data"]["candidate"]["files"]["features/part.py"])
        self.assertNotIn("features/part.py", original_red["observed_source"]["files"])
        current_check = self.command_check("observe-regression", observation["id"], "verify-local",
                                           [a1.PYTHON, "-B", "-c", "from pathlib import Path; assert not Path('features/part.py').exists()"])
        self.assertEqual("PASS", current_check["state"], current_check)
        self.refuse_start("old-red-after-observation", "PRODUCTION", ["A1"], write_manifest=[reader, new])
        self.open_phase("fresh-manifest-test", "TEST_ONLY", ["A1"])
        retired_red = self.proof("fresh-manifest-red", "A1", "fresh-manifest-test", passing=False)
        self.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE + "\n# The earlier exact test bytes changed.\n"})
        self.refuse_start("changed-expanded-test", "PRODUCTION", ["A1"], write_manifest=[reader, new])
        self.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
        self.retire(retired_red["id"])
        self.refuse_start("retired-expanded-red", "PRODUCTION", ["A1"], write_manifest=[reader, new])
        fresh = self.proof("current-manifest-red", "A1", "fresh-manifest-test", passing=False)
        result = self.preflight("named-production", "PRODUCTION", ["A1"], write_manifest=[reader, new])
        self.assertEqual("PASS", result["state"], result)
        self.assertEqual(fresh["observed_source"], result["start"]["data"]["candidate"])
        self.assertEqual({"reader.py", "features/part.py"}, set(result["start"]["data"]["write_scope"]))
        self.assertEqual({"reader.py", "features/part.py"}, set(result["start"]["data"]["path_identities"]))
        self.write_files({"reader.py": a1.WORKING["reader.py"], "features/part.py": "value = 1\n"})
        altered_command = [*self.selected_command("A1")[0], "-q"]
        altered = self.request_proof("altered-expanded-command", "A1", "named-production", command=altered_command)
        self.refuse(altered, "altered-expanded-command")
        self.assertNotIn("receipt", altered)
        result = self.request_proof("green-with-manifest", "A1", "named-production")
        self.assertEqual("PASS", result["state"], result)
        green = result["proof"]
        receipt, raw = self.read_receipt(green["data"]["output"])
        self.assertEqual(0, receipt["exit"])
        self.assertIn(b"Ran 1 test", raw)
        self.assertIsNotNone(green["observed_source"]["files"]["features/part.py"])
        self.assertEqual("preserve\n", outside.read_text())
        self.assertEqual(original_red, self.event(original_red["id"]))
        self.assertEqual(observation, self.event(observation["id"]))
        self.final_proofs = {"A1": green}
        self.finish_workflow(start="named-production")

    def test_batch_delegated_independent_removal_preserves_parent_and_continuation(self):
        tickets = [{"id": "reader-ticket", "acceptance": ["A1"]}, {"id": "display-ticket", "acceptance": ["A2W"]}]
        for dependent in (True, False):
            with self.subTest(dependent=dependent):
                f = WorkflowFixture()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.configure(ids=("A1", "A2W"), tickets=tickets)
                f.plan_extras["batch"] = {
                    "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
                    "dependencies": {"reader-ticket": ["display-ticket"] if dependent else [], "display-ticket": []},
                    "interaction_checks": ["full"],
                }
                f.prepare_plan()
                body = {"plan": f.plan, "previous": None, "members": ["reader-ticket"],
                        "candidate": f.current()["sha256"], "continuations": {"display-ticket": "later-display"},
                        "reason": "Approved independent continuation."}
                if dependent:
                    with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
                        f.push("subset", "batch_membership", body)
                else:
                    f.push("subset", "batch_membership", body)
                    f.open_phase("removed-ticket", "TEST_ONLY", ["A2W"], expected="BLOCK")
                    f.cycle("change", ["A1"])
                    f.final_proofs = {"A1": f.event("change-green-A1")}
                    result = f.finish_workflow()
                    self.assertEqual(["reader-ticket"], result["active_tickets"])
                    self.assertFalse(result["parent_complete"])
                    self.assertEqual({"display-ticket": "later-display"}, result["continuations"])
                    self.assertFalse((f.repo / a1.WEB_TEST).exists())

    def test_predecessor_acceptance_and_exact_commit_remain_pinned(self):
        self.configure("Direct")
        self.prepare_plan()
        self.cycle("change", ["A1"])
        accepted = self.finish_workflow()
        previous = self.history()
        commit = self.candidate_commit()
        proof = self.root / "predecessor-acceptance.json"
        proof.write_bytes(a1.runtime.canonical(accepted))
        next_repo = self.root / "next-batch"
        self.git("clone", "--no-local", "--no-hardlinks", str(self.repo), str(next_repo))
        self.git("-C", str(next_repo), "fetch", "--no-tags", str(self.repo), commit)
        self.git("-C", str(next_repo), "checkout", "--detach", commit)
        contract = self.contract()
        contract.update(run_id="dependent-run", repo=str(next_repo))
        contract["source"] = dict(contract["source"], base=commit, predecessor={
            "run": a1.RUN, "prefix": previous["sha256"], "candidate": accepted["candidate"]["sha256"],
            "commit": commit, "acceptance": a1.runtime.reference(proof),
        })
        self.assertEqual(commit, self.ledger.init_run(contract)["contract"]["source"]["base"])
        self.retire(previous["sha256"])
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            self.ledger.init_run(dict(contract, run_id="stale-dependent"))

    def test_material_failure_and_persistent_setup_retain_original_raw_attempt(self):
        for material in (True, False):
            with self.subTest(material=material):
                f = WorkflowFixture()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.prepare_plan()
                f.open_phase("investigate", "VERIFY", ["A1"])
                ids, outputs = [], []
                for index in range(1 if material else 2):
                    command = [a1.PYTHON, "-B", "-c", "import missing_synthetic_dependency"]
                    failed = f.command_check("failure-" + str(index), "investigate", "verify-local", command)
                    f.refuse(failed, "failure-" + str(index))
                    attempt = next(e for e in reversed(f.history()["events"]) if e["type"] == "proof_attempt")
                    ids.append(attempt["id"])
                    outputs.append(failed["receipt"])
                    f.push("triage-" + str(index), "failure_classification", {
                        "attempt": attempt["id"], "defect": "fixture-failure",
                        "kind": "MATERIAL" if material else "ROUTINE_SETUP",
                        "reason": "Synthetic classification tied to the actual preserved command.",
                    })
                    obligations = f.ledger.check(a1.RUN)["failure_obligations"]["fixture-failure"]
                    expected = "CANONICAL_REQUIRED" if material or index else "ITERATION"
                    self.assertEqual(expected, obligations["state"], obligations)
                self.assertEqual(ids, obligations["attempts"])
                self.assertEqual(outputs[0], obligations["first_output"])
                f.open_phase("before-capture", "TEST_ONLY", ["A1"], expected="BLOCK")

    def test_distinct_rechecker_is_required_and_can_close_current_finding(self):
        self.configure("Direct")
        self.prepare_plan()
        self.cycle("change", ["A1"])
        self.finding("finding", "reader")
        green = self.proof("finding-current-green", "A1", "change-production")
        same = self.push("same-recheck", "recheck", {
            "plan": self.plan, "candidate": self.current()["sha256"], "verdict": "APPROVE",
            "reviewer": self.reviewer("finding-auditor", a1.SOL_MODEL), "proof": green["id"], "findings": [],
        })
        self.push("same-disposition", "disposition", {
            "review": "finding", "finding": "coverage", "action": "FIXED", "reason": "Fixture recheck.",
            "evidence": green["data"]["output"], "recheck": green["id"], "review_recheck": same["id"],
        })
        self.assertIn("unresolved actionable finding finding/coverage", self.ledger.check(a1.RUN)["errors"])
        self.disposition("finding", green, action="FIXED")
        self.final_proofs = {"A1": green}
        self.finish_workflow()

    def test_eligible_standard_batch_can_finish_with_combined_verifier(self):
        tickets = [{"id": "reader-ticket", "acceptance": ["A1"]}, {"id": "display-ticket", "acceptance": ["A2W"]}]
        for covered, expected in ((True, ["combined"]), (False, ["code", "security", "tests"])):
            with self.subTest(covered=covered):
                f = WorkflowFixture()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.configure(ids=("A1", "A2W"), tickets=tickets, risk="Low", direct_eligible=True,
                            assurance=assurance(ticket_count=2, interaction_coverage=covered))
                f.prepare_plan()
                f.cycle("change", list(f.ids))
                completed = f.finish_workflow()
                actual = [e["data"]["kind"] for e in f.history()["events"] if e["type"] == "audit"]
                self.assertEqual(expected, actual)
                self.assertTrue(completed["parent_complete"])
                self.assertEqual(1, sum(e["type"] == "plan_review" for e in f.history()["events"]))

    def test_high_finding_stays_with_the_sol_implementation_owner(self):
        self.contract_extras["coordinator"] = "root-session"
        self.prepare_plan()
        self.cycle("change", ["A1"])
        for severity in ("High", "Medium"):
            name = "finding-" + severity.lower()
            finding = {
                "id": "reader", "actionable": True, "material": severity == "High",
                "severity": severity, "requirement": "reader", "validation": "reader",
                "evidence": a1.runtime.reference(self.raw), "text": "Synthetic reader issue.",
                "consequence": "Reader output can violate the fixture contract.",
                "correction": "Correct the affected reader behavior.",
            }
            self.review(name, "audit", name + "-sol", a1.SOL_MODEL, audit_kind="code",
                        verdict="REVISE", findings=[finding])
        status = self.ledger.check(a1.RUN)
        self.assertEqual({"finding-high/reader": a1.SOL_MODEL, "finding-medium/reader": a1.SOL_MODEL},
                         status["repair_owners"])
        self.assertEqual("Standard", status["lane"])
        self.assertEqual("root-session", status["roles"]["coordinator"])
        self.assertEqual("lead-session", status["roles"]["lead"])
        self.assertEqual(a1.ACTOR, status["roles"]["owner"])
        self.open_phase("open-high-finding", "TEST_ONLY", ["A1"], expected="BLOCK")

    def test_failed_direct_repair_requires_receiving_plan_and_fresh_review(self):
        self.configure("Direct")
        self.plan_extras["remediations"] = [self.mapping]
        self.prepare_plan()
        self.cycle("change", ["A1"])
        self.write_files({"reader.py": a1.BROKEN_READER})
        self.capture_failure("first-broken-reader")
        self.consult_mapped("first-repair-lookup", "repair", self.current()["sha256"])
        self.open_phase("direct-repair-test", "TEST_ONLY", ["A1"], bounded=True)
        self.proof("direct-repair-red", "A1", "direct-repair-test", passing=False)
        start = self.open_phase("direct-repair-production", "PRODUCTION", ["A1"], bounded=True)["start"]
        self.write_files({"reader.py": a1.STUBS["reader.py"]})
        rejected = self.request_proof("failed-direct-green", "A1", start["id"])
        self.refuse(rejected, "failed-direct-green")
        receipt, raw = self.read_receipt(rejected["receipt"])
        self.assertIn(b"AssertionError", raw)
        current = self.current()
        attempt = next(e for e in reversed(self.history()["events"]) if e["type"] == "proof_attempt")
        self.push("classify-failed-repair", "failure_classification", {
            "attempt": attempt["id"], "defect": a1.READER_DEFECT,
            "kind": "MATERIAL", "reason": "Real failed reader repair on the current fixture.",
        })
        failure_id = "failed-direct-repair-command"
        self.push(failure_id, "failure", {
            "defect": a1.READER_DEFECT, "broken": current, "command": receipt["argv"],
            "output": rejected["receipt"], "exit": receipt["exit"],
        })
        capture = self.failure_intent()
        capture.update(id="capture-direct-failed-repair", defect=a1.READER_DEFECT)
        capture["failure"].update(command=receipt["argv"], output=rejected["receipt"], inputs=[])
        capture["case"].update(check_id="reader", title="Synthetic Direct repair still fails")
        capture["case"]["origin"]["failure_id"] = failure_id
        capture["case"]["evidence_refs"][0]["sha256"] = rejected["receipt"]["sha256"]
        captured = self.ledger.capture(a1.RUN, self.history()["seq"], capture)
        self.assertEqual("PASS", captured["state"], captured)
        self.push("failed-direct-repair", "repair", {
            "defect": a1.READER_DEFECT, "outcome": "FAIL", "before": start["data"]["candidate"]["sha256"],
            "after": current["sha256"], "output": rejected["receipt"], "start": start["id"],
        })
        self.consult_mapped("receiving-repair-lookup", "repair", current["sha256"])
        self.assertEqual("Standard", self.ledger.check(a1.RUN)["required_lane"])
        self.open_phase("no-direct-retry", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")
        previous = self.history()["events"]
        self.push("direct-to-standard", "handoff", {
            "prior_plan": self.plan, "target_lane": "Standard", "candidate": current["sha256"],
            "defect": a1.READER_DEFECT, "prior_actor": a1.ACTOR,
            "next_action": "PLAN_REVIEW", "reason": "Direct repair failed with a retained canonical case.",
        })
        self.lane = "Standard"
        self.policy_value = policy_request(priority="P2")
        self.push("receiving-route", "observation", {
            "kind": "ROUTING", "owner": self.actor(a1.ACTOR), "probe": self.actor("probe-session"),
            "lead": self.actor("lead-session"),
        })
        self.publish_plan("receiving-plan", self.plan_content(), approve=False)
        self.open_phase("no-receiving-approval", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")
        self.review("receiving-approval", "plan_review", "receiving-astra", a1.ASTRA_MODEL)
        self.open_phase("receiving-approved", "TEST_ONLY", ["A1"], bounded=True)
        self.assertEqual(previous, self.history()["events"][:len(previous)])

    def test_assertion_failure_cannot_be_relabelled_as_routine_setup(self):
        self.prepare_plan()
        self.open_phase("verify", "VERIFY", ["A1"])
        failed = self.command_check("actual-assertion", "verify", "verify-local",
                                    [a1.PYTHON, "-B", "-c", "raise AssertionError('Fixture product assertion')"])
        self.refuse(failed, "actual-assertion")
        _, raw = self.read_receipt(failed["receipt"])
        self.assertIn(b"AssertionError: Fixture product assertion", raw)
        attempt = next(e for e in reversed(self.history()["events"]) if e["type"] == "proof_attempt")
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            self.push("wrong-classification", "failure_classification", {
                "attempt": attempt["id"], "defect": "fixture-assertion", "kind": "ROUTINE_SETUP",
                "reason": "Try to relabel a product assertion.",
            })
        self.open_phase("uncaptured-assertion", "TEST_ONLY", ["A1"], expected="BLOCK")

    def test_nonbehavior_needs_concrete_reason_and_current_named_check(self):
        self.initialize()
        content = self.plan_content()
        content.update(acceptance=[{"id": "A1", "behavior": False}], checks=["verify-local"],
                       required_checks=["verify-local"], aggregate_checks={},
                       result_map={"A1": {"check": "verify-local", "test": [], "production": ["reader.py"]}})
        lookup = self.consult_mapped("nonbehavior-consult", "plan", "nonbehavior-plan")
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            self.ledger.append(a1.RUN, {"id": "nonbehavior-plan", "type": "plan", "data": {
                "revision": a1.runtime.digest(content), "content": content,
                "consultation": lookup["consultation"]["id"], "supersedes": None,
            }}, self.history()["seq"])
        content["acceptance"][0]["reason"] = "Change a source comment without changing behavior."
        self.publish_plan("nonbehavior-plan", content, consultation=lookup["consultation"]["id"])
        self.open_phase("nonbehavior-production", "PRODUCTION", ["A1"])
        self.write_files({"reader.py": "# Updated synthetic explanation.\n" + a1.STUBS["reader.py"]})
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])
        result = self.command_check("nonbehavior-check", "nonbehavior-production", "verify-local",
                                    [a1.PYTHON, "-B", "-c", "from reader import read; assert read([]) == []"])
        self.assertEqual("PASS", result["state"], result)
        self.assertFalse(any(e["type"] == "proof" and e["data"]["phase"] == "RED" for e in self.history()["events"]))

    def test_run_rejects_overfive_tickets_and_duplicate_ownership(self):
        default = self.contract()
        trials = (
            [{"id": "ticket-" + str(i), "acceptance": ["behavior-" + str(i)]} for i in range(6)],
            [{"id": "duplicate", "acceptance": ["A1"]}, {"id": "duplicate", "acceptance": ["A2W"]}],
            [{"id": "reader-a", "acceptance": ["A1"]}, {"id": "reader-b", "acceptance": ["A1"]}],
        )
        for tickets in trials:
            with self.subTest(tickets=tickets):
                with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
                    self.ledger.init_run(dict(default, tickets=tickets))
        self.assertEqual(default, self.ledger.init_run(default)["contract"])


class ManifestAuthorityV5Tests(WorkflowFixture):
    def fresh(self):
        fixture = ManifestAuthorityV5Tests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def nonbehavior_plan(self):
        self.initialize()
        content = self.plan_content()
        content.update(
            acceptance=[{"id": item, "behavior": False, "reason": "Change only the synthetic documentation."}
                        for item in self.ids],
            checks=[a1.CHECKS[item] for item in self.ids],
            required_checks=[a1.CHECKS[item] for item in self.ids],
            aggregate_checks={},
        )
        for row in content["result_map"].values():
            row["test"] = []
        self.publish_plan("manifest-boundary-plan", content)

    def attempt_conflicting_surface(self, path, role, ticket, mode, acceptance):
        boundary = self.contract()["write_boundary"]
        boundary["surfaces"] = [{"path": path, "kind": "file", "role": role, "ticket": ticket}]
        self.contract_extras["write_boundary"] = boundary
        target = self.repo / path
        before = target.read_bytes() if target.is_file() else None
        try:
            self.nonbehavior_plan()
        except (a1.runtime.RuntimeError, ValueError) as error:
            self.assertTrue(any(word in str(error).casefold() for word in ("path", "surface", "role", "ticket",
                                                                         "protected", "manifest", "ownership")),
                            error)
            self.assertEqual(before, target.read_bytes() if target.is_file() else None)
            return
        baseline = hashlib.sha256(before).hexdigest() if before is not None else None
        row = manifest(path, ticket, role, baseline)
        history = self.history()
        result = self.preflight("forbidden-surface", mode, [acceptance], write_manifest=[row])
        self.assertEqual(before, target.read_bytes() if target.is_file() else None)
        self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
        self.assertEqual(history, self.history())

    def test_manifest_refuses_immutable_instructions_harness_and_dependency_grants(self):
        for path in a1.INSTRUCTIONS:
            with self.subTest(path=path):
                f = self.fresh()
                f.attempt_conflicting_surface(path, "production", "fixture-ticket", "PRODUCTION", "A1")

    def test_manifest_refuses_both_existing_role_reclassifications(self):
        for path, role, mode in (("reader.py", "test", "TEST_ONLY"),
                                 (a1.SHARED_TEST, "production", "PRODUCTION")):
            with self.subTest(path=path):
                f = self.fresh()
                f.attempt_conflicting_surface(path, role, "fixture-ticket", mode, "A1")

    def test_manifest_cannot_give_an_initial_path_to_another_ticket(self):
        self.configure(ids=("A1", "A2W"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "display-ticket", "acceptance": ["A2W"]},
        ])
        self.attempt_conflicting_surface("reader.py", "production", "display-ticket", "PRODUCTION", "A2W")

    def test_intake_refuses_actual_case_alias_of_immutable_harness(self):
        protected = self.repo / a1.HARNESS
        alias = self.repo / a1.HARNESS.upper()
        if not alias.exists() or not protected.samefile(alias):
            self.skipTest("Fixture volume does not equate the case variants")
        self.assertEqual(1, protected.stat().st_nlink)
        self.assertNotIn(alias.name, {item.name for item in self.repo.iterdir()})
        original = protected.read_bytes()
        contract = self.contract()
        contract["scope"] = [*contract["scope"], alias.name]
        contract["write_boundary"]["production"].append(alias.name)
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            self.ledger.init_run(contract)
        self.assertEqual(original, protected.read_bytes())

    def test_initial_sharing_set_keeps_each_exact_mapped_owner(self):
        self.configure(ids=("A1", "A2S"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "server-ticket", "acceptance": ["A2S"]},
        ])
        self.prepare_plan()
        row = manifest(a1.SHARED_TEST, "reader-ticket", "test", None)
        for acceptance, ticket in (("A1", "reader-ticket"), ("A2S", "server-ticket")):
            selected = dict(row, ticket=ticket)
            result = self.preflight("shared-" + ticket, "TEST_ONLY", [acceptance], write_manifest=[selected])
            self.assertEqual("PASS", result["state"], result)
            self.assertEqual([a1.SHARED_TEST], result["start"]["data"]["write_scope"])
        self.refuse_start("wrong-shared-owner", "TEST_ONLY", ["A2S"], write_manifest=[row])
        self.assertFalse((self.repo / a1.SHARED_TEST).exists())

    def test_shared_intake_observations_preserve_mapped_owners_after_reopen(self):
        self.configure(ids=("A1", "A2S"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "server-ticket", "acceptance": ["A2S"]},
        ])
        self.prepare_plan()
        path = a1.SHARED_TEST
        current = self.current()
        reader = manifest(path, "reader-ticket", "test", None)
        server = dict(reader, ticket="server-ticket")
        for label, rows in (
            ("wrong-owner-observation", [server]),
            ("wrong-role-observation", [dict(reader, role="production")]),
            ("duplicate-observation", [reader, reader]),
        ):
            self.refuse_start(label, "VERIFY", ["A1"], observe_manifest=rows)
        starts = [
            self.observe_paths("reader-observation", ["A1"], [reader]),
            self.observe_paths("server-observation", ["A2S"], [server]),
        ]
        for start in starts:
            self.assertEqual(current, start["data"]["candidate"])
            self.assertIsNone(start["data"]["path_identities"][path]["leaf"])
        before = self.history()
        self.ledger = a1.runtime.Ledger(str(self.db))
        self.assertEqual(before, self.history())
        replay = self.ledger.check(a1.RUN)
        with self.subTest(boundary="historical-check"):
            self.assertEqual(current, replay.get("candidate"), replay)
            self.assertFalse(any("historical observation" in error for error in replay["errors"]), replay)
        self.refuse_start("wrong-owner-after-restart", "TEST_ONLY", ["A1"], write_manifest=[server])
        allowed = self.preflight("shared-test-after-restart", "TEST_ONLY", ["A2S"], write_manifest=[server])
        self.assertEqual("PASS", allowed["state"], allowed)
        self.assertEqual([path], allowed["start"]["data"]["write_scope"])
        self.assertEqual(starts, [self.event(start["id"]) for start in starts])
        self.assertFalse((self.repo / path).exists())

    def test_observation_refuses_physical_and_absent_leaf_collisions(self):
        self.feature_surface()
        tracked = "features/caf\u00e9.py"
        self.write_files({tracked: "value = 1\n"})
        canonical_name = next(entry.name for entry in (self.repo / "features").iterdir())
        canonical = "features/" + canonical_name
        self.git("-c", "core.precomposeunicode=false", "add", "--", canonical)
        self.git("-c", "user.name=V2 fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Canonical fixture spelling", "--no-gpg-sign")
        self.base_commit = self.git("rev-parse", "HEAD").strip()
        self.prepare_plan()
        baseline = hashlib.sha256((self.repo / canonical).read_bytes()).hexdigest()
        exact = manifest(canonical, "fixture-ticket", "production", baseline)
        self.refuse_start("register-with-writes", "VERIFY", ["A1"], write_manifest=[exact])
        actual_aliases = 0
        alternate_normalization = unicodedata.normalize("NFD", canonical_name)
        if alternate_normalization == canonical_name:
            alternate_normalization = unicodedata.normalize("NFC", canonical_name)
        alternatives = [canonical.upper(), "features/" + alternate_normalization]
        for index, alternate in enumerate(alternatives):
            path = self.repo / alternate
            if alternate == canonical or not path.exists() or not path.samefile(self.repo / canonical):
                continue
            actual_aliases += 1
            self.refuse_start("alias-" + str(index), "VERIFY", ["A1"],
                              observe_manifest=[dict(exact, path=alternate)])
            self.refuse_start("duplicate-identity-" + str(index), "VERIFY", ["A1"],
                              observe_manifest=[exact, dict(exact, path=alternate)])
        outside = self.root / "path-authority-sentinel"
        outside.write_bytes(b"Protected synthetic data.\n")
        symlink = self.repo / "features" / "symlink.py"
        hardlink = self.repo / "features" / "hardlink.py"
        symlink.symlink_to(outside)
        os.link(outside, hardlink)
        for link in (symlink, hardlink):
            self.refuse_start("refused-" + link.stem, "VERIFY", ["A1"], observe_manifest=[
                dict(exact, path=str(link.relative_to(self.repo)), baseline=None),
            ])
        hardlink.unlink()
        self.assertEqual(b"Protected synthetic data.\n", outside.read_bytes())
        absent = manifest("features/empty.py", "fixture-ticket", "production", None)
        if actual_aliases and (self.repo / "FEATURES").exists():
            self.refuse_start("absent-ancestor-alias", "VERIFY", ["A1"],
                              observe_manifest=[dict(absent, path="FEATURES/empty.py")])
            self.refuse_start("absent-leaf-collision", "VERIFY", ["A1"],
                              observe_manifest=[absent, dict(absent, path="features/EMPTY.PY")])
        self.observe_paths("canonical-entry", ["A1"], [exact])
        self.assertEqual(b"value = 1\n", (self.repo / canonical).read_bytes())

    def test_observation_preserves_binding_and_refuses_dirty_or_append_time_drift(self):
        self.configure(ids=("A1", "A2W"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "display-ticket", "acceptance": ["A2W"]},
        ])
        self.feature_surface(ticket="reader-ticket")
        self.prepare_plan()
        path = "features/part.py"
        row = manifest(path, "reader-ticket", "production", None)
        target = self.repo / path
        target.write_text("unapproved ambient bytes\n")
        self.refuse_start("dirty-observation", "VERIFY", ["A1"], observe_manifest=[row])
        self.assertEqual("unapproved ambient bytes\n", target.read_text())
        target.unlink()

        def drift(*args, **kwargs):
            target.write_text("changed before append\n")
            return append(*args, **kwargs)

        append = self.ledger._append
        with patch.object(self.ledger, "_append", side_effect=drift) as patched:
            self.refuse_start("raced-observation", "VERIFY", ["A1"], observe_manifest=[row])
        self.assertEqual(1, patched.call_count)
        self.assertEqual("changed before append\n", target.read_text())
        target.unlink()

        original_parent = target.parent.stat().st_ino

        def change_ancestor(*args, **kwargs):
            os.replace(target.parent, self.repo / "features-before-race")
            target.parent.mkdir()
            return append(*args, **kwargs)

        with patch.object(self.ledger, "_append", side_effect=change_ancestor) as patched:
            self.refuse_start("same-bytes-new-ancestor", "VERIFY", ["A1"], observe_manifest=[row])
        self.assertEqual(1, patched.call_count)
        self.assertNotEqual(original_parent, target.parent.stat().st_ino)
        self.assertFalse(target.exists())
        (target.parent / "private").mkdir()
        excluded = dict(row, path="features/private/refused.py")
        self.refuse_start("excluded-descendant", "VERIFY", ["A1"], observe_manifest=[excluded])
        before = self.history()
        stale = self.ledger.preflight(a1.RUN, "VERIFY", before["seq"] - 1,
                                      {"id": "stale-observation", "acceptance": ["A1"], "observe_manifest": [row]})
        self.assertEqual(("BLOCK", None), (stale["state"], stale["start"]), stale)
        self.assertEqual(before, self.history())
        observed = self.observe_paths("bind-new-path", ["A1"], [row])
        self.refuse_start("reticket-observation", "VERIFY", ["A2W"],
                          observe_manifest=[dict(row, ticket="display-ticket")])
        self.refuse_start("reclassify-observation", "VERIFY", ["A1"],
                          observe_manifest=[dict(row, role="test")])
        self.refuse_start("rewrite-observation-baseline", "VERIFY", ["A1"],
                          observe_manifest=[dict(row, baseline="f" * 64)])
        self.assertEqual(observed, self.event("bind-new-path"))
        self.assertFalse(target.exists())
        self.git("-c", "user.name=V2 fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Unreviewed base change", "--no-gpg-sign", "--allow-empty")
        self.refuse_start("changed-base", "VERIFY", ["A1"],
                          observe_manifest=[dict(row, path="features/other.py")])


class MappedVerificationV5Tests(WorkflowFixture):
    def mapped_plan(self, *, configure=None):
        self.initialize()
        content = self.plan_content()
        content["verification_map"] = self.verification_map(self.ids)
        if configure:
            configure(content)
        lookup = self.consult_mapped("verify-plan-consult", "plan", "verify-plan")
        revision = a1.runtime.digest(content)
        request = {"id": "verify-plan", "type": "plan", "data": {
            "revision": revision, "content": content,
            "consultation": lookup["consultation"]["id"], "supersedes": None,
        }}
        completed, event = self.cli("run", "append", request=request)
        self.assertEqual(0, completed.returncode, f"The exact native verification map must be accepted: {event}")
        self.assertEqual(content["verification_map"], event["data"]["content"]["verification_map"])
        self.plan, self.content = revision, copy.deepcopy(content)
        self.review("verify-plan-approved", "plan_review", "verify-planner", a1.ASTRA_MODEL)

    def test_plan_admits_exact_native_verification_map_at_public_boundary(self):
        self.mapped_plan()
        self.assertEqual(self.content["verification_map"], self.verification_map(self.ids))
        self.open_phase("approved-verify", "VERIFY", self.ids)

    def test_expanded_exact_red_with_live_unrelated_case_aggregate_and_carry(self):
        self.configure(ids=("A1", "A2W"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "display-ticket", "acceptance": ["A2W"]},
        ])
        self.feature_surface(ticket="reader-ticket")
        subgroup = "display-regression"

        def include_subgroup(content):
            content["checks"].append(subgroup)
            content["required_checks"].append(subgroup)
            content["aggregate_checks"][subgroup] = ["A2W"]

        self.mapped_plan(configure=include_subgroup)
        self.cycle("prior-display", ["A2W"])
        old_green = self.event("prior-display-green-A2W")
        self.decision("reader-tdd", "The native reader assertion establishes the exact expected behavior.",
                      behavior="A1", strategy="TDD_RED")
        for check in (a1.CHECKS["A2W"], subgroup):
            self.archived_case(check)
        self.consult_mapped("carry-healthy-cases", "repair", self.current()["sha256"])
        addition = manifest("features/part.py", "reader-ticket", "production", None)
        observation = self.observe_paths("expanded-verify", ["A1", "A2W"], [addition])
        original_check = self.native_check("expanded-display", observation["id"], "A2W")
        group = self.aggregate("expanded-display-group", observation["id"], subgroup, [("A2W", original_check)])
        self.assertEqual("PASS", group["state"], group)
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])

        self.open_phase("reader-test", "TEST_ONLY", ["A1"])
        suite = a1.PYTHON_SUITE.replace(
            "        self.assertEqual(['a', 'b'], read(['b', 'a', 'b']))",
            "        self.assertEqual(['a', 'b'], read(['b', 'a', 'b']))\n"
            "        from pathlib import Path\n"
            "        self.assertTrue(Path('features/part.py').is_file(), 'Expected the admitted reader file')",
        )
        self.write_files({a1.SHARED_TEST: suite})
        red = self.proof("expanded-reader-red", "A1", "reader-test", passing=False)
        reader = manifest("reader.py", "reader-ticket", "production", self.current()["files"]["reader.py"])
        rows = [reader, addition]
        stale = self.refuse_start("before-refreshed-cases", "PRODUCTION", ["A1"], write_manifest=rows)
        self.assertTrue(any("case regression" in error for error in stale["errors"]), stale)
        self.open_phase("refresh-verify", "VERIFY", ["A1", "A2W"])
        self.refuse(self.aggregate("old-boundary-group", "refresh-verify", subgroup,
                                   [("A2W", original_check)]), "old-boundary-group")
        fresh_check = self.native_check("fresh-display", "refresh-verify", "A2W")
        result = self.aggregate("fresh-display-group", "refresh-verify", subgroup, [("A2W", fresh_check)])
        self.assertEqual("PASS", result["state"], result)
        self.retire(fresh_check["id"])
        self.refuse_start("withdrawn-covered-result", "PRODUCTION", ["A1"], write_manifest=rows)
        final_check = self.native_check("current-display", "refresh-verify", "A2W")
        result = self.aggregate("current-display-group", "refresh-verify", subgroup, [("A2W", final_check)])
        self.assertEqual("PASS", result["state"], result)
        ready = self.preflight("expanded-production", "PRODUCTION", ["A1"], write_manifest=rows)
        self.assertEqual("PASS", ready["state"], ready)
        self.assertEqual(red["observed_source"], ready["start"]["data"]["candidate"])
        self.assertEqual({"reader.py", "features/part.py"}, set(ready["start"]["data"]["write_scope"]))
        self.write_files({"reader.py": a1.WORKING["reader.py"], "features/part.py": "value = 1\n"})
        current_reader = self.proof("expanded-reader-green", "A1", "expanded-production")
        current_display = self.proof("expanded-display-green", "A2W", "expanded-production")
        self.assertNotEqual(old_green["data"]["candidate"], current_display["data"]["candidate"])
        self.assertEqual(red["data"]["test"], current_reader["data"]["test"])
        group = self.aggregate("production-display-group", "expanded-production", subgroup, [("A2W", current_display)])
        self.assertEqual("PASS", group["state"], group)
        self.final_proofs = {"A1": current_reader, "A2W": current_display}
        result = self.finish_workflow(start="expanded-production")
        self.assertEqual((observation, old_green), (self.event(observation["id"]), self.event(old_green["id"])))
        self.assertIsNone(observation["data"]["candidate"]["files"]["features/part.py"])
        self.assertIsNotNone(result["candidate"]["files"]["features/part.py"])

    def test_unobserved_ambient_input_cannot_supply_expanded_production_red(self):
        self.feature_surface()
        self.prepare_plan()
        self.open_phase("original-test", "TEST_ONLY", ["A1"])
        suite = """from pathlib import Path
import unittest


class Behaviors(unittest.TestCase):
    def test_A1(self):
        self.assertFalse(Path('features/part.py').exists(), 'Unexpected synthetic ambient input')


if __name__ == '__main__':
    unittest.main()
"""
        self.write_files({a1.SHARED_TEST: suite})
        target = self.repo / "features/part.py"
        command, _ = self.selected_command("A1")
        clean = subprocess.run(command, cwd=self.repo, capture_output=True, timeout=15, check=False)
        self.assertEqual(0, clean.returncode, clean.stdout + clean.stderr)
        target.write_text("unobserved synthetic input\n")
        old_red = self.proof("ambient-original-red", "A1", "original-test", passing=False)
        target.unlink()
        row = manifest("features/part.py", "fixture-ticket", "production", None)
        self.observe_paths("ambient-observation", ["A1"], [row])
        self.refuse_start("unproved-expanded-production", "PRODUCTION", ["A1"], write_manifest=[row])
        self.open_phase("ambient-retest", "TEST_ONLY", ["A1"])
        refused = self.request_proof("ambient-fresh-red", "A1", "ambient-retest", passing=False)
        self.refuse(refused, "ambient-fresh-red")
        receipt, raw = self.read_receipt(refused["receipt"])
        self.assertEqual((command, 0), (receipt["argv"], receipt["exit"]))
        self.assertIn(b"Ran 1 test", raw)
        self.assertEqual(old_red, self.event(old_red["id"]))
        self.assertFalse(target.exists())

    def test_mapped_check_refuses_bad_selection_coverage_and_completion_without_tdd(self):
        self.mapped_plan()
        self.cycle("change", ["A1"])
        old_green = self.event("change-green-A1")
        self.open_phase("first-verify", "VERIFY", ["A1"])
        actual = self.native_check("first-check", "first-verify", "A1")
        command, _ = self.selected_command("A1")
        wrong = [
            ("wrong-selector", self.mapped_check("wrong-selector", "first-verify", "A1", test_id="different")),
            ("wrong-argv", self.mapped_check("wrong-argv", "first-verify", "A1", command=[a1.PYTHON, "-B", "-c", "pass"])),
            ("opaque", self.command_check("opaque", "first-verify", "reader", command)),
            ("partial", self.aggregate("partial", "first-verify", "full", [])),
            ("duplicate", self.aggregate("duplicate", "first-verify", "full", [("A1", actual), ("A1", actual)])),
            ("misattributed", self.aggregate("misattributed", "first-verify", "full", [("A2W", actual)])),
            ("green-substitute", self.aggregate("green-substitute", "first-verify", "full", [("A1", old_green)])),
        ]
        for label, result in wrong:
            self.refuse(result, label)
        accepted = self.aggregate("native-full", "first-verify", "full", [("A1", actual)])
        self.assertEqual("PASS", accepted["state"], accepted)
        self.open_phase("second-verify", "VERIFY", ["A1"])
        self.refuse(self.aggregate("mixed-boundary", "second-verify", "full", [("A1", actual)]), "mixed-boundary")
        self.open_phase("reopened-test", "TEST_ONLY", ["A1"])
        self.open_phase("reopened-verify", "VERIFY", ["A1"])
        new_check = self.native_check("current-check-without-red", "reopened-verify", "A1")
        covered = self.aggregate("current-covered-without-red", "reopened-verify", "full", [("A1", new_check)])
        self.assertEqual("PASS", covered["state"], covered)
        refused = self.refuse_start("check-is-not-red", "PRODUCTION", ["A1"])
        self.assertTrue(any("red" in error.casefold() for error in refused["errors"]), refused)
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])

    def mapped_consumer_fixture(self):
        self.configure(ids=("A1", "A2W"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "display-ticket", "acceptance": ["A2W"]},
        ])
        self.mapped_plan()
        self.decision("display-choice", "Review the exact synthetic display contract.", behavior="A2W")
        self.support("selected-display-review")
        self.cycle("change", list(self.ids))
        self.final_proofs = {item: self.event("change-green-" + item) for item in self.ids}
        for check in ("display", "full"):
            self.archived_case(check)
        self.consult_mapped("consumer-case-lookup", "repair", self.current()["sha256"])
        self.finding("display-result-finding", "display")
        self.finding("aggregate-result-finding", "full")
        self.open_phase("mapped-consumer-verify", "VERIFY", list(self.ids))
        results = [(item, self.native_check("current-check-" + item, "mapped-consumer-verify", item)) for item in self.ids]
        aggregate = self.aggregate("mapped-consumer-full", "mapped-consumer-verify", "full", results)
        self.assertEqual("PASS", aggregate["state"], aggregate)
        self.disposition("display-result-finding", dict(results)["A2W"], action="FIXED")
        self.disposition("aggregate-result-finding", aggregate["proof"], action="FIXED")
        completed = self.finish_workflow(prefix="mapped-consumer-", full=False)
        self.assertTrue(completed["ready"], completed)
        return results, aggregate["proof"]

    def test_mapped_check_consumers_reject_withdrawn_acceptance_or_selected_review(self):
        for change in ("acceptance", "selected-review", "decision-revision", "effective-review"):
            with self.subTest(change=change):
                f = MappedVerificationV5Tests()
                self.addCleanup(f.doCleanups)
                f.setUp()
                results, original_aggregate = f.mapped_consumer_fixture()
                if change == "acceptance":
                    f.retire("A2W")
                elif change == "selected-review":
                    f.retire("selected-display-review")
                elif change == "decision-revision":
                    f.decision("revised-display-choice", "The relevant display decision now has different reviewed terms.",
                               behavior="A2W")
                else:
                    f.support("nonqualifying-display-review", verdict="REVISE")
                history = f.history()
                completed = f.ledger.check(a1.RUN)
                expected_errors = [
                    "carried case regression proof missing: display",
                    "carried case regression proof missing: full",
                    "unresolved actionable finding display-result-finding/coverage",
                    "unresolved actionable finding aggregate-result-finding/coverage",
                ]
                with self.subTest(consumer="completion"):
                    self.assertEqual(("BLOCK", False), (completed["state"], completed["ready"]), completed)
                for error in expected_errors:
                    with self.subTest(consumer=error):
                        self.assertIn(error, completed["errors"], completed)
                self.assertEqual(history, f.history())
                self.assertEqual(original_aggregate, f.event(original_aggregate["id"]))
                if change == "acceptance":
                    with patch.object(subprocess, "Popen", wraps=subprocess.Popen) as launched:
                        fresh = f.mapped_check("withdrawn-fresh-check", "mapped-consumer-verify", "A2W")
                    native = [call.args[0] for call in launched.call_args_list if call.args and
                              isinstance(call.args[0], list) and call.args[0]
                              and Path(call.args[0][0]).name == "sandbox-exec"]
                    with self.subTest(consumer="fresh-check-refusal"):
                        f.refuse(fresh, "withdrawn-fresh-check")
                    with self.subTest(consumer="fresh-check-dispatch"):
                        self.assertFalse(native, native)
                    with self.subTest(consumer="fresh-check-prefix"):
                        self.assertEqual(history, f.history())
                before_aggregate = f.history()
                aggregate = f.aggregate("retired-consumer-full", "mapped-consumer-verify", "full", results)
                with self.subTest(consumer="aggregate-issuance"):
                    f.refuse(aggregate, "retired-consumer-full")
                    self.assertEqual(before_aggregate, f.history())
                with self.subTest(consumer="case-preflight"):
                    denied = f.refuse_start("reader-after-stale-check", "TEST_ONLY", ["A1"])
                    self.assertIn("carried case regression proof missing: display", denied["errors"], denied)
                    self.assertIn("carried case regression proof missing: full", denied["errors"], denied)

    def test_unselected_review_withdrawal_preserves_current_mapped_check_consumers(self):
        results, original_aggregate = self.mapped_consumer_fixture()
        selected = self.event("selected-display-review")
        self.assertLess(selected["seq"], self.event("change-test")["seq"])
        self.assertLess(selected["seq"], self.event("mapped-consumer-verify")["seq"])
        self.retire("display-choice-review")
        completed = self.ledger.check(a1.RUN)
        self.assertEqual(("PASS", True), (completed["state"], completed["ready"]), completed)
        self.assertEqual(original_aggregate, self.event(original_aggregate["id"]))
        aggregate = self.aggregate("still-current-full", "mapped-consumer-verify", "full", results)
        self.assertEqual("PASS", aggregate["state"], aggregate)
        result = self.preflight("reader-after-unselected-review", "TEST_ONLY", ["A1"])
        self.assertEqual("PASS", result["state"], result)
        self.assertEqual([a1.SHARED_TEST], result["start"]["data"]["write_scope"])

    def test_mapped_check_retains_real_nonzero_setup_and_timeout_receipts(self):
        suite = """import time
import unittest


class Behaviors(unittest.TestCase):
    def test_A1(self):
        print('synthetic check started', flush=True)
        time.sleep(15)


if __name__ == '__main__':
    unittest.main()
"""
        trials = [
            ("nonzero", a1.PYTHON_SUITE, 15, b"AssertionError", False),
            ("setup", "import synthetic_dependency_that_is_not_present\n", 15, b"ModuleNotFoundError", False),
            ("timeout", suite, 1, b"synthetic check started", True),
        ]
        for label, body, timeout, message, timed_out in trials:
            with self.subTest(label=label):
                f = MappedVerificationV5Tests()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.mapped_plan()
                f.open_phase("test-file", "TEST_ONLY", ["A1"])
                f.write_files({a1.SHARED_TEST: body})
                f.open_phase("read-only", "VERIFY", ["A1"])
                result = f.mapped_check(label, "read-only", "A1", timeout_seconds=timeout)
                f.refuse(result, label)
                receipt, raw = f.read_receipt(result["receipt"])
                self.assertEqual(f.selected_command("A1")[0], receipt["argv"])
                self.assertEqual(timed_out, receipt["timed_out"])
                self.assertNotEqual(0, receipt["exit"])
                self.assertIn(message, raw)


class RepairOwnershipV5Tests(WorkflowFixture):
    historical_profile = True

    def captured_high_finding(self):
        self.contract_extras["coordinator"] = "root-session"
        self.prepare_plan()
        self.cycle("change", ["A1"])
        self.write_files({"reader.py": a1.BROKEN_READER})
        self.capture_failure("high-reader-failure")
        self.review("reader-high", "audit", "high-finder", a1.SOL_MODEL, audit_kind="code",
                    verdict="REVISE", findings=[{
                        "id": "coverage", "actionable": True, "material": True, "severity": "High",
                        "requirement": "reader", "validation": "reader", "evidence": a1.runtime.reference(self.raw),
                        "text": "The synthetic reader returns repeated rows.",
                        "consequence": "Repeated rows change the downstream synthetic result.",
                        "correction": "Restore distinct reader rows.",
                    }])
        self.mapping = dict(self.mapping, findings=[{"review": "reader-high", "finding": "coverage"}])

    def plan_repair(self, name, actor=None):
        contributors = list(self.content["contributors"])
        if actor is not None:
            self.mapping = dict(self.mapping, repair_actor=actor)
            if actor["session"] not in contributors:
                contributors.append(actor["session"])
        self.publish_plan(name, dict(self.content, contributors=contributors, remediations=[self.mapping]))
        self.consult_mapped(name + "-repair", "repair", self.current()["sha256"])

    def test_high_named_remediation_without_astra_cannot_open_test_only(self):
        self.captured_high_finding()
        try:
            self.plan_repair("no-repair-actor")
        except (a1.runtime.RuntimeError, ValueError) as error:
            self.assertTrue(any(word in str(error).casefold() for word in ("actor", "astra", "high")), error)
            return
        self.open_phase("unassigned-repair", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")

    def test_high_repair_refuses_a_reviewed_assignment_with_unqualified_observation(self):
        trials = [
            ("repair-sol", a1.SOL_MODEL, {}),
            ("repair-effort", a1.ASTRA_MODEL, {"effort": "high"}),
            ("repair-tier", a1.ASTRA_MODEL, {"service_tier": None}),
            ("root-session", a1.ASTRA_MODEL, {}),
            ("lead-session", a1.ASTRA_MODEL, {}),
            ("high-finder", a1.ASTRA_MODEL, {}),
        ]
        for session, model, observation in trials:
            with self.subTest(session=session):
                f = RepairOwnershipV5Tests()
                self.addCleanup(f.doCleanups)
                f.setUp()
                f.captured_high_finding()
                f.observations[session] = observation
                actor = f.actor(session, model)
                try:
                    f.plan_repair("unqualified-assignment", actor)
                except (a1.runtime.RuntimeError, ValueError) as error:
                    self.assertTrue(any(word in str(error).casefold()
                                        for word in ("actor", "repair", "identity", "reviewer", "tier", "effort")), error)
                else:
                    f.open_phase("unqualified-phase", "TEST_ONLY", ["A1"], bounded=True, expected="BLOCK")

    def test_high_repair_uses_observed_astra_only_for_the_exact_named_scope(self):
        self.captured_high_finding()
        assigned = self.actor("reader-repair-astra", a1.ASTRA_MODEL)
        self.plan_repair("qualified-repair", assigned)
        scope = dict(self.mapping, before=self.current()["sha256"], reason="Repair the captured High finding.")
        for index, invalid in enumerate((
            self.actor("lead-session"),
            self.actor("high-finder"),
            dict(assigned, session="root-session"),
            dict(assigned, model=a1.SOL_MODEL),
            dict(assigned, effort="high"),
            dict(assigned, requested_tier="Fast"),
            dict(assigned, observed_tier=None),
        )):
            self.refuse_start("changed-repair-actor-" + str(index), "TEST_ONLY", ["A1"],
                              remediation=dict(scope, repair_actor=invalid))
        started = self.open_phase("high-repair-test", "TEST_ONLY", ["A1"], bounded=True)["start"]
        self.assertEqual(assigned, started["data"]["remediation"]["repair_actor"])
        wrong = self.request_proof("ordinary-owner-cannot-repair", "A1", started["id"], passing=False)
        self.refuse(wrong, "ordinary-owner-cannot-repair")
        self.assertNotIn("receipt", wrong)
        red = self.request_proof("high-reader-red", "A1", started["id"], passing=False, actor=assigned["session"])
        self.assertEqual("PASS", red["state"], red)
        red_receipt, red_output = self.read_receipt(red["proof"]["data"]["output"])
        self.assertNotEqual(0, red_receipt["exit"])
        self.assertIn(b"AssertionError", red_output)
        production = self.open_phase("high-repair-production", "PRODUCTION", ["A1"], bounded=True)["start"]
        self.assertEqual(assigned, production["data"]["remediation"]["repair_actor"])
        self.write_files({"reader.py": a1.REPAIRED_READER})
        wrong = self.request_proof("ordinary-owner-cannot-record-repair-green", "A1", production["id"])
        self.refuse(wrong, "ordinary-owner-cannot-record-repair-green")
        self.assertNotIn("receipt", wrong)
        result = self.request_proof("high-reader-green", "A1", production["id"], actor=assigned["session"])
        self.assertEqual("PASS", result["state"], result)
        green = result["proof"]
        green_receipt, _ = self.read_receipt(green["data"]["output"])
        self.assertEqual((assigned["session"], 0), (green_receipt["actor"], green_receipt["exit"]))
        self.assertEqual(red["proof"]["data"]["test"], green["data"]["test"])
        self.push("verified-high-repair", "repair", {
            "defect": a1.READER_DEFECT, "outcome": "PASS", "before": production["data"]["candidate"]["sha256"],
            "after": self.current()["sha256"], "output": green["data"]["output"], "start": production["id"],
        })
        self.disposition("reader-high", green, action="FIXED")
        group = self.aggregate("high-repair-full", production["id"], "full", [("A1", green)], actor=assigned["session"])
        self.assertEqual("PASS", group["state"], group)
        self.final_proofs = {"A1": green}
        completed = self.finish_workflow(start=production["id"], full=False)
        self.assertEqual(("Standard", "root-session", "lead-session", a1.ACTOR),
                         (completed["lane"], completed["roles"]["coordinator"], completed["roles"]["lead"],
                          completed["roles"]["owner"]))
        self.assertFalse(completed["repair_owners"])
        self.open_phase("ordinary-verify-after-repair", "VERIFY", ["A1"])
        command = [a1.PYTHON, "-B", "-c", "from reader import read; assert read(['a', 'a']) == ['a']"]
        self.refuse(self.command_check("stale-repair-actor", "ordinary-verify-after-repair", "verify-local", command,
                                       actor=assigned["session"]), "stale-repair-actor")
        ordinary = self.command_check("ordinary-owner-check", "ordinary-verify-after-repair", "verify-local", command)
        self.assertEqual("PASS", ordinary["state"], ordinary)
        receipt, _ = self.read_receipt(ordinary["proof"]["data"]["output"])
        self.assertEqual(a1.ACTOR, receipt["actor"])


class ArchitectureSpecialistV5Tests(WorkflowFixture):
    def architecture_audit(self, label, session, *, model=a1.ASTRA_MODEL, candidate=None):
        command, _ = self.selected_command("A1")
        native = subprocess.run(command, cwd=self.repo, capture_output=True, timeout=15, check=False)
        self.assertEqual(0, native.returncode, native.stdout + native.stderr)
        current = self.current()["sha256"]
        streams = {}
        for name in ("stdout", "stderr"):
            artifact = self.root / (label + "-" + name)
            artifact.write_bytes(getattr(native, name))
            streams[name] = a1.runtime.reference(artifact)
        body = {
            "kind": "architecture", "plan": self.plan, "candidate": candidate or current, "verdict": "APPROVE",
            "reviewer": self.reviewer(session, model), "findings": [], "specialists": ["architecture"],
            "executed": [{"check": "reader", "argv": command, "exit": native.returncode,
                          "candidate": current, **streams}],
            "inspected": ["reader.py"],
        }
        return self.push(label, "audit", body)

    def attempt_unqualified_architecture_audit(self, label, session, **kwargs):
        try:
            self.architecture_audit(label, session, **kwargs)
        except (a1.runtime.RuntimeError, ValueError) as error:
            self.assertTrue(any(word in str(error).casefold() for word in ("audit", "specialist", "review", "candidate",
                                                                         "identity", "astra", "evidence")),
                            error)
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])

    def test_selected_architecture_audit_requires_later_independent_final(self):
        self.configure("Critical", specialists=["architecture"], significant_architecture=True)
        self.prepare_plan()
        self.cycle("change", ["A1"])
        self.final_proofs = {"A1": self.event("change-green-A1")}
        missing = self.finish_workflow(prefix="before-architecture-", final=True, require_ready=False)
        self.assertTrue(any("specialist" in error.casefold() or "architecture" in error.casefold()
                            for error in missing["errors"]), missing)
        self.attempt_unqualified_architecture_audit("wrong-model-architecture", "architecture-sol", model=a1.SOL_MODEL)
        self.attempt_unqualified_architecture_audit("stale-architecture", "architecture-stale", candidate="f" * 64)
        self.attempt_unqualified_architecture_audit("reused-architecture", "workflow-plan-planner")
        architecture = self.architecture_audit("verified-architecture", "specialist-astra")
        ordered = self.ledger.check(a1.RUN)
        self.assertFalse(ordered["ready"], ordered)
        self.assertTrue(any("final" in error.casefold() for error in ordered["errors"]), ordered)
        self.consult_mapped("consult-after-specialist", "final", self.current()["sha256"])
        self.review("specialist-as-final", "final_review", "specialist-astra", a1.ASTRA_MODEL)
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])
        completed = self.finish_workflow(prefix="after-architecture-", full=False, final=True)
        self.assertEqual("ACCEPTED_LOCAL", completed["lifecycle"])
        final = self.event("after-architecture-final-review")
        self.assertIn("specialist-astra", final["data"]["reviewer"]["excluded"])
        self.assertLess(architecture["seq"], final["seq"])
        sol_audits = [self.event("after-architecture-audit-" + kind) for kind in ("code", "security", "tests")]
        self.assertEqual(3, len({event["data"]["reviewer"]["session"] for event in sol_audits}))

    def test_unrequested_architecture_audit_cannot_supply_specialist_authority(self):
        self.prepare_plan()
        self.cycle("change", ["A1"])
        before = self.history()
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            self.architecture_audit("unrequested-architecture", "unrequested-astra")
        self.assertEqual(before, self.history())

    def test_architecture_audit_cannot_replace_sol_audits_or_prewrite_doubt(self):
        self.configure("Critical", specialists=["architecture"], significant_architecture=True)
        self.prepare_plan()
        self.cycle("change", ["A1"])
        self.final_proofs = {"A1": self.event("change-green-A1")}
        covered = self.coverage("critical-coverage", "change-production")
        self.assertEqual("PASS", covered["state"], covered)
        self.architecture_audit("only-architecture", "different-specialist")
        status = self.ledger.check(a1.RUN)
        self.assertFalse(status["ready"], status)
        for kind in ("code", "security", "tests"):
            self.assertTrue(any(kind + " audit" in error for error in status["errors"]), status)
        data = {
            "lineage": "new-architecture-risk", "kind": "architecture", "strategy": "REVIEW",
            "contributors": self.contract()["contributors"], "artifact": a1.runtime.reference(self.raw),
            "acceptance": ["A1"], "choice": "Revisit the synthetic reader boundary.",
            "alternatives": [], "tradeoff": "The boundary still needs independent review.",
            "supersedes": None,
        }
        self.push("new-architecture-decision", "decision", dict(data, revision=a1.runtime.digest(data)))
        refused = self.refuse_start("unreviewed-architecture-write", "TEST_ONLY", ["A1"])
        self.assertTrue(any("challenge" in error or "support" in error for error in refused["errors"]), refused)


class NativeSelectorSyntaxTests(WorkflowFixture):
    native_selectors = {
        "A1": "Behaviors.test_A1",
        "A2W": "A2W labels recorded and missing telemetry",
    }

    def selector_cli(self, *operation, request):
        argv = [a1.PYTHON, "-B", str(a1.base.SCRIPT), *operation, "--db", str(self.db),
                "--run", a1.RUN, "--expect", str(self.history()["seq"]), "--input", "-"]
        data = json.dumps(request)
        completed = subprocess.run(argv, cwd=self.repo, input=data, encoding="utf-8",
                                   capture_output=True, timeout=40, check=False)
        print(json.dumps({"argv": argv, "cwd": str(self.repo), "stdin": data, "exit": completed.returncode,
                          "stdout": completed.stdout, "stderr": completed.stderr}, sort_keys=True), flush=True)
        return completed

    def selector_plan(self):
        plan_id = "native-selector-plan"
        lookup = self.consult_mapped("native-selector-lookup", "plan", plan_id)
        content = self.plan_content()
        content["verification_map"] = self.verification_map(self.ids)
        for item, identity in self.native_selectors.items():
            content["verification_map"][item]["test_id"] = identity
        return {"id": plan_id, "type": "plan", "data": {
            "revision": a1.runtime.digest(content), "content": content,
            "consultation": lookup["consultation"]["id"], "supersedes": None,
        }}

    def selector_red(self, item, identity, label):
        command, _ = self.selected_command(item)
        return {"id": label, "phase": "RED", "check": a1.CHECKS[item], "start": "native-selector-test",
                "actor": a1.ACTOR, "acceptance": item, "test_id": identity,
                "test_path": a1.TEST_FILES[item], "command": command, "failure_kind": "ASSERTION"}

    def open_selector_test(self):
        self.open_phase("native-selector-test", "TEST_ONLY", self.ids)
        self.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE, a1.WEB_TEST: a1.JS_SUITE})

    def test_public_plan_map_accepts_exact_native_selector_strings(self):
        self.configure(ids=tuple(self.native_selectors))
        self.initialize()
        request = self.selector_plan()
        completed = self.selector_cli("run", "append", request=request)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        event = json.loads(completed.stdout)
        self.assertEqual("plan", event["type"])
        self.assertEqual(request["data"]["content"]["verification_map"], event["data"]["content"]["verification_map"])
        self.assertEqual(event, self.event(request["id"]))

    def test_public_proof_requests_accept_exact_native_selector_strings(self):
        self.configure(ids=tuple(self.native_selectors))
        self.prepare_plan()
        self.open_selector_test()
        before = self.current()
        for item, identity in self.native_selectors.items():
            with self.subTest(item=item):
                request = self.selector_red(item, identity, "native-selector-red-" + item)
                completed = self.selector_cli("proof", request=request)
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual("PASS", result["state"], result)
                proof = result["proof"]
                self.assertEqual((identity, "INTENDED_ASSERTION_FAILURE"),
                                 (proof["data"]["test_id"], proof["data"]["outcome"]))
                receipt, raw = self.read_receipt(proof["data"]["output"])
                streams = {name: Path(receipt[name]["path"]).read_bytes().decode("utf-8")
                           for name in ("stdout", "stderr")}
                print(json.dumps({"native_proof": proof["id"], "receipt": receipt, **streams},
                                 sort_keys=True), flush=True)
                self.assertEqual(request["command"], receipt["argv"])
                self.assertNotEqual(0, receipt["exit"])
                self.assertIn(identity.encode(), raw)
                marker = b"ERR_ASSERTION" if item == "A2W" else b"AssertionError"
                self.assertIn(marker, raw)
                self.assertEqual(proof, self.event(request["id"]))
        self.assertEqual(before, self.current())

    def test_public_native_selector_boundaries_refuse_malformed_values(self):
        malformed = ("", " leading", "trailing ", "two\twords", "two\nlines", "two\rlines",
                     "nul\x00character", "line\u2028separator", "paragraph\u2029separator",
                     "control\x7fcharacter", "x" * 513, None, 123)
        self.configure(ids=tuple(self.native_selectors))
        self.initialize()
        template = self.selector_plan()
        before_plan = self.history()
        for identity in malformed:
            with self.subTest(boundary="plan", identity=identity):
                request = copy.deepcopy(template)
                content = request["data"]["content"]
                content["verification_map"]["A2W"]["test_id"] = identity
                request["data"]["revision"] = a1.runtime.digest(content)
                completed = self.selector_cli("run", "append", request=request)
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                self.assertEqual("BLOCK", json.loads(completed.stdout)["state"])
                self.assertEqual(before_plan, self.history())

        self.publish_plan("native-selector-proof-plan", self.plan_content())
        self.open_selector_test()
        before_proof, source = self.history(), self.current()
        for index, identity in enumerate(malformed):
            with self.subTest(boundary="proof", identity=identity):
                request = self.selector_red("A2W", identity, f"native-selector-invalid-{index}")
                completed = self.selector_cli("proof", request=request)
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual("BLOCK", result["state"], result)
                self.assertNotIn("proof", result)
                self.assertNotIn("receipt", result)
                self.assertEqual(before_proof, self.history())
                self.assertEqual(source, self.current())


class AuditRepairRuntimeTests(WorkflowFixture):
    selector_cli = NativeSelectorSyntaxTests.selector_cli

    def fresh_repair_fixture(self):
        fixture = type(self)()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def retain_native(self, label, reference):
        receipt, raw = self.read_receipt(reference)
        streams = {name: Path(receipt[name]["path"]).read_bytes().decode("utf-8")
                   for name in ("stdout", "stderr")}
        print(json.dumps({"label": label, "receipt": receipt, **streams}, sort_keys=True), flush=True)
        return receipt, raw

    def test_audit_mapped_check_requires_actual_named_result(self):
        title = NativeSelectorSyntaxTests.native_selectors["A2W"]
        for scenario in ("python-skip", "node-excluded", "node-zero", "node-wrong", "node-duplicate"):
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                item = "A1" if scenario == "python-skip" else "A2W"
                fixture.configure(ids=(item,))
                mappings = fixture.verification_map([item])
                if scenario == "node-excluded":
                    mappings[item]["command"].insert(2, "--test-name-pattern=^AbsentFixtureSelector$")
                fixture.plan_extras["verification_map"] = mappings
                fixture.prepare_plan()
                fixture.cycle("selection-control", [item])
                genuine = fixture.event("selection-control-green-" + item)
                control, raw = fixture.retain_native(scenario + "-genuine", genuine["data"]["output"])
                self.assertEqual(0, control["exit"])
                self.assertIn(mappings[item]["test_id"].encode(), raw)

                if scenario != "node-excluded":
                    fixture.open_phase("selection-test", "TEST_ONLY", [item])
                    if scenario == "python-skip":
                        body = a1.PYTHON_SUITE.replace("    def test_A1(self):",
                            '    @unittest.skip("synthetic assertion was not run")\n    def test_A1(self):')
                    elif scenario == "node-zero":
                        body = "const { test } = require('node:test');\n"
                    elif scenario == "node-wrong":
                        body = a1.JS_SUITE.replace(title, "Different selected assertion")
                    else:
                        body = a1.JS_SUITE + f"test({json.dumps(title)}, () => assert.equal(1, 1));\n"
                    fixture.write_files({a1.TEST_FILES[item]: body})

                fixture.open_phase("selection-verify", "VERIFY", [item])
                source = fixture.current()
                request = {key: mappings[item][key] for key in ("test_path", "test_id", "command")}
                request.update(id="empty-native-check", phase="CHECK", check=a1.CHECKS[item],
                               start="selection-verify", actor=a1.ACTOR, acceptance=item)
                completed = fixture.selector_cli("proof", request=request)
                with self.subTest(consumer="issuance"):
                    self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                result = json.loads(completed.stdout)
                admitted = result.get("proof")
                reference = admitted["data"]["output"] if admitted else result["receipt"]
                receipt, raw = fixture.retain_native(scenario + "-selection", reference)
                self.assertEqual(0, receipt["exit"])
                if scenario == "python-skip":
                    self.assertIn(b"OK (skipped=1)", raw)
                elif scenario == "node-wrong":
                    self.assertIn(b"Different selected assertion", raw)
                    self.assertNotIn(title.encode(), raw)
                elif scenario == "node-duplicate":
                    self.assertEqual(2, raw.count(title.encode()))
                else:
                    self.assertNotIn(title.encode(), raw)
                    self.assertIn(a1.WEB_TEST.encode(), raw)
                aggregate = fixture.selector_cli("proof", request={
                    "id": "empty-native-aggregate", "phase": "CHECK", "check": "full",
                    "start": "selection-verify", "actor": a1.ACTOR,
                    "results": [{"acceptance": item, "proof": request["id"]}],
                })
                with self.subTest(consumer="aggregate"):
                    self.assertEqual(1, aggregate.returncode, aggregate.stdout + aggregate.stderr)
                    self.assertEqual("BLOCK", json.loads(aggregate.stdout)["state"])
                with self.subTest(consumer="history"):
                    self.assertFalse(any(event["id"] in {request["id"], "empty-native-aggregate"}
                                         for event in fixture.history()["events"]))
                self.assertEqual(source, fixture.current())

    def test_audit_lifecycle_assertion_is_refused_at_red_issuance_and_replay(self):
        title = NativeSelectorSyntaxTests.native_selectors["A2W"]
        suites = {
            "A1": a1.PYTHON_SUITE.replace("class Behaviors(unittest.TestCase):\n",
                'class Behaviors(unittest.TestCase):\n    def setUp(self):\n'
                '        raise AssertionError("fixture setup assertion")\n\n').replace(
                "    def test_A1(self):\n", '    def test_A1(self):\n        print("SELECTED_BODY_EXECUTED")\n'),
            "A2W": a1.JS_SUITE.replace("const {test}", "const {test, before}").replace(
                f"test('{title}', () => {{",
                f"before(() => assert.equal(1, 2, 'fixture hook assertion'));\n"
                f"test('{title}', () => {{\n  console.log('SELECTED_BODY_EXECUTED');"),
        }
        for item, body in suites.items():
            with self.subTest(item=item):
                fixture = self.fresh_repair_fixture()
                fixture.configure(ids=(item,))
                fixture.prepare_plan()
                start = fixture.open_phase("lifecycle-test", "TEST_ONLY", [item])["start"]
                fixture.write_files({a1.TEST_FILES[item]: body})
                command, identity = fixture.selected_command(item)
                request = {"id": "lifecycle-red", "phase": "RED", "check": a1.CHECKS[item],
                           "start": start["id"], "actor": a1.ACTOR, "acceptance": item,
                           "test_id": identity, "test_path": a1.TEST_FILES[item],
                           "command": command, "failure_kind": "ASSERTION"}
                completed = fixture.selector_cli("proof", request=request)
                with self.subTest(consumer="issuance"):
                    self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                response = json.loads(completed.stdout)
                admitted = response.get("proof")
                reference = admitted["data"]["output"] if admitted else response["receipt"]
                receipt, raw = fixture.retain_native("lifecycle-" + item, reference)
                self.assertEqual(1, receipt["exit"])
                self.assertIn(b"in setUp" if item == "A1" else b"TestHook.run", raw)
                self.assertNotIn(b"SELECTED_BODY_EXECUTED", raw)
                state = fixture.history()
                attempt = dict(request, plan=fixture.plan, candidate=receipt["candidate"],
                               source=receipt["source"], runner=receipt["runner"], output=reference,
                               exit=receipt["exit"], outcome="INTENDED_ASSERTION_FAILURE")
                with self.subTest(consumer="native-replay"):
                    with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
                        a1.runtime._v2()._validate_native(state, attempt, fixture.event("workflow-plan"), start)
                with self.subTest(consumer="history"):
                    self.assertFalse(any(event["id"] == request["id"] for event in state["events"]))


    def test_audit_original_selected_witness_withdrawal_blocks_own_green_before_launch(self):
        for retired in ("test-plan", "red-plan", "production-plan", "reader-decision-review"):
            with self.subTest(retired=retired):
                fixture = self.fresh_repair_fixture()
                fixture.prepare_plan()
                fixture.decision("reader-decision", "Require the selected reader assertion.", behavior="A1")
                fixture.review("test-plan", "plan_review", "test-plan-astra", a1.ASTRA_MODEL)
                fixture.open_phase("own-test", "TEST_ONLY", ["A1"])
                fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
                fixture.review("red-plan", "plan_review", "red-plan-astra", a1.ASTRA_MODEL)
                fixture.proof("own-red", "A1", "own-test", passing=False)
                fixture.review("production-plan", "plan_review", "production-plan-astra", a1.ASTRA_MODEL)
                fixture.open_phase("own-production", "PRODUCTION", ["A1"])
                fixture.write_files({"reader.py": a1.WORKING["reader.py"]})
                fixture.review("new-plan", "plan_review", "new-plan-astra", a1.ASTRA_MODEL)
                fixture.support("new-reader-review")
                fixture.retire(retired)
                before = fixture.history()
                with patch.object(subprocess, "Popen", wraps=subprocess.Popen) as launched:
                    result = fixture.request_proof("retired-original-green", "A1", "own-production")
                native = [call.args[0] for call in launched.call_args_list if call.args and
                          isinstance(call.args[0], list) and call.args[0]
                          and Path(call.args[0][0]).name == "sandbox-exec"]
                print(json.dumps({"retired": retired, "native_argv": native, "result": result},
                                 sort_keys=True), flush=True)
                if result.get("proof"):
                    fixture.retain_native("retired-origin-green", result["proof"]["data"]["output"])
                with self.subTest(boundary="proof"):
                    fixture.refuse(result, "retired-original-green")
                    self.assertNotIn("receipt", result)
                with self.subTest(boundary="before-launch"):
                    self.assertFalse(native, native)
                    self.assertEqual(before, fixture.history())

    def test_audit_original_green_witness_stays_live_through_all_consumers(self):
        for withdrawn in ("selected-plan", "selected-decision", "unselected-plan"):
            with self.subTest(withdrawn=withdrawn):
                fixture = self.fresh_repair_fixture()
                fixture.prepare_plan()
                fixture.decision("reader-choice", "Preserve the named reader behavior.", behavior="A1")
                fixture.review("selected-origin-plan", "plan_review", "selected-origin-astra", a1.ASTRA_MODEL)

                def renew_support():
                    fixture.review("later-plan", "plan_review", "later-plan-astra", a1.ASTRA_MODEL)
                    fixture.support("later-reader-review")

                fixture.cycle("origin", ["A1"], before_green=renew_support)
                order = {name: fixture.event(name)["seq"] for name in (
                    "selected-origin-plan", "reader-choice-review", "origin-test", "origin-red-A1",
                    "later-plan", "later-reader-review", "origin-production", "origin-green-A1",
                )}
                self.assertLess(order["selected-origin-plan"], order["origin-test"])
                self.assertLess(order["reader-choice-review"], order["origin-test"])
                self.assertLess(order["origin-test"], order["origin-red-A1"])
                for renewal in ("later-plan", "later-reader-review"):
                    self.assertLess(order["origin-red-A1"], order[renewal])
                    self.assertLess(order[renewal], order["origin-production"])
                self.assertLess(order["origin-production"], order["origin-green-A1"])
                original_red = fixture.event("origin-red-A1")
                fixture.retain_native("earlier-origin-red", original_red["data"]["output"])
                for check in ("reader", "full"):
                    fixture.archived_case(check)
                fixture.consult_mapped("origin-repair-lookup", "repair", fixture.current()["sha256"])
                fixture.finding("own-reader-finding", "reader")
                fixture.finding("own-aggregate-finding", "full")
                green = fixture.proof("current-own-green", "A1", "origin-production")
                fixture.final_proofs = {"A1": green}
                aggregate = fixture.coverage("current-own-aggregate", "origin-production")
                self.assertEqual("PASS", aggregate["state"], aggregate)
                fixture.disposition("own-reader-finding", green, action="FIXED")
                fixture.disposition("own-aggregate-finding", aggregate["proof"], action="FIXED")
                completed = fixture.finish_workflow(start="origin-production", full=False, prefix="origin-")
                self.assertTrue(completed["ready"], completed)
                if withdrawn == "selected-plan":
                    fixture.retire("selected-origin-plan")
                elif withdrawn == "selected-decision":
                    fixture.retire("reader-choice-review")
                else:
                    fixture.retire("workflow-plan-review")
                result = fixture.ledger.check(a1.RUN)
                fresh_aggregate = fixture.coverage("after-origin-withdrawal", "origin-production")
                print(json.dumps({"withdrawn": withdrawn, "witness_order": order, "check": result,
                                  "aggregate": fresh_aggregate}, sort_keys=True), flush=True)
                if withdrawn == "unselected-plan":
                    self.assertEqual(("PASS", True), (result["state"], result["ready"]), result)
                    self.assertEqual("PASS", fresh_aggregate["state"], fresh_aggregate)
                else:
                    with self.subTest(consumer="completion"):
                        self.assertEqual(("BLOCK", False), (result["state"], result["ready"]), result)
                    for error in ("carried case regression proof missing: reader",
                                  "carried case regression proof missing: full",
                                  "unresolved actionable finding own-reader-finding/coverage",
                                  "unresolved actionable finding own-aggregate-finding/coverage"):
                        with self.subTest(consumer=error):
                            self.assertIn(error, result["errors"], result)
                    with self.subTest(consumer="aggregate"):
                        fixture.refuse(fresh_aggregate, "after-origin-withdrawal")
                    self.assertEqual(green, fixture.event(green["id"]))
                    self.assertEqual(aggregate["proof"], fixture.event(aggregate["proof"]["id"]))

    def test_audit_required_standard_and_critical_evidence_is_complete_and_live(self):
        for lane in ("Standard", "Critical"):
            for missing in ("both", "empty-executed", "inspected", "withdrawn"):
                with self.subTest(lane=lane, missing=missing):
                    fixture = self.fresh_repair_fixture()
                    fixture.configure(lane)
                    fixture.prepare_plan()
                    fixture.cycle("audit", ["A1"])
                    green = fixture.event("audit-green-A1")
                    coverage = fixture.coverage("audit-full", "audit-production", {"A1": green})
                    self.assertEqual("PASS", coverage["state"], coverage)
                    candidate = fixture.current()["sha256"]
                    for kind in ("code", "security", "tests"):
                        label = "required-" + kind
                        executed, inspected = fixture.audit_execution(label, {"A1": green})
                        record = {
                            "kind": kind, "plan": fixture.plan, "candidate": candidate, "verdict": "APPROVE",
                            "reviewer": fixture.reviewer(label + "-sol", a1.SOL_MODEL), "findings": [],
                            "executed": executed, "inspected": inspected,
                        }
                        if kind == "tests":
                            if missing == "both":
                                del record["executed"], record["inspected"]
                            elif missing == "empty-executed":
                                record["executed"] = []
                            elif missing == "inspected":
                                del record["inspected"]
                        fixture.push(label, "audit", record)
                    fixture.consult_mapped("required-audit-final-lookup", "final", candidate)
                    if lane == "Critical":
                        fixture.review("required-audit-final", "final_review", "required-final-astra", a1.ASTRA_MODEL)
                    if missing == "withdrawn":
                        fixture.retire("required-tests")
                    result = fixture.ledger.check(a1.RUN)
                    print(json.dumps({"lane": lane, "missing": missing, "check": result}, sort_keys=True), flush=True)
                    self.assertFalse(result["ready"], result)
                    self.assertTrue(any("required-tests" in error or "tests audit" in error
                                        for error in result["errors"]), result)


    def test_audit_removed_ticket_requires_observed_paths_at_first_baseline(self):
        added, present, retained = "features/new.md", "features/existing.md", "reader-features/retained.md"
        for scenario in ("added", "changed", "restored"):
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                fixture.configure(ids=("A1", "A2S"), tickets=[
                    {"id": "reader-ticket", "acceptance": ["A1"]},
                    {"id": "server-ticket", "acceptance": ["A2S"]},
                ])
                fixture.feature_surface(ticket="server-ticket")
                (fixture.repo / "reader-features").mkdir()
                fixture.contract_extras["write_boundary"]["surfaces"].append({
                    "path": "reader-features", "kind": "directory", "role": "production", "ticket": "reader-ticket",
                })
                original = "Pinned synthetic baseline.\n"
                fixture.write_files({present: original})
                fixture.git("add", "--", present)
                fixture.git("-c", "user.name=V6 fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "-qm", "Synthetic observed path baseline", "--no-gpg-sign")
                fixture.base_commit = fixture.git("rev-parse", "HEAD").strip()
                fixture.plan_extras["batch"] = {
                    "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
                    "dependencies": {"reader-ticket": [], "server-ticket": []}, "interaction_checks": ["full"],
                }
                fixture.initialize()
                content = fixture.plan_content()
                content["acceptance"][1].update(behavior=False, reason="Synthetic server documentation.")
                content["result_map"]["A2S"]["test"] = []
                fixture.publish_plan("remove-observed-plan", content)

                reader_row = manifest(retained, "reader-ticket", "production", None)
                server_rows = [
                    manifest(added, "server-ticket", "production", None),
                    manifest(present, "server-ticket", "production", hashlib.sha256(original.encode()).hexdigest()),
                ]
                fixture.observe_paths("observe-removal-scope", ["A1", "A2S"], [reader_row, *server_rows])
                if scenario == "restored":
                    fixture.open_phase("retained-test", "TEST_ONLY", ["A1"])
                    fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
                    fixture.proof("retained-red", "A1", "retained-test", passing=False)
                    reader = manifest("reader.py", "reader-ticket", "production",
                                      fixture.current()["files"]["reader.py"])
                    production = fixture.preflight("retained-production", "PRODUCTION", ["A1"],
                                                   write_manifest=[reader, reader_row])
                    self.assertEqual("PASS", production["state"], production)
                    fixture.write_files({"reader.py": a1.WORKING["reader.py"], retained: "Keep retained work.\n"})
                    fixture.proof("retained-green", "A1", "retained-production")

                phase = fixture.preflight("server-production", "PRODUCTION", ["A2S"], write_manifest=server_rows)
                self.assertEqual("PASS", phase["state"], phase)
                if scenario in ("added", "restored"):
                    fixture.write_files({added: "Synthetic removed-ticket addition.\n"})
                if scenario in ("changed", "restored"):
                    fixture.write_files({present: "Changed synthetic server baseline.\n"})
                if scenario == "restored":
                    fixture.write_files({present: original})
                    (fixture.repo / added).unlink()
                before, candidate = fixture.history(), fixture.current()
                completed = fixture.selector_cli("run", "append", request={
                    "id": "remove-observed-ticket", "type": "batch_membership", "data": {
                        "plan": fixture.plan, "previous": None, "members": ["reader-ticket"],
                        "candidate": candidate["sha256"], "continuations": {"server-ticket": "later-server"},
                        "reason": "Continue independently owned server documentation later.",
                    },
                })
                expected = 0 if scenario == "restored" else 1
                self.assertEqual(expected, completed.returncode, completed.stdout + completed.stderr)
                self.assertEqual(candidate, fixture.current())
                if scenario != "restored":
                    self.assertEqual("BLOCK", json.loads(completed.stdout)["state"])
                    self.assertEqual(before, fixture.history())
                    continue
                self.assertEqual("batch_membership", json.loads(completed.stdout)["type"])
                self.assertFalse((fixture.repo / added).exists())
                self.assertEqual(original, (fixture.repo / present).read_text())
                self.assertEqual("Keep retained work.\n", (fixture.repo / retained).read_text())
                fixture.final_proofs = {"A1": fixture.proof("retained-current", "A1", "server-production")}
                result = fixture.finish_workflow(start="server-production", prefix="removed-")
                self.assertEqual(["reader-ticket"], result["active_tickets"])
                self.assertEqual({"server-ticket": "later-server"}, result["continuations"])
                self.assertFalse(result["parent_complete"], result)


INTERACTION_CHECK = "reader-server-interaction"


def configure_batch(fixture, *, allowed=(("reader-ticket", "server-ticket"),), dependencies=None):
    tickets = [
        {"id": "reader-ticket", "acceptance": ["A1"]},
        {"id": "server-ticket", "acceptance": ["A2S"]},
        {"id": "display-ticket", "acceptance": ["A2W"]},
    ]
    fixture.configure(ids=("A1", "A2S", "A2W"), tickets=tickets)
    fixture.plan_extras["batch"] = {
        "allowed_subsets": [list(subset) for subset in allowed],
        "subset_delivery": True,
        "dependencies": dependencies if dependencies is not None else {row["id"]: [] for row in tickets},
        "interaction_checks": [INTERACTION_CHECK],
    }


def batch_content(fixture, *, server_behavior=True):
    content = fixture.plan_content()
    content["checks"].append(INTERACTION_CHECK)
    if not server_behavior:
        content["acceptance"][1].update(behavior=False, reason="Verify the retained synthetic server baseline.")
        content["result_map"]["A2S"]["test"] = []
        content["aggregate_checks"]["full"].remove("A2S")
    return content


def membership_request(fixture, members, *, previous=None):
    return {
        "plan": fixture.plan,
        "previous": previous,
        "members": list(members),
        "candidate": fixture.current()["sha256"],
        "continuations": {ticket["id"]: "later-" + ticket["id"] for ticket in fixture.tickets
                          if ticket["id"] not in members},
        "reason": "Continue each removed independent fixture ticket separately.",
    }


def record_interaction(fixture, label, start, *, expected_status=405):
    command = [a1.PYTHON, "-B", "-c",
               "from reader import read; from server import status; "
               f"assert read(['b', 'a', 'b']) == ['a', 'b']; assert status('POST') == {expected_status}"]
    return fixture.command_check(label, start, INTERACTION_CHECK, command)


def audit_candidate(fixture, prefix):
    candidate = fixture.current()["sha256"]
    route = a1.runtime.evaluate_policy(fixture.content["policy"], historical=a1.runtime._historical(fixture.history()))
    for kind in route["audits"]:
        label = prefix + kind
        executed, inspected = fixture.audit_execution(label, fixture.final_proofs)
        fixture.push(label, "audit", {
            "kind": kind, "plan": fixture.plan, "candidate": candidate, "verdict": "APPROVE",
            "reviewer": fixture.reviewer(label + "-sol", a1.SOL_MODEL),
            "findings": [], "executed": executed, "inspected": inspected,
        })
    fixture.consult_mapped(prefix + "final-cases", "final", candidate)


def refresh_acceptance(fixture, prefix, proofs):
    audit_candidate(fixture, prefix + "audit-")
    ready = fixture.ledger.check(a1.RUN)
    fixture.assertTrue(ready["ready"], ready)
    candidate = ready["candidate"]["sha256"]
    fixture.assertEqual(fixture.current()["sha256"], candidate)
    for proof in proofs:
        fixture.assertEqual(proof, fixture.event(proof["id"]))
        fixture.assertEqual(candidate, proof["data"]["candidate"])
        fixture.assertEqual([], fixture.proof_errors(proof))
    fixture.push(prefix + "report", "observation", {
        "status": "COMPLETED", "summary": "Current synthetic checks and independent audit evidence passed.",
        "candidate": candidate,
    })
    fixture.push(prefix + "brief", "teaching", {
        "report": prefix + "report", "plan": fixture.plan, "candidate": candidate,
        "problem": "Validate acceptance after a fixture state transition.",
        "path": "Execute the current native checks and review the exact resulting candidate.",
        "decisions": [], "alternatives": [], "tradeoffs": [],
        "proofs": [proof["id"] for proof in proofs], "sources": [proof["data"]["output"] for proof in proofs],
        "principle": "Current evidence controls acceptance after a change.",
        "example": "A current selected check can replace proof that no longer applies.",
        "limits": "Disposable local fixture with synthetic review identities.",
    })
    accepted = fixture.ledger.check(a1.RUN)
    fixture.assertEqual(("PASS", "ACCEPTED_LOCAL"), (accepted["state"], accepted["lifecycle"]), accepted)
    return accepted


class AuditFollowupRuntimeTests(a1.RetainedFixture, WorkflowFixture):
    fresh_repair_fixture = AuditRepairRuntimeTests.fresh_repair_fixture
    retain_native = AuditRepairRuntimeTests.retain_native
    selector_cli = NativeSelectorSyntaxTests.selector_cli

    def test_selected_final_review_retirement_invalidates_completion(self):
        for lane in ("Critical", "Standard"):
            for annotation in ("withdrawal", "supersession"):
                with self.subTest(lane=lane, annotation=annotation):
                    fixture = self.fresh_repair_fixture()
                    triggers = dict(a1.base.ordinary_policy()["triggers"], user_or_project_requirement=True)
                    fixture.configure(lane, triggers=triggers)
                    fixture.prepare_plan()
                    fixture.cycle("change", ["A1"])
                    accepted = fixture.finish_workflow(final=True)
                    historical = fixture.event("workflow-final-review")
                    selected = fixture.review("current-final", "final_review", "current-final-astra", a1.ASTRA_MODEL)
                    current = fixture.ledger.check(a1.RUN)
                    self.assertEqual(("PASS", True), (current["state"], current["ready"]), current)

                    retired = fixture.retire(selected["id"], annotation)
                    self.assertLess(historical["seq"], selected["seq"])
                    self.assertFalse(any(e["type"] in {"withdrawal", "supersession"}
                                         and e["data"].get("target") == historical["id"]
                                         for e in fixture.history()["events"]))
                    result = fixture.ledger.check(a1.RUN)
                    print(json.dumps({"lane": lane, "selected": selected["id"], "retirement": retired,
                                      "live_historical": historical["id"],
                                      "before": current, "after": result}, sort_keys=True), flush=True)
                    with self.subTest(boundary="selected final retirement"):
                        self.assertEqual(("BLOCK", False), (result["state"], result["ready"]), result)
                        self.assertTrue(any("final" in error.casefold() or selected["id"] in error
                                            for error in result["errors"]), result)
                    self.assertEqual(accepted["candidate"], result["candidate"])
                    self.assertEqual(historical, fixture.event(historical["id"]))
                    self.assertEqual(selected, fixture.event(selected["id"]))

                    fixture.review("fresh-final", "final_review", "fresh-final-astra", a1.ASTRA_MODEL)
                    recovered = fixture.ledger.check(a1.RUN)
                    self.assertEqual(("PASS", "ACCEPTED_LOCAL"), (recovered["state"], recovered["lifecycle"]), recovered)
                    fixture.retire(historical["id"], annotation)
                    after_unselected = fixture.ledger.check(a1.RUN)
                    self.assertEqual(("PASS", "ACCEPTED_LOCAL"),
                                     (after_unselected["state"], after_unselected["lifecycle"]), after_unselected)
                    self.assertEqual(accepted["candidate"], after_unselected["candidate"])

    def own_green_consumers(self):
        for check in ("reader", "full"):
            self.archived_case(check)
            self.finding("decision-" + check + "-finding", check)
        self.consult_mapped("decision-consumer-cases", "repair", self.current()["sha256"])
        green = self.proof("current-own-green", "A1", "change-production")
        self.final_proofs = {"A1": green}
        coverage = self.coverage("own-full", "change-production")
        self.assertEqual("PASS", coverage["state"], coverage)
        aggregate = coverage["proof"]
        self.disposition("decision-reader-finding", green, action="FIXED")
        self.disposition("decision-full-finding", aggregate, action="FIXED")
        self.finish_workflow(full=False)
        return green, aggregate

    def test_own_green_post_issuance_decision_revision_invalidates_consumers(self):
        for change in ("revised", "newly-relevant", "reassigned"):
            with self.subTest(change=change):
                fixture = self.fresh_repair_fixture()
                fixture.prepare_plan()
                if change != "newly-relevant":
                    fixture.decision("original-reader-choice", "Retain the original reader result.", behavior="A1")
                fixture.cycle("change", ["A1"])
                green, aggregate = fixture.own_green_consumers()
                candidate = fixture.current()
                fixture.decision("later-choice", "Use a materially different contract.",
                                 behavior="A2S" if change == "reassigned" else "A1")
                for revision in ("changed", "restored") if change == "revised" else ("changed",):
                    if revision == "restored":
                        fixture.decision("restored-choice", "Retain the original reader result.", behavior="A1")
                    result = fixture.ledger.check(a1.RUN)
                    self.assertEqual(candidate, fixture.current())
                    print(json.dumps({"change": change, "revision": revision, "green": green["id"],
                                      "aggregate": aggregate["id"], "result": result}, sort_keys=True), flush=True)
                    with self.subTest(revision=revision, consumer="completion"):
                        self.assertEqual(("BLOCK", False), (result["state"], result["ready"]), result)
                    with self.subTest(revision=revision, consumer="native replay"):
                        self.assertTrue(fixture.proof_errors(green, "GREEN"))
                        self.assertTrue(fixture.proof_errors(aggregate))
                    with self.subTest(revision=revision, consumer="aggregate issuance"):
                        proof_id = "revised-aggregate-" + revision
                        new = fixture.coverage(proof_id, "change-production")
                        fixture.refuse(new, proof_id)
                    for check in ("reader", "full"):
                        with self.subTest(revision=revision, consumer=check):
                            self.assertIn("carried case regression proof missing: " + check, result["errors"])
                            self.assertIn("unresolved actionable finding decision-" + check + "-finding/coverage",
                                          result["errors"])
                    self.assertEqual(green, fixture.event(green["id"]))
                    self.assertEqual(aggregate, fixture.event(aggregate["id"]))

    def test_reviewed_decision_before_own_production_remains_valid(self):
        self.prepare_plan()
        self.decision("d1", "Keep the original synthetic reader rule.", behavior="A1")
        self.cycle("change", ["A1"], before_green=lambda: self.decision(
            "d2", "Use the revised synthetic reader rule.", behavior="A1"))
        red, revised, production, green = (
            self.event(label) for label in ("change-red-A1", "d2-review", "change-production", "change-green-A1")
        )
        self.assertLess(red["seq"], revised["seq"])
        self.assertLess(revised["seq"], production["seq"])
        self.assertLess(production["seq"], green["seq"])
        self.assertEqual([], self.proof_errors(green, "GREEN"))
        self.finish_workflow()

        unrelated = copy.deepcopy(self.event("d1")["data"])
        del unrelated["revision"]
        unrelated.update(lineage="other-status", acceptance=["A2S"], choice="First independent rule.", supersedes=None)
        first = a1.runtime.digest(unrelated)
        for label in ("other-original", "other-revised"):
            revision = a1.runtime.digest(unrelated)
            self.push(label, "decision", dict(unrelated, revision=revision))
            self.push(label + "-review", "doubt_review", {
                "decision": unrelated["lineage"], "revision": revision, "verdict": "SUPPORTED",
                "reviewer": self.reviewer(label + "-sol", a1.SOL_MODEL), "findings": [],
            })
            unrelated.update(choice="A second independent rule.", supersedes=first)
        self.assertEqual([], self.proof_errors(green, "GREEN"))
        self.assertTrue(self.ledger.check(a1.RUN)["ready"])

        self.retire("d1-review")
        self.assertTrue(self.proof_errors(green, "GREEN"))
        self.assertFalse(self.ledger.check(a1.RUN)["ready"])

    def test_declared_interaction_is_required_outside_required_checks(self):
        for members in (("reader-ticket", "server-ticket"), None):
            with self.subTest(membership=members):
                fixture = self.fresh_repair_fixture()
                configure_batch(fixture)
                fixture.initialize()
                fixture.publish_plan("workflow-plan", batch_content(fixture))
                retained = fixture.ids
                if members is not None:
                    fixture.push("retained-tickets", "batch_membership", membership_request(fixture, members))
                    retained = ("A1", "A2S")
                fixture.cycle("change", retained)
                fixture.final_proofs = {item: fixture.event("change-green-" + item) for item in retained}
                result = fixture.coverage("full-without-interaction", "change-production")
                self.assertEqual("PASS", result["state"], result)
                self.assertNotIn(INTERACTION_CHECK, fixture.content["required_checks"])
                audit_candidate(fixture, "without-interaction-")
                blocked = fixture.ledger.check(a1.RUN)
                print(json.dumps({"members": members, "completion": blocked}, sort_keys=True), flush=True)
                with self.subTest(boundary="missing interaction"):
                    self.assertFalse(blocked["ready"], blocked)
                    self.assertTrue(any(INTERACTION_CHECK in reason for reason in blocked["errors"]), blocked)
                proof = record_interaction(fixture, "current-interaction", "change-production")
                self.assertEqual("PASS", proof["state"], proof)
                fixture.retain_native("declared-interaction", proof["proof"]["data"]["output"])
                ready = fixture.finish_workflow(prefix="with-interaction-", full=False)
                self.assertEqual(members is None, ready["parent_complete"])

    def test_interaction_proof_predating_membership_is_stale(self):
        retained = ("reader-ticket", "server-ticket")
        for change in ("predates-membership", "wrong-membership", "withdrawn", "failed"):
            with self.subTest(change=change):
                fixture = self.fresh_repair_fixture()
                configure_batch(fixture, allowed=(retained, ("reader-ticket",)))
                fixture.initialize()
                fixture.publish_plan("workflow-plan", batch_content(fixture, server_behavior=False))
                fixture.cycle("change", ["A1"])
                fixture.final_proofs = {"A1": fixture.event("change-green-A1")}
                start = "change-production"
                server = fixture.command_check("unchanged-server", start, "server", [
                    a1.PYTHON, "-B", "-c", "from server import status; assert status('POST') == 500",
                ])
                self.assertEqual("PASS", server["state"], server)
                if change != "predates-membership":
                    fixture.push("first-membership", "batch_membership", membership_request(fixture, retained))
                result = record_interaction(fixture, "earlier-interaction", start, expected_status=500)
                self.assertEqual("PASS", result["state"], result)
                proof = result["proof"]
                if change == "predates-membership":
                    event = fixture.push("first-membership", "batch_membership", membership_request(fixture, retained))
                    self.assertLess(proof["seq"], event["seq"])
                elif change == "wrong-membership":
                    event = fixture.push("second-membership", "batch_membership",
                                         membership_request(fixture, ("reader-ticket",), previous="first-membership"))
                    self.assertLess(proof["seq"], event["seq"])
                elif change == "withdrawn":
                    fixture.retire(proof["id"])
                else:
                    failed = record_interaction(fixture, "failed-interaction", start, expected_status=123)
                    fixture.refuse(failed, "failed-interaction")
                    fixture.retain_native("failed-interaction", failed["receipt"])
                    fixture.retire(proof["id"])
                self.assertEqual(proof["data"]["candidate"], fixture.current()["sha256"])
                aggregate = fixture.coverage("membership-full", start)
                self.assertEqual("PASS", aggregate["state"], aggregate)
                audit_candidate(fixture, "stale-interaction-")
                blocked = fixture.ledger.check(a1.RUN)
                with self.subTest(boundary="stale interaction"):
                    self.assertFalse(blocked["ready"], blocked)
                    self.assertTrue(any(INTERACTION_CHECK in reason for reason in blocked["errors"]), blocked)
                if change != "failed":
                    current = record_interaction(fixture, "renewed-interaction", start, expected_status=500)
                    self.assertEqual("PASS", current["state"], current)
                    fixture.finish_workflow(prefix="renewed-", full=False)

    def removal_mode_fixture(self, origin):
        fixture = self.fresh_repair_fixture()
        fixture.configure(ids=("A1", "A2W"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "display-ticket", "acceptance": ["A2W"]},
        ])
        fixture.plan_extras["batch"] = {
            "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
            "dependencies": {"reader-ticket": [], "display-ticket": []}, "interaction_checks": ["full"],
        }
        if origin == "initial":
            name = "display.cjs"
            path = fixture.repo / name
            self.assertTrue(fixture.git("ls-tree", fixture.base_commit, "--", name).startswith("100644 "))
            baseline_mode = 0o755
            path.chmod(baseline_mode)
        else:
            fixture.feature_surface(ticket="display-ticket")
            name = "features/existing.md"
            path = fixture.repo / name
            path.write_bytes(b"Synthetic tracked documentation.\n")
            baseline_mode = 0o644
            path.chmod(baseline_mode)
            fixture.git("add", "--", name)
            fixture.git("-c", "user.name=Mode fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "Synthetic observed baseline", "--no-gpg-sign")
            fixture.base_commit = fixture.git("rev-parse", "HEAD").strip()
        fixture.initialize()
        content = fixture.plan_content()
        content["acceptance"][1].update(behavior=False, reason="Verify the independent synthetic baseline.")
        content["result_map"]["A2W"]["test"] = []
        content["aggregate_checks"]["full"].remove("A2W")
        fixture.publish_plan("workflow-plan", content)
        if origin == "observed":
            existing = manifest(name, "display-ticket", "production", hashlib.sha256(path.read_bytes()).hexdigest())
            absent = manifest("features/uncreated.md", "display-ticket", "production", None)
            fixture.observe_paths("baseline-observation", fixture.ids, [existing, absent])
            phase = fixture.preflight("baseline-production", "PRODUCTION", ["A2W"],
                                      write_manifest=[existing, absent])
        else:
            phase = fixture.preflight("baseline-production", "PRODUCTION", ["A2W"])
        self.assertEqual("PASS", phase["state"], phase)
        return fixture, path, baseline_mode

    def test_removed_initial_and_observed_paths_restore_mode_baselines(self):
        for origin in ("initial", "observed"):
            for restore in (False, True):
                with self.subTest(origin=origin, restore=restore):
                    fixture, path, baseline_mode = self.removal_mode_fixture(origin)
                    baseline_bytes = path.read_bytes()
                    path.chmod(baseline_mode ^ stat.S_IXUSR)
                    self.assertEqual(baseline_bytes, path.read_bytes())
                    self.assertNotEqual(baseline_mode, stat.S_IMODE(path.stat().st_mode))
                    if restore:
                        path.chmod(baseline_mode)
                        self.assertEqual(baseline_mode, stat.S_IMODE(path.stat().st_mode))
                        absent = fixture.repo / "features/uncreated.md"
                        if origin == "observed":
                            absent.write_bytes(b"A newly present removed path.\n")
                            with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
                                fixture.push("present-removed-path", "batch_membership",
                                             membership_request(fixture, ("reader-ticket",)))
                            absent.unlink()
                        self.assertFalse(absent.exists())
                    before = fixture.history()
                    completed = fixture.selector_cli("run", "append", request={
                        "id": "mode-removal", "type": "batch_membership",
                        "data": membership_request(fixture, ("reader-ticket",)),
                    })
                    self.assertEqual(0 if restore else 1, completed.returncode, completed.stdout + completed.stderr)
                    result = json.loads(completed.stdout)
                    if restore:
                        self.assertEqual(["reader-ticket"], result["data"]["members"])
                        self.assertEqual({"display-ticket": "later-display-ticket"}, result["data"]["continuations"])
                    else:
                        self.assertEqual("BLOCK", result["state"], result)
                        self.assertEqual(before, fixture.history())

        fixture = self.fresh_repair_fixture()
        fixture.configure(ids=("A1", "A2S"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1"]},
            {"id": "server-ticket", "acceptance": ["A2S"]},
        ])
        fixture.plan_extras["batch"] = {
            "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
            "dependencies": {"reader-ticket": [], "server-ticket": []}, "interaction_checks": ["full"],
        }
        fixture.prepare_plan()
        fixture.open_phase("shared-baseline-test", "TEST_ONLY", ["A1"])
        shared = fixture.repo / a1.SHARED_TEST
        shared.write_text(a1.PYTHON_SUITE)
        with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
            fixture.push("changed-shared-path", "batch_membership", membership_request(fixture, ("reader-ticket",)))
        shared.unlink()
        fixture.push("restored-shared-path", "batch_membership", membership_request(fixture, ("reader-ticket",)))
        fixture.open_phase("retained-shared-owner", "TEST_ONLY", ["A1"])

    def assert_mode_consumers_stale(self, fixture, proof, aggregate, *, phase):
        current = fixture.current()
        outcome = fixture.ledger.check(a1.RUN)
        print(json.dumps({"phase": phase, "proof": proof["id"], "proof_candidate": proof["data"]["candidate"],
                          "current": current, "completion": outcome}, sort_keys=True), flush=True)
        with self.subTest(consumer="mode drift completion"):
            self.assertEqual(("BLOCK", False), (outcome["state"], outcome["ready"]), outcome)
        for event, mode in ((proof, phase), (aggregate, "PASS")):
            with self.subTest(consumer=event["id"]):
                errors = a1.runtime._proof_errors(fixture.history(), event, mode, current["sha256"], fixture.plan)
                self.assertTrue(errors, event["id"])
        for check in ("reader", "full"):
            with self.subTest(consumer=check):
                self.assertIn("carried case regression proof missing: " + check, outcome["errors"])
                self.assertIn("unresolved actionable finding decision-" + check + "-finding/coverage", outcome["errors"])

    def test_mode_only_change_invalidates_native_and_composed_proof(self):
        for phase in ("GREEN", "CHECK"):
            with self.subTest(phase=phase):
                fixture = self.fresh_repair_fixture()
                if phase == "CHECK":
                    fixture.plan_extras["verification_map"] = fixture.verification_map(["A1"])
                fixture.prepare_plan()
                fixture.cycle("change", ["A1"])
                if phase == "GREEN":
                    proof, aggregate = fixture.own_green_consumers()
                else:
                    for check in ("reader", "full"):
                        fixture.archived_case(check)
                        fixture.finding("decision-" + check + "-finding", check)
                    fixture.consult_mapped("mode-consumer-cases", "repair", fixture.current()["sha256"])
                    fixture.open_phase("mapped-mode-verify", "VERIFY", ["A1"])
                    proof = fixture.native_check("mapped-mode-reader", "mapped-mode-verify", "A1")
                    covered = fixture.aggregate("mapped-mode-full", "mapped-mode-verify", "full", [("A1", proof)])
                    self.assertEqual("PASS", covered["state"], covered)
                    aggregate = covered["proof"]
                    fixture.disposition("decision-reader-finding", proof, action="FIXED")
                    fixture.disposition("decision-full-finding", aggregate, action="FIXED")
                    fixture.finish_workflow(full=False)

                target = fixture.repo / "reader.py"
                before_bytes = target.read_bytes()
                before_mode = stat.S_IMODE(target.stat().st_mode)
                before = fixture.current()
                target.chmod(before_mode ^ stat.S_IXUSR)
                self.assertEqual(before_bytes, target.read_bytes())
                self.assertNotEqual(before_mode, stat.S_IMODE(target.stat().st_mode))
                self.assert_mode_consumers_stale(fixture, proof, aggregate, phase=phase)
                if phase == "GREEN":
                    covered = fixture.coverage("stale-mode-aggregate", "change-production")
                    with self.subTest(consumer="fresh aggregate with stale native result"):
                        fixture.refuse(covered, "stale-mode-aggregate")
                    green = fixture.proof("mode-current-reader", "A1", "change-production")
                    fixture.final_proofs = {"A1": green}
                    covered = fixture.coverage("mode-current-full", "change-production")
                else:
                    target.chmod(before_mode)
                    self.assertEqual(before, fixture.current())
                    fixture.open_phase("renewed-mode-verify", "VERIFY", ["A1"])
                    green = fixture.native_check("renewed-mode-reader", "renewed-mode-verify", "A1")
                    covered = fixture.aggregate("renewed-mode-full", "renewed-mode-verify", "full", [("A1", green)])
                self.assertEqual("PASS", covered["state"], covered)
                fixture.disposition("decision-reader-finding", green, action="FIXED")
                fixture.disposition("decision-full-finding", covered["proof"], action="FIXED")
                refresh_acceptance(fixture, "mode-renewed-", [green, covered["proof"]])

    def test_mode_identity_obeys_phase_and_history_boundaries(self):
        scenarios = ("off-grant", "test-only-production", "production-test", "verify-source", "verify-instructions")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                if scenario == "off-grant":
                    fixture.configure(ids=("A1", "A2S"))
                fixture.prepare_plan()
                proof_id = "mode-phase-proof"
                if scenario.startswith("verify-"):
                    start = "mode-verify"
                    fixture.open_phase(start, "VERIFY", ["A1"])
                    path = "reader.py" if scenario == "verify-source" else a1.INSTRUCTIONS[0]
                else:
                    start = "mode-test"
                    fixture.open_phase(start, "TEST_ONLY", ["A1"])
                    fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
                    if scenario == "test-only-production":
                        path = "reader.py"
                    else:
                        fixture.proof("mode-red", "A1", start, passing=False)
                        start = "mode-production"
                        fixture.open_phase(start, "PRODUCTION", ["A1"])
                        fixture.write_files({"reader.py": a1.WORKING["reader.py"]})
                        path = "server.py" if scenario == "off-grant" else a1.SHARED_TEST
                target = fixture.repo / path
                body, mode = target.read_bytes(), stat.S_IMODE(target.stat().st_mode)
                target.chmod(mode ^ stat.S_IXUSR)
                self.assertEqual(body, target.read_bytes())
                self.assertNotEqual(mode, stat.S_IMODE(target.stat().st_mode))
                before = fixture.history()
                if scenario.startswith("verify-"):
                    result = fixture.command_check(proof_id, start, "verify-local", [
                        a1.PYTHON, "-B", "-c", "from reader import read; assert read([]) == []",
                    ])
                else:
                    result = fixture.request_proof(proof_id, "A1", start, passing=scenario != "test-only-production")
                print(json.dumps({"scenario": scenario, "path": path, "result": result}, sort_keys=True), flush=True)
                fixture.refuse(result, proof_id)
                self.assertNotIn("receipt", result)
                self.assertEqual(before, fixture.history())

        fixture = self.fresh_repair_fixture()
        fixture.configure(ids=("A1", "A2W"))
        fixture.prepare_plan()
        fixture.open_phase("legal-mode-test", "TEST_ONLY", ["A1"])
        fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
        red = fixture.proof("legal-mode-red", "A1", "legal-mode-test", passing=False)
        fixture.open_phase("legal-mode-production", "PRODUCTION", ["A1"])
        fixture.write_files({"reader.py": a1.WORKING["reader.py"]})
        legacy_work = a1.runtime.snapshot(fixture.repo, fixture.files, a1.INSTRUCTIONS)
        (fixture.repo / "reader.py").chmod(0o744)
        self.assertEqual(legacy_work, a1.runtime.snapshot(fixture.repo, fixture.files, a1.INSTRUCTIONS))
        self.assertEqual({"repo", "files", "instructions", "sha256"}, legacy_work.keys())
        legacy_body = {name: value for name, value in legacy_work.items() if name != "sha256"}
        self.assertEqual(a1.runtime.digest(legacy_body), legacy_work["sha256"])
        green = fixture.proof("legal-mode-green", "A1", "legal-mode-production")
        self.assertEqual(red["data"]["test"], green["data"]["test"])
        observed = green["observed_source"]
        with self.subTest(boundary="complete v2 mode observation after qualifying GREEN"):
            self.assertIn("modes", observed)
            byte_map = observed["files"] | observed["instructions"]
            self.assertEqual(byte_map.keys(), observed["modes"].keys())
            self.assertIsNone(byte_map[a1.WEB_TEST])
            self.assertIsNone(observed["modes"][a1.WEB_TEST])
            for name, checksum in byte_map.items():
                expected_mode = None
                if checksum is not None:
                    actual = (fixture.repo / name).stat().st_mode
                    expected_mode = "100755" if actual & stat.S_IXUSR else "100644"
                self.assertEqual(expected_mode, observed["modes"][name], name)
            self.assertEqual("100755", observed["modes"]["reader.py"])
            self.assertEqual("100644", observed["modes"][a1.SHARED_TEST])
            snapshot_body = {name: value for name, value in observed.items() if name != "sha256"}
            self.assertEqual(a1.runtime.digest(snapshot_body), observed["sha256"])
            self.assertEqual(observed, fixture.current())

        with self.subTest(boundary="unsupported special bit"):
            target = fixture.repo / "reader.py"
            body = target.read_bytes()
            target.chmod(0o644 | stat.S_ISUID)
            self.assertTrue(target.stat().st_mode & stat.S_ISUID)
            self.assertEqual(body, target.read_bytes())
            result = fixture.refuse_start("special-bit-mode", "VERIFY", ["A1"])
            self.assertTrue(any("mode" in error.casefold() for error in result["errors"]), result)

        with self.subTest(boundary="observed existing path mode must match the pinned Git base"):
            fixture = self.fresh_repair_fixture()
            fixture.feature_surface()
            name = "features/pinned-mode.py"
            target = fixture.repo / name
            body = b"value = 1\n"
            target.write_bytes(body)
            target.chmod(0o644)
            fixture.git("add", "--", name)
            fixture.git("-c", "user.name=Mode fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "Synthetic pinned mode", "--no-gpg-sign")
            fixture.base_commit = fixture.git("rev-parse", "HEAD").strip()
            fixture.prepare_plan()
            target.chmod(0o744)
            self.assertTrue(fixture.git("ls-tree", fixture.base_commit, "--", name).startswith("100644 "))
            self.assertTrue(target.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(body, target.read_bytes())
            row = manifest(name, "fixture-ticket", "production", hashlib.sha256(body).hexdigest())
            result = fixture.refuse_start("mode-mismatch-observation", "VERIFY", ["A1"], observe_manifest=[row])
            self.assertTrue(any("mode" in error.casefold() for error in result["errors"]), result)

        fixture = self.fresh_repair_fixture()
        contract = fixture.contract()
        legacy = a1.runtime.snapshot(fixture.repo, fixture.files, a1.INSTRUCTIONS)
        profile = a1.runtime.profile_identity()
        stored = {"contract": contract, "initial_source": legacy, "profile": profile}
        # Reproduce the prior serialized intake shape using real byte observations.
        with fixture.ledger._connection(create=True) as conn:
            conn.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (
                a1.RUN, a1.runtime.canonical(contract).decode(), a1.runtime.digest(stored),
                a1.runtime.canonical(profile).decode(), a1.runtime.canonical(legacy).decode(),
            ))
        fixture.prepare_plan()
        before = fixture.history()
        self.assertEqual(legacy, before["initial_source"])
        self.assertNotIn("modes", before["initial_source"])
        self.assertFalse(fixture.ledger.check(a1.RUN)["ready"])
        result = fixture.preflight("legacy-mode-unknown", "TEST_ONLY", ["A1"])
        with self.subTest(boundary="old v2 historical readability and live mode uncertainty"):
            self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
            self.assertTrue(any("mode" in reason.casefold() for reason in result["errors"]), result)
            self.assertEqual(before, fixture.history())

    def test_named_and_post_await_node_body_red_qualifies(self):
        for form, signature, setup, frame in (
            ("anonymous-sync", "() =>", "", b"TestContext.<anonymous>"),
            ("named-sync", "function testLabel()", "", b"TestContext.testLabel"),
            ("post-await", "async () =>", "  await Promise.resolve();\n", b"async Test.run"),
        ):
            with self.subTest(form=form):
                fixture = self.fresh_repair_fixture()
                fixture.configure(ids=("A2W",))
                fixture.plan_extras["verification_map"] = fixture.verification_map(["A2W"])
                fixture.prepare_plan()
                command, title = fixture.selected_command("A2W")
                suite = a1.JS_SUITE.replace(f"test('{title}', () => {{\n", f"test('{title}', {signature} {{\n{setup}")
                if form != "anonymous-sync":
                    self.assertNotEqual(a1.JS_SUITE, suite)
                fixture.open_phase("node-body-test", "TEST_ONLY", ["A2W"])
                fixture.write_files({a1.WEB_TEST: suite})
                request = {"id": "node-body-red", "phase": "RED", "check": "display", "start": "node-body-test",
                           "actor": a1.ACTOR, "acceptance": "A2W", "test_id": title,
                           "test_path": a1.WEB_TEST, "command": command, "failure_kind": "ASSERTION"}
                completed = fixture.selector_cli("proof", request=request)
                result = json.loads(completed.stdout)
                output = result["proof"]["data"]["output"] if "proof" in result else result["receipt"]
                receipt, raw = fixture.retain_native(form, output)
                self.assertEqual(1, receipt["exit"])
                self.assertIn(title.encode(), raw)
                self.assertIn(b"ERR_ASSERTION", raw)
                self.assertIn(frame, raw)
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                self.assertEqual("PASS", result["state"], result)
                red = result["proof"]
                self.assertEqual("INTENDED_ASSERTION_FAILURE", red["data"]["outcome"])
                self.assertEqual([], fixture.proof_errors(red, "RED"))
                fixture.open_phase("node-body-production", "PRODUCTION", ["A2W"])
                fixture.write_files({"display.cjs": a1.WORKING["display.cjs"]})
                green = fixture.proof("node-body-green", "A2W", "node-body-production")
                self.assertEqual(red["data"]["test"], green["data"]["test"])
                self.assertEqual([], fixture.proof_errors(green, "GREEN"))
                fixture.open_phase("node-body-verify", "VERIFY", ["A2W"])
                verified = fixture.native_check("node-body-check", "node-body-verify", "A2W")
                self.assertEqual(red["data"]["test"], verified["data"]["test"])
                self.assertEqual([], fixture.proof_errors(verified, "CHECK"))

    def test_node_lifecycle_assertions_remain_ineligible(self):
        scenarios = ("before", "beforeEach", "after", "afterEach",
                     "async-before", "async-beforeEach", "async-after", "async-afterEach",
                     "wrong-title", "duplicate-title", "excluded-title")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                fixture.configure(ids=("A2W",))
                fixture.prepare_plan()
                fixture.open_phase("node-lifecycle-test", "TEST_ONLY", ["A2W"])
                command, title = fixture.selected_command("A2W")
                declaration = json.dumps(title)
                if scenario == "wrong-title":
                    suite = a1.JS_SUITE.replace(title, "A different failing test")
                elif scenario == "duplicate-title":
                    suite = a1.JS_SUITE + f"test({declaration}, () => assert.equal(1, 2));\n"
                elif scenario == "excluded-title":
                    suite = a1.JS_SUITE
                    command.insert(2, "--test-name-pattern=^AbsentFixtureSelector$")
                else:
                    hook = scenario.removeprefix("async-")
                    callback = "async () => { await Promise.resolve();" if scenario.startswith("async-") else "() => {"
                    suite = (
                        f"const {{ test, {hook} }} = require('node:test');\n"
                        "const assert = require('node:assert/strict');\n"
                        f"{hook}({callback} assert.equal(1, 2, 'synthetic lifecycle assertion'); }});\n"
                        f"test({declaration}, () => {{ console.log('SELECTED_BODY_EXECUTED'); assert.equal(1, 1); }});\n"
                    )
                fixture.write_files({a1.WEB_TEST: suite})
                request = {"id": "lifecycle-red", "phase": "RED", "check": "display",
                           "start": "node-lifecycle-test", "actor": a1.ACTOR, "acceptance": "A2W",
                           "test_id": title, "test_path": a1.WEB_TEST, "command": command, "failure_kind": "ASSERTION"}
                completed = fixture.selector_cli("proof", request=request)
                result = json.loads(completed.stdout)
                output = result["proof"]["data"]["output"] if "proof" in result else result["receipt"]
                receipt, raw = fixture.retain_native(scenario, output)
                self.assertEqual(0 if scenario == "excluded-title" else 1, receipt["exit"])
                if scenario != "excluded-title":
                    self.assertIn(b"ERR_ASSERTION", raw)
                if scenario in ("after", "afterEach", "async-after", "async-afterEach"):
                    self.assertIn(b"SELECTED_BODY_EXECUTED", raw)
                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                self.assertEqual("BLOCK", result["state"], result)
                self.assertNotIn("proof", result)
                state = fixture.history()
                attempted = dict(request, plan=fixture.plan, candidate=receipt["candidate"],
                                 source=receipt["source"], runner=receipt["runner"], output=output,
                                 exit=receipt["exit"], outcome="INTENDED_ASSERTION_FAILURE")
                with self.assertRaisesRegex((a1.runtime.RuntimeError, ValueError), "selected test|assertion RED"):
                    a1.runtime._v2()._validate_native(
                        state, attempted, fixture.event("workflow-plan"), fixture.event("node-lifecycle-test"))
                self.assertFalse(any(event["id"] == request["id"] for event in state["events"]))

    def test_removed_ticket_baselines_hold_current_acceptance(self):
        for drift in ("mode", "bytes", "create", "delete"):
            for recover in (False, True):
                with self.subTest(drift=drift, recover=recover):
                    fixture = self.fresh_repair_fixture()
                    start = prepare_removed_server(fixture, observed=drift in {"create", "delete"})
                    removed = fixture.push("remove-server", "batch_membership",
                                           membership_request(fixture, ("reader-ticket",)))
                    clean_candidate = fixture.current()
                    if not recover:
                        clean, _ = complete_removed_reader(fixture, start, "clean-")
                        self.assertEqual((["reader-ticket"], removed["data"]["continuations"], False),
                                         (clean["active_tickets"], clean["continuations"], clean["parent_complete"]))
                    name, original, mode = change_removed_path(fixture, drift)
                    if recover:
                        # Model separately authorized restoration in the disposable fixture.
                        path = fixture.repo / name
                        if original is None:
                            path.unlink()
                        else:
                            path.write_bytes(original)
                            path.chmod(mode)
                        self.assertEqual(clean_candidate, fixture.current())
                        self.assertEqual("BLOCK", fixture.ledger.check(a1.RUN)["state"])
                        before_recovery = fixture.history()["seq"]
                        recovered, proofs = complete_removed_reader(fixture, start, "restored-")
                        self.assertEqual((["reader-ticket"], removed["data"]["continuations"], False),
                                         (recovered["active_tickets"], recovered["continuations"],
                                          recovered["parent_complete"]))
                        self.assertTrue(all(proof["seq"] > before_recovery for proof in proofs))
                        continue

                    before = fixture.history()
                    executor = a1.runtime._v2().executor
                    with patch.object(executor, "run_read_only", wraps=executor.run_read_only) as runner:
                        result = fixture.request_proof("after-drift-green", "A1", start)
                    print(json.dumps({"drift": drift, "path": name, "result": result,
                                      "native_launches": runner.call_count}, sort_keys=True), flush=True)
                    if result["state"] == "PASS":
                        self.assertEqual(1, runner.call_count)
                        complete_removed_reader(fixture, start, "after-drift-", green=result["proof"])
                        exit_code, check = removed_baseline_cli(fixture, "check")
                        self.assertEqual((1, "BLOCK"), (exit_code, check["state"]),
                                         f"Public check accepted removed-ticket drift on {name}")
                    else:
                        self.assertEqual("BLOCK", result["state"], result)
                        self.assertEqual(0, runner.call_count)
                        self.assertNotIn("receipt", result)
                        self.assertEqual(before, fixture.history())
                        assert_removed_baseline(fixture, result["errors"], name)
                        exit_code, check = removed_baseline_cli(fixture, "check")
                        self.assertEqual((1, "BLOCK"), (exit_code, check["state"]))
                        assert_removed_baseline(fixture, check["errors"], name)

    def test_removed_ticket_baselines_hold_proof_and_successive_authority(self):
        fixture = self.fresh_repair_fixture()
        start = prepare_removed_server(fixture)
        name, _, mode = change_removed_path(fixture, "mode")
        drifted = fixture.current()
        proof = fixture.proof("pre-removal-drift", "A1", start)
        earlier = fixture.history()
        (fixture.repo / name).chmod(mode)
        fixture.push("remove-server", "batch_membership", membership_request(fixture, ("reader-ticket",)))
        change_removed_path(fixture, "mode")
        self.assertEqual(drifted, fixture.current())
        self.assertEqual((drifted, fixture.plan), (proof["observed_source"], proof["data"]["plan"]))
        self.assertEqual([], fixture.proof_errors(proof, "GREEN", state=earlier))
        with self.subTest(boundary="current proof consumption"):
            errors = fixture.proof_errors(proof, "GREEN")
            print(json.dumps({"proof": proof["id"], "candidate": drifted, "errors": errors},
                             sort_keys=True), flush=True)
            assert_removed_baseline(fixture, errors, name)
        with self.subTest(boundary="fresh aggregate"):
            before = fixture.history()
            result = fixture.coverage("after-removal-aggregate", start, {"A1": proof})
            print(json.dumps(result, sort_keys=True), flush=True)
            self.assertEqual("BLOCK", result["state"], result)
            assert_removed_baseline(fixture, result["errors"], name)
            self.assertEqual(before, fixture.history())

        for mode in ("VERIFY", "TEST_ONLY", "PRODUCTION"):
            with self.subTest(boundary=mode):
                fixture = self.fresh_repair_fixture()
                if mode == "PRODUCTION":
                    configure_removed_server_batch(fixture, interaction="reader")
                    ManifestAuthorityV5Tests.nonbehavior_plan(fixture)
                    fixture.open_phase("combined-production", "PRODUCTION", fixture.ids)
                else:
                    prepare_removed_server(fixture)
                fixture.push("remove-server", "batch_membership", membership_request(fixture, ("reader-ticket",)))
                change_removed_path(fixture, "mode")
                before = fixture.history()
                result = fixture.preflight("drifted-start", mode, ["A1"])
                print(json.dumps({"mode": mode, "result": result}, sort_keys=True), flush=True)
                self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
                assert_removed_baseline(fixture, result["errors"], "server.py")
                self.assertEqual(before, fixture.history())

        for restored in (False, True):
            with self.subTest(boundary="successive removal", restored=restored):
                fixture = self.fresh_repair_fixture()
                retained = ("reader-ticket", "display-ticket")
                configure_batch(fixture, allowed=(retained, ("reader-ticket",)))
                fixture.initialize()
                fixture.publish_plan("successive-plan", batch_content(fixture, server_behavior=False))
                fixture.open_phase("prior-server-production", "PRODUCTION", ["A2S"])
                first = fixture.push("first-removal", "batch_membership", membership_request(fixture, retained))
                path, _, mode = change_removed_path(fixture, "mode")
                if restored:
                    (fixture.repo / path).chmod(mode)
                before = fixture.history()
                request = membership_request(fixture, ("reader-ticket",), previous=first["id"])
                completed = fixture.selector_cli("run", "append", request={
                    "id": "second-removal", "type": "batch_membership", "data": request,
                })
                result = json.loads(completed.stdout)
                if restored:
                    self.assertEqual(0, completed.returncode, result)
                    self.assertEqual(first, fixture.event("first-removal"))
                    self.assertEqual(request, result["data"])
                    self.assertEqual({"server-ticket": "later-server-ticket", "display-ticket": "later-display-ticket"},
                                     result["data"]["continuations"])
                else:
                    self.assertEqual((1, "BLOCK"), (completed.returncode, result.get("state")), result)
                    assert_removed_baseline(fixture, result["errors"], path)
                    self.assertEqual(before, fixture.history())

        with self.subTest(boundary="remapped fresh grant"):
            fixture = self.fresh_repair_fixture()
            configure_removed_server_batch(fixture, interaction="reader")
            ManifestAuthorityV5Tests.nonbehavior_plan(fixture)
            fixture.open_phase("initial-combined-production", "PRODUCTION", fixture.ids)
            fixture.push("remove-server", "batch_membership", membership_request(fixture, ("reader-ticket",)))
            content = copy.deepcopy(fixture.content)
            content["result_map"]["A1"]["production"] = ["server.py"]
            content["result_map"]["A2S"]["production"] = ["reader.py"]
            fixture.publish_plan("reviewed-remap", content)
            self.assertEqual(fixture.history()["initial_source"], fixture.current())
            before = fixture.history()
            result = fixture.preflight("remapped-production", "PRODUCTION", ["A1"])
            print(json.dumps(result, sort_keys=True), flush=True)
            self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
            self.assertTrue(any("removed" in error and "server.py" in error for error in result["errors"]), result)
            self.assertEqual(before, fixture.history())

    def test_removed_ticket_baselines_preserve_shared_work_and_diagnostics(self):
        with self.subTest(boundary="retained original co-owner"):
            fixture = self.fresh_repair_fixture()
            configure_removed_server_batch(fixture)
            fixture.prepare_plan()
            owners = a1.runtime._v2().contract.initial_owners(fixture.history()["contract"], fixture.content)
            self.assertEqual({"reader-ticket": {"A1"}, "server-ticket": {"A2S"}}, owners[a1.SHARED_TEST])
            initial = fixture.current()
            fixture.open_phase("shared-before-removal", "TEST_ONLY", ["A1"])
            fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
            before = fixture.history()
            with self.assertRaisesRegex((a1.runtime.RuntimeError, ValueError), "removed.*baseline"):
                fixture.push("dirty-shared-removal", "batch_membership",
                             membership_request(fixture, ("reader-ticket",)))
            self.assertEqual(before, fixture.history())
            (fixture.repo / a1.SHARED_TEST).unlink()
            self.assertEqual(initial, fixture.current())
            fixture.push("clean-shared-removal", "batch_membership",
                         membership_request(fixture, ("reader-ticket",)))
            fixture.cycle("retained-shared", ["A1"])
            fixture.final_proofs = {"A1": fixture.event("retained-shared-green-A1")}
            local = fixture.finish_workflow(start="retained-shared-production", prefix="retained-shared-")
            self.assertFalse(local["parent_complete"])
            self.assertEqual({"server-ticket": "later-server-ticket"}, local["continuations"])
            self.assertEqual(a1.PYTHON_SUITE, (fixture.repo / a1.SHARED_TEST).read_text())

        with self.subTest(boundary="broken source and case capture"):
            fixture = self.fresh_repair_fixture()
            prepare_removed_server(fixture)
            fixture.push("remove-server", "batch_membership", membership_request(fixture, ("reader-ticket",)))
            name, _, _ = change_removed_path(fixture, "mode")
            broken = fixture.current()
            before = fixture.history()
            exit_code, shown = removed_baseline_cli(fixture, "run", "show")
            self.assertEqual(0, exit_code)
            self.assertEqual(before, shown)
            command = [a1.PYTHON, "-B", "-c",
                       "from pathlib import Path; assert not Path('server.py').stat().st_mode & 0o100"]
            completed = subprocess.run(command, cwd=fixture.repo, input=b"", capture_output=True,
                                       timeout=15, check=False)
            self.assertEqual(1, completed.returncode)
            self.assertIn(b"AssertionError", completed.stderr)
            self.assertEqual(broken, fixture.current())
            streams = {}
            for channel in ("stdout", "stderr"):
                path = fixture.root / ("removed-baseline-diagnostic-" + channel)
                path.write_bytes(getattr(completed, channel))
                streams[channel] = a1.runtime.reference(path)
            print(json.dumps({"argv": command, "cwd": str(fixture.repo), "exit": completed.returncode,
                              "streams": streams, "broken": broken}, sort_keys=True), flush=True)
            defect = "removed-server-baseline"
            fixture.push("baseline-diagnostic", "failure", {
                "defect": defect, "broken": broken, "command": command,
                "exit": completed.returncode, "output": streams["stderr"],
            })
            request = fixture.failure_intent()
            request.update(id="capture-baseline-diagnostic", defect=defect)
            request["failure"].update(command=command, output=streams["stderr"], inputs=[streams["stdout"]])
            case = request["case"]
            case.update(title="Removed server mode changed", check_id="server",
                        expected_behavior="The removed server stays at its first file mode.",
                        actual_behavior="The removed server became executable.")
            case["origin"]["failure_id"] = "baseline-diagnostic"
            case["evidence_refs"][0]["sha256"] = streams["stderr"]["sha256"]
            captured = fixture.ledger.capture(a1.RUN, fixture.history()["seq"], request)
            self.assertEqual("PASS", captured["state"], captured)
            show_ref = captured["link"]["data"]["show"]
            self.assertTrue(a1.runtime.verify_reference(show_ref))
            case_show = json.loads(Path(show_ref["path"]).read_bytes())
            self.assertEqual((captured["digest"], broken["sha256"]),
                             (case_show["digest"], case_show["record"]["origin"]["broken_source_identity"]))
            self.assertEqual(broken["files"][name], request["failure"]["broken_files"][name]["sha256"])
            self.assertEqual(broken, fixture.event("baseline-diagnostic")["observed_source"])
            self.assertFalse(any(event["type"] in {"proof", "proof_attempt", "start"}
                                 for event in fixture.history()["events"][before["seq"]:]))


    def test_shared_path_removal_requires_applicable_retained_grant(self):
        for drift in ("mode", "bytes", "create", "delete"):
            with self.subTest(drift=drift):
                fixture = self.fresh_repair_fixture()
                shared = "server-note.txt" if drift == "create" else "server.py"
                start = prepare_shared_reader(fixture, shared=shared)
                removal = remove_shared_server(fixture)
                complete_removed_reader(fixture, start, "shared-clean-")
                exit_code, clean = removed_baseline_cli(fixture, "check")
                self.assertEqual((0, "PASS", "ACCEPTED_LOCAL"), (exit_code, clean["state"], clean["lifecycle"]))
                assert_shared_subset(fixture, clean, removal)
                change_shared_path(fixture, shared, drift)
                before = fixture.history()
                executor = a1.runtime._v2().executor
                with patch.object(executor, "run_read_only", wraps=executor.run_read_only) as run:
                    result = fixture.request_proof("shared-drift-green", "A1", start)
                print(json.dumps({"drift": drift, "result": result, "launches": run.call_count},
                                 sort_keys=True), flush=True)
                if result["state"] == "PASS":
                    self.assertEqual(1, run.call_count)
                    complete_removed_reader(fixture, start, "shared-drift-", green=result["proof"])
                else:
                    self.assertEqual("BLOCK", result["state"], result)
                    self.assertEqual(0, run.call_count)
                    self.assertNotIn("receipt", result)
                    self.assertEqual(before, fixture.history())
                    assert_shared_grant_refusal(fixture, result["errors"], shared)
                exit_code, current = removed_baseline_cli(fixture, "check")
                self.assertEqual((1, "BLOCK"), (exit_code, current["state"]),
                                 f"Public check accepted shared {drift} under the removed ticket's grant")
                assert_shared_grant_refusal(fixture, current["errors"], shared)

    def test_shared_path_removal_preserves_authority_chronology(self):
        for consumer in ("current proof", "new aggregate", "public readiness"):
            with self.subTest(consumer=consumer):
                fixture = self.fresh_repair_fixture()
                start = prepare_shared_reader(fixture)
                shared = "server.py"
                _, mode = change_shared_path(fixture, shared, "mode")
                proof = fixture.proof("shared-pre-removal", "A1", start)
                earlier = fixture.history()
                changed = fixture.current()
                (fixture.repo / shared).chmod(mode)
                removal = remove_shared_server(fixture)
                self.assertEqual(fixture.current()["sha256"], removal["data"]["candidate"])
                change_shared_path(fixture, shared, "mode")
                self.assertEqual((changed, fixture.plan), (fixture.current(), proof["data"]["plan"]))
                self.assertEqual(changed, proof["observed_source"])
                self.assertEqual([], fixture.proof_errors(proof, "GREEN", state=earlier))

                if consumer == "current proof":
                    errors = fixture.proof_errors(proof, "GREEN")
                    print(json.dumps({"proof": proof["id"], "prior_prefix": earlier["sha256"],
                                      "current": fixture.current(), "errors": errors},
                                     sort_keys=True), flush=True)
                    assert_shared_grant_refusal(fixture, errors, shared)
                    continue

                before = fixture.history()
                aggregate = fixture.coverage("after-shared-removal-aggregate", start, {"A1": proof})
                print(json.dumps({"consumer": consumer, "aggregate": aggregate}, sort_keys=True), flush=True)
                if consumer == "new aggregate":
                    self.assertEqual("BLOCK", aggregate["state"], aggregate)
                elif aggregate["state"] == "PASS":
                    complete_removed_reader(fixture, start, "reintroduced-", green=proof)
                    exit_code, result = removed_baseline_cli(fixture, "check")
                    self.assertEqual((1, "BLOCK"), (exit_code, result["state"]),
                                     "Public check treated removal as an unchanged shared observation")
                else:
                    self.assertEqual("BLOCK", aggregate["state"], aggregate)
                if aggregate["state"] == "BLOCK":
                    assert_shared_grant_refusal(fixture, aggregate["errors"], shared)
                    self.assertEqual(before, fixture.history())
                    if consumer == "public readiness":
                        exit_code, result = removed_baseline_cli(fixture, "check")
                        self.assertEqual((1, "BLOCK"), (exit_code, result["state"]))
                        assert_shared_grant_refusal(fixture, result["errors"], shared)

        for boundary in ("VERIFY", "TEST_ONLY", "PRODUCTION", "after diagnostic", "after remap", "second removal"):
            with self.subTest(boundary=boundary):
                fixture = self.fresh_repair_fixture()
                shared = "server.py"
                third = boundary in {"after remap", "second removal"}
                if boundary == "PRODUCTION" or third:
                    prepare_shared_plan(fixture, nonbehavior=True, third_ticket=third)
                    shared_production(fixture, "server-only-production", ["A2S"],
                                      [shared_path_row(fixture, shared, "server-ticket")])
                else:
                    prepare_shared_reader(fixture, reader_surface=boundary == "VERIFY")
                removal = remove_shared_server(fixture, third_ticket=third)
                change_shared_path(fixture, shared, "mode")

                if boundary == "after diagnostic":
                    broken = fixture.current()
                    _, captured = capture_shared_diagnostic(fixture)
                    lookup = fixture.consult_mapped("shared-diagnostic-lookup", "repair",
                                                    broken["sha256"])["consultation"]
                    self.assertLess(captured["link"]["seq"], lookup["seq"])
                    self.assertIn(captured["digest"], lookup["data"]["shown"])
                    decisions = [event["data"] for event in fixture.history()["events"][lookup["seq"]:]
                                 if event["type"] == "case_decision"
                                 and event["data"]["consultation"] == lookup["id"]
                                 and event["data"]["digest"] == captured["digest"]]
                    self.assertEqual([("APPLIES", ["reader"])],
                                     [(row["applicability"], row["checks"]) for row in decisions])
                    self.assertEqual(broken, fixture.current())
                if boundary == "after remap":
                    remapped = copy.deepcopy(fixture.content)
                    remapped["result_map"]["A2W"]["production"].append(shared)
                    fixture.publish_plan("reviewed-shared-remap", remapped)
                before = fixture.history()
                if boundary == "second removal":
                    request = membership_request(fixture, ("reader-ticket",), previous=removal["id"])
                    completed = fixture.selector_cli("run", "append", request={
                        "id": "later-display-removal", "type": "batch_membership", "data": request,
                    })
                    result = json.loads(completed.stdout)
                    self.assertEqual((1, "BLOCK"), (completed.returncode, result.get("state")), result)
                else:
                    mode = {"after remap": "PRODUCTION", "after diagnostic": "VERIFY"}.get(boundary, boundary)
                    options = {}
                    if boundary == "VERIFY":
                        options["observe_manifest"] = [manifest("features/reader-note.md", "reader-ticket",
                                                                "production", None)]
                    elif mode == "PRODUCTION":
                        options["write_manifest"] = [shared_path_row(fixture, shared, "reader-ticket")]
                    result = fixture.preflight("new-retained-start", mode, ["A1"], **options)
                    print(json.dumps({"boundary": boundary, "result": result}, sort_keys=True), flush=True)
                    self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
                assert_shared_grant_refusal(fixture, result["errors"], shared)
                self.assertEqual(before, fixture.history())

    def test_shared_path_removal_allows_lawful_carry_and_recovery(self):
        for grant in ("explicit", "implicit", "old combined"):
            with self.subTest(grant=grant):
                fixture = self.fresh_repair_fixture()
                prepare_shared_plan(fixture, later_reader_check=True)
                if grant != "old combined":
                    removal = remove_shared_server(fixture)
                open_shared_reader_test(fixture)
                selection = ["A1", "A2S"] if grant == "old combined" else ["A1"]
                rows = None if grant == "implicit" else [
                    shared_path_row(fixture, "reader.py", "reader-ticket"),
                    shared_path_row(fixture, "server.py", "reader-ticket"),
                ]
                own = shared_production(fixture, "shared-owner-production", selection, rows)
                self.assertEqual(["reader.py", "server.py"], own["data"]["write_scope"])
                if rows is not None:
                    self.assertEqual(rows, own["data"]["write_manifest"])
                fixture.write_files({"reader.py": a1.WORKING["reader.py"]})
                if grant == "old combined":
                    removal = remove_shared_server(fixture)
                change_shared_path(fixture, "server.py", "bytes")
                changed = fixture.current()
                initial_green = fixture.proof("authorized-shared-green", "A1", own["id"])

                later = shared_production(fixture, "reader-only-later-production", ["A3"],
                                          [shared_path_row(fixture, "reader.py", "reader-ticket")])
                self.assertEqual(["reader.py"], later["data"]["write_scope"])
                check = fixture.command_check("later-reader-check", later["id"], "narrator", [
                    a1.PYTHON, "-B", "-c", "from reader import read; assert read(['b', 'a']) == ['a', 'b']",
                ])
                self.assertEqual("PASS", check["state"], check)
                local, _ = complete_removed_reader(fixture, later["id"], "carried-shared-")
                assert_shared_subset(fixture, local, removal)
                self.assertEqual(changed, local["candidate"])
                self.assertEqual(own, fixture.event(own["id"]))
                self.assertEqual(initial_green, fixture.event(initial_green["id"]))

        with self.subTest(boundary="diagnostic and restoration"):
            fixture = self.fresh_repair_fixture()
            start = prepare_shared_reader(fixture)
            removal = remove_shared_server(fixture)
            baseline = fixture.current()
            _, mode = change_shared_path(fixture, "server.py", "mode")
            before = fixture.history()
            exit_code, shown = removed_baseline_cli(fixture, "run", "show")
            self.assertEqual((0, before), (exit_code, shown))
            failure, captured = capture_shared_diagnostic(fixture)
            self.assertFalse(any(event["type"] in {"start", "proof", "proof_attempt"}
                                 for event in fixture.history()["events"][before["seq"]:]))
            (fixture.repo / "server.py").chmod(mode)
            self.assertEqual(baseline, fixture.current())
            self.assertEqual("BLOCK", fixture.ledger.check(a1.RUN)["state"])
            before_recovery = fixture.history()["seq"]
            local, proofs = complete_removed_reader(fixture, start, "shared-restored-")
            assert_shared_subset(fixture, local, removal)
            self.assertTrue(all(proof["seq"] > before_recovery for proof in proofs))
            self.assertEqual(failure, fixture.event(failure["id"]))
            link = captured["link"]
            self.assertEqual(link, fixture.event(link["id"]))
            self.assertEqual(captured["digest"], link["data"]["digest"])
            self.assertTrue(any(event["type"] == "case_decision"
                                and event["data"]["digest"] == captured["digest"]
                                and event["data"]["checks"] == ["reader"]
                                for event in fixture.history()["events"]))


    def test_shared_path_carry_requires_continuous_retained_mapping(self):
        shared = "server.py"
        reader = "reader-ticket"
        command = [a1.PYTHON, "-B", "-c",
                   "from reader import read; from server import status; "
                   "assert read([]) == []; assert status('POST') == 500"]

        def prepare():
            fixture = self.fresh_repair_fixture()
            prepare_shared_plan(fixture, nonbehavior=True)
            baseline = fixture.current()
            original = copy.deepcopy(fixture.content)
            remove_shared_server(fixture)
            start = shared_production(fixture, "original-shared-owner", ["A1"],
                                      [shared_path_row(fixture, shared, reader)])
            self.assertEqual([shared], start["data"]["write_scope"])
            return fixture, baseline, original, start

        def check(fixture, start, label):
            source = fixture.current()
            result = fixture.command_check(label, start["id"], "reader", command)
            self.assertEqual("PASS", result["state"], result)
            proof = result["proof"]
            receipt, _ = fixture.retain_native(label, proof["data"]["output"])
            self.assertEqual((0, source["sha256"], start["id"]),
                             (receipt["exit"], receipt["candidate"], receipt["start"]))
            self.assertEqual(source, proof["observed_source"])
            return proof

        def drop_mapping(fixture, original):
            content = copy.deepcopy(original)
            content["result_map"]["A1"]["production"].remove(shared)
            return fixture.publish_plan("drop-original-shared-mapping", content)

        def regain_mapping(fixture, original, *, exact=False):
            content = copy.deepcopy(original)
            if not exact:
                content["decision_reason"] = "Restore the reviewed reader mapping with the source held fixed."
            return fixture.publish_plan("regain-original-shared-mapping", content)

        def observe_gap(fixture, original, *, verify=False, exact=False):
            changed = fixture.current()
            lost = drop_mapping(fixture, original)
            if verify:
                prior = fixture.history()
                result = fixture.preflight("verify-while-mapping-absent", "VERIFY", ["A1"])
                print(json.dumps({"boundary": "missing map", "result": result}, sort_keys=True), flush=True)
                self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
                assert_removed_baseline(fixture, result["errors"], shared)
                self.assertEqual(prior, fixture.history())
            regained = regain_mapping(fixture, original, exact=exact)
            self.assertEqual(changed, lost["observed_source"])
            self.assertEqual(changed, regained["observed_source"])
            self.assertEqual(changed, fixture.current())
            return lost, regained

        def start_request(fixture, name, path):
            request = {"acceptance": ["A1"], "write_manifest": [shared_path_row(fixture, path, reader)]}
            before = fixture.history()
            current = fixture.current()
            result = fixture.preflight(name, "PRODUCTION", **request)
            print(json.dumps({"boundary": name, "request": request, "result": result, "candidate": current,
                              "seq_before": before["seq"], "seq_after": fixture.history()["seq"]},
                             sort_keys=True), flush=True)
            return before, current, result

        def assert_path_hold(errors, *, mapping=False):
            reasons = [error for error in errors if shared in error and "shared" in error.casefold()]
            if mapping:
                self.assertTrue(any("mapping" in error.casefold() for error in reasons), errors)
            else:
                self.assertTrue(any("mapping" in error.casefold() or "grant" in error.casefold()
                                    for error in reasons), errors)

        for boundary in ("after VERIFY", "back-to-back plans", "proposed shared grant", "current proof"):
            with self.subTest(boundary=boundary):
                fixture, _, original, owner = prepare()
                change_shared_path(fixture, shared, "mode")
                proof = check(fixture, owner, "lawful-pre-gap-check")
                historical = fixture.history()
                changed = fixture.current()
                lost, regained = observe_gap(fixture, original, verify=boundary == "after VERIFY",
                                              exact=boundary == "current proof")
                self.assertLess(lost["seq"], regained["seq"])
                if boundary == "current proof":
                    self.assertEqual((changed, fixture.plan), (proof["observed_source"], proof["data"]["plan"]))
                    self.assertEqual([], fixture.proof_errors(proof, state=historical))
                    before = fixture.history()
                    errors = fixture.proof_errors(proof)
                    print(json.dumps({"boundary": boundary, "proof": proof["id"], "proof_sha256": proof["sha256"],
                                      "earlier_prefix": historical["sha256"], "source": changed, "errors": errors},
                                     sort_keys=True), flush=True)
                    assert_path_hold(errors, mapping=True)
                else:
                    path = shared if boundary == "proposed shared grant" else "reader.py"
                    before, current, result = start_request(fixture, "production-after-mapping-gap", path)
                    if result["state"] == "PASS":
                        self.assertEqual((before["seq"] + 1, current, [path]),
                                         (result["start"]["seq"], result["start"]["data"]["candidate"],
                                          result["start"]["data"]["write_scope"]))
                    self.assertEqual(("BLOCK", None), (result["state"], result["start"]),
                                     "A recorded shared mapping gap authorized a fresh production start")
                    assert_path_hold(result["errors"], mapping=True)
                    exit_code, readiness = removed_baseline_cli(fixture, "check")
                    self.assertEqual((1, "BLOCK", current), (exit_code, readiness["state"], readiness["candidate"]))
                    assert_path_hold(readiness["errors"], mapping=True)
                self.assertEqual(before, fixture.history())

        for recovery in ("near", "exact"):
            with self.subTest(recovery=recovery):
                fixture, baseline, original, owner = prepare()
                original_bytes, original_mode = change_shared_path(fixture, shared, "mode")
                proof = check(fixture, owner, "pre-recovery-check")
                lost, regained = observe_gap(fixture, original)
                path = fixture.repo / shared
                # These disposable writes model separate restoration authority.
                path.chmod(original_mode)
                if recovery == "near":
                    path.write_bytes(original_bytes + b"\n# Synthetic near restoration.\n")
                    candidate = fixture.current()
                    self.assertEqual(baseline["modes"], candidate["modes"])
                    self.assertNotEqual(baseline["files"][shared], candidate["files"][shared])
                    before, _, result = start_request(fixture, "production-after-near-restoration", "reader.py")
                    self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
                    assert_path_hold(result["errors"])
                    self.assertEqual(before, fixture.history())
                else:
                    self.assertEqual(baseline, fixture.current())
                    start = shared_production(fixture, "production-after-exact-restoration", ["A1"],
                                              [shared_path_row(fixture, "reader.py", reader)])
                    renewed = check(fixture, start, "restored-shared-check")
                    self.assertGreater(renewed["seq"], regained["seq"])
                    self.assertEqual([], fixture.proof_errors(renewed))
                for event in (proof, lost, regained):
                    self.assertEqual(event, fixture.event(event["id"]))

        with self.subTest(boundary="changed incoming tuple"):
            fixture, baseline, original, _ = prepare()
            lost = drop_mapping(fixture, original)
            self.assertEqual(baseline, lost["observed_source"])
            change_shared_path(fixture, shared, "mode")
            regained = regain_mapping(fixture, original)
            self.assertEqual(fixture.current(), regained["observed_source"])
            before, _, result = start_request(fixture, "production-after-changed-remap", "reader.py")
            self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
            assert_path_hold(result["errors"])
            self.assertEqual(before, fixture.history())

        for boundary in ("continuous mapping", "retirement after observation", "retirement before observation"):
            with self.subTest(boundary=boundary):
                fixture, _, original, owner = prepare()
                if boundary == "retirement before observation":
                    fixture.retire(owner["id"])
                    change_shared_path(fixture, shared, "mode")
                    before, _, result = start_request(fixture, "production-after-retired-change", "reader.py")
                    self.assertEqual(("BLOCK", None), (result["state"], result["start"]), result)
                    assert_shared_grant_refusal(fixture, result["errors"], shared)
                    self.assertEqual(before, fixture.history())
                    continue
                change_shared_path(fixture, shared, "mode")
                proof = check(fixture, owner, "observed-while-owner-live")
                current = fixture.current()
                historical = fixture.history()
                if boundary == "retirement after observation":
                    fixture.retire(owner["id"])
                    self.assertEqual([], fixture.proof_errors(proof, state=historical))
                    errors = fixture.proof_errors(proof)
                    self.assertTrue(any("withdrawn" in error for error in errors), errors)
                else:
                    original["decision_reason"] = "Review the same continuing shared path mapping."
                    plan = fixture.publish_plan("keep-original-shared-mapping", original)
                    self.assertEqual(current, plan["observed_source"])
                later = shared_production(fixture, "reader-only-lawful-carry", ["A1"],
                                          [shared_path_row(fixture, "reader.py", reader)])
                self.assertEqual(["reader.py"], later["data"]["write_scope"])
                renewed = check(fixture, later, "carried-shared-check")
                self.assertEqual(current, renewed["observed_source"])
                self.assertEqual([], fixture.proof_errors(renewed))
                self.assertEqual(owner, fixture.event(owner["id"]))

    def test_shared_transition_requires_original_phase_support(self):
        runtime = a1.runtime._v2()
        shared = "server.py"
        reader = "reader-ticket"
        grant_error = "shared path change lacks an applicable retained original-owner grant: server.py"

        def prepare(scenario):
            fixture = self.fresh_repair_fixture()
            behavior = scenario == "original RED"
            prepare_shared_plan(fixture, nonbehavior=not behavior, later_reader_check=behavior)
            plan = fixture.event("shared-path-plan")
            if scenario not in {"new relevant decision", "original RED"}:
                plan = bind_shared_support_decision(fixture)
            if scenario == "unselected review":
                fixture.support("selected-shared-review")
            elif scenario == "unrelated decision":
                add_unrelated_shared_decision(fixture)
            if behavior:
                open_shared_reader_test(fixture)
            baseline = fixture.current()
            removal = remove_shared_server(fixture)
            prefix = fixture.history()
            owner = shared_production(fixture, "original-supported-grant", ["A1"],
                                      [shared_path_row(fixture, shared, reader)])
            self.assertEqual((baseline, prefix["sha256"], plan["data"]["revision"], [shared]),
                             (owner["data"]["candidate"], owner["data"]["prefix"],
                              owner["data"]["plan"], owner["data"]["write_scope"]))
            self.assertEqual([reader], removal["data"]["members"])
            return fixture, baseline, plan, owner, prefix

        def record_observation(fixture):
            source = fixture.current()
            content = copy.deepcopy(fixture.content)
            content["decision_reason"] = "Review the observed source with the original shared mapping retained."
            observation = fixture.publish_plan("observe-shared-support", content)
            self.assertEqual(source, observation["observed_source"])
            owners = runtime.contract.initial_owners(fixture.history()["contract"], content)
            self.assertEqual({"reader-ticket": {"A1"}, "server-ticket": {"A2S"}}, owners[shared])
            return observation

        def reader_start(fixture, acceptance="A1"):
            return fixture.preflight("later-reader-only", "PRODUCTION", [acceptance],
                                     write_manifest=[shared_path_row(fixture, "reader.py", reader)])

        for scenario in ("selected review withdrawal", "selected review supersession",
                         "changed relevant revision", "new relevant decision", "original RED"):
            with self.subTest(scenario=scenario):
                fixture, baseline, plan, owner, prefix = prepare(scenario)
                issued = runtime.decision_witnesses(prefix, plan, ["A1"])
                if scenario.startswith("selected review"):
                    kind = "withdrawal" if scenario.endswith("withdrawal") else "supersession"
                    retired = fixture.retire("shared-contract-review", kind)
                    self.assertIn(retired["data"]["target"], {event["id"] for event in issued})
                    support = fixture.support("replacement-shared-review")
                    self.assertGreater(support["seq"], retired["seq"])
                elif scenario == "original RED":
                    red = fixture.event("shared-reader-red")
                    self.assertLess(red["seq"], owner["seq"])
                    self.assertEqual([], fixture.proof_errors(red, "RED", state=prefix))
                    fixture.retain_native("original-selected-red", red["data"]["output"])
                    support = fixture.retire(red["id"])
                else:
                    fixture.decision("relevant-shared-contract", "Select the revised synthetic reader rule.",
                                     behavior="A1")
                    support = fixture.event("relevant-shared-contract-review")
                change_shared_path(fixture, shared, "mode")
                candidate = fixture.current()
                self.assertEqual(baseline["files"], candidate["files"])
                self.assertNotEqual(baseline["modes"][shared], candidate["modes"][shared])
                current_support = runtime.decision_witnesses(fixture.history(), plan, ["A1"])
                observation = record_observation(fixture)
                self.assertLess(owner["seq"], support["seq"])
                self.assertLess(support["seq"], observation["seq"])
                before = fixture.history()
                item, check = ("A3", "narrator") if scenario == "original RED" else ("A1", "reader")
                result = reader_start(fixture, item)
                print(json.dumps({"scenario": scenario, "grant": owner["id"], "observation": observation["id"],
                                  "issued_support": [event["id"] for event in issued],
                                  "current_support": [event["id"] for event in current_support],
                                  "support_boundary": support["id"], "source": candidate["sha256"],
                                  "seq_before": before["seq"], "seq_after": fixture.history()["seq"],
                                  "result": result}, sort_keys=True), flush=True)
                if result["state"] == "PASS":
                    start = result["start"]
                    self.assertEqual((before["seq"] + 1, candidate, ["reader.py"]),
                                     (start["seq"], start["data"]["candidate"], start["data"]["write_scope"]))
                    proof = check_shared_status(fixture, start, "later-reader-check", check=check)
                    self.assertEqual("PASS", proof["state"], proof)
                else:
                    self.assertIn(grant_error, result["errors"], result)
                    self.assertEqual(before, fixture.history())
                    self.assertEqual(candidate, fixture.current())
                self.assertEqual(("BLOCK", None), (result["state"], result["start"]),
                                 "A changed shared value gained a start after its selected support expired")

        with self.subTest(scenario="native launch after selected review withdrawal"):
            fixture, _, plan, owner, prefix = prepare("selected review withdrawal")
            issued = runtime.decision_witnesses(prefix, plan, ["A1"])
            retired = fixture.retire("shared-contract-review")
            replacement = fixture.support("replacement-shared-review")
            self.assertIn(retired["data"]["target"], {event["id"] for event in issued})
            self.assertEqual(issued[-1]["data"]["revision"], replacement["data"]["revision"])
            change_shared_path(fixture, shared, "mode")
            candidate = fixture.current()
            before = fixture.history()
            executor = runtime.executor
            with patch.object(executor, "run_read_only", wraps=executor.run_read_only) as run:
                result = check_shared_status(fixture, owner, "check-after-withdrawal", check="reader")
            after = fixture.history()
            print(json.dumps({"scenario": "native launch", "source": candidate["sha256"],
                              "selected": retired["data"]["target"], "replacement": replacement["id"],
                              "launches": run.call_count, "seq_before": before["seq"],
                              "seq_after": after["seq"], "result": result}, sort_keys=True), flush=True)
            if result["state"] == "PASS":
                self.assertEqual((1, before["seq"] + 1), (run.call_count, result["proof"]["seq"]))
            else:
                self.assertIn(grant_error, result["errors"], result)
                self.assertEqual(0, run.call_count)
                self.assertNotIn("receipt", result)
                self.assertNotIn("proof", result)
                self.assertEqual(before, after)
            self.assertEqual(candidate, fixture.current())
            self.assertEqual("BLOCK", result["state"], "A shared change with expired support launched native proof")

        for scenario in ("retirement after observation", "unselected review", "unrelated decision"):
            with self.subTest(control=scenario):
                fixture, _, plan, owner, prefix = prepare(scenario)
                selected = {event["id"] for event in runtime.decision_witnesses(prefix, plan, ["A1"])}
                if scenario == "retirement after observation":
                    change_shared_path(fixture, shared, "mode")
                    result = check_shared_status(fixture, owner, "observed-with-live-support", check="reader")
                    self.assertEqual("PASS", result["state"], result)
                    earlier = fixture.history()
                    fixture.retire("shared-contract-review")
                    fixture.support("replacement-shared-review")
                    self.assertIn("shared-contract-review", selected)
                    self.assertEqual([], fixture.proof_errors(result["proof"], state=earlier))
                else:
                    target = "shared-contract-review" if scenario == "unselected review" else "unrelated-shared-review"
                    self.assertNotIn(target, selected)
                    fixture.retire(target)
                    change_shared_path(fixture, shared, "mode")
                observation = record_observation(fixture)
                later = reader_start(fixture)
                self.assertEqual("PASS", later["state"], later)
                self.assertEqual(observation["observed_source"], later["start"]["data"]["candidate"])
                proof = check_shared_status(fixture, later["start"], "lawful-reader-check", check="reader")
                self.assertEqual("PASS", proof["state"], proof)

        for restore in ("partial", "exact"):
            with self.subTest(recovery=restore):
                fixture, baseline, _, owner, _ = prepare("selected review withdrawal")
                fixture.retire("shared-contract-review")
                fixture.support("replacement-shared-review")
                original, mode = change_shared_path(fixture, shared, "mode")
                observed = record_observation(fixture)
                self.assertNotEqual(baseline, observed["observed_source"])
                path = fixture.repo / shared
                path.chmod(mode)
                if restore == "partial":
                    path.write_bytes(original + b"\n# Disposable partial restoration.\n")
                    self.assertEqual(baseline["modes"], fixture.current()["modes"])
                    self.assertNotEqual(baseline["files"][shared], fixture.current()["files"][shared])
                    before = fixture.history()
                    later = reader_start(fixture)
                    self.assertEqual(("BLOCK", None), (later["state"], later["start"]), later)
                    self.assertIn(grant_error, later["errors"], later)
                    self.assertEqual(before, fixture.history())
                else:
                    self.assertEqual(baseline, fixture.current())
                    later = reader_start(fixture)
                    self.assertEqual("PASS", later["state"], later)
                    proof = check_shared_status(fixture, later["start"], "restored-reader-check", check="reader")
                    self.assertEqual("PASS", proof["state"], proof)
                self.assertEqual(owner, fixture.event(owner["id"]))
                self.assertEqual(observed, fixture.event(observed["id"]))

    def test_unscoped_check_consumption_keeps_original_global_decision_support(self):
        runtime = a1.runtime._v2()
        for scenario in ("review-backed", "RED-backed", "unselected review", "unrelated decision"):
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                proof_backed = scenario == "RED-backed"
                prepare_shared_plan(fixture, nonbehavior=not proof_backed, later_reader_check=proof_backed)
                plan = bind_shared_support_decision(fixture, strategy="TDD_RED" if proof_backed else "REVIEW")
                self.assertEqual(["status-contract"], plan["data"]["content"]["decisions"])
                if proof_backed:
                    open_shared_reader_test(fixture)
                elif scenario == "unselected review":
                    fixture.support("selected-shared-review")
                elif scenario == "unrelated decision":
                    add_unrelated_shared_decision(fixture)
                baseline = fixture.current()
                remove_shared_server(fixture)
                prefix = fixture.history()
                owner = shared_production(fixture, "original-supported-grant", ["A1"],
                                          [shared_path_row(fixture, "server.py", "reader-ticket")])
                issued = runtime.decision_witnesses(prefix, plan, [])
                if proof_backed:
                    self.assertEqual(["shared-contract"], [event["id"] for event in issued])
                    red = fixture.event("shared-reader-red")
                    self.assertEqual(("A1", "RED", "INTENDED_ASSERTION_FAILURE", baseline["sha256"], fixture.plan),
                                     (red["data"]["acceptance"], red["data"]["phase"], red["data"]["outcome"],
                                      red["data"]["candidate"], red["data"]["plan"]))
                    self.assertLess(red["seq"], owner["seq"])
                    self.assertEqual([], fixture.proof_errors(red, "RED", state=prefix))
                    fixture.retain_native("original-global-decision-red", red["data"]["output"])
                elif scenario == "review-backed":
                    change_shared_path(fixture, "server.py", "mode")
                native = check_shared_status(fixture, owner, "original-unscoped-check")
                self.assertEqual("PASS", native["state"], native)
                proof = native["proof"]
                candidate = fixture.current()
                self.assertEqual((candidate, fixture.plan, plan["id"]),
                                 (proof["observed_source"], proof["data"]["plan"], proof["data"]["plan_event"]))
                if proof_backed:
                    self.assertEqual(baseline, candidate)
                historical = fixture.history()
                ref = proof["data"]["output"]
                receipt, streams = fixture.read_receipt(ref)
                if scenario in {"review-backed", "RED-backed"}:
                    target = red["id"] if proof_backed else "shared-contract-review"
                    if not proof_backed:
                        self.assertIn(target, {event["id"] for event in issued})
                    withdrawn = fixture.retire(target)
                    replacement = fixture.support("replacement-shared-review")
                    self.assertLess(proof["seq"], withdrawn["seq"])
                    self.assertLess(withdrawn["seq"], replacement["seq"])
                    self.assertEqual(issued[0]["data"]["revision"], replacement["data"]["revision"])
                else:
                    target = "shared-contract-review" if scenario == "unselected review" else "unrelated-shared-review"
                    self.assertNotIn(target, {event["id"] for event in issued})
                    fixture.retire(target)
                before = fixture.history()
                self.assertEqual([], fixture.proof_errors(proof, state=historical))
                errors = fixture.proof_errors(proof)
                self.assertEqual(before, fixture.history())
                self.assertEqual(candidate, fixture.current())
                self.assertEqual(proof, fixture.event(proof["id"]))
                self.assertEqual((receipt, streams), fixture.read_receipt(ref))
                print(json.dumps({"scenario": scenario, "proof": proof["id"], "proof_sha256": proof["sha256"],
                                  "candidate": candidate["sha256"], "plan": fixture.plan, "retired": target,
                                  "historical_prefix": historical["sha256"], "current_prefix": before["sha256"],
                                  "errors": errors}, sort_keys=True), flush=True)
                if scenario in {"review-backed", "RED-backed"}:
                    verify = fixture.preflight("replacement-verification", "VERIFY", ["A1"])
                    self.assertEqual("PASS", verify["state"], verify)
                    renewed = check_shared_status(fixture, verify["start"], "renewed-unscoped-check")
                    self.assertEqual("PASS", renewed["state"], renewed)
                    self.assertEqual([], fixture.proof_errors(renewed["proof"]))
                    self.assertIn("selected proof dependency was withdrawn or superseded", errors,
                                  "Current unscoped CHECK consumption ignored the retired original support")
                else:
                    self.assertEqual([], errors)

    def test_shared_transition_replay_does_not_repeat_full_red_validation(self):
        runtime = a1.runtime._v2()
        prepare_shared_plan(self, later_reader_check=True)
        open_shared_reader_test(self)
        red = self.event("shared-reader-red")
        self.retain_native("long-history-original-red", red["data"]["output"])
        baseline = self.current()
        remove_shared_server(self)
        owner = shared_production(self, "long-history-owner", ["A1"],
                                  [shared_path_row(self, "server.py", "reader-ticket")])
        self.assertEqual(("INTENDED_ASSERTION_FAILURE", baseline["sha256"], self.plan),
                         (red["data"]["outcome"], red["data"]["candidate"], red["data"]["plan"]))
        self.assertLess(red["seq"], owner["seq"])
        shared = self.repo / "server.py"
        original = shared.read_bytes()
        observations = []
        for step in range(1, 13):
            shared.write_bytes(original + f"\n# Disposable observation {step}.\n".encode())
            source = self.current()
            result = check_shared_status(self, owner, f"long-history-check-{step}")
            self.assertEqual("PASS", result["state"], result)
            proof = result["proof"]
            self.assertEqual((source, baseline["modes"]), (proof["observed_source"], source["modes"]))
            observations.append((proof["seq"], source["files"]["server.py"]))
        sequences, values = zip(*observations)
        self.assertEqual(tuple(sorted(set(sequences))), sequences)
        self.assertGreater(sequences[0], owner["seq"])
        self.assertEqual(12, len(set(values)))
        self.assertNotIn(baseline["files"]["server.py"], values)
        before = self.history()
        candidate = self.current()
        with (
            patch.object(runtime, "_validate_removed_chronology", wraps=runtime._validate_removed_chronology) as replay,
            patch.object(runtime, "_validate_proof", wraps=runtime._validate_proof) as full_proof,
        ):
            runtime._validate_removed_baselines(before, candidate)
        self.assertEqual((1, 0), (replay.call_count, full_proof.call_count))
        self.assertEqual(before, self.history())
        self.assertEqual(candidate, self.current())
        self.assertEqual(red, self.event(red["id"]))
        print(json.dumps({"observations": observations, "prefix": before["sha256"],
                          "chronology_calls": replay.call_count, "full_proof_calls": full_proof.call_count},
                         sort_keys=True), flush=True)

    def capture_shared_check(self, start, label):
        runtime = a1.runtime._v2()
        evidence = self.db.parent / "evidence"

        def evidence_inventory():
            return {str(path.relative_to(evidence)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in evidence.rglob("*") if path.is_file()}

        before = self.history()
        candidate = self.current()
        files = evidence_inventory()
        with patch.object(runtime.executor, "run_read_only", wraps=runtime.executor.run_read_only) as launch:
            result = check_shared_status(self, start, label)
        after = self.history()
        current_files = evidence_inventory()
        facts = {
            "label": label, "result": result, "native_launches": launch.call_count,
            "candidate": candidate, "source_unchanged": candidate == self.current(),
            "before_prefix": before["sha256"], "after_prefix": after["sha256"],
            "ledger_unchanged": before == after,
            "appended": [(event["type"], event["id"]) for event in after["events"][before["seq"]:]],
            "evidence_unchanged": files == current_files,
            "new_evidence": sorted(current_files.keys() - files.keys()),
        }
        print(json.dumps(facts, sort_keys=True), flush=True)
        return facts

    def assert_shared_check_issued(self, facts):
        result = facts["result"]
        self.assertEqual(("PASS", 1, True),
                         (result["state"], facts["native_launches"], facts["source_unchanged"]), facts)
        proof = result["proof"]
        self.assertEqual([("proof", proof["id"])], facts["appended"])
        self.assertEqual(proof["observed_source"], facts["candidate"])
        return proof

    def assert_shared_check_blocked(self, facts, error):
        result = facts["result"]
        self.assertEqual(("BLOCK", 0, True, True, True, []),
                         (result["state"], facts["native_launches"], facts["source_unchanged"],
                          facts["ledger_unchanged"], facts["evidence_unchanged"], facts["appended"]), facts)
        self.assertNotIn("receipt", result)
        self.assertNotIn("proof", result)
        self.assertIn(error, result["errors"])

    def test_cross_acceptance_red_support_preserves_phase_selection(self):
        runtime = a1.runtime._v2()
        grant_error = "shared path change lacks an applicable retained original-owner grant: server.py"
        retired_error = "selected proof dependency was withdrawn or superseded"
        for retire_red in (False, True):
            with self.subTest(retire_red=retire_red):
                fixture = self.fresh_repair_fixture()
                prepare_shared_plan(fixture, later_reader_check=True)
                fixture.decision("scope-global-decision", "Use the original synthetic reader RED.",
                                 behavior="A1", strategy="TDD_RED")
                global_decision = fixture.event("scope-global-decision")
                content = copy.deepcopy(fixture.content)
                content["decisions"] = [global_decision["data"]["lineage"]]
                content["result_map"]["A3"]["production"].append("server.py")
                plan = fixture.publish_plan("cross-acceptance-plan", content)
                open_shared_reader_test(fixture)
                red = fixture.event("shared-reader-red")
                red_receipt, red_streams = fixture.retain_native("scope-original-reader-red", red["data"]["output"])
                self.assertEqual(("A1", "RED", "INTENDED_ASSERTION_FAILURE", 1),
                                 (red["data"]["acceptance"], red["data"]["phase"],
                                  red["data"]["outcome"], red_receipt["exit"]))
                self.assertIn(b"AssertionError", red_streams)
                local = dict(global_decision["data"], lineage="a1-only-contract", strategy="REVIEW",
                             choice="Record a later synthetic decision specific to A1.")
                del local["revision"]
                local_decision = fixture.push("a1-only-decision", "decision", dict(local, revision=a1.runtime.digest(local)))
                remove_shared_server(fixture)
                admission = fixture.history()
                for selection in ([], ["A3"]):
                    self.assertEqual([global_decision], runtime.decision_witnesses(admission, plan, selection))
                self.assertEqual([], fixture.proof_errors(red, "RED", admission))
                start = shared_production(fixture, "a3-production", ["A3"],
                                          [shared_path_row(fixture, "server.py", "reader-ticket")])
                self.assertEqual((["A3"], ["server.py"], admission["sha256"], red["data"]["candidate"]),
                                 (start["data"]["acceptance"], start["data"]["write_scope"],
                                  start["previous_sha256"], start["data"]["candidate"]["sha256"]))
                self.assertLess(red["seq"], local_decision["seq"])
                self.assertLess(local_decision["seq"], start["seq"])
                proof = fixture.assert_shared_check_issued(fixture.capture_shared_check(start, "scope-original-check"))
                historical = fixture.history()
                original_receipt = fixture.read_receipt(proof["data"]["output"])
                with self.subTest(boundary="immediate unchanged consumption"):
                    self.assertEqual([], fixture.proof_errors(proof))

                if retire_red:
                    withdrawal = fixture.retire(red["id"])
                    replacement = fixture.support("scope-replacement-review")
                    self.assertLess(proof["seq"], withdrawal["seq"])
                    self.assertLess(withdrawal["seq"], replacement["seq"])
                    self.assertEqual(global_decision["data"]["revision"], replacement["data"]["revision"])
                    self.assertEqual([global_decision, replacement], runtime.decision_witnesses(fixture.history(), plan, []))

                before_replay = fixture.history()
                historical_errors = fixture.proof_errors(proof, state=historical)
                current_errors = fixture.proof_errors(proof)
                print(json.dumps({"retire_red": retire_red, "proof": proof["sha256"],
                                  "historical_prefix": historical["sha256"], "current_prefix": before_replay["sha256"],
                                  "historical_errors": historical_errors, "current_errors": current_errors}), flush=True)
                self.assertEqual(before_replay, fixture.history())
                with self.subTest(boundary="historical consumption"):
                    self.assertEqual([], historical_errors)
                if retire_red:
                    with self.subTest(boundary="retired current consumption"):
                        self.assertIn(retired_error, current_errors)
                    unchanged = fixture.capture_shared_check(start, "scope-unchanged-after-retirement")
                    with self.subTest(boundary="retired unchanged issuance"):
                        fixture.assert_shared_check_blocked(unchanged, retired_error)
                change_shared_path(fixture, "server.py", "mode")
                changed = fixture.capture_shared_check(start, "scope-first-changed-check")
                with self.subTest(boundary="first changed observation"):
                    if retire_red:
                        fixture.assert_shared_check_blocked(changed, grant_error)
                    else:
                        changed_proof = fixture.assert_shared_check_issued(changed)
                        self.assertEqual([], fixture.proof_errors(changed_proof))
                self.assertEqual((red, local_decision, proof),
                                 tuple(fixture.event(row["id"]) for row in (red, local_decision, proof)))
                self.assertEqual(original_receipt, fixture.read_receipt(proof["data"]["output"]))

    def test_selected_decision_integrity_guards_native_checks_and_grants(self):
        grant_error = "shared path change lacks an applicable retained original-owner grant: server.py"
        scenarios = {
            "digest": (False, True, "decision revision digest mismatch"),
            "predecessor": (True, False, "decision lineage must retain its immediate predecessor"),
            "valid reviewed revision": (True, True, None),
        }
        for scenario, (digest_valid, predecessor_valid, error) in scenarios.items():
            with self.subTest(scenario=scenario):
                fixture = self.fresh_repair_fixture()
                prepare_shared_plan(fixture, nonbehavior=True)
                plan = bind_shared_support_decision(fixture)
                original = fixture.event("shared-contract")
                original_review = fixture.event("shared-contract-review")
                remove_shared_server(fixture)
                start = shared_production(fixture, "original-reviewed-grant", ["A1"],
                                          [shared_path_row(fixture, "server.py", "reader-ticket")])
                proof = fixture.assert_shared_check_issued(fixture.capture_shared_check(start, "integrity-original-check"))
                self.assertEqual(plan["id"], proof["data"]["plan_event"])
                self.assertEqual([], fixture.proof_errors(proof))
                historical = fixture.history()
                original_receipt = fixture.read_receipt(proof["data"]["output"])
                if error is None:
                    fixture.decision("later-decision", "Use a valid later synthetic contract.", behavior="A1")
                    selected = fixture.event("later-decision")
                    review = fixture.event("later-decision-review")
                    self.assertEqual(selected["data"]["revision"], review["data"]["revision"])
                    self.assertLess(selected["seq"], review["seq"])
                else:
                    data = dict(original["data"])
                    if scenario == "digest":
                        data.update(choice="Record an altered synthetic contract with the original revision.",
                                    supersedes=original["data"]["revision"])
                    selected = fixture.ledger.append(a1.RUN, {"id": "later-decision", "type": "decision", "data": data},
                                                     historical["seq"])
                    self.assertEqual(historical["sha256"], selected["previous_sha256"])
                    self.assertEqual(original["data"]["revision"], selected["data"]["revision"])
                self.assertEqual(selected, fixture.event(selected["id"]))
                self.assertLess(proof["seq"], selected["seq"])
                payload = dict(selected["data"])
                claimed = payload.pop("revision")
                self.assertEqual((digest_valid, predecessor_valid),
                                 (a1.runtime.digest(payload) == claimed, payload["supersedes"] == original["data"]["revision"]))
                self.assertEqual(proof["observed_source"], fixture.current())
                before_replay = fixture.history()
                earlier_errors = fixture.proof_errors(proof, state=historical)
                current_errors = fixture.proof_errors(proof)
                print(json.dumps({"scenario": scenario, "proof": proof["sha256"], "claimed_revision": claimed,
                                  "computed_revision": a1.runtime.digest(payload), "predecessor": payload["supersedes"],
                                  "expected_predecessor": original["data"]["revision"],
                                  "historical_prefix": historical["sha256"], "current_prefix": before_replay["sha256"],
                                  "historical_errors": earlier_errors, "current_errors": current_errors}), flush=True)
                self.assertEqual(before_replay, fixture.history())
                self.assertEqual([], earlier_errors)
                with self.subTest(boundary="original proof current consumption"):
                    if error is None:
                        self.assertEqual([], current_errors)
                    else:
                        self.assertIn(error, current_errors)

                unchanged = fixture.capture_shared_check(start, "integrity-new-unchanged-check")
                with self.subTest(boundary="new unchanged native issuance"):
                    if error is None:
                        new_proof = fixture.assert_shared_check_issued(unchanged)
                        self.assertEqual([], fixture.proof_errors(new_proof))
                    else:
                        fixture.assert_shared_check_blocked(unchanged, error)
                if error is not None:
                    with self.subTest(boundary="fresh unchanged preflight"):
                        refused = fixture.refuse_start("integrity-fresh-production", "PRODUCTION", ["A1"],
                                                       write_manifest=[shared_path_row(fixture, "reader.py", "reader-ticket")])
                        print(json.dumps({"scenario": scenario, "fresh_preflight": refused}), flush=True)
                        self.assertIn(error, refused["errors"])

                change_shared_path(fixture, "server.py", "mode")
                changed = fixture.capture_shared_check(start, "integrity-first-changed-check")
                with self.subTest(boundary="first changed native observation"):
                    fixture.assert_shared_check_blocked(changed, grant_error)
                self.assertEqual((original, original_review, proof),
                                 tuple(fixture.event(row["id"]) for row in (original, original_review, proof)))
                self.assertEqual(original_receipt, fixture.read_receipt(proof["data"]["output"]))

    def test_shared_grant_uses_each_qualifying_acceptance(self):
        runtime = a1.runtime._v2()
        for explicit in (True, False):
            with self.subTest(explicit=explicit):
                fixture = self.fresh_repair_fixture()
                prepare_shared_plan(fixture, later_reader_check=True)
                fixture.decision("a1-only-contract", "Use the synthetic A1-only rule.", behavior="A1")
                original = fixture.event("a1-only-contract")
                review = fixture.event("a1-only-contract-review")
                content = copy.deepcopy(fixture.content)
                content["result_map"]["A3"]["production"].append("server.py")
                plan = fixture.publish_plan("two-acceptance-plan", content)
                open_shared_reader_test(fixture)
                owners = runtime.contract.initial_owners(fixture.history()["contract"], content)
                self.assertEqual({"reader-ticket": {"A1", "A3"}, "server-ticket": {"A2S"}}, owners["server.py"])
                remove_shared_server(fixture)
                admission = fixture.history()
                self.assertEqual([original, review], runtime.decision_witnesses(admission, plan, ["A1"]))
                self.assertEqual([], runtime.decision_witnesses(admission, plan, ["A3"]))
                rows = [shared_path_row(fixture, "server.py", "reader-ticket")] if explicit else None
                start = shared_production(fixture, "two-acceptance-grant", ["A1", "A3"], rows)
                self.assertIn("server.py", start["data"]["write_scope"])
                self.assertEqual(explicit, "write_manifest" in start["data"])
                self.assertEqual(admission["sha256"], start["previous_sha256"])
                withdrawal = fixture.retire(review["id"])
                self.assertLess(start["seq"], withdrawal["seq"])
                current = fixture.history()
                with self.assertRaisesRegex(ValueError, "selected proof dependency was withdrawn or superseded"):
                    runtime.decision_witnesses(current, plan, ["A1"])
                self.assertEqual([], runtime.decision_witnesses(current, plan, ["A3"]))
                change_shared_path(fixture, "server.py", "mode")
                proof = fixture.assert_shared_check_issued(fixture.capture_shared_check(start, "two-acceptance-changed-check"))
                self.assertEqual([], fixture.proof_errors(proof))


def bind_shared_support_decision(fixture, *, strategy="REVIEW"):
    fixture.decision("shared-contract", "Preserve the synthetic shared reader rule.",
                     behavior="A1", strategy=strategy)
    content = copy.deepcopy(fixture.content)
    content["decisions"] = ["status-contract"]
    return fixture.publish_plan("shared-decision-plan", content)


def add_unrelated_shared_decision(fixture):
    data = copy.deepcopy(fixture.event("shared-contract")["data"])
    del data["revision"]
    data.update(lineage="server-only-contract", acceptance=["A2S"], supersedes=None,
                choice="Preserve the unrelated synthetic server rule.")
    revision = a1.runtime.digest(data)
    fixture.push("unrelated-shared-decision", "decision", dict(data, revision=revision))
    fixture.push("unrelated-shared-review", "doubt_review", {
        "decision": data["lineage"], "revision": revision, "verdict": "SUPPORTED",
        "reviewer": fixture.reviewer("unrelated-shared-reviewer", a1.SOL_MODEL), "findings": [],
    })


def check_shared_status(fixture, start, label, *, check="verify-local"):
    source = fixture.current()
    command = [a1.PYTHON, "-B", "-c", "from reader import read; from server import status; "
               "assert read([]) == []; assert status('POST') == 500"]
    result = fixture.command_check(label, start["id"], check, command)
    fixture.assertEqual(source, fixture.current())
    if result["state"] == "PASS":
        proof = result["proof"]
        data = proof["data"]
        receipt, _ = fixture.retain_native(label, data["output"])
        fixture.assertEqual(("CHECK", check, source, start["id"]),
                            (data["phase"], data["check"], proof["observed_source"], data["start"]))
        fixture.assertEqual((0, source["sha256"], start["id"], data["plan_event"], command, str(fixture.repo)),
                            (receipt["exit"], receipt["candidate"], receipt["start"], receipt["plan_event"],
                             receipt["argv"], receipt["cwd"]))
        fixture.assertNotIn("acceptance", data)
        fixture.assertNotIn("results", data)
    return result


def configure_removed_server_batch(fixture, *, interaction="full"):
    fixture.configure(ids=("A1", "A2S"), tickets=[
        {"id": "reader-ticket", "acceptance": ["A1"]},
        {"id": "server-ticket", "acceptance": ["A2S"]},
    ])
    fixture.plan_extras["batch"] = {
        "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
        "dependencies": {"reader-ticket": [], "server-ticket": []}, "interaction_checks": [interaction],
    }


def prepare_removed_server(fixture, *, observed=False, delivery=None):
    configure_removed_server_batch(fixture)
    if delivery is not None:
        fixture.contract_extras.update(
            delivery=delivery, authority={"actions": ["edit", "merge_github"], "evidence": delivery["authority"]},
        )
        fixture.plan_extras["delivery"] = delivery
    if observed:
        fixture.feature_surface(ticket="server-ticket")
        present = "features/existing.md"
        fixture.write_files({present: "Pinned synthetic server note.\n"})
        fixture.git("add", "--", present)
        fixture.git("-c", "user.name=Baseline fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "Synthetic observed note", "--no-gpg-sign")
        fixture.base_commit = fixture.git("rev-parse", "HEAD").strip()
    fixture.initialize()
    content = fixture.plan_content()
    content["acceptance"][1].update(behavior=False, reason="Keep the independent server baseline.")
    content["result_map"]["A2S"]["test"] = []
    content["aggregate_checks"]["full"].remove("A2S")
    fixture.publish_plan("removed-baseline-plan", content)
    grant = {}
    if observed:
        rows = [
            manifest("features/notes.md", "server-ticket", "production", None),
            manifest(present, "server-ticket", "production", hashlib.sha256((fixture.repo / present).read_bytes()).hexdigest()),
        ]
        fixture.observe_paths("server-path-baselines", fixture.ids, rows)
        grant["write_manifest"] = [manifest("server.py", "server-ticket", "production",
                                            fixture.current()["files"]["server.py"]), *rows]
    fixture.cycle("retained-reader", ["A1"])
    start = fixture.preflight("server-production", "PRODUCTION", ["A2S"], **grant)
    fixture.assertEqual("PASS", start["state"], start)
    return start["start"]["id"]


def complete_removed_reader(fixture, start, prefix, *, green=None):
    if green is None:
        green = fixture.proof(prefix + "green", "A1", start)
    receipt, raw = fixture.read_receipt(green["data"]["output"])
    fixture.assertEqual((0, fixture.current()["sha256"], start),
                        (receipt["exit"], receipt["candidate"], receipt["start"]))
    fixture.assertIn(b"Ran 1 test", raw)
    fixture.final_proofs = {"A1": green}
    local = fixture.finish_workflow(start=start, prefix=prefix)
    return local, [green, fixture.event(prefix + "full")]


def change_removed_path(fixture, drift):
    name = {"mode": "server.py", "bytes": "server.py",
            "create": "features/notes.md", "delete": "features/existing.md"}[drift]
    state, before = fixture.history(), fixture.current()
    if name in state["initial_source"]["files"]:
        first = state["initial_source"]
    else:
        row, first = a1.runtime._v2()._first_observations(state)[name]
        fixture.assertEqual(row["baseline"], first["files"][name])
    fixture.assertEqual((first["files"][name], first["modes"][name]),
                        (before["files"][name], before["modes"][name]))
    path = fixture.repo / name
    original = path.read_bytes() if path.exists() else None
    mode = stat.S_IMODE(path.stat().st_mode) if original is not None else None
    if drift == "mode":
        path.chmod(mode ^ stat.S_IXUSR)
        fixture.assertEqual(original, path.read_bytes())
    elif drift == "bytes":
        path.write_bytes(original + b"\n# Synthetic drift.\n")
        fixture.assertEqual(mode, stat.S_IMODE(path.stat().st_mode))
    elif drift == "create":
        fixture.assertIsNone(original)
        path.write_bytes(b"Synthetic newly present note.\n")
    else:
        fixture.assertTrue(fixture.git("ls-tree", fixture.base_commit, "--", name).startswith("100644 "))
        path.unlink()
        fixture.assertFalse(path.exists())
    current = fixture.current()
    fixture.assertNotEqual(before["sha256"], current["sha256"])
    fixture.assertEqual(drift != "mode", before["files"][name] != current["files"][name])
    fixture.assertEqual(drift != "bytes", before["modes"][name] != current["modes"][name])
    print(json.dumps({"path": name, "fixture": str(fixture.root), "first": first,
                      "before": before, "after": current}, sort_keys=True), flush=True)
    return name, original, mode


def assert_removed_baseline(fixture, errors, name):
    fixture.assertTrue(any(name in error and "removed" in error and "baseline" in error
                           for error in errors), errors)


def removed_baseline_cli(fixture, *operation):
    argv = [a1.PYTHON, "-B", str(a1.base.SCRIPT), *operation,
            "--db", str(fixture.db), "--run", a1.RUN]
    completed = subprocess.run(argv, cwd=fixture.repo, input="", capture_output=True,
                               encoding="utf-8", timeout=60, check=False)
    print(json.dumps({"argv": argv, "cwd": str(fixture.repo), "stdin": "", "exit": completed.returncode,
                      "stdout": completed.stdout, "stderr": completed.stderr}, sort_keys=True), flush=True)
    return completed.returncode, json.loads(completed.stdout)


def prepare_shared_plan(fixture, *, shared="server.py", nonbehavior=False, third_ticket=False,
                        reader_surface=False, later_reader_check=False, delivery=None, worker=False):
    if third_ticket:
        configure_batch(fixture, allowed=(("reader-ticket", "display-ticket"), ("reader-ticket",)))
        fixture.plan_extras["batch"]["interaction_checks"] = ["reader"]
    elif later_reader_check:
        fixture.configure(ids=("A1", "A2S", "A3"), tickets=[
            {"id": "reader-ticket", "acceptance": ["A1", "A3"]},
            {"id": "server-ticket", "acceptance": ["A2S"]},
        ])
        fixture.plan_extras["batch"] = {
            "allowed_subsets": [["reader-ticket"]], "subset_delivery": True,
            "dependencies": {"reader-ticket": [], "server-ticket": []}, "interaction_checks": ["full"],
        }
    else:
        configure_removed_server_batch(fixture, interaction="reader" if nonbehavior else "full")
    if shared != "server.py":
        fixture.files = sorted([*fixture.files, shared])
        boundary = fixture.contract()["write_boundary"]
        boundary["production"] = sorted([*boundary["production"], shared])
        fixture.contract_extras["write_boundary"] = boundary
    if reader_surface:
        fixture.feature_surface(ticket="reader-ticket")
    if worker:
        fixture.contract_extras["authority"] = {
            "actions": ["edit", "worker"], "evidence": a1.runtime.reference(fixture.raw),
        }
    if delivery is not None:
        fixture.contract_extras.update(
            delivery=delivery, authority={"actions": ["edit", "merge_github"], "evidence": delivery["authority"]},
        )
        fixture.plan_extras["delivery"] = delivery
    fixture.initialize()
    content = fixture.plan_content()
    content["result_map"]["A1"]["production"].append(shared)
    if shared != "server.py":
        content["result_map"]["A2S"]["production"].append(shared)
    if later_reader_check:
        content["result_map"]["A3"]["production"] = ["reader.py"]
    nonbehavior_items = set(fixture.ids) if nonbehavior else set(fixture.ids) - {"A1"}
    for row in content["acceptance"]:
        if row["id"] in nonbehavior_items:
            row.update(behavior=False, reason="Preserve the synthetic behavior while verifying path authority.")
            content["result_map"][row["id"]]["test"] = []
            content["aggregate_checks"]["full"].remove(row["id"])
    if nonbehavior:
        content["checks"].remove("full")
        content["required_checks"].remove("full")
        content["aggregate_checks"] = {}
    fixture.publish_plan("shared-path-plan", content)
    owners = a1.runtime._v2().contract.initial_owners(fixture.history()["contract"], content)
    fixture.assertEqual({"reader-ticket": {"A1"}, "server-ticket": {"A2S"}}, owners[shared])


def shared_path_row(fixture, path, ticket):
    return manifest(path, ticket, "production", fixture.current()["files"][path])


def shared_production(fixture, label, acceptance, rows):
    options = {} if rows is None else {"write_manifest": rows}
    started = fixture.preflight(label, "PRODUCTION", acceptance, **options)
    fixture.assertEqual("PASS", started["state"], started)
    return started["start"]


def open_shared_reader_test(fixture):
    fixture.open_phase("shared-reader-test", "TEST_ONLY", ["A1"])
    fixture.write_files({a1.SHARED_TEST: a1.PYTHON_SUITE})
    fixture.proof("shared-reader-red", "A1", "shared-reader-test", passing=False)


def prepare_shared_reader(fixture, *, shared="server.py", reader_surface=False, delivery=None):
    prepare_shared_plan(fixture, shared=shared, reader_surface=reader_surface, delivery=delivery)
    open_shared_reader_test(fixture)
    reader = shared_production(fixture, "shared-reader-production", ["A1"],
                               [shared_path_row(fixture, "reader.py", "reader-ticket")])
    fixture.assertEqual(["reader.py"], reader["data"]["write_scope"])
    fixture.write_files({"reader.py": a1.WORKING["reader.py"]})
    fixture.proof("shared-original-reader-green", "A1", reader["id"])
    server_rows = [shared_path_row(fixture, shared, "server-ticket")]
    server = shared_production(fixture, "server-only-production", ["A2S"], server_rows)
    fixture.assertEqual((["A2S"], [shared], server_rows),
                        (server["data"]["acceptance"], server["data"]["write_scope"],
                         server["data"]["write_manifest"]))
    return server["id"]


def remove_shared_server(fixture, *, third_ticket=False):
    retained = ("reader-ticket", "display-ticket") if third_ticket else ("reader-ticket",)
    return fixture.push("shared-server-removal", "batch_membership", membership_request(fixture, retained))


def change_shared_path(fixture, name, drift):
    before = fixture.current()
    first = fixture.history()["initial_source"]
    fixture.assertEqual((first["files"][name], first["modes"][name]),
                        (before["files"][name], before["modes"][name]))
    path = fixture.repo / name
    original = path.read_bytes() if path.exists() else None
    mode = stat.S_IMODE(path.stat().st_mode) if original is not None else None
    if drift == "mode":
        path.chmod(mode ^ stat.S_IXUSR)
        fixture.assertEqual(original, path.read_bytes())
    elif drift == "bytes":
        path.write_bytes(original + b"\n# Synthetic shared note.\n")
        fixture.assertEqual(mode, stat.S_IMODE(path.stat().st_mode))
    elif drift == "create":
        fixture.assertIsNone(original)
        path.write_bytes(b"Synthetic shared path.\n")
    else:
        fixture.assertIsNotNone(original)
        path.unlink()
        fixture.assertFalse(path.exists())
    after = fixture.current()
    fixture.assertNotEqual(before["sha256"], after["sha256"])
    fixture.assertEqual(set() if drift == "mode" else {name},
                        {path for path in before["files"] if before["files"][path] != after["files"][path]})
    fixture.assertEqual(set() if drift == "bytes" else {name},
                        {path for path in before["modes"] if before["modes"][path] != after["modes"][path]})
    active = a1.runtime._latest(fixture.history(), "start")
    print(json.dumps({"path": name, "fixture": str(fixture.root), "before": before, "after": after,
                      "phase": active, "membership": a1.runtime._v2().membership_record(fixture.history())},
                     sort_keys=True), flush=True)
    return original, mode


def capture_shared_diagnostic(fixture):
    broken = fixture.current()
    command = [a1.PYTHON, "-B", "-c",
               "from pathlib import Path; assert not Path('server.py').stat().st_mode & 0o100"]
    completed = subprocess.run(command, cwd=fixture.repo, input=b"", capture_output=True, timeout=15, check=False)
    fixture.assertEqual(1, completed.returncode)
    fixture.assertIn(b"AssertionError", completed.stderr)
    fixture.assertEqual(broken, fixture.current())
    streams = {}
    for channel in ("stdout", "stderr"):
        output = fixture.root / ("shared-path-diagnostic-" + channel)
        output.write_bytes(getattr(completed, channel))
        streams[channel] = a1.runtime.reference(output)
    print(json.dumps({"argv": command, "cwd": str(fixture.repo), "exit": completed.returncode,
                      "streams": streams, "broken": broken}, sort_keys=True), flush=True)
    defect = "synthetic-shared-path-mode"
    failure = fixture.push("shared-path-diagnostic", "failure", {
        "defect": defect, "broken": broken, "command": command, "exit": completed.returncode,
        "output": streams["stderr"],
    })
    request = fixture.failure_intent()
    request.update(id="capture-shared-path-diagnostic", defect=defect)
    request["failure"].update(command=command, output=streams["stderr"], inputs=[streams["stdout"]])
    request["case"].update(title="Shared path mode left its synthetic baseline", check_id="reader",
                           expected_behavior="Removed server grant leaves the shared path at baseline.",
                           actual_behavior="The shared server path became executable.")
    request["case"]["origin"]["failure_id"] = failure["id"]
    request["case"]["evidence_refs"][0]["sha256"] = streams["stderr"]["sha256"]
    captured = fixture.ledger.capture(a1.RUN, fixture.history()["seq"], request)
    fixture.assertEqual("PASS", captured["state"], captured)
    shown = captured["link"]["data"]["show"]
    fixture.assertTrue(a1.runtime.verify_reference(shown))
    case = json.loads(Path(shown["path"]).read_bytes())
    fixture.assertEqual((captured["digest"], broken["sha256"]),
                        (case["digest"], case["record"]["origin"]["broken_source_identity"]))
    fixture.assertEqual(broken, failure["observed_source"])
    return failure, captured


def assert_shared_grant_refusal(fixture, errors, path):
    fixture.assertTrue(any(path in error and all(word in error.casefold() for word in ("shared", "retained", "grant"))
                           for error in errors), errors)


def assert_shared_subset(fixture, result, removal):
    fixture.assertEqual((removal["data"]["members"], removal["data"]["continuations"], False),
                        (result["active_tickets"], result["continuations"], result["parent_complete"]))
