"""Local delivery tests with an argv-level GitHub fixture and real local acceptance."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from unittest.mock import patch

import test_four_behavior_repair as a1
from test_i2e_v2_runtime import (
    INTERACTION_CHECK,
    WorkflowFixture,
    assert_removed_baseline,
    assert_shared_grant_refusal,
    assert_shared_subset,
    batch_content,
    change_removed_path,
    change_shared_path,
    complete_removed_reader,
    configure_batch,
    membership_request,
    prepare_removed_server,
    prepare_shared_reader,
    record_interaction,
    refresh_acceptance,
    removed_baseline_cli,
    remove_shared_server,
)


REPOSITORY = "fixture/merge-target"
TARGET = "main"
PR = 7
ACTOR = "fixture-writer"
CHECK_NAME = "i2e-v2"
APP_ID = 101
VERSION = "2026-03-10"


def fixture_membership(history):
    selected = next((row for row in reversed(history["events"]) if row["type"] == "batch_membership"), None)
    if selected is None:
        return {"event": None, "members": [ticket["id"] for ticket in history["contract"]["tickets"]],
                "continuations": {}}
    return {"event": {"id": selected["id"], "sha256": selected["sha256"]},
            "members": selected["data"]["members"], "continuations": selected["data"]["continuations"]}


class FakeGitHub:
    """Only fixture state changes. Unknown requests are test failures."""

    def __init__(self, head, base, receipt, intent_observer):
        self.head, self.base = head, base
        self.receipt = receipt
        self.intent_observer = intent_observer
        self.calls = []
        self.puts = []
        self.effects = 0
        self.rules_visible = True
        self.admin_bypass = False
        self.strict = True
        self.producer = APP_ID
        self.current_review = True
        self.check_visible = True
        self.ack = "normal"
        self.target_race = False
        self.merged = False
        self.merge_sha = "e" * 40
        self.parents = []
        self.path = f"repos/{REPOSITORY}"
        self.pull = self.path + f"/pulls/{PR}"

    @staticmethod
    def reply(argv, result=None, *, error=None):
        return subprocess.CompletedProcess(argv, 0 if error is None else 1,
                                           json.dumps(result).encode() if result is not None else b"",
                                           b"" if error is None else error.encode())

    def __call__(self, argv):
        assert isinstance(argv, list) and argv[1] == "api", argv
        self.calls.append(list(argv))
        method = argv[argv.index("--method") + 1] if "--method" in argv else "GET"
        path = next(arg for arg in argv if arg.startswith("repos/") or arg == "user")
        path = path.split("?", 1)[0]
        if method == "PUT":
            assert path == self.pull + "/merge", argv
            self.puts.append(list(argv))
            assert self.intent_observer(), "No immutable operation intent existed before the merge call"
            fields = dict(argv[i + 1].split("=", 1) for i, item in enumerate(argv) if item in {"-f", "--raw-field"})
            assert fields.get("merge_method") == "merge" and fields.get("sha") == self.head, argv
            if self.target_race:
                self.base = "f" * 40
                return self.reply(argv, error="409 strict current-target required check invalidated")
            if self.ack == "none":
                return self.reply(argv, {"status": "409", "message": "Merge rejected", "merged": False},
                                  error="gh: Merge rejected (HTTP 409)")
            if self.ack == "unknown":
                return self.reply(argv, error="transport lost merge response")
            self.merged = True
            self.effects += 1
            self.parents = [("d" * 40 if self.ack == "unintended" else self.base), self.head]
            if self.ack in {"intended", "unintended"}:
                return self.reply(argv, error="lost acknowledgment after effect")
            return self.reply(argv, {"merged": True, "sha": self.merge_sha, "message": "Synthetic merge"})
        assert method == "GET", argv
        if path == "user":
            return self.reply(argv, {"login": ACTOR, "id": 47})
        if path == self.pull:
            return self.reply(argv, {
                "number": PR, "state": "closed" if self.merged else "open", "draft": False,
                "merged": self.merged, "merge_commit_sha": self.merge_sha if self.merged else None,
                "mergeable": True,
                "head": {"sha": self.head, "ref": "fixture-branch", "repo": {"full_name": REPOSITORY}},
                "base": {"sha": self.base, "ref": TARGET, "repo": {"full_name": REPOSITORY}},
            })
        if path == self.path:
            return self.reply(argv, {"full_name": REPOSITORY, "allow_merge_commit": True, "archived": False})
        if path == self.path + "/branches/" + TARGET:
            return self.reply(argv, {"name": TARGET, "commit": {"sha": self.merge_sha if self.merged else self.base},
                                    "protected": True})
        if path == self.path + "/branches/" + TARGET + "/protection":
            if not self.rules_visible:
                return self.reply(argv, error="403 protection administration read unavailable")
            return self.reply(argv, {
                "required_status_checks": {"strict": self.strict, "checks": [{"context": CHECK_NAME, "app_id": APP_ID}]},
                "enforce_admins": {"enabled": not self.admin_bypass},
                "required_pull_request_reviews": {
                    "dismiss_stale_reviews": True, "require_last_push_approval": True, "required_approving_review_count": 1,
                    "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
                },
                "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
                "required_linear_history": {"enabled": False},
            })
        if path in {self.path + "/rules/branches/" + TARGET, self.path + "/rulesets"}:
            return self.reply(argv, [])
        if path == self.path + f"/collaborators/{ACTOR}/permission":
            return self.reply(argv, {"permission": "write", "role_name": "write", "user": {"login": ACTOR}})
        if path == self.pull + "/reviews":
            return self.reply(argv, [{
                "id": 5, "state": "APPROVED", "commit_id": self.head if self.current_review else "b" * 40,
                "user": {"login": "fixture-reviewer", "id": 71}, "submitted_at": "2026-11-01T10:00:00Z",
            }])
        if path == self.path + f"/commits/{self.head}/check-runs":
            runs = [{
                "id": 3, "name": CHECK_NAME, "head_sha": self.head, "status": "completed", "conclusion": "success",
                "app": {"id": self.producer, "slug": "fixture-i2e"},
                "output": {"summary": json.dumps(self.receipt)},
            }] if self.check_visible else []
            return self.reply(argv, {"total_count": len(runs), "check_runs": runs})
        if path == self.path + f"/commits/{self.merge_sha}" and self.merged:
            return self.reply(argv, {"sha": self.merge_sha, "parents": [{"sha": parent} for parent in self.parents]})
        raise AssertionError(f"Unexpected fake GitHub request: {argv}")


class DeliveryV2Tests(WorkflowFixture):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory
        register_cleanup = self.addCleanup

        def preserve_fixture(callback, *args, **kwargs):
            directory = getattr(self, "temp", None)
            if directory is None or callback != directory.cleanup:
                register_cleanup(callback, *args, **kwargs)

        with (
            patch.object(tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary(delete=False, **kw)),
            patch.object(self, "addCleanup", side_effect=preserve_fixture),
        ):
            super().setUp()
        print("retained synthetic delivery fixture", self.root, flush=True)

    def delivery_fixture(self):
        self.configure("Direct")
        authority = a1.runtime.reference(self.raw)
        self.contract_extras["authority"] = {"actions": ["edit", "merge_github"], "evidence": authority}
        self.contract_extras["delivery"] = {
            "repository": REPOSITORY, "target": TARGET, "pr": PR, "action": "merge_commit",
            "actor": ACTOR, "trusted_check": {"name": CHECK_NAME, "app_id": APP_ID},
            "rules_admin_trust": True, "authority": authority,
        }
        self.prepare_plan()
        self.cycle("change", ["A1"])
        local = self.finish_workflow()
        head = self.candidate_commit()
        base = self.base_commit
        events = self.history()["events"]
        checks = [{"check": e["data"]["check"], "event": e["id"], "sha256": e["sha256"]}
                  for e in events if e["type"] == "proof" and e["data"]["phase"] in {"GREEN", "CHECK"}]
        reviews = [{"event": e["id"], "sha256": e["sha256"]} for e in events if e["type"] == "audit"]
        proof_source = self.event("change-green-A1")["data"]["source"]
        receipt = {"schema": "i2e-team-github-check-v2", "repository": REPOSITORY, "head": head,
                   "target": TARGET, "base": base, "candidate": local["candidate"]["sha256"], "plan": self.plan,
                   "source": proof_source, "checks": checks, "reviews": reviews}
        if "modes" in local["candidate"]:
            receipt["membership"] = fixture_membership(self.history())

        def intent_exists():
            return any(e["type"] == "delivery_intent" and e["data"]["head"] == head for e in self.history()["events"])

        provider = FakeGitHub(head, base, receipt, intent_exists)
        request = {"repository": REPOSITORY, "target": TARGET, "pr": PR, "head": head, "base": base,
                   "candidate": local["candidate"]["sha256"], "actor": ACTOR, "action": "merge_commit",
                   "authority": authority}
        return provider, request

    def effect(self, provider, operation, body, label):
        return self.ledger.delivery(a1.RUN, operation, self.history()["seq"], dict(body, id=label),
                                    transport=provider)

    def prepare_delivery(self, provider, request):
        result = self.effect(provider, "prepare", request, "merge-intent")
        self.assertEqual("PASS", result["state"], result)
        return {"operation": result["intent"]["id"], "actor": ACTOR, "authority": request["authority"]}

    def fresh(self):
        fixture = DeliveryV2Tests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_exact_merge_uses_conditional_head_version_and_server_target_controls(self):
        provider, request = self.delivery_fixture()
        inspection = self.effect(provider, "inspect", request, "inspect-target")
        self.assertEqual("PASS", inspection["state"], inspection)
        self.assertEqual([], provider.puts)
        intent = self.prepare_delivery(provider, request)
        result = self.effect(provider, "execute", intent, "merge-effect")
        self.assertEqual(("PASS", "INTENDED"), (result["state"], result["outcome"]), result)
        self.assertEqual([request["base"], request["head"]], provider.parents)
        self.assertEqual(1, len(provider.puts))
        argv = provider.puts[0]
        self.assertIn("X-GitHub-Api-Version: " + VERSION, argv)
        self.assertIn("sha=" + request["head"], argv)
        self.assertIn("merge_method=merge", argv)
        self.assertFalse(any(arg in {"--admin", "--auto", "--squash", "--rebase"} for arg in argv))

    def test_unverified_rule_producer_receipt_reviews_and_bypass_hold_before_effect(self):
        changes = {
            "unreadable-rules": lambda p: setattr(p, "rules_visible", False),
            "bypass": lambda p: setattr(p, "admin_bypass", True),
            "stale-target-control": lambda p: setattr(p, "strict", False),
            "wrong-producer": lambda p: setattr(p, "producer", APP_ID + 1),
            "missing-producer": lambda p: setattr(p, "check_visible", False),
            "missing-native-check": lambda p: p.receipt["checks"].pop(),
            "wrong-base-receipt": lambda p: p.receipt.update(base="c" * 40),
            "stale-review": lambda p: setattr(p, "current_review", False),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                f = self.fresh()
                provider, request = f.delivery_fixture()
                change(provider)
                denied = f.effect(provider, "prepare", request, "denied")
                self.assertIn(denied["state"], {"BLOCK", "HOLD"}, denied)
                self.assertEqual([], provider.puts)

    def test_changed_head_target_authority_or_local_candidate_blocks_effect(self):
        for changed in ("head", "target", "authority", "candidate", "server-race"):
            with self.subTest(changed=changed):
                f = self.fresh()
                provider, request = f.delivery_fixture()
                intent = f.prepare_delivery(provider, request)
                if changed == "head":
                    provider.head = "a" * 40
                elif changed == "target":
                    provider.base = "a" * 40
                elif changed == "authority":
                    fake = f.root / "different-authority"
                    fake.write_text("Different synthetic authority bytes.")
                    intent["authority"] = a1.runtime.reference(fake)
                elif changed == "candidate":
                    f.write_files({"reader.py": "# Unreviewed local drift.\n" + a1.WORKING["reader.py"]})
                else:
                    provider.target_race = True
                result = f.effect(provider, "execute", intent, "changed-before-effect")
                self.assertIn(result["state"], {"BLOCK", "HOLD"}, result)
                self.assertEqual(0, provider.effects)
                if changed != "server-race":
                    self.assertEqual([], provider.puts)

    def test_lost_acknowledgment_distinguishes_all_four_effect_outcomes(self):
        for ack, outcome in (("intended", "INTENDED"), ("none", "NO_EFFECT"),
                             ("unintended", "UNINTENDED"), ("unknown", "UNKNOWN")):
            with self.subTest(ack=ack):
                f = self.fresh()
                provider, request = f.delivery_fixture()
                intent = f.prepare_delivery(provider, request)
                provider.ack = ack
                f.effect(provider, "execute", copy.deepcopy(intent), "attempt-merge")
                result = f.effect(provider, "reconcile", intent, "reconcile-after-loss")
                self.assertEqual(outcome, result["outcome"], result)
                self.assertEqual(1, len(provider.puts))
                if ack == "unknown":
                    retry = f.effect(provider, "execute", intent, "unsafe-retry")
                    self.assertEqual("HOLD", retry["state"], retry)
                    self.assertEqual(1, len(provider.puts))

    def test_public_delivery_inspection_reads_offline_provider_without_effect(self):
        provider, request = self.delivery_fixture()
        before = self.history()
        body = dict(request, id="inspect-through-cli")
        fixture = self.root / "offline-gh"
        fixture.mkdir()
        fixture_data = fixture / "fixture.json"
        fixture_data.write_text(json.dumps({"head": provider.head, "base": provider.base,
                                            "receipt": provider.receipt}))
        original_payload = fixture_data.read_bytes()
        program = f"#!{a1.PYTHON}\nFIXTURE_SOURCE = {str(Path(__file__).resolve())!r}\n" + r"""import json, runpy, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(FIXTURE_SOURCE).parent))
fake = runpy.run_path(FIXTURE_SOURCE)["FakeGitHub"]
data = json.loads((root / "fixture.json").read_bytes())
provider = fake(data["head"], data["base"], data["receipt"], lambda: False)
argv = list(sys.argv)
method = argv[argv.index("--method") + 1] if "--method" in argv else "GET"
try:
    if method != "GET":
        raise AssertionError("offline inspection fixture only serves GET")
    result = provider(argv)
except (AssertionError, ValueError, IndexError, StopIteration) as exc:
    result = subprocess.CompletedProcess(argv, 2, b"", str(exc).encode())
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"argv": argv, "method": method, "exit": result.returncode,
                             "stdout": result.stdout.decode(), "stderr": result.stderr.decode(),
                             "effects": provider.effects}) + "\n")
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
"""
        fake_gh = fixture / "gh"
        fake_gh.write_text(program)
        fake_gh.chmod(0o700)
        env = {"PATH": str(fixture), "PYTHONDONTWRITEBYTECODE": "1",
               "GH_CONFIG_DIR": str(fixture / "config"), "GH_PROMPT_DISABLED": "1"}
        argv = [a1.PYTHON, "-B", str(a1.base.SCRIPT), "delivery", "inspect", "--db", str(self.db),
                "--run", a1.RUN, "--expect", str(before["seq"]), "--input", "-"]
        completed = subprocess.run(argv, cwd=self.repo, env=env, input=json.dumps(body).encode(),
                                   capture_output=True, timeout=35, check=False)
        (fixture / "cli.stdout").write_bytes(completed.stdout)
        (fixture / "cli.stderr").write_bytes(completed.stderr)
        (fixture / "cli-command.json").write_text(json.dumps({
            "argv": argv, "cwd": str(self.repo), "env": env, "request": body, "exit": completed.returncode,
        }))
        self.assertEqual(before, self.history())
        self.assertEqual(original_payload, fixture_data.read_bytes())
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("PASS", result["state"], result)
        calls = [json.loads(line) for line in (fixture / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(calls)
        self.assertTrue(all(row["method"] == "GET" and row["effects"] == 0 and row["exit"] == 0 for row in calls))
        self.assertTrue(all(row["argv"][0] == str(fake_gh) for row in calls))


    def test_audit_delivery_rechecks_local_binding_after_last_provider_get(self):
        for changed in ("authority", "candidate"):
            with self.subTest(changed=changed):
                fixture = self.fresh()
                provider, request = fixture.delivery_fixture()
                intent = fixture.prepare_delivery(provider, request)
                authority = Path(intent["authority"]["path"])
                self.assertTrue(authority.is_relative_to(fixture.root))
                original = authority.read_bytes()
                source_before = fixture.current()
                before_calls = len(provider.calls)
                final_reads = []

                def change_after_qualification(argv):
                    reply = provider(argv)
                    if "GET" in argv and any("/check-runs?" in arg for arg in argv):
                        final_reads.append(len(provider.calls) - before_calls)
                        if len(final_reads) == 2:
                            if changed == "authority":
                                authority.write_bytes(b"Changed disposable delivery authority.\n")
                            else:
                                fixture.write_files({"reader.py": "# Local drift during final GET.\n"
                                                                  + a1.WORKING["reader.py"]})
                    return reply

                result = fixture.effect(change_after_qualification, "execute", intent, "late-local-drift")
                self.assertEqual(2, len(final_reads), provider.calls[before_calls:])
                self.assertEqual(changed == "authority", source_before == fixture.current())
                self.assertEqual(changed == "candidate", original == authority.read_bytes())
                history = fixture.history()
                dispatch = next(event for event in history["events"] if event["type"] == "delivery_dispatch")
                final = next(event for event in history["events"] if event["type"] == "delivery_result")
                print(json.dumps({"changed": changed, "check_reads": final_reads,
                                  "calls": provider.calls[before_calls:], "effects": provider.effects,
                                  "before_source": source_before, "after_source": fixture.current(),
                                  "result": result, "dispatch": dispatch, "final": final}, sort_keys=True),
                      flush=True)
                with self.subTest(boundary="native-effect"):
                    self.assertEqual([], provider.puts)
                    self.assertEqual(0, provider.effects)
                with self.subTest(boundary="durable-result"):
                    self.assertEqual(("BLOCK", "NO_EFFECT"), (result["state"], result["outcome"]), result)
                    self.assertIs(result["readback"]["put_started"], False)
                    self.assertEqual(dispatch["id"], final["data"]["dispatch"])
                    self.assertEqual("NO_EFFECT", final["data"]["outcome"])
                    self.assertIsNone(final["data"]["effect"]["put"])

    def provider_for_proofs(self, local, head, proofs, audit_prefix):
        history = self.history()
        proofs = sorted(proofs, key=lambda event: event["seq"])
        checks = [{"check": e["data"]["check"], "event": e["id"], "sha256": e["sha256"]} for e in proofs]
        reviews = [{"event": e["id"], "sha256": e["sha256"]} for e in history["events"]
                   if e["type"] == "audit" and e["id"].startswith(audit_prefix)]
        boundary = history["contract"]["delivery"]
        receipt = {"schema": "i2e-team-github-check-v2", "repository": REPOSITORY, "head": head,
                   "target": TARGET, "base": self.base_commit, "candidate": local["candidate"]["sha256"],
                   "plan": self.plan, "source": proofs[0]["data"]["source"], "checks": checks, "reviews": reviews}
        if "modes" in local["candidate"]:
            receipt["membership"] = fixture_membership(history)

        def intent_exists():
            return any(e["type"] == "delivery_intent" and e["data"]["head"] == head
                       for e in self.history()["events"])

        provider = FakeGitHub(head, self.base_commit, receipt, intent_exists)
        request = {key: boundary[key] for key in ("repository", "target", "pr", "actor", "action", "authority")}
        request.update(head=head, base=self.base_commit, candidate=local["candidate"]["sha256"])
        return provider, request

    def subset_fixture(self, *, dependent=False):
        retained = ("reader-ticket", "server-ticket")
        dependencies = {"reader-ticket": ["display-ticket"], "server-ticket": [], "display-ticket": []}
        configure_batch(self, allowed=(retained, ("reader-ticket",)), dependencies=dependencies if dependent else None)
        authority = a1.runtime.reference(self.raw)
        boundary = {
            "repository": REPOSITORY, "target": TARGET, "pr": PR, "action": "merge_commit",
            "actor": ACTOR, "trusted_check": {"name": CHECK_NAME, "app_id": APP_ID},
            "rules_admin_trust": True, "authority": authority,
        }
        self.contract_extras.update(delivery=boundary, authority={"actions": ["edit", "merge_github"], "evidence": authority})
        self.plan_extras["delivery"] = boundary
        self.initialize()
        self.publish_plan("workflow-plan", batch_content(self, server_behavior=False))
        return membership_request(self, retained)

    def accepted_subset(self):
        subset = self.push("subset", "batch_membership", self.subset_fixture())
        self.cycle("change", ["A1"])
        green = self.event("change-green-A1")
        self.final_proofs = {"A1": green}
        server = self.command_check("retained-server", "change-production", "server", [
            a1.PYTHON, "-B", "-c", "from server import status; assert status('POST') == 500",
        ])
        self.assertEqual("PASS", server["state"], server)
        interaction = record_interaction(self, "subset-interaction", "change-production", expected_status=500)
        self.assertEqual("PASS", interaction["state"], interaction)
        local = self.finish_workflow()
        self.assertEqual(("ACCEPTED_LOCAL", False, subset["data"]["members"], subset["data"]["continuations"]),
                         (local["lifecycle"], local["parent_complete"], local["active_tickets"], local["continuations"]))
        self.git("add", "--", "reader.py", a1.SHARED_TEST)
        tree = self.git("write-tree").strip()
        head = self.git("-c", "user.name=Subset fixture", "-c", "user.email=fixture@example.invalid",
                        "commit-tree", tree, "-p", self.base_commit, "-m", "Synthetic retained tickets").strip()
        proofs = [green, server["proof"], interaction["proof"], self.event("workflow-full")]
        provider, request = self.provider_for_proofs(local, head, proofs, "workflow-audit-")
        return local, provider, request

    def advance_subset(self):
        membership = self.push("reduced-subset", "batch_membership",
                               membership_request(self, ("reader-ticket",), previous="subset"))
        result = record_interaction(self, "reduced-interaction", "change-production", expected_status=500)
        self.assertEqual("PASS", result["state"], result)
        coverage = self.coverage("reduced-full", "change-production")
        self.assertEqual("PASS", coverage["state"], coverage)
        local = refresh_acceptance(self, "reduced-", [*self.final_proofs.values(), result["proof"], coverage["proof"]])
        self.assertEqual(membership["data"]["continuations"], local["continuations"])
        self.assertFalse(local["parent_complete"], local)
        return local

    def test_authorized_subset_delivers_with_open_parent(self):
        for change in ("unchanged", "after-intent", "after-delivery"):
            with self.subTest(change=change):
                fixture = self.fresh()
                local, provider, request = fixture.accepted_subset()
                expected = fixture_membership(fixture.history())
                inspection = fixture.effect(provider, "inspect", request, "inspect-subset")
                print(json.dumps({"change": change, "local": local, "inspection": inspection,
                                  "provider_calls": provider.calls}, sort_keys=True), flush=True)
                self.assertEqual("PASS", inspection["state"], inspection)
                self.assertTrue(provider.calls)
                self.assertEqual(expected, inspection["candidate"]["membership"])
                self.assertEqual([], provider.puts)

                if change == "unchanged":
                    provider.receipt["membership"] = dict(expected, continuations={})
                    mismatch = fixture.effect(provider, "inspect", request, "wrong-continuation-receipt")
                    self.assertIn(mismatch["state"], {"BLOCK", "HOLD"}, mismatch)
                    self.assertEqual([], provider.puts)
                    provider.receipt["membership"] = expected

                operation = fixture.prepare_delivery(provider, request)
                saved = fixture.event(operation["operation"])
                self.assertEqual(expected, saved["data"]["local"]["membership"])
                if change == "after-intent":
                    reduced = fixture.advance_subset()
                    self.assertEqual(local["candidate"], reduced["candidate"])
                    rejected = fixture.effect(provider, "execute", operation, "retired-intent")
                    self.assertIn(rejected["state"], {"BLOCK", "HOLD"}, rejected)
                    self.assertEqual(([], 0), (provider.puts, provider.effects))
                    self.assertFalse(any(e["type"] == "delivery_dispatch" for e in fixture.history()["events"]))
                    continue

                delivered = fixture.effect(provider, "execute", operation, "deliver-subset")
                self.assertEqual(("PASS", "INTENDED"), (delivered["state"], delivered["outcome"]), delivered)
                self.assertEqual((1, 1), (len(provider.puts), provider.effects))
                state = fixture.ledger.check(a1.RUN)
                self.assertEqual(("DELIVERED", False, expected["members"], expected["continuations"]),
                                 (state["lifecycle"], state["parent_complete"], state["active_tickets"], state["continuations"]))
                if change == "after-delivery":
                    reduced = fixture.advance_subset()
                    self.assertEqual(local["candidate"], reduced["candidate"])
                    self.assertEqual("ACCEPTED_LOCAL", reduced["lifecycle"], reduced)
                observed = fixture.effect(provider, "reconcile", operation, "observe-original-intent")
                self.assertEqual(("PASS", "INTENDED"), (observed["state"], observed["outcome"]), observed)
                self.assertEqual((1, 1), (len(provider.puts), provider.effects))
                if change == "after-delivery":
                    self.assertEqual("ACCEPTED_LOCAL", fixture.ledger.check(a1.RUN)["lifecycle"])

        for invalid in ("authority", "missing-interaction"):
            with self.subTest(invalid=invalid):
                fixture = self.fresh()
                _, provider, request = fixture.accepted_subset()
                if invalid == "authority":
                    request["actor"] = "different-actor"
                else:
                    fixture.retire("subset-interaction")
                    outcome = fixture.ledger.check(a1.RUN)
                    with self.subTest(boundary="missing live interaction"):
                        self.assertTrue(any(INTERACTION_CHECK in reason for reason in outcome["errors"]), outcome)
                refused = fixture.effect(provider, "inspect", request, "unqualified-subset")
                self.assertIn(refused["state"], {"BLOCK", "HOLD"}, refused)
                self.assertEqual(([], 0), (provider.calls, provider.effects))

        for invalid in ("continuation", "dependency"):
            with self.subTest(invalid=invalid):
                fixture = self.fresh()
                membership = fixture.subset_fixture(dependent=invalid == "dependency")
                if invalid == "continuation":
                    membership["continuations"] = {}
                before = fixture.history()
                with self.assertRaises((a1.runtime.RuntimeError, ValueError)):
                    fixture.push("invalid-subset", "batch_membership", membership)
                self.assertEqual(before, fixture.history())

    def test_delivery_requires_mode_bound_acceptance_for_matching_head(self):
        provider, request = self.delivery_fixture()
        path = self.repo / "reader.py"
        original, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode ^ stat.S_IXUSR)
        self.assertEqual(original, path.read_bytes())
        self.assertNotEqual(mode, stat.S_IMODE(path.stat().st_mode))
        old_head = self.effect(provider, "inspect", request, "inspect-old-mode-head")
        self.assertIn(old_head["state"], {"BLOCK", "HOLD"}, old_head)
        self.assertEqual([], provider.calls)

        matching_head = self.candidate_commit()
        self.assertNotEqual(request["head"], matching_head)
        self.assertTrue(self.git("ls-tree", matching_head, "--", "reader.py").startswith("100755 "))
        provider.head = matching_head
        provider.receipt["head"] = matching_head
        provider.receipt["candidate"] = self.current()["sha256"]
        request.update(head=matching_head, candidate=self.current()["sha256"])
        stale = self.effect(provider, "inspect", request, "inspect-matching-mode-stale-proof")
        print(json.dumps({"old_head": old_head, "matching_head": matching_head, "stale": stale,
                          "provider_calls": provider.calls}, sort_keys=True), flush=True)
        with self.subTest(boundary="matching Git mode with stale acceptance"):
            self.assertIn(stale["state"], {"BLOCK", "HOLD"}, stale)
            self.assertEqual([], provider.calls)

        renewed = self.proof("current-mode-green", "A1", "change-production")
        self.final_proofs = {"A1": renewed}
        covered = self.coverage("renewed-mode-full", "change-production")
        self.assertEqual("PASS", covered["state"], covered)
        local = refresh_acceptance(self, "renewed-mode-", [renewed, covered["proof"]])
        provider, request = self.provider_for_proofs(
            local, matching_head, [renewed, covered["proof"]], "renewed-mode-audit-",
        )
        inspected = self.effect(provider, "inspect", request, "inspect-renewed-mode")
        self.assertEqual("PASS", inspected["state"], inspected)
        operation = self.prepare_delivery(provider, request)
        reads = []

        def change_mode_after_last_get(argv):
            reply = provider(argv)
            if "GET" in argv and any("/check-runs?" in arg for arg in argv):
                reads.append(list(argv))
                if len(reads) == 2:
                    path.chmod(mode)
            return reply

        denied = self.effect(change_mode_after_last_get, "execute", operation, "mode-drift-before-merge")
        self.assertEqual(2, len(reads), provider.calls)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(("BLOCK", "NO_EFFECT"), (denied["state"], denied["outcome"]), denied)
        self.assertEqual(([], 0), (provider.puts, provider.effects))
        self.assertIs(denied["readback"]["put_started"], False)
        dispatch, = (e for e in self.history()["events"] if e["type"] == "delivery_dispatch")
        result, = (e for e in self.history()["events"] if e["type"] == "delivery_result")
        self.assertEqual((dispatch["id"], "NO_EFFECT"), (result["data"]["dispatch"], result["data"]["outcome"]))

    def removed_delivery_fixture(self, *, observed=False):
        fixture = self.fresh()
        boundary = {
            "repository": REPOSITORY, "target": TARGET, "pr": PR, "action": "merge_commit",
            "actor": ACTOR, "trusted_check": {"name": CHECK_NAME, "app_id": APP_ID},
            "rules_admin_trust": True, "authority": a1.runtime.reference(fixture.raw),
        }
        start = prepare_removed_server(fixture, observed=observed, delivery=boundary)
        removal = fixture.push("remove-server", "batch_membership", membership_request(fixture, ("reader-ticket",)))
        return fixture, start, removal

    def removed_delivery_head(self):
        candidate = self.current()
        self.assertEqual(self.base_commit, self.git("rev-parse", "HEAD").strip())
        present = [name for name, checksum in candidate["files"].items() if checksum is not None]
        self.git("add", "--", *present)
        tree = self.git("write-tree").strip()
        head = self.git("-c", "user.name=Removal fixture", "-c", "user.email=fixture@example.invalid",
                        "commit-tree", tree, "-p", self.base_commit, "-m", "Synthetic current removed subset").strip()
        self.assertEqual(self.base_commit, self.git("rev-parse", head + "^").strip())
        for name, checksum in candidate["files"].items():
            entry = self.git("ls-tree", head, "--", name)
            if checksum is None:
                self.assertEqual("", entry)
            else:
                self.assertTrue(entry.startswith(candidate["modes"][name] + " blob "), entry)
                self.assertEqual((self.repo / name).read_bytes(), self.git("show", f"{head}:{name}").encode())
        return head

    def test_delivery_refuses_drift_on_removed_ticket_baselines(self):
        for drift in ("mode", "create"):
            with self.subTest(drift=drift):
                fixture, start, removal = self.removed_delivery_fixture(observed=drift == "create")
                path, _, _ = change_removed_path(fixture, drift)
                head = fixture.removed_delivery_head()
                native = fixture.request_proof("drifted-green", "A1", start)
                if native["state"] == "PASS":
                    local, proofs = complete_removed_reader(fixture, start, "drifted-", green=native["proof"])
                    self.assertEqual(removal["data"]["continuations"], local["continuations"])
                    self.assertFalse(local["parent_complete"])
                    provider, request = fixture.provider_for_proofs(local, head, proofs, "drifted-audit-")
                else:
                    self.assertEqual("BLOCK", native["state"], native)
                    assert_removed_baseline(fixture, native["errors"], path)
                    exit_code, local = removed_baseline_cli(fixture, "check")
                    self.assertEqual((1, "BLOCK"), (exit_code, local["state"]), local)
                    assert_removed_baseline(fixture, local["errors"], path)
                    boundary = fixture.history()["contract"]["delivery"]
                    request = {key: boundary[key] for key in ("repository", "target", "pr", "actor", "action", "authority")}
                    request.update(head=head, base=fixture.base_commit, candidate=fixture.current()["sha256"])
                    provider = FakeGitHub(head, fixture.base_commit, None, lambda: False)

                before = fixture.history()
                inspected = fixture.effect(provider, "inspect", request, "inspect-removed-drift")
                print(json.dumps({"head": head, "removed_path": path, "native": native, "local": local,
                                  "inspect": inspected, "calls": provider.calls}, sort_keys=True), flush=True)
                self.assertEqual(("BLOCK", []), (inspected["state"], provider.calls),
                                 "Drifted removed ticket reached provider inspection")
                self.assertEqual([], provider.puts)
                self.assertEqual(0, provider.effects)
                self.assertEqual(before, fixture.history())
                self.assertFalse(any(event["type"] in {"delivery_intent", "delivery_dispatch"}
                                     for event in fixture.history()["events"]))

        for boundary in ("last GET", "original readback"):
            with self.subTest(boundary=boundary):
                fixture, start, removal = self.removed_delivery_fixture()
                local, proofs = complete_removed_reader(fixture, start, "clean-")
                self.assertFalse(local["parent_complete"])
                self.assertEqual(removal["data"]["continuations"], local["continuations"])
                head = fixture.removed_delivery_head()
                provider, request = fixture.provider_for_proofs(local, head, proofs, "clean-audit-")
                inspection = fixture.effect(provider, "inspect", request, "inspect-clean-removal")
                self.assertEqual("PASS", inspection["state"], inspection)
                expected = fixture_membership(fixture.history())
                self.assertEqual(expected, inspection["candidate"]["membership"])
                operation = fixture.prepare_delivery(provider, request)
                self.assertEqual(expected, fixture.event(operation["operation"])["data"]["local"]["membership"])

                if boundary == "last GET":
                    reads = []

                    def drift_after_last_get(argv):
                        reply = provider(argv)
                        if "GET" in argv and any("/check-runs?" in part for part in argv):
                            reads.append(list(argv))
                            if len(reads) == 2:
                                change_removed_path(fixture, "mode")
                        return reply

                    result = fixture.effect(drift_after_last_get, "execute", operation, "removed-drift-during-get")
                    self.assertEqual(2, len(reads), provider.calls)
                    self.assertEqual(("BLOCK", "NO_EFFECT"), (result["state"], result["outcome"]), result)
                    self.assertIs(result["readback"]["put_started"], False)
                    self.assertEqual(([], 0), (provider.puts, provider.effects))
                    dispatch, = (event for event in fixture.history()["events"] if event["type"] == "delivery_dispatch")
                    saved, = (event for event in fixture.history()["events"] if event["type"] == "delivery_result")
                    self.assertEqual((dispatch["id"], "NO_EFFECT", None),
                                     (saved["data"]["dispatch"], saved["data"]["outcome"], saved["data"]["effect"]["put"]))
                else:
                    delivered = fixture.effect(provider, "execute", operation, "deliver-clean-removal")
                    self.assertEqual(("PASS", "INTENDED"), (delivered["state"], delivered["outcome"]), delivered)
                    self.assertEqual("DELIVERED", fixture.ledger.check(a1.RUN)["lifecycle"])
                    change_removed_path(fixture, "mode")
                    result = fixture.effect(provider, "reconcile", operation, "read-original-removal")
                    self.assertEqual(("PASS", "INTENDED"), (result["state"], result["outcome"]), result)
                    self.assertEqual((1, 1), (len(provider.puts), provider.effects))
                after = fixture.ledger.check(a1.RUN)
                self.assertEqual("BLOCK", after["state"], after)
                self.assertFalse(after["parent_complete"])
                print(json.dumps({"boundary": boundary, "result": result, "local": after,
                                  "calls": provider.calls, "puts": provider.puts}, sort_keys=True), flush=True)


    def shared_delivery_fixture(self):
        fixture = self.fresh()
        boundary = {
            "repository": REPOSITORY, "target": TARGET, "pr": PR, "action": "merge_commit",
            "actor": ACTOR, "trusted_check": {"name": CHECK_NAME, "app_id": APP_ID},
            "rules_admin_trust": True, "authority": a1.runtime.reference(fixture.raw),
        }
        start = prepare_shared_reader(fixture, delivery=boundary)
        return fixture, start, remove_shared_server(fixture)

    def test_delivery_requires_shared_path_transition_authority(self):
        with self.subTest(boundary="matching head"):
            fixture, start, removal = self.shared_delivery_fixture()
            change_shared_path(fixture, "server.py", "mode")
            head = fixture.removed_delivery_head()
            self.assertTrue(fixture.git("ls-tree", head, "--", "server.py").startswith("100755 "))
            native = fixture.request_proof("drifted-shared-delivery-green", "A1", start)
            if native["state"] == "PASS":
                local, proofs = complete_removed_reader(fixture, start, "drifted-shared-delivery-", green=native["proof"])
                assert_shared_subset(fixture, local, removal)
                provider, request = fixture.provider_for_proofs(local, head, proofs, "drifted-shared-delivery-audit-")
            else:
                self.assertEqual("BLOCK", native["state"], native)
                assert_shared_grant_refusal(fixture, native["errors"], "server.py")
                exit_code, local = removed_baseline_cli(fixture, "check")
                self.assertEqual((1, "BLOCK"), (exit_code, local["state"]))
                assert_shared_grant_refusal(fixture, local["errors"], "server.py")
                boundary = fixture.history()["contract"]["delivery"]
                request = {key: boundary[key] for key in ("repository", "target", "pr", "actor", "action", "authority")}
                request.update(head=head, base=fixture.base_commit, candidate=fixture.current()["sha256"])
                provider = FakeGitHub(head, fixture.base_commit, None, lambda: False)
            before = fixture.history()
            result = fixture.effect(provider, "inspect", request, "inspect-shared-drift")
            print(json.dumps({"request": request, "native": native, "local": local, "result": result,
                              "calls": provider.calls}, sort_keys=True), flush=True)
            self.assertEqual(("BLOCK", []), (result["state"], provider.calls),
                             "Shared drift reached offline provider inspection")
            self.assertEqual(([], 0), (provider.puts, provider.effects))
            self.assertEqual(before, fixture.history())
            self.assertFalse(any(event["type"] in {"delivery_intent", "delivery_dispatch"}
                                 for event in fixture.history()["events"]))

        for boundary in ("late GET", "original readback"):
            with self.subTest(boundary=boundary):
                fixture, start, removal = self.shared_delivery_fixture()
                local, proofs = complete_removed_reader(fixture, start, "clean-shared-delivery-")
                assert_shared_subset(fixture, local, removal)
                head = fixture.removed_delivery_head()
                provider, request = fixture.provider_for_proofs(local, head, proofs, "clean-shared-delivery-audit-")
                inspected = fixture.effect(provider, "inspect", request, "inspect-clean-shared")
                self.assertEqual("PASS", inspected["state"], inspected)
                expected = fixture_membership(fixture.history())
                self.assertEqual(expected, inspected["candidate"]["membership"])
                operation = fixture.prepare_delivery(provider, request)
                self.assertEqual(expected, fixture.event(operation["operation"])["data"]["local"]["membership"])

                if boundary == "late GET":
                    reads = []

                    def change_after_last_read(argv):
                        reply = provider(argv)
                        if "GET" in argv and any("/check-runs?" in part for part in argv):
                            reads.append(list(argv))
                            if len(reads) == 2:
                                change_shared_path(fixture, "server.py", "mode")
                        return reply

                    result = fixture.effect(change_after_last_read, "execute", operation, "late-shared-drift")
                    self.assertEqual(2, len(reads), provider.calls)
                    self.assertEqual(("BLOCK", "NO_EFFECT"), (result["state"], result["outcome"]), result)
                    self.assertIs(result["readback"]["put_started"], False)
                    self.assertEqual(([], 0), (provider.puts, provider.effects))
                    dispatch, = (event for event in fixture.history()["events"] if event["type"] == "delivery_dispatch")
                    saved, = (event for event in fixture.history()["events"] if event["type"] == "delivery_result")
                    self.assertEqual((dispatch["id"], "NO_EFFECT", None),
                                     (saved["data"]["dispatch"], saved["data"]["outcome"], saved["data"]["effect"]["put"]))
                else:
                    done = fixture.effect(provider, "execute", operation, "deliver-clean-shared")
                    self.assertEqual(("PASS", "INTENDED"), (done["state"], done["outcome"]), done)
                    self.assertEqual("DELIVERED", fixture.ledger.check(a1.RUN)["lifecycle"])
                    change_shared_path(fixture, "server.py", "mode")
                    result = fixture.effect(provider, "reconcile", operation, "read-original-shared-intent")
                    self.assertEqual(("PASS", "INTENDED"), (result["state"], result["outcome"]), result)
                    self.assertEqual((1, 1), (len(provider.puts), provider.effects))
                current = fixture.ledger.check(a1.RUN)
                self.assertEqual("BLOCK", current["state"], current)
                assert_shared_subset(fixture, current, removal)
                print(json.dumps({"boundary": boundary, "result": result, "local": current,
                                  "calls": provider.calls, "puts": provider.puts}, sort_keys=True), flush=True)
