"""Disposable worker setup, phase grants and local Git admission for the label pilot."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import test_four_behavior_repair as a1
from test_i2e_v2_runtime import WorkflowFixture, manifest


COMMIT_PROGRAM = """
def commit(path):
    for args in (
        ['add', '--', path],
        ['-c', 'user.name=Worker fixture', '-c', 'user.email=fixture@example.invalid',
         'commit', '--no-gpg-sign', '-m', 'Synthetic worker change'],
    ):
        subprocess.run(['/usr/bin/git', *args], check=True)
"""


class WorkerV2Tests(WorkflowFixture):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory
        register_cleanup = self.addCleanup

        def preserve_fixture(callback, *args, **kwargs):
            directory = getattr(self, "temp", None)
            if directory is None or callback != directory.cleanup:
                register_cleanup(callback, *args, **kwargs)

        # Preserve the actual contained process artifacts for replay. Only the
        # explicit cleanup test removes an admitted, never-dispatched clone.
        with (
            patch.object(tempfile, "TemporaryDirectory", side_effect=lambda **kw: temporary(delete=False, **kw)),
            patch.object(self, "addCleanup", side_effect=preserve_fixture),
        ):
            super().setUp()
        print("retained synthetic worker fixture", self.root, flush=True)
        self.contract_extras["authority"] = {
            "actions": ["edit", "worker", "cleanup"], "evidence": a1.runtime.reference(self.raw),
        }
        directory = self.repo / "feature-tests"
        directory.mkdir()
        (directory / ".keep").write_text("registered fixture parent\n")
        self.git("add", "--", "feature-tests/.keep")
        self.git("-c", "user.name=Worker fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Synthetic test parent", "--no-gpg-sign")
        self.base_commit = self.git("rev-parse", "HEAD").strip()
        boundary = self.contract()["write_boundary"]
        boundary["surfaces"] = [{"path": "feature-tests", "kind": "directory", "role": "test", "ticket": "fixture-ticket"}]
        self.contract_extras["write_boundary"] = boundary
        self.prepare_plan()

    def worker_argv(self, operation, sequence):
        return [a1.PYTHON, "-B", str(a1.base.SCRIPT), "worker", operation,
                "--db", str(self.db), "--run", a1.RUN, "--expect", str(sequence), "--input", "-"]

    def worker(self, operation, label, *, passing=True, cli=True, expected_seq=None, **fields):
        request = {"id": label, "actor": a1.ACTOR, **fields}
        sequence = self.history()["seq"] if expected_seq is None else expected_seq
        if cli:
            argv = self.worker_argv(operation, sequence)
            completed = subprocess.run(argv, cwd=self.repo, input=json.dumps(request),
                                       text=True, capture_output=True, timeout=60, check=False)
            self.assertEqual(passing, completed.returncode == 0, {
                "argv": argv, "request": request, "exit": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr,
            })
            result = json.loads(completed.stdout)
        else:
            result = self.ledger.worker(a1.RUN, operation, sequence, request)
        if passing:
            self.assertEqual("PASS", result["state"], result)
        else:
            self.assertIn(result["state"], {"BLOCK", "HOLD"}, result)
        return result

    def prepare_attempt(self, attempt, start, *, predecessor=None, qualify=True):
        result = self.worker("prepare", "prepare-" + attempt, attempt=attempt, ticket="fixture-ticket",
                             start=start, predecessor=predecessor or self.base_commit, mode=a1.EXECUTOR)
        data = result["attempt"]
        root = Path(data["root"])
        self.assertEqual(root, root.resolve())
        self.assertNotEqual(self.repo, root)
        self.assertTrue((root / ".git").is_dir())
        self.assertFalse((root / ".git" / "objects" / "info" / "alternates").exists())
        self.assertNotEqual((root / ".git").stat().st_ino, (self.repo / ".git").stat().st_ino)
        if qualify:
            self.worker("qualify", "qualify-" + attempt, attempt=attempt)
        return data

    def run_script(self, attempt, program, *args, passing=True, cli=True):
        return self.worker("run", "run-" + attempt, passing=passing, cli=cli, attempt=attempt,
                           command=[a1.PYTHON, "-B", "-c", program, *map(str, args)])

    def commit_from(self, attempt):
        return self.git("-C", attempt["root"], "rev-parse", "HEAD").strip()

    def submit(self, attempt, commit, *, passing=True):
        return self.worker("submit", "submit-" + attempt, attempt=attempt, commit=commit,
                           passing=passing)["submission"] if passing else self.worker(
                               "submit", "stale-submit-" + attempt, attempt=attempt, commit=commit, passing=False,
                           )

    def test_unknown_mode_unregistered_path_and_cleanup_without_quiescence_hold(self):
        self.open_phase("test-phase", "TEST_ONLY", ["A1"])
        self.worker("prepare", "unsupported-mode", attempt="unsupported", ticket="fixture-ticket",
                    start="test-phase", predecessor=self.base_commit, mode="native-collaboration", passing=False)
        attempt = self.prepare_attempt("cleanup-generation", "test-phase", qualify=False)
        clone = Path(attempt["root"])
        self.worker("run", "unqualified-run", attempt="cleanup-generation",
                    command=[a1.PYTHON, "-B", "-c", "raise SystemExit('not expected to run')"], passing=False)
        (clone / ".git" / "info").mkdir(exist_ok=True)
        (clone / ".git" / "info" / "exclude").write_text("untracked-evidence.txt\n")
        ignored = clone / "untracked-evidence.txt"
        ignored.write_text("preserve fixture evidence\n")
        self.worker("cleanup", "ignored-cleanup", attempt="cleanup-generation", retained_commit=self.base_commit,
                    passing=False)
        self.assertEqual("preserve fixture evidence\n", ignored.read_text())

    def test_never_dispatched_clean_clone_can_be_retained_and_removed(self):
        self.open_phase("test-phase", "TEST_ONLY", ["A1"])
        attempt = self.prepare_attempt("disposable", "test-phase", qualify=False)
        result = self.worker("cleanup", "clean-inactive", attempt="disposable", retained_commit=self.base_commit)
        self.assertFalse(Path(attempt["root"]).exists())
        self.assertGreater(result["reclaimed_bytes"], 0)
        self.assertEqual(self.base_commit, self.git("rev-parse", "HEAD").strip())

    def test_manifest_addition_requires_new_generation_before_actual_write(self):
        path = "feature-tests/extra.py"
        self.open_phase("initial-test", "TEST_ONLY", ["A1"])
        old = self.prepare_attempt("initial-scope", "initial-test")
        guarded = """import sys
from pathlib import Path
try:
    Path(sys.argv[1]).write_text('fixture bytes')
except PermissionError:
    print('unregistered denied')
"""
        first = self.run_script("initial-scope", guarded, path)
        _, initial = self.read_receipt(first["receipt"])
        self.assertIn(b"unregistered denied", initial)
        rows = [manifest(a1.SHARED_TEST, "fixture-ticket", "test", None),
                manifest(path, "fixture-ticket", "test", None)]
        observed = self.observe_paths("observe-expanded-test", ["A1"], [rows[1]])
        self.assertEqual([], observed["data"]["write_scope"])
        self.assertIsNone(observed["data"]["candidate"]["files"][path])
        admitted = self.ledger.preflight(a1.RUN, "TEST_ONLY", self.history()["seq"], {
            "id": "expanded-test", "acceptance": ["A1"], "write_manifest": rows,
        })
        self.assertEqual("PASS", admitted["state"], admitted)
        new = self.prepare_attempt("expanded-scope", "expanded-test")
        self.assertNotEqual(old["root"], new["root"])
        self.assertGreater(new["generation"], old["generation"])
        self.run_script("expanded-scope", guarded, path)
        self.assertFalse((Path(old["root"]) / path).exists())
        self.assertEqual("fixture bytes", (Path(new["root"]) / path).read_text())
        self.assertFalse((self.repo / path).exists())
