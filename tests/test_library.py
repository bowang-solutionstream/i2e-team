"""Exercise the CLI and actual Git refs using isolated, file-only transports."""
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
PUBLIC_URL = "https://github.com/bowang-solutionstream/i2e-team.git"
PROPERTIES = "i2e-property-libraries"
RULES = "i2e-misses-to-rules"
PROP = "properties/prop-round-trip.md"
RULE = "rules/rule-check-reader.md"
ASTRA = "i2e-astra-sol"
FABLE = "i2e-fable-opus"
OPUS = "i2e-opus-sonnet"


def markdown(path, seen="parser exercise", updated="2026-01-10", status="candidate"):
    if path.startswith("properties/"):
        kind, subtype = "property", "round-trip"
        body = "## Statement\n\nReading an encoded value restores the input.\n"
    else:
        kind, subtype = "rule", "test"
        body = ("## Trigger\n\nA writer changes.\n\n## Check\n\nRun the reader against its output."
                "\n\n## Why it flags\n\nA previous reader may reject that output.\n")
    return (f"---\nid: {Path(path).stem}\nkind: {kind}\ntype: {subtype}\nstatus: {status}\n"
            f"tags: encoding\napplies-to: any\nseen-in: {seen}\nupdated: {updated}\n---\n\n{body}")


def write_json(path, content):
    path.write_text(json.dumps(content), encoding="utf-8")


def file_reference(path, text):
    raw = text.encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def ledger_receipt(version):
    payload = {"schema": f"i2e-team-check-v{version}", "state": "PASS", "errors": [],
               "candidate": {"sha256": hashlib.sha256(b"successful local candidate").hexdigest()}, "seq": 19}
    if version == 2:
        payload["ready"] = True
    return payload


def critical_receipt():
    return {"schema": "i2e-critical-run-v1", "phase": "complete", "acceptance_current": True,
            "checks": {name: {"result": "PASS", "exit_code": 0} for name in ("lint", "e2e")}}


# A native controller test double checks the actual argument order and emits the
# supplied native receipts. Its optional second-call barrier orders real Git pushes.
CONTROLLER = """\
import json
from pathlib import Path
import sys
import time

args = sys.argv[1:]
if len(args) == 5 and args[:2] == ["check", "--db"] and args[3] == "--run":
    kind, run = "ledger", args[4]
elif len(args) == 4 and args[:2] == ["critical", "--state"] and args[3] == "status":
    kind, run = "critical", None
else:
    sys.exit(2)
state = Path(args[2])
data = json.loads(state.read_text())
if not state.is_absolute() or [kind, run] != [data["kind"], data["run"]]:
    sys.exit(3)
calls = state.with_suffix(".calls")
with calls.open("a") as stream:
    stream.write("called\\n")
number = len(calls.read_text().splitlines())
if data["pause"] and number == 2:
    state.with_suffix(".ready").touch()
    deadline = time.monotonic() + 30
    while not state.with_suffix(".release").exists():
        if time.monotonic() > deadline:
            sys.exit(4)
        time.sleep(0.02)
reports = data["reports"]
report = reports[min(number, len(reports)) - 1]
print(json.dumps(report))
sys.exit(data["exit_code"])
"""


class LibraryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="i2e-library-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.remote = self.root / "remote.git"
        self.checkout = self.root / "installed-library"
        self.env = {
            "PATH": os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Fixture Author",
            "GIT_COMMITTER_NAME": "Fixture Committer",
            "GIT_AUTHOR_EMAIL": "fixture-author@example.invalid",
            "GIT_COMMITTER_EMAIL": "fixture-committer@example.invalid",
        }
        self.git(self.root, "config", "--global", f"url.{self.remote.as_uri()}.insteadOf", PUBLIC_URL)
        self.git(self.root, "init", "--quiet", "--bare", "--initial-branch=main", self.remote)
        self.git(self.root, "init", "--quiet", "--initial-branch=main", self.checkout)
        (self.checkout / "tools").mkdir()
        for name in ("delivery.py", "records.py", "library.py"):
            shutil.copyfile(SOURCE / "tools" / name, self.checkout / "tools" / name)
        for name in ("README.md", "rules/README.md", "properties/README.md"):
            path = self.checkout / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"Fixture for {name}\n", encoding="utf-8")
        self.git(self.checkout, "add", ".")
        self.git(self.checkout, "commit", "--quiet", "-m", "Seed independent library fixture")
        self.git(self.checkout, "remote", "add", "origin", PUBLIC_URL)
        self.git(self.checkout, "push", "--atomic", "origin", "main",
                 f"main:refs/heads/{PROPERTIES}", f"main:refs/heads/{RULES}")
        self.seed = self.git(self.checkout, "rev-parse", "HEAD")
        self.controller = self.root / "controller.py"
        self.controller.write_text(CONTROLLER, encoding="utf-8")

    def git(self, directory, *args):
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", directory, *args],
                                env=self.env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.rstrip("\n")

    def refs(self):
        lines = self.git(self.remote, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
        return dict(line.split() for line in lines.splitlines())

    def remote_text(self, branch, path):
        return self.git(self.remote, "show", f"{branch}:{path}") + "\n"

    def assert_ancestor(self, older, newer):
        self.git(self.remote, "merge-base", "--is-ancestor", older, newer)

    def drafts(self, files):
        root = Path(tempfile.mkdtemp(dir=self.root))
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return root

    def handoff(self, workflow=FABLE):
        private = Path(tempfile.mkdtemp(dir=self.root))
        source = file_reference(private / "delivered.txt", "Fixture implementation\n")
        deletion = {"path": str(private / "removed.txt"), "sha256": None}
        check = file_reference(private / "check.log", "1 test passed\n")
        review = file_reference(private / "review.log", "Reviewed the final implementation.\n")
        manifest = {"workflow": workflow, "status": "PASS", "sources": [source, deletion],
                    "checks": [dict(check, name="reader tests", status="PASS")],
                    "review": dict(review, verdict="APPROVE")}
        path = private / "handoff.json"
        write_json(path, manifest)
        return ["--workflow", workflow, "--handoff", path]

    def native(self, kind, reports, *, run="local-run", exit_code=0, pause=False):
        private = Path(tempfile.mkdtemp(dir=self.root))
        state = private / "input.json"
        write_json(state, {"kind": kind, "run": run if kind == "ledger" else None,
                           "reports": reports, "exit_code": exit_code, "pause": pause})
        flags = ["--state", state] if kind == "critical" else ["--db", state, "--run", run]
        return ["--workflow", ASTRA, "--i2e", self.controller, *flags], state

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", self.checkout / "tools/library.py", *args],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(result.returncode, 0 if success else 1, (result.stdout, result.stderr))
        try:
            return json.loads(result.stdout)
        except ValueError:
            self.fail(f"Library CLI did not return JSON: {result.stdout!r} {result.stderr!r}")

    def reflect(self, drafts, adapter=None, *, success=True):
        return self.cli("reflect", "--entries", drafts, *(adapter or self.handoff()), success=success)

    def assert_refusal(self, drafts, adapter, status="BLOCKED"):
        before = self.refs()
        result = self.reflect(drafts, adapter, success=False)
        self.assertEqual(result["status"], status, result)
        self.assertEqual(self.refs(), before)
        return result

    def test_both_topics_merge_into_main_with_isolated_history(self):
        entries = {PROP: markdown(PROP), RULE: markdown(RULE)}
        receipt = self.reflect(self.drafts(entries))
        heads = self.refs()
        self.assertEqual(receipt["status"], "MERGED")
        self.assertEqual(receipt["main"], heads["main"])
        self.assertEqual(set(receipt["branches"]), {PROPERTIES, RULES})
        self.assertEqual(set(receipt["entries"]), set(entries))
        for topic, name in ((PROPERTIES, PROP), (RULES, RULE)):
            self.assertEqual(self.git(self.remote, "diff", "--name-only", self.seed, topic), name)
            self.assertEqual(self.remote_text(topic, name), entries[name])
            self.assertEqual(self.remote_text("main", name), entries[name])
            self.assert_ancestor(heads[topic], heads["main"])
        merges = self.git(self.remote, "rev-list", "--first-parent", "--parents", f"{self.seed}..main")
        parents = [line.split() for line in merges.splitlines()]
        self.assertEqual([len(line) for line in parents], [3, 3])
        self.assertEqual(parents[0][1], parents[1][0])
        self.assertEqual(parents[1][1], self.seed)
        self.assertEqual({line[2] for line in parents}, {heads[PROPERTIES], heads[RULES]})
        identities = self.git(self.remote, "log", f"{self.seed}..main", "--format=%an <%ae>|%cn <%ce>")
        public_identity = "I2E Library <i2e-library@users.noreply.github.com>"
        self.assertEqual(set(identities.splitlines()), {f"{public_identity}|{public_identity}"})
        self.assertEqual(self.git(self.remote, "diff", "--name-only", self.seed, "main").splitlines(),
                         sorted(entries))

    def test_each_single_category_leaves_other_topic_at_its_last_commit(self):
        for path, branch, other in ((PROP, PROPERTIES, RULES), (RULE, RULES, PROPERTIES)):
            with self.subTest(path=path):
                before = self.refs()
                receipt = self.reflect(self.drafts({path: markdown(path)}))
                after = self.refs()
                self.assertEqual(receipt["branches"], [branch])
                self.assertEqual(before[other], after[other])
                self.assertNotEqual(before[branch], after[branch])
                self.assertEqual(self.git(self.remote, "show", "-s", "--format=%P", "main").split(),
                                 [before["main"], after[branch]])
                self.assert_ancestor(before[branch], after[branch])
        self.assertEqual(self.remote_text("main", PROP), markdown(PROP))

    def test_empty_repeated_and_new_sightings(self):
        initial = self.refs()
        self.assertEqual(self.reflect(self.drafts({}))["status"], "NO_CHANGES")
        self.assertEqual(self.refs(), initial)
        first = self.drafts({PROP: markdown(PROP)})
        self.assertEqual(self.reflect(first)["status"], "MERGED")
        initial = self.refs()
        different_case = self.drafts({PROP: markdown(PROP, seen="PARSER Exercise", updated="2026-01-15")})
        for replay in (first, different_case):
            self.assertEqual(self.reflect(replay)["status"], "NO_CHANGES")
            self.assertEqual(self.refs(), initial)
        latest = self.drafts({PROP: markdown(PROP, seen="PARSER Exercise, reader exercise", updated="2026-01-01")})
        self.assertEqual(self.reflect(latest)["status"], "MERGED")
        expected = markdown(PROP, seen="parser exercise, reader exercise")
        self.assertEqual(self.remote_text("main", PROP), expected)
        self.assertEqual(self.remote_text(PROPERTIES, PROP), expected)
        after = self.refs()
        self.assertEqual(self.reflect(latest)["status"], "NO_CHANGES")
        self.assertEqual(self.refs(), after)

    def test_catalog_reads_installed_commit_even_when_remote_and_worktree_differ(self):
        self.reflect(self.drafts({PROP: markdown(PROP)}))
        (self.checkout / RULE).write_text("Uncommitted draft", encoding="utf-8")
        self.assertEqual(self.cli("catalog"), {"entries": [], "revision": self.seed})
        self.git(self.checkout, "pull", "--ff-only", "origin", "main")
        catalog = self.cli("catalog", "--status", "candidate")
        self.assertEqual(catalog["revision"], self.refs()["main"])
        self.assertEqual([entry["path"] for entry in catalog["entries"]], [PROP])
        self.assertEqual(self.cli("catalog", "--status", "adopted")["entries"], [])

    def test_conflicting_definition_or_alias_blocks_entire_submission(self):
        self.reflect(self.drafts({PROP: markdown(PROP)}))
        alias = "properties/prop-reader-identity.md"
        changed = markdown(PROP, seen="new observation").replace("restores the input", "yields a constant")
        duplicate = markdown(alias).replace("Reading an encoded", "READING  an encoded")
        for path, draft in ((PROP, changed), (alias, duplicate)):
            with self.subTest(path=path):
                self.assert_refusal(self.drafts({path: draft, RULE: markdown(RULE)}), self.handoff())

    def test_private_content_and_misplaced_draft_are_never_published(self):
        for name, text in ((PROP, markdown(PROP) + "Contact the fixture at sample@example.invalid.\n"),
                           (PROP, markdown(PROP) + "api_key: synthetic-fixture-only\n"),
                           ("notes/raw.md", "Private run notes")):
            with self.subTest(name=name, text=text[-32:]):
                refusal = self.assert_refusal(self.drafts({name: text, RULE: markdown(RULE)}), self.handoff())
                self.assertNotIn("sample@example.invalid", str(refusal))
                self.assertNotIn("synthetic-fixture-only", str(refusal))

    def test_reflection_preserves_curated_status(self):
        for path in (PROP, RULE):
            with self.subTest(path=path):
                adoption = markdown(path, seen="first change, second change", status="adopted")
                self.assert_refusal(self.drafts({path: adoption}), self.handoff())
                first = self.reflect(self.drafts({path: markdown(path, seen="first change")}))
                self.assertEqual(first["status"], "MERGED")
                sighting = self.reflect(self.drafts({path: adoption}))
                self.assertEqual(sighting["status"], "MERGED")
                self.assertEqual(self.remote_text("main", path), markdown(path, seen="first change, second change"))

    def test_unmerged_category_work_blocks_mixed_reflection(self):
        self.git(self.checkout, "switch", "--detach", self.seed)
        (self.checkout / RULE).write_text(markdown(RULE), encoding="utf-8")
        self.git(self.checkout, "add", RULE)
        self.git(self.checkout, "commit", "--quiet", "-m", "Outstanding category work")
        self.git(self.checkout, "push", "origin", f"HEAD:refs/heads/{RULES}")
        self.assert_refusal(self.drafts({PROP: markdown(PROP), RULE: markdown(RULE)}),
                            self.handoff(), status="PENDING")

    def test_remote_without_atomic_push_leaves_all_refs_untouched(self):
        self.git(self.remote, "config", "receive.advertiseAtomic", "false")
        self.assert_refusal(self.drafts({PROP: markdown(PROP), RULE: markdown(RULE)}),
                            self.handoff(), status="PENDING")

    def test_publisher_honors_configured_pre_push_policy(self):
        hooks = self.root / "policy-hooks"
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o700)
        self.git(self.root, "config", "--global", "core.hooksPath", str(hooks))
        self.assert_refusal(self.drafts({PROP: markdown(PROP)}), self.handoff(), status="PENDING")

    def test_both_claude_workflows_verify_hashed_delivery_and_deletion(self):
        for workflow in (FABLE, OPUS):
            with self.subTest(workflow=workflow):
                result = self.reflect(self.drafts({PROP: markdown(PROP, seen=workflow)}), self.handoff(workflow))
                self.assertEqual(result["status"], "MERGED")
        self.assertEqual(self.remote_text("main", PROP), markdown(PROP, seen=f"{FABLE}, {OPUS}"))

    def test_failed_missing_or_stale_handoff_evidence_does_not_move_refs(self):
        drafts = self.drafts({PROP: markdown(PROP)})
        for defect in ("wrong workflow", "failed handoff", "failed check", "rejected review", "missing checks",
                       "changed source", "changed check", "changed review", "restored deletion"):
            with self.subTest(defect=defect):
                adapter = self.handoff(OPUS)
                path = adapter[-1]
                handoff = json.loads(path.read_bytes())
                if defect == "wrong workflow":
                    handoff["workflow"] = FABLE
                elif defect == "failed handoff":
                    handoff["status"] = "FAIL"
                elif defect == "failed check":
                    handoff["checks"][0]["status"] = "FAIL"
                elif defect == "rejected review":
                    handoff["review"]["verdict"] = "REJECT"
                elif defect == "missing checks":
                    handoff["checks"] = []
                else:
                    targets = {"changed source": handoff["sources"][0], "changed check": handoff["checks"][0],
                               "changed review": handoff["review"], "restored deletion": handoff["sources"][1]}
                    Path(targets[defect]["path"]).write_text("Changed since acceptance\n", encoding="utf-8")
                write_json(path, handoff)
                self.assert_refusal(drafts, adapter)

    def test_native_direct_standard_and_critical_controller_contracts(self):
        cases = (("direct", "ledger", ledger_receipt(1)), ("standard", "ledger", ledger_receipt(2)),
                 ("critical", "critical", critical_receipt()))
        for lane, kind, payload in cases:
            with self.subTest(lane=lane):
                adapter, state = self.native(kind, [payload], run=lane)
                result = self.reflect(self.drafts({PROP: markdown(PROP, seen=lane)}), adapter)
                self.assertEqual(result["status"], "MERGED")
                self.assertEqual(len(state.with_suffix(".calls").read_text().splitlines()), 2)

    def test_failed_partial_and_stale_native_receipts_do_not_move_refs(self):
        bad_lint = critical_receipt()
        bad_lint["checks"]["lint"]["exit_code"] = 1
        v2_missing_ready = ledger_receipt(2)
        del v2_missing_ready["ready"]
        failures = [
            ("ledger", [dict(ledger_receipt(1), state="BLOCK")], 0),
            ("ledger", [dict(ledger_receipt(2), ready=False)], 0),
            ("ledger", [v2_missing_ready], 0),
            ("ledger", [{"state": "PASS"}], 0),
            ("ledger", [[]], 0),
            ("ledger", [ledger_receipt(2)], 1),
            ("critical", [dict(critical_receipt(), phase="verify")], 0),
            ("critical", [dict(critical_receipt(), acceptance_current=False)], 0),
            ("critical", [bad_lint], 0),
            ("critical", [critical_receipt(), dict(critical_receipt(), acceptance_current=False)], 0),
        ]
        drafts = self.drafts({PROP: markdown(PROP), RULE: markdown(RULE)})
        for kind, reports, exit_code in failures:
            with self.subTest(kind=kind, reports=reports, exit_code=exit_code):
                adapter, state = self.native(kind, reports, exit_code=exit_code)
                self.assert_refusal(drafts, adapter)
                self.assertEqual(len(state.with_suffix(".calls").read_text().splitlines()), len(reports))

    def test_concurrent_sightings_retry_from_latest_and_preserve_both(self):
        self.reflect(self.drafts({PROP: markdown(PROP)}))
        baseline = self.refs()
        jobs = []
        for name in ("first reader", "second reader"):
            adapter, state = self.native("ledger", [ledger_receipt(2)], run=name, pause=True)
            jobs.append((self.drafts({PROP: markdown(PROP, seen=name)}), adapter, state))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            submissions = [pool.submit(self.reflect, drafts, adapter) for drafts, adapter, _ in jobs]
            try:
                deadline = time.monotonic() + 20
                while not all(state.with_suffix(".ready").exists() for _, _, state in jobs):
                    for submission in submissions:
                        if submission.done():
                            self.fail(f"Submission stopped before the shared push barrier: {submission.result()}")
                    if time.monotonic() >= deadline:
                        self.fail("Submissions did not reach their shared push barrier")
                    time.sleep(0.02)
                jobs[0][2].with_suffix(".release").touch()
                winner = submissions[0].result(timeout=20)
            finally:
                for _, _, state in jobs:
                    state.with_suffix(".release").touch()
            retried = submissions[1].result(timeout=20)
        self.assertEqual([winner["status"], retried["status"]], ["MERGED", "MERGED"])
        self.assertGreaterEqual(len(jobs[1][2].with_suffix(".calls").read_text().splitlines()), 3)
        heads = self.refs()
        self.assertEqual(heads[RULES], baseline[RULES])
        self.assert_ancestor(winner["main"], heads["main"])
        self.assert_ancestor(baseline[PROPERTIES], heads[PROPERTIES])
        self.assert_ancestor(heads[PROPERTIES], heads["main"])
        expected = markdown(PROP, seen="parser exercise, first reader, second reader")
        self.assertEqual(self.remote_text("main", PROP), expected)
        self.assertEqual(self.remote_text(PROPERTIES, PROP), expected)


if __name__ == "__main__":
    unittest.main()
