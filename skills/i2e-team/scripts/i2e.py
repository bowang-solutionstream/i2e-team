#!/usr/bin/env python3
"""Local consistency helpers for the distinct I2E team profile.

These helpers do not authenticate agents, grant authority, or execute evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import runpy
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path


POLICY_SCHEMA = "i2e-team-policy-v1"
V1_MODELS = {"sol": "gpt-6.1-sol", "astra": "gpt-6-astra"}
AMENDED_PHASES = True
TRIGGERS = (
    "consequential_authorization_or_tenant",
    "destructive_migration",
    "critical_financial_behavior",
    "uncertain_cross_system_interaction",
    "material_redesign",
    "conflicting_reviews",
    "user_or_project_requirement",
)
MAX_JSON_BYTES = 524_288
MAX_FILE_BYTES = 8 * 1024 * 1024
PROOF_TIMEOUT_SECONDS = 1800
ROLLOUT_SCHEMA = "i2e-team-rollout-v1"
MAX_ROLLOUT_BYTES = 512 * 1024 * 1024
EVENT_TYPES = {
    "observation", "checkpoint", "correction", "withdrawal", "supersession",
    "plan", "plan_review", "decision", "doubt_review", "disposition",
    "audit", "final_review", "case_decision", "failure", "repair", "escalation",
    "human_decision", "teaching", "recheck",
}
INTERNAL_TYPES = {"start", "proof", "consultation", "capture_intent", "case_link", "operation_gap", "lookup_intent", "lookup_progress"}
REVIEW_TYPES = {"plan_review", "doubt_review", "audit", "final_review", "recheck", "escalation"}
V2_INTERNAL_TYPES = {
    "case_binding", "proof_attempt", "worker_attempt", "worker_qualification",
    "worker_dispatch_intent", "worker_dispatch_result", "worker_submission", "worker_revocation",
    "worker_admission_intent", "worker_admission_result", "worker_cleanup_intent", "worker_cleanup_result",
    "delivery_intent", "delivery_dispatch", "delivery_result",
}
V2_EVENT_TYPES = {"batch_membership", "handoff", "failure_classification"}


def _is_v2(state):
    return state["contract"]["schema"] == "i2e-team-run-v2"


@lru_cache(maxsize=1)
def _v2():
    # The v1 loader can execute this entrypoint as a standalone file or through
    # importlib without a package. Resolve the v2 siblings only on v2 selection.
    import importlib.util
    from types import SimpleNamespace

    modules = {}
    for name in ("v2_contract", "worker_adapter", "github_adapter", "v2_runtime"):
        path = _safe_path(Path(__file__).absolute().with_name(name + ".py"))
        spec = importlib.util.spec_from_file_location("i2e_team_" + name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("v2 component loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules["v2_runtime"].Runtime(
        SimpleNamespace(**globals()), modules["v2_contract"], modules["worker_adapter"], modules["github_adapter"],
    )


class RuntimeError(Exception):
    """A bounded local evidence or consistency failure."""


def canonical(value: object) -> bytes:
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise RuntimeError("value is not bounded strict JSON") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise RuntimeError("JSON record exceeds byte limit")
    return encoded


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _safe_path(path) -> Path:
    target = Path(path).expanduser().absolute()
    if ".." in target.parts:
        raise RuntimeError("traversal spellings are not canonical paths")
    for part in (target, *target.parents):
        if part.is_symlink():
            raise RuntimeError("symlink paths are not permitted")
    return target


def _file_bytes(path, *, reject_links=True) -> bytes:
    target = _safe_path(path)
    if not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
        raise RuntimeError("evidence must be a regular local file")
    if reject_links and target.stat().st_nlink != 1:
        raise RuntimeError("private evidence and declared source may not escape through hardlinks")
    with target.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise RuntimeError("local file exceeds byte limit")
    return data


def reference(path) -> dict:
    return {"path": str(_safe_path(path)), "sha256": hashlib.sha256(_file_bytes(path)).hexdigest()}


def verify_reference(ref) -> bool:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise RuntimeError("evidence reference must contain path and sha256")
    if not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute():
        raise RuntimeError("evidence path must be absolute")
    if reference(ref["path"]) != ref:
        raise RuntimeError("local evidence is missing or changed")
    return True


def _paths(values) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > 128:
        raise RuntimeError("literal path manifest must be a bounded list")
    for value in values:
        if not isinstance(value, str) or not value or value.startswith("/") or any(c in value for c in "\\*?[]\x00"):
            raise RuntimeError("scope must use literal relative paths")
        parts = value.split("/")
        if any(p in {"", ".", "..", ".git"} for p in parts):
            raise RuntimeError("scope may not traverse or read Git internals")
        if any(p == ".env" or p.startswith(".env.") or p.endswith((".pem", ".key")) for p in parts):
            raise RuntimeError("sensitive files are not allowed in manifests")
    if len(values) != len(set(values)):
        raise RuntimeError("manifest paths must be unique")
    return list(values)


def snapshot(repo, scope, instructions=()) -> dict:
    root = _safe_path(repo)
    if not root.is_dir():
        raise RuntimeError("source repository is unavailable")
    result = {"repo": str(root), "files": {}, "instructions": {}}
    for group, names in (("files", scope), ("instructions", instructions)):
        for name in _paths(names):
            path = _safe_path(root / name)
            if not path.exists() and group == "files":
                result[group][name] = None
            else:
                result[group][name] = hashlib.sha256(_file_bytes(path)).hexdigest()
    result["sha256"] = digest(result)
    return result


def profile_identity() -> dict:
    """Observe the active distributed profile; callers cannot omit guidance."""
    root = _safe_path(Path(__file__).absolute().parents[1])
    files = {}
    for directory, names, leaves in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name != "__pycache__")
        for name in names:
            _safe_path(Path(directory) / name)
        for name in sorted(leaves):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(directory) / name
            # The guarded installer retains an owned inode anchor to SKILL.md.
            # This manifest verifies payload bytes, not private evidence ownership.
            files[str(path.relative_to(root))] = hashlib.sha256(_file_bytes(path, reject_links=False)).hexdigest()
            if len(files) > 128:
                raise RuntimeError("active profile exceeds file manifest limit")
    if not {"SKILL.md", "scripts/i2e.py"} <= set(files):
        raise RuntimeError("active profile entrypoint or runtime is missing")
    return {"root": str(root), "files": files, "sha256": digest(files)}


def _label(value, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value):
        raise RuntimeError(f"{name} must be a stable nonempty identifier")
    return value


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Ledger:
    def __init__(self, db):
        self.db = _safe_path(db)

    def _privacy(self, contract):
        root = _safe_path(contract["repo"])
        package = _safe_path(Path(__file__).absolute().parents[1])
        directories = [_safe_path(contract["case_store"]), _safe_path(self.db.parent / "evidence")]
        for private in [self.db, *directories]:
            for public in (root, package):
                if private.is_relative_to(public) or (private in directories and public.is_relative_to(private)):
                    raise RuntimeError("complete private storage footprint overlaps source or skill package")
        if self.db.exists() and (not self.db.is_file() or self.db.stat().st_nlink != 1):
            raise RuntimeError("database must be a private regular file without hardlinks")

    def _evidence_root(self, run_id):
        return _safe_path(self.db.parent / "evidence" / hashlib.sha256(run_id.encode()).hexdigest())

    @contextlib.contextmanager
    def _connection(self, create=False):
        _safe_path(self.db)
        if not self.db.exists():
            if not create:
                raise RuntimeError("run database is unavailable")
            self.db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        if self.db.stat().st_nlink != 1 or self.db.stat().st_mode & 0o077:
            raise RuntimeError("run database must be private and have one local link")
        conn = sqlite3.connect(str(self.db), timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            if create:
                conn.executescript('''
                    CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, contract TEXT NOT NULL, sha256 TEXT NOT NULL, profile TEXT NOT NULL, initial_source TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS events(run_id TEXT NOT NULL REFERENCES runs(run_id), seq INTEGER NOT NULL,
                        event_id TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                        PRIMARY KEY(run_id,seq), UNIQUE(run_id,event_id));
                    CREATE TABLE IF NOT EXISTS artifact_publications(run_id TEXT NOT NULL REFERENCES runs(run_id),
                        object_sha256 TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                        PRIMARY KEY(run_id,object_sha256));
                    CREATE TRIGGER IF NOT EXISTS immutable_runs_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT,'immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS immutable_runs_delete BEFORE DELETE ON runs BEGIN SELECT RAISE(ABORT,'immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS immutable_artifacts_update BEFORE UPDATE ON artifact_publications BEGIN SELECT RAISE(ABORT,'immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS immutable_artifacts_delete BEFORE DELETE ON artifact_publications BEGIN SELECT RAISE(ABORT,'immutable'); END;
                ''')
            yield conn
        except (sqlite3.Error, OSError) as exc:
            raise RuntimeError(f"local ledger operation failed: {exc}") from exc
        finally:
            conn.close()

    def _read(self, conn, run_id):
        row = conn.execute("SELECT contract,sha256,profile,initial_source FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise RuntimeError("unknown run")
        contract = json.loads(row[0])
        initial_profile = json.loads(row[2])
        initial_source = json.loads(row[3])
        self._privacy(contract)
        if digest({"contract": contract, "profile": initial_profile, "initial_source": initial_source}) != row[1]:
            raise RuntimeError("run contract digest mismatch")
        # The stored routing revision participates in the ledger hash. Source
        # drift comparisons use only the profile observed on disk.
        routing = {}
        if "critical_workflow" in initial_profile:
            routing["critical_workflow"] = initial_profile.pop("critical_workflow")
        events, previous = [], row[1]
        for seq, encoded, claimed in conn.execute("SELECT seq,payload,sha256 FROM events WHERE run_id=? ORDER BY seq", (run_id,)):
            event = json.loads(encoded)
            if seq != len(events) + 1 or event.get("seq") != seq or event.get("previous_sha256") != previous or digest(event) != claimed:
                raise RuntimeError("ledger prefix or event digest mismatch")
            previous = claimed
            events.append(dict(event, sha256=claimed))
        if contract.get("schema") not in {"i2e-team-run-v1", "i2e-team-run-v2"}:
            raise RuntimeError("unknown persisted run schema")
        result = {**routing, "contract": contract, "initial_profile": initial_profile, "initial_source": initial_source, "events": events, "seq": len(events), "sha256": previous,
                  "current_annotations": [e for e in events if e["type"] in {"correction", "withdrawal", "supersession"}],
                  "evidence_root": str(self._evidence_root(run_id))}
        if _is_v2(result):
            result["ledger_path"] = str(self.db)
        return result

    def init_run(self, contract, *, historical_profile=False):
        if isinstance(contract, dict) and contract.get("schema") == "i2e-team-run-v2":
            runtime = _v2()
            runtime.contract.validate_run(contract, runtime.core)
            self._privacy(contract)
            runtime.validate_predecessor({"contract": contract, "ledger_path": str(self.db)})
            initial_source = runtime.snapshot({"contract": contract, "events": []})
        else:
            required = {"schema", "run_id", "project", "repo", "scope", "test_scope", "instructions", "contributors", "authority", "policy", "case_store", "case_helper", "case_helper_sha256", "known_cases"}
            if not isinstance(contract, dict) or set(contract) != required or contract.get("schema") != "i2e-team-run-v1":
                raise RuntimeError("unsupported or incomplete run contract")
            _label(contract["run_id"], "run_id")
            _label(contract["project"], "project")
            root = _safe_path(contract["repo"])
            self._privacy(contract)
            initial_source = snapshot(root, contract["scope"], contract["instructions"])
            if not set(_paths(contract["test_scope"])) <= set(contract["scope"]):
                raise RuntimeError("immutable test_scope must be an explicit subset of owned source")
            if not contract["contributors"] or not isinstance(contract["contributors"], list):
                raise RuntimeError("actual contributor sessions are required")
            for session in contract["contributors"]:
                _label(session, "contributor")
            if evaluate_policy(contract["policy"])["state"] != "PASS":
                raise RuntimeError("unknown policy blocks run initialization")
            authority = contract["authority"]
            if not isinstance(authority, dict) or set(authority) != {"actions", "evidence"} or not isinstance(authority["actions"], list):
                raise RuntimeError("explicit action authority and source evidence are required")
            verify_reference(authority["evidence"])
            if not isinstance(contract["known_cases"], list) or any(not isinstance(d, str) or not re.fullmatch("[0-9a-f]{64}", d) for d in contract["known_cases"]):
                raise RuntimeError("known case digests must be explicit")
        encoded = canonical(contract).decode()
        with self._connection(create=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT contract FROM runs WHERE run_id=?", (contract["run_id"],)).fetchone()
            if old and old[0] != encoded:
                raise RuntimeError("run already has a different immutable contract")
            if not old:
                profile = profile_identity()
                if not historical_profile:
                    if evaluate_policy(contract["policy"]).get("workflow") == "critical-four-v1":
                        raise RuntimeError("start a Critical run with i2e.py critical --state PATH init")
                    profile["critical_workflow"] = "critical-four-v1"
                conn.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (contract["run_id"], encoded,
                             digest({"contract": contract, "profile": profile, "initial_source": initial_source}), canonical(profile).decode(), canonical(initial_source).decode()))
            conn.commit()
            return self._read(conn, contract["run_id"])

    def append(self, run_id, event, expected_seq):
        return self._append(run_id, event, expected_seq)

    def _append(self, run_id, event, expected_seq, *, internal=False, guard=None):
        automatic = internal and expected_seq is None
        if not automatic and (type(expected_seq) is not int or expected_seq < 0):
            raise RuntimeError("expected sequence must be a nonnegative integer")
        if not isinstance(event, dict) or set(event) != {"id", "type", "data"} or not isinstance(event["data"], dict):
            raise RuntimeError("event must contain exactly id, type and object data")
        _label(event["id"], "event id")
        if not internal and event["id"].startswith("i2e/"):
            raise RuntimeError("internal operation identity namespace is reserved")
        allowed = EVENT_TYPES | V2_EVENT_TYPES
        if internal:
            allowed |= INTERNAL_TYPES | V2_INTERNAL_TYPES
        if not isinstance(event["type"], str) or event["type"] not in allowed:
            raise RuntimeError("unsupported or reserved event type")
        canonical(event)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = self._read(conn, run_id)
            v2 = _is_v2(state)
            if event["type"] in V2_INTERNAL_TYPES | V2_EVENT_TYPES and not v2:
                raise RuntimeError("this event requires an explicit v2 run")
            if event["type"] in REVIEW_TYPES:
                _validate_review(event, v2=v2)
            if v2 and event["type"] == "plan":
                runtime = _v2()
                runtime.contract.fields(event["data"], {"revision", "content", "consultation", "supersedes"}, "v2 plan event")
                runtime.contract.validate_plan(state, event["data"]["content"], runtime.core)
            for old in state["events"]:
                if old["id"] == event["id"]:
                    if {k: old[k] for k in ("id", "type", "data")} != event:
                        raise RuntimeError("event id already has different immutable content")
                    return old
            if not automatic and state["seq"] != expected_seq:
                raise RuntimeError("expected sequence conflict; reload the current prefix")
            if v2 and event["type"] == "plan":
                _v2().observe_plan(state, event["data"]["content"])
            if v2 and (event["type"] in V2_EVENT_TYPES or event["type"] == "audit"):
                _v2().validate_event(state, event)
            if guard:
                guard(state)
            saved = self._insert_event(conn, state, event)
            conn.commit()
            return saved

    def _insert_event(self, conn, state, event):
        """Insert a validated event on the caller's current writer transaction."""
        contract = state["contract"]
        saved = dict(event, seq=state["seq"] + 1, previous_sha256=state["sha256"])
        v2 = _is_v2(state)
        if event["type"] == "plan" and not v2:
            saved["observed_instructions"] = snapshot(contract["repo"], [], contract["instructions"])["instructions"]
        if event["type"] in {"plan", "proof", "failure"}:
            saved["observed_source"] = _source_snapshot(state)
        if v2 and event["type"] == "plan":
            saved["observed_instructions"] = saved["observed_source"]["instructions"]
        if v2 and event["type"] == "proof" and saved["observed_source"]["sha256"] != event["data"]["candidate"]:
            raise RuntimeError("proof source bytes or modes changed before recording")
        if event["type"] in {"plan", "proof"} | REVIEW_TYPES:
            saved["observed_profile"] = profile_identity()
        sha = digest(saved)
        conn.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                     (contract["run_id"], saved["seq"], saved["id"], canonical(saved).decode(), sha))
        return dict(saved, sha256=sha)

    def show(self, run_id):
        with self._connection() as conn:
            return self._read(conn, run_id)

    def worker(self, run_id, operation, expected_seq, request):
        try:
            state = self.show(run_id)
            if not _is_v2(state):
                raise RuntimeError("worker operations require an explicit v2 run")
            runtime = _v2()
            return runtime.executor.Worker(self, runtime).apply(state, operation, expected_seq, request)
        except (RuntimeError, ValueError, OSError, TypeError, KeyError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}

    def delivery(self, run_id, operation, expected_seq, request, *, transport=None):
        try:
            state = self.show(run_id)
            if not _is_v2(state):
                raise RuntimeError("delivery operations require an explicit v2 run")
            runtime = _v2()
            return runtime.github.Delivery(self, runtime, transport).apply(state, operation, expected_seq, request)
        except (RuntimeError, ValueError, OSError, TypeError, KeyError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}

    def search(self, project, query):
        if not isinstance(query, str) or not query.strip():
            raise RuntimeError("retrieval query must be nonempty")
        with self._connection() as conn:
            results = []
            for (run_id,) in conn.execute("SELECT run_id FROM runs ORDER BY run_id"):
                state = self._read(conn, run_id)
                chunks = [state["contract"], *state["events"]]
                # _read already verified each stored record under its input cap.
                # Returned sha256 metadata is a derived view, not another input.
                if state["contract"]["project"] == project and any(query.casefold() in json.dumps(chunk, ensure_ascii=False, allow_nan=False).casefold() for chunk in chunks):
                    results.append(state)
            return results

    def preflight(self, run_id, mode, expected_seq, request):
        try:
            state = self.show(run_id)
            v2 = _is_v2(state)
            runtime = _v2() if v2 else None
            allowed = {"id", "acceptance", "repair_defect", "remediation"}
            if v2:
                allowed.update(("write_manifest", "observe_manifest"))
            if not isinstance(request, dict) or set(request) - allowed or not {"id", "acceptance"} <= set(request):
                raise RuntimeError("preflight request requires id and acceptance; optional repair_defect")
            if state["seq"] != expected_seq or (v2 and type(expected_seq) is not int):
                raise RuntimeError("expected sequence conflict")
            plan = _latest(state, "plan")
            if plan is None:
                raise RuntimeError("approved plan is missing")
            opened = (runtime.observe_start(state, mode, request["acceptance"], request) if v2
                      else {"candidate": _source_snapshot(state)})
            candidate = opened["candidate"]
            data = {"mode": mode, "plan": plan["data"]["revision"], "acceptance": request["acceptance"],
                    "profile": profile_identity(), "prefix": state["sha256"], **opened}
            if "remediation" in request:
                data["remediation"] = request["remediation"]
            data["write_scope"] = _write_scope(state, data)
            data["pending_defects"] = sorted(_pending_defects(state, candidate["sha256"]))
            if v2:
                data["source"] = runtime.contract.read_only_source(state, candidate, runtime.core, observe=True)
            if "repair_defect" in request:
                data["repair_defect"] = request["repair_defect"]
            errors = _start_errors(state, data)
            if errors:
                return {"state": "BLOCK", "errors": errors, "start": None}

            def guard(prefix):
                if v2:
                    current = runtime.observe_start(prefix, mode, request["acceptance"], request)
                    runtime.contract.read_only_source(prefix, current["candidate"], runtime.core, observe=True)
                else:
                    current = {"candidate": _source_snapshot(prefix)}
                if current != opened or profile_identity() != data["profile"] or _start_errors(prefix, data):
                    message = "preflight source, path identities or prerequisites changed before append" if v2 else (
                        "preflight source or prerequisites changed before append"
                    )
                    raise RuntimeError(message)

            saved = self._append(run_id, {"id": request["id"], "type": "start", "data": data}, expected_seq, internal=True, guard=guard)
            return {"state": "PASS", "errors": [], "start": saved}
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)], "start": None}

    def prove(self, run_id, expected_seq, request):
        try:
            state = self.show(run_id)
        except RuntimeError:
            state = None
        if state is not None and _is_v2(state):
            return _v2().prove(self, state, expected_seq, request)
        try:
            fields = {"id", "phase", "check", "start", "command", "acceptance", "test_id", "test_path", "failure_kind"}
            if not isinstance(request, dict) or set(request) - fields or not {"id", "phase", "check", "start", "command"} <= set(request):
                raise RuntimeError("proof requires id, phase, check, start and command; RED/GREEN add acceptance, test_id and test_path")
            _label(request["id"], "proof id")
            phase, command = request["phase"], request["command"]
            if request["id"].startswith("i2e/"):
                raise RuntimeError("internal operation identity namespace is reserved")
            if phase not in {"RED", "GREEN", "CHECK"}:
                raise RuntimeError("proof phase must be RED, GREEN or CHECK")
            if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command):
                raise RuntimeError("proof command must be a nonempty argument list")
            behavioral = phase in {"RED", "GREEN"}
            if behavioral and not {"acceptance", "test_id", "test_path"} <= set(request):
                raise RuntimeError("RED and GREEN proofs require acceptance, test_id and test_path")
            if (phase == "RED") != ("failure_kind" in request):
                raise RuntimeError("RED requires a declared failure_kind; GREEN and CHECK must not declare one")
            if phase == "RED":
                _label(request["failure_kind"], "failure_kind")
            state = self.show(run_id)
            if state["seq"] != expected_seq:
                raise RuntimeError("expected sequence conflict")
            if any(e["id"] == request["id"] for e in state["events"]):
                raise RuntimeError("proof id is already recorded")
            plan = _latest(state, "plan")
            if plan is None:
                raise RuntimeError("approved plan is missing")
            contract = state["contract"]
            if behavioral and request["test_path"] not in _paths(contract["test_scope"]):
                raise RuntimeError("test_path must be a declared test source")
            before = snapshot(contract["repo"], contract["scope"], contract["instructions"])
            try:
                completed = subprocess.run(command, cwd=contract["repo"], stdin=subprocess.DEVNULL, capture_output=True,
                                           timeout=PROOF_TIMEOUT_SECONDS, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"proof command could not complete: {exc}") from exc
            if snapshot(contract["repo"], contract["scope"], contract["instructions"]) != before:
                raise RuntimeError("proof command changed declared source or instructions")
            receipt = self._artifact(run_id, canonical({"argv": command, "cwd": contract["repo"], "exit": completed.returncode,
                                                        "stdout": self._artifact(run_id, completed.stdout),
                                                        "stderr": self._artifact(run_id, completed.stderr)}))
            # RED must fail; GREEN and CHECK must pass. A refused run is kept only as its receipt.
            if (completed.returncode != 0) != (phase == "RED"):
                return {"state": "BLOCK", "errors": [f"{phase} cannot record a command that exited {completed.returncode}"], "receipt": receipt}
            kind = request.get("failure_kind")
            data = {"plan": plan["data"]["revision"], "candidate": before["sha256"], "phase": phase, "check": request["check"],
                    "start": request["start"], "command": command, "output": receipt, "exit": completed.returncode,
                    "outcome": "PASS" if phase != "RED" else "INTENDED_ASSERTION_FAILURE" if kind == "ASSERTION" else "FAILURE",
                    "failure_kind": kind}
            data.update({name: request[name] for name in ("acceptance", "test_id", "test_path") if name in request})
            if behavioral:
                data["test"] = self._artifact(run_id, _file_bytes(_safe_path(Path(contract["repo"]) / request["test_path"])))

            def guard(prefix):
                if snapshot(contract["repo"], contract["scope"], contract["instructions"]) != before:
                    raise RuntimeError("source changed before the proof was recorded")

            saved = self._append(run_id, {"id": request["id"], "type": "proof", "data": data}, expected_seq, internal=True, guard=guard)
            return {"state": "PASS", "proof": saved, "errors": []}
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}

    def rollout(self, run_id, path):
        try:
            extract = _rollout_extract(path, include_context=_is_v2(self.show(run_id)))
            return {"state": "PASS", "session": extract["session"], "model": extract["model"], "effort": extract["effort"],
                    "invocation": self._artifact(run_id, canonical(extract)), "errors": []}
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}

    def check(self, run_id):
        check_schema = "i2e-team-check-v1"
        try:
            state = self.show(run_id)
            v2 = _is_v2(state)
            runtime = _v2() if v2 else None
            if v2:
                check_schema = "i2e-team-check-v2"
            errors = []
            for index, event in enumerate(state["events"]):
                if event["type"] != "start":
                    continue
                prefix = dict(state, events=state["events"][:index], seq=index, sha256=event["previous_sha256"])
                if event["data"].get("prefix") != prefix["sha256"]:
                    errors.append(f"{event['id']}: start prefix mismatch")
                errors.extend(f"{event['id']}: {issue}" for issue in _start_errors(prefix, event["data"]))
            plan = _latest(state, "plan")
            if plan is None:
                raise RuntimeError("plan is missing")
            content, revision = plan["data"]["content"], plan["data"]["revision"]
            candidate = _source_snapshot(state)
            active = runtime.active_acceptance(state) if v2 else {a["id"] for a in content["acceptance"]}
            current_request = {"mode": "TEST_ONLY", "plan": revision,
                               "acceptance": [a["id"] for a in content["acceptance"] if a["id"] in active], "candidate": candidate,
                               "profile": profile_identity(), "prefix": state["sha256"]}
            current_request["write_scope"] = _write_scope(state, current_request)
            if v2:
                current_request["source"] = runtime.contract.read_only_source(state, candidate, runtime.core, observe=True)
            errors.extend(_start_errors(state, current_request))
            latest_start = _latest_work_start(state)
            if latest_start is None or latest_start["data"]["mode"] != "PRODUCTION" or latest_start["data"]["plan"] != revision:
                errors.append("latest work is unclosed; a current PRODUCTION cycle is required")
                latest_start = None
            after = latest_start["seq"] if latest_start else state["seq"] + 1
            current_proofs = []
            for acceptance in content["acceptance"]:
                if not acceptance["behavior"] or acceptance["id"] not in active:
                    continue
                proof = _latest(state, "proof", lambda e: e["data"].get("acceptance") == acceptance["id"] and e["data"].get("phase") == "GREEN")
                if proof is None:
                    errors.append(f"missing GREEN for {acceptance['id']}")
                    continue
                issues = _proof_errors(state, proof, "GREEN", candidate["sha256"], revision)
                if proof["seq"] <= after or proof["data"].get("start") != (latest_start or {}).get("id"):
                    issues.append("GREEN predates latest production start")
                if not v2:
                    red = _latest(state, "proof", lambda e: e["seq"] < after and e["data"].get("acceptance") == acceptance["id"] and e["data"].get("phase") == "RED")
                    if red is None or any(proof["data"].get(k) != red["data"].get(k) for k in ("test_id", "test", "command")):
                        issues.append("GREEN must use the unchanged RED test identity and content")
                errors.extend(f"{proof['id']}: {issue}" for issue in issues)
                current_proofs.append(proof)
            required_checks = runtime.required_checks(state, content) if v2 else content["checks"]
            for check_id in required_checks:
                if v2:
                    try:
                        proof = runtime.required_check_proof(state, content, check_id)
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                else:
                    proof = _latest(state, "proof", lambda e: e["data"].get("check") == check_id and e["data"].get("phase") != "RED")
                if proof is None or proof["seq"] <= after:
                    errors.append(f"missing current check {check_id}")
                else:
                    issues = _proof_errors(state, proof, "PASS", candidate["sha256"], revision)
                    if v2 and check_id in content.get("batch", {}).get("interaction_checks", []):
                        issues = [f"interaction check {check_id}: {issue}" for issue in issues]
                    errors.extend(issues)
                    current_proofs.append(proof)
            policy = evaluate_policy(content["policy"], historical=_historical(state))
            audit_sessions, audits, specialists = set(), [], set()
            kinds = list(policy["audits"]) if v2 else ["combined"] if policy["lane"] == "light" else ["code", "security", "tests"]
            requested_specialists = set(content["policy"].get("specialists", [])) if v2 else set()
            if "architecture" in requested_specialists:
                kinds.append("architecture")
            for kind in kinds:
                audit = _latest(state, "audit", lambda e: e["data"].get("kind") == kind)
                if audit is None:
                    errors.append(f"missing independent {kind} audit")
                    continue
                excluded = _contributors(state)
                role = "sol"
                if kind == "architecture":
                    role = "astra"
                    excluded |= _participants(state, before=audit["seq"])
                issues = _review_errors(state, audit, role, excluded)
                if audit["data"].get("candidate") != candidate["sha256"] or audit["data"].get("plan") != revision or audit["data"].get("verdict") != "APPROVE":
                    issues.append("audit is stale or unapproved")
                if audit["seq"] <= max([after] + [e["seq"] for e in current_proofs]):
                    issues.append("audit must follow current proof")
                session = audit["data"].get("reviewer", {}).get("session")
                if session in audit_sessions:
                    issues.append("code, security and tests audits require distinct actual sessions")
                audit_sessions.add(session)
                audits.append(audit)
                if v2:
                    issues.extend(runtime.audit_errors(state, audit, candidate["sha256"]))
                    if not issues:
                        specialists.update(audit["data"].get("specialists", []))
                errors.extend(f"{audit['id']}: {issue}" for issue in issues)
            if not requested_specialists <= specialists:
                errors.append("required specialist coverage is missing from qualifying current audits")
            consultation = _latest(state, "consultation", lambda e: e["data"].get("stage") == "final" and e["data"].get("target") == candidate["sha256"])
            errors.extend(_consultation_errors(state, consultation))
            errors.extend(_knowledge_errors(state, candidate["sha256"]))
            errors.extend(_finding_errors(state, candidate["sha256"]))
            if policy["state"] != "PASS":
                errors.append("unknown policy blocks completion")
            elif policy["final_review"] == "astra":
                final = _latest(state, "final_review")
                if final is None:
                    errors.append("trigger requires fresh independent Astra final review")
                else:
                    excluded = _contributors(state) | _participants(state, before=final["seq"])
                    errors.extend(_review_errors(state, final, "astra", excluded))
                    if v2:
                        errors.extend(runtime.final_review_errors(state, final))
                    if final["data"].get("candidate") != candidate["sha256"] or final["data"].get("plan") != revision or final["data"].get("verdict") != "APPROVE":
                        errors.append("latest final review is stale or unapproved")
                    if final["seq"] <= max([after, consultation["seq"] if consultation else after] + [e["seq"] for e in audits]):
                        errors.append("final review must follow current audits and consultation")
            if any(e["type"] == "withdrawal" and e["data"].get("target") in {run_id, revision, *[a["id"] for a in content["acceptance"]]} for e in state["events"]):
                errors.append("current objective or acceptance was withdrawn")
            # Readiness covers delivery only; the status report and brief follow it.
            handoff = _teaching_errors(state, candidate["sha256"], revision)
            result = {"schema": check_schema, "state": "BLOCK" if errors or handoff else "PASS", "ready": not errors,
                      "errors": sorted(set(errors + handoff)), "candidate": candidate, "seq": state["seq"]}
            if v2:
                result.update(runtime.check_fields(state, policy, candidate["sha256"], errors, handoff))
            return result
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            return {"schema": check_schema, "state": "BLOCK", "ready": False, "errors": [str(exc)]}

    def bind_case(self, run_id, expected_seq, request):
        state = self.show(run_id)
        if not _is_v2(state):
            return {"state": "BLOCK", "errors": ["case binding requires an explicit v2 run"]}
        return _v2().bind_case(self, state, expected_seq, request)

    def capture(self, run_id, expected_seq, request):
        intent_id = request.get("id") if isinstance(request, dict) else None
        intent = None
        try:
            if not isinstance(request, dict) or set(request) != {"id", "defect", "case", "failure"}:
                raise RuntimeError("capture requires id, stable defect, unchanged canonical case and preserved failure")
            _label(request["id"], "capture id")
            _label(request["defect"], "defect")
            state = self.show(run_id)
            contract = state["contract"]
            existing = next((e for e in _events(state, "capture_intent") if e["id"] == intent_id), None)
            if existing:
                if existing["data"]["request"] != request:
                    raise RuntimeError("capture retry must retain the exact frozen request bytes")
                intent = existing
            else:
                if state["seq"] != expected_seq:
                    raise RuntimeError("capture expected sequence conflict")
                failure = request["failure"]
                if set(failure) != {"command", "output", "inputs", "broken", "broken_files"} or not isinstance(failure["command"], list) or not failure["command"]:
                    raise RuntimeError("preserved failed command, output, inputs and broken state are required")
                verify_reference(failure["output"])
                for ref in failure["inputs"]:
                    verify_reference(ref)
                current = _source_snapshot(state)
                if failure["broken"] != current:
                    raise RuntimeError("capture broken snapshot is not the actual current source")
                required = {name: sha for name, sha in {**current["files"], **current["instructions"]}.items() if sha is not None}
                if set(failure["broken_files"]) != set(required):
                    raise RuntimeError("preserve every required broken source/instruction file before capture")
                for name, sha in required.items():
                    verify_reference(failure["broken_files"][name])
                    if failure["broken_files"][name]["sha256"] != sha:
                        raise RuntimeError("preserved broken bytes mismatch source snapshot")
                case = request["case"]
                if case["scope"] != contract["project"] or case["origin"]["task_id"] != run_id or case["origin"]["broken_source_identity"] != current["sha256"]:
                    raise RuntimeError("canonical case scope/task/broken identity mismatch")
                frozen = self._artifact(run_id, canonical(case))
                validation = self._invoke_cases(contract, "validate", ["--kind", "case", "--input", frozen["path"]])
                _validate_capture_input(validation, contract, frozen, digest(case))
                data = {"request": request, "expected_digest": digest(case), "defect": request["defect"],
                        "store": contract["case_store"], "helper_sha256": contract["case_helper_sha256"],
                        "input": frozen, "validation": validation["_receipt"]}
                intent = self._append(run_id, {"id": intent_id, "type": "capture_intent", "data": data}, expected_seq, internal=True)
            verify_reference(intent["data"]["input"])
            _capture_validation(intent, contract)
            if intent["data"]["store"] != contract["case_store"] or intent["data"]["helper_sha256"] != contract["case_helper_sha256"]:
                raise RuntimeError("frozen case destination or helper changed")
            linked = next((e for e in _events(self.show(run_id), "case_link") if e["data"]["intent"] == intent_id), None)
            if linked:
                return {"state": "PASS", "digest": linked["data"]["digest"], "link": linked, "errors": []}
            expected = intent["data"]["expected_digest"]
            captured = self._invoke_cases(contract, "capture", ["--kind", "case", "--input", intent["data"]["input"]["path"]])
            if captured.get("state") != "CAPTURED_LOCAL" or captured.get("kind") != "case" or captured.get("digest") != expected or captured.get("shared") is not False or captured.get("store") != contract["case_store"]:
                raise RuntimeError("unsupported or mismatched canonical capture output")
            shown = self._invoke_cases(contract, "show", ["--digest", expected, "--include-drafts"])
            _validate_shown(shown, expected, contract["project"])
            link = self._capture_link(run_id, intent, shown, captured.get("_receipt"))
            return {"state": "PASS", "digest": expected, "link": link, "errors": []}
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            self._record_gap(run_id, "capture", intent_id, str(exc), started=intent is not None)
            return {"state": "BLOCK", "errors": [str(exc)]}

    def _capture_link(self, run_id, intent, shown, capture_receipt=None):
        event = {"id": _internal_id("case-link", intent["id"]), "type": "case_link", "data": {
            "intent": intent["id"], "digest": intent["data"]["expected_digest"],
            "defect": intent["data"]["defect"], "show": self._artifact(run_id, canonical(shown)), "capture": capture_receipt}}
        return self._append(run_id, event, None, internal=True)

    def consult(self, run_id, expected_seq, request):
        intent = None
        try:
            if not isinstance(request, dict) or set(request) - {"id", "stage", "target", "query", "recovery_for", "recovery_reason"} or not {"id", "stage", "target", "query"} <= set(request):
                raise RuntimeError("consultation requires id/stage/target/query and optional explicit recovery")
            _label(request["id"], "consultation id")
            _label(request["target"], "consultation target")
            if request["id"].startswith("i2e/") or not isinstance(request["stage"], str) or request["stage"] not in {"plan", "repair", "final"} or not isinstance(request["query"], str) or not request["query"].strip():
                raise RuntimeError("consultation stage or query is unknown")
            state = self.show(run_id)
            old = next((e for e in state["events"] if e["id"] == request["id"]), None)
            if old:
                if old["type"] == "consultation" and old["data"].get("request") == request:
                    return {"state": "PASS" if old["data"]["state"] == "COMPLETE" else "BLOCK", "consultation": old, "errors": old["data"]["gaps"]}
                raise RuntimeError("consultation id already has different content")
            contract = state["contract"]
            intent_id = _internal_id("lookup", request["id"])
            intent = next((e for e in _events(state, "lookup_intent") if e["id"] == intent_id), None)
            if intent:
                if intent["data"]["request"] != request:
                    raise RuntimeError("lookup retry must preserve its immutable request")
            else:
                intent = self._append(run_id, {"id": intent_id, "type": "lookup_intent", "data": {
                    "request": request, "known": sorted(_known_cases(state))}}, expected_seq, internal=True)
            # A begun lookup is now visible before any external helper call.
            known = _known_cases(self.show(run_id))
            gaps, ranked, shown, search_ref = [], [], {}, None
            try:
                answer = self._invoke_cases(contract, "search", ["--scope", contract["project"], "--query", request["query"], "--include-drafts", "--limit", "100"])
                required = {"scope", "query", "include_drafts", "snapshot_commit", "snapshot_observed_at", "freshness", "results"}
                if set(answer) - {"_receipt"} != required or answer["scope"] != contract["project"] or answer["include_drafts"] is not True or not isinstance(answer["results"], list):
                    raise RuntimeError("unsupported canonical search output")
                if len(answer["results"]) >= 100:
                    gaps.append("canonical search saturated at limit 100; coverage remains incomplete")
                for row in answer["results"]:
                    case_digest = row["digest"]
                    if row["scope"] != contract["project"] or not re.fullmatch("[0-9a-f]{64}", case_digest):
                        raise RuntimeError("canonical search returned wrong scope or malformed digest")
                    ranked.append(case_digest)
                    known.add(case_digest)
                search_ref = self._artifact(run_id, canonical(answer))
                progress = {"intent": intent_id, "known": sorted(known), "ranked": ranked, "search": search_ref}
                self._append(run_id, {"id": _internal_id("lookup-progress", intent_id + search_ref["sha256"]),
                             "type": "lookup_progress", "data": progress}, None, internal=True)
            except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
                gaps.append(str(exc))
            known.update(_known_cases(self.show(run_id)))
            for case_digest in sorted(known):
                try:
                    answer = self._invoke_cases(contract, "show", ["--digest", case_digest, "--include-drafts"])
                    _validate_shown(answer, case_digest, contract["project"])
                    shown[case_digest] = self._artifact(run_id, canonical(answer))
                except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
                    gaps.append(f"required show {case_digest}: {exc}")
            recovery = request.get("recovery_for")
            if recovery:
                failed = next((e for e in _events(state, "lookup_intent") if e["data"]["request"]["id"] == recovery), None)
                outcome = next((e for e in _events(state, "consultation") if e["id"] == recovery), None)
                previous_request = failed["data"]["request"] if failed else {}
                if failed is None or (outcome and outcome["data"]["state"] != "GAP") or not request.get("recovery_reason") or any(previous_request.get(k) != request[k] for k in ("stage", "target", "query")):
                    gaps.append("recovery must reference the earlier failed matching consultation with a reason")
                elif outcome and any("saturated" in gap for gap in outcome["data"]["gaps"]):
                    gaps.append("saturated coverage cannot be cleared by an unproved narrower retry")
            additional = _known_cases(self.show(run_id)) - known
            if additional:
                known.update(additional)
                gaps.append("concurrent known cases require complete show coverage")
            data = {"intent": intent_id, "request": request, "stage": request["stage"], "target": request["target"], "state": "GAP" if gaps else "COMPLETE",
                    "known": sorted(known), "ranked": ranked, "shown": shown, "search": search_ref, "gaps": gaps}
            if recovery:
                data["recovery_for"] = recovery
            def guard(prefix):
                if not _known_cases(prefix) <= known:
                    raise RuntimeError("concurrent carried case appeared; lookup intent remains pending")
            saved = self._append(run_id, {"id": request["id"], "type": "consultation", "data": data}, None, internal=True, guard=guard)
            return {"state": "BLOCK" if gaps else "PASS", "consultation": saved, "errors": gaps}
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            if intent:
                self._record_gap(run_id, "lookup", intent["id"], str(exc))
            return {"state": "BLOCK", "errors": [str(exc)]}

    def _invoke_cases(self, contract, operation, options):
        if operation not in {"validate", "capture", "search", "show", "status"} or "--config" in options:
            raise RuntimeError("adapter permits only explicit local canonical case operations")
        helper = _safe_path(contract["case_helper"])
        if helper.name != "shared_cases.py" or reference(helper)["sha256"] != contract["case_helper_sha256"]:
            raise RuntimeError("canonical helper is unavailable or differs from pinned dependency")
        _safe_path(contract["case_store"])
        argv = _case_argv(contract, operation, options)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("canonical helper invocation unavailable or timed out") from exc
        receipt = self._artifact(contract["run_id"], canonical({"argv": argv, "exit": result.returncode,
                    "stdout": result.stdout.decode("utf-8", errors="replace"), "stderr": result.stderr.decode("utf-8", errors="replace")}))
        if result.returncode != 0:
            raise RuntimeError(f"canonical helper failed; raw local receipt {receipt['path']}")
        try:
            answer = json.loads(result.stdout.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
            canonical(answer)
            if not isinstance(answer, dict):
                raise ValueError("not an object")
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise RuntimeError("canonical helper returned unsupported strict JSON") from exc
        return dict(answer, _receipt=receipt)

    def _artifact(self, run_id, content):
        if not isinstance(content, bytes) or len(content) > MAX_FILE_BYTES:
            raise RuntimeError("private artifact must be bounded bytes")
        state = self.show(run_id)
        self._privacy(state["contract"])
        root = self._evidence_root(run_id)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        object_sha = hashlib.sha256(content).hexdigest()
        path = root / (object_sha + ".json")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload,sha256 FROM artifact_publications WHERE run_id=? AND object_sha256=?", (run_id, object_sha)).fetchone()
            if row is None:
                if path.exists():
                    raise RuntimeError("immutable private artifact conflict or missing owned publication intent")
                # Partial/uncommitted stages stay private and never occupy the
                # final name. Only this durable exact inode intent allows reuse.
                fd, stage_name = tempfile.mkstemp(prefix=".pending-", dir=root)
                stage = Path(stage_name)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                _sync_directory(root)
                _sync_directory(root.parent)
                _sync_directory(root.parent.parent)
                identity = stage.stat()
                publication = {"stage": str(stage), "final": str(path), "sha256": object_sha,
                               "size": len(content), "device": identity.st_dev, "inode": identity.st_ino}
                conn.execute("INSERT INTO artifact_publications VALUES(?,?,?,?)", (run_id, object_sha, canonical(publication).decode(), digest(publication)))
                conn.commit()  # Synchronous durable ownership precedes publication.
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT payload,sha256 FROM artifact_publications WHERE run_id=? AND object_sha256=?", (run_id, object_sha)).fetchone()
            publication = json.loads(row[0])
            if digest(publication) != row[1] or set(publication) != {"stage", "final", "sha256", "size", "device", "inode"}:
                raise RuntimeError("owned artifact publication intent is malformed")
            stage = _safe_path(publication["stage"])
            if stage.parent != root or not stage.name.startswith(".pending-") or publication["final"] != str(path) or publication["sha256"] != object_sha or publication["size"] != len(content):
                raise RuntimeError("owned artifact publication intent differs from exact retry")

            def owned(target):
                target = _safe_path(target)
                if not target.exists():
                    return None
                identity = target.stat()
                if not stat.S_ISREG(identity.st_mode) or identity.st_mode & 0o077 or (identity.st_dev, identity.st_ino) != (publication["device"], publication["inode"]):
                    raise RuntimeError("artifact publication object identity or private mode changed")
                if _file_bytes(target, reject_links=False) != content:
                    raise RuntimeError("immutable private artifact conflict; owned bytes retained")
                return identity

            staged, final = owned(stage), owned(path)
            if staged is not None and final is None:
                if staged.st_nlink != 1:
                    raise RuntimeError("unpublished artifact has foreign hardlinks")
                os.link(stage, path)  # Native no-replace; the intent is committed.
                staged, final = owned(stage), owned(path)
            if staged is not None:
                if final is None or staged.st_nlink != 2 or final.st_nlink != 2:
                    raise RuntimeError("owned artifact pair has ambiguous or foreign hardlinks")
                stage.unlink()  # Only the recorded owned stage may be removed.
            elif final is None:
                raise RuntimeError("owned artifact stage and final are both missing")
            _sync_directory(root)
            result = reference(path)  # Final must now have exactly one link.
            conn.commit()
            return result

    def _record_gap(self, run_id, operation, intent, reason, *, started=True):
        try:
            self._append(run_id, {"id": "gap-" + uuid.uuid4().hex, "type": "operation_gap",
                         "data": {"operation": operation, "intent": intent, "reason": reason, "started": started}}, None, internal=True)
        except (RuntimeError, OSError):
            # The returned BLOCK still exposes an unavailable ledger; never claim capture.
            pass

    def brief(self, run_id):
        try:
            state = self.show(run_id)
            teaching = _latest(state, "teaching")
            if teaching is None:
                raise RuntimeError("no recorded engineering brief")
            data = teaching["data"]
            errors = _teaching_errors(state, data["candidate"], data["plan"], allow_partial=True)
            if errors:
                return {"state": "BLOCK", "errors": errors}
            report = next(e for e in state["events"] if e["id"] == data["report"])
            decisions = [e for e in state["events"] if e["id"] in data["decisions"]]
            lines = [f"{report['data']['status']}: {report['data']['summary']}", "", data["problem"], data["path"]]
            for decision in decisions:
                lines.append("Decision: " + decision["data"].get("choice", "See recorded decision artifact " + decision["id"]))
            if not decisions:
                lines.append("Decisions: none recorded.")
            alternatives = [a for e in decisions for a in e["data"].get("alternatives", [])]
            lines.append("Alternatives: " + ("; ".join(a["choice"] + " — " + a["reason"] for a in alternatives) if alternatives else "not recorded."))
            lines.extend(["Tradeoffs: " + ("; ".join(data["tradeoffs"]) if data["tradeoffs"] else "not recorded."),
                          "Proof: " + (", ".join(data["proofs"]) if data["proofs"] else "none recorded."),
                          "Limits: " + data["limits"], "Principle: " + data["principle"], "Example: " + data["example"]])
            lines.extend(e["type"] + ": " + e["data"].get("text", "See " + e["id"]) for e in state["current_annotations"])
            return {"state": "PASS", "text": "\n".join(lines), "teaching": teaching, "annotations": state["current_annotations"]}
        except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}


def _validate_shown(answer, expected, project):
    required = {"kind", "digest", "record", "provenance", "review", "freshness", "warning", "authority"}
    if not isinstance(answer, dict) or set(answer) - {"_receipt"} != required or answer.get("kind") != "case" or answer.get("digest") != expected or answer["record"].get("scope") != project or digest(answer["record"]) != expected:
        raise RuntimeError("unsupported, wrong-scope or digest-mismatched complete canonical show output")


def _internal_id(kind, value):
    return "i2e/" + kind + "/" + hashlib.sha256(value.encode()).hexdigest()


def _known_cases(state):
    known = set(state["contract"]["known_cases"])
    for event in state["events"]:
        if event["type"] == "case_link":
            known.add(event["data"]["digest"])
        elif event["type"] == "capture_intent":
            known.add(event["data"]["expected_digest"])
        elif event["type"] in {"consultation", "lookup_intent", "lookup_progress"}:
            known.update(event["data"].get("known", []))
    return known


def _case_argv(contract, operation, options):
    python = sys.executable
    if contract.get("schema") == "i2e-team-run-v2":
        python = str(Path(python).resolve(strict=True))
    prefix = [python, contract["case_helper"], operation]
    # validate is read-only and the canonical parser has no --store argument.
    return [*prefix, *options] if operation == "validate" else [*prefix, "--store", contract["case_store"], *options]


def _helper_receipt(answer, contract, operation, options):
    verify_reference(answer["_receipt"])
    raw = _read_json(answer["_receipt"]["path"])
    argv = _case_argv(contract, operation, options)
    if set(raw) != {"argv", "exit", "stdout", "stderr"} or raw["argv"] != argv or type(raw["exit"]) is not int or raw["exit"] != 0:
        raise RuntimeError("canonical raw invocation receipt does not match the scoped local operation")
    decoded = json.loads(raw["stdout"], object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    if decoded != {k: v for k, v in answer.items() if k != "_receipt"}:
        raise RuntimeError("canonical parsed output differs from actual raw invocation output")


def _validate_capture_input(answer, contract, frozen, expected):
    _helper_receipt(answer, contract, "validate", ["--kind", "case", "--input", frozen["path"]])
    if set(answer) - {"_receipt"} != {"canonical_bytes", "digest", "kind", "state"} or answer.get("state") != "VALID" or answer.get("kind") != "case" or answer.get("digest") != expected or type(answer.get("canonical_bytes")) is not int or answer["canonical_bytes"] != len(_file_bytes(frozen["path"])):
        raise RuntimeError("canonical validation receipt does not bind the complete frozen case")


def _capture_validation(intent, contract):
    data = intent["data"]
    verify_reference(data["validation"])
    raw = _read_json(data["validation"]["path"])
    answer = json.loads(raw["stdout"], object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    _validate_capture_input(dict(answer, _receipt=data["validation"]), contract, data["input"], data["expected_digest"])


def _events(state, kind):
    return [e for e in state["events"] if e["type"] == kind]


def _latest(state, kind, predicate=lambda e: True):
    return next((e for e in reversed(state["events"]) if e["type"] == kind and predicate(e)), None)


def _latest_work_start(state):
    return _latest(state, "start", lambda e: e["data"].get("mode") != "VERIFY")


def _contributors(state):
    result = set(state["contract"]["contributors"])
    for event in state["events"]:
        if event["type"] == "plan":
            result.update(event["data"]["content"]["contributors"])
        if event["type"] == "decision":
            result.update(event["data"]["contributors"])
        if event["type"] == "observation" and event["data"].get("kind") == "ROUTING":
            roles = ("owner", "probe", "lead") if _is_v2(state) else ("owner", "probe")
            if _is_v2(state):
                result.update(event["data"][role]["session"] for role in roles if role in event["data"])
            else:
                result.update(event["data"][role]["session"] for role in roles)
    return result


def _participants(state, before=None):
    participants = set()
    for event in state["events"]:
        if event["type"] in REVIEW_TYPES and (before is None or event["seq"] < before):
            _validate_review(event, v2=_is_v2(state))
            participants.add(event["data"]["reviewer"]["session"])
    return participants


def _validate_review(event, *, v2=False):
    if event["type"] not in REVIEW_TYPES:
        raise RuntimeError("only typed review records can supply reviewers or findings")
    data = event["data"]
    reviewer = data.get("reviewer")
    required = {"session", "model", "effort", "fresh", "excluded", "input", "invocation", "response"}
    if not isinstance(reviewer, dict) or set(reviewer) != required:
        raise RuntimeError("reviewer receipt has unsupported or missing fields")
    for name in ("session", "model", "effort"):
        _label(reviewer[name], "reviewer " + name)
    excluded = reviewer["excluded"]
    if type(reviewer["fresh"]) is not bool or not isinstance(excluded, list):
        raise RuntimeError("reviewer freshness and excluded sessions have malformed types")
    for session in excluded:
        _label(session, "excluded reviewer session")
    if len(excluded) != len(set(excluded)):
        raise RuntimeError("excluded reviewer sessions must be unique")
    for name in ("input", "invocation", "response"):
        verify_reference(reviewer[name])
    findings = data.get("findings", [] if event["type"] == "escalation" else None)
    if not isinstance(findings, list):
        raise RuntimeError("typed review findings must be an array")
    seen = set()
    for finding in findings:
        if v2:
            runtime = _v2()
            runtime.contract.validate_finding(finding, runtime.core)
        elif not isinstance(finding, dict) or set(finding) != {"id", "actionable", "material", "text"}:
            raise RuntimeError("typed review finding must contain id, actionable, material and text")
        _label(finding["id"], "finding id")
        if type(finding["actionable"]) is not bool or type(finding["material"]) is not bool or not isinstance(finding["text"], str) or not finding["text"].strip() or finding["id"] in seen:
            raise RuntimeError("finding IDs, boolean classifications and text must be explicit and unique")
        seen.add(finding["id"])


def _review_errors(state, event, role, excluded):
    try:
        v2 = _is_v2(state)
        _validate_review(event, v2=v2)
        reviewer = event["data"]["reviewer"]
        required = {"session", "model", "effort", "fresh", "excluded", "input", "invocation", "response"}
        if set(reviewer) != required:
            raise RuntimeError("reviewer receipt has unsupported or missing fields")
        _label(reviewer["session"], "reviewer session")
        requested = _v2().contract.settings(role) if v2 else {"model": V1_MODELS[role], "effort": "max"}
        if (reviewer["model"] != requested["model"] or reviewer["effort"] != requested["effort"]
                or reviewer["fresh"] is not True):
            raise RuntimeError("review requires its designated model/effort and fresh neutral context")
        if reviewer["session"] in excluded or not set(excluded) <= set(reviewer["excluded"]):
            raise RuntimeError("reviewer independence or excluded-context coverage failed")
        plan = _latest(dict(state, events=[e for e in state["events"] if e["seq"] < event["seq"]]), "plan")
        if plan is None or event.get("observed_profile") != plan.get("observed_profile"):
            raise RuntimeError("review profile identity differs from the approved plan context")
        for name in ("input", "invocation", "response"):
            verify_reference(reviewer[name])
        _verify_identity(state, reviewer["invocation"], reviewer)
        if v2:
            extract = _read_json(reviewer["invocation"]["path"])
            if (extract.get("synthetic") is not state["contract"]["synthetic"]
                    or extract.get("observed_tier") != requested["tier"]):
                raise RuntimeError("reviewer observed tier or synthetic context does not qualify")
        return []
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        return [str(exc)]


def _decision_resolution_errors(state, review):
    """Qualify a cycle resolution in its original position, not today's view."""
    try:
        if review["type"] != "doubt_review" or review["data"].get("verdict") != "SUPPORTED":
            raise RuntimeError("decision cycle resolution requires a supported doubt review")
        prefix = dict(state, events=[e for e in state["events"] if e["seq"] < review["seq"]],
                      seq=review["seq"] - 1, sha256=review["previous_sha256"])
        lineage = review["data"]["decision"]
        decisions = [e for e in _events(prefix, "decision") if e["data"].get("lineage") == lineage]
        if not decisions or review["data"].get("revision") != decisions[-1]["data"]["revision"]:
            raise RuntimeError("decision support does not bind the revision active at its review position")
        decision = decisions[-1]["data"]
        substantive = dict(decision)
        revision = substantive.pop("revision")
        if revision != digest(substantive) or decision.get("supersedes") != (decisions[-2]["data"]["revision"] if len(decisions) > 1 else None):
            raise RuntimeError("historical decision revision or predecessor binding failed")
        verify_reference(decision["artifact"])
        if decision.get("kind") not in {"ordinary", "architecture", "critical"}:
            raise RuntimeError("historical decision risk classification is unknown")
        role = "sol" if decision["kind"] == "ordinary" else "astra"
        earlier = [e for e in _events(prefix, "doubt_review") if e["data"].get("decision") == lineage]
        excluded = _contributors(prefix) | {e["data"]["reviewer"]["session"] for e in earlier}
        return _review_errors(prefix, review, role, excluded)
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        return [str(exc)]


def _consultation_errors(state, consultation):
    if consultation is None or consultation["data"].get("state") != "COMPLETE" or consultation["data"].get("gaps"):
        return ["complete scoped case search/show consultation is missing or has gaps"]
    known = _known_cases(dict(state, events=[e for e in state["events"] if e["seq"] < consultation["seq"]]))
    data = consultation["data"]
    if not known <= set(data.get("known", [])) or set(data.get("known", [])) != set(data.get("shown", {})):
        return ["consultation omitted carried or complete shown cases"]
    errors = []
    try:
        verify_reference(data["search"])
        answer = _read_json(data["search"]["path"])
        request = data["request"]
        contract = state["contract"]
        intent = next(e for e in _events(state, "lookup_intent") if e["id"] == data["intent"] and e["seq"] < consultation["seq"])
        if intent["data"]["request"] != request or any(data[k] != request[k] for k in ("stage", "target")):
            raise RuntimeError("lookup outcome differs from its earlier frozen intent")
        _helper_receipt(answer, contract, "search", ["--scope", contract["project"], "--query", request["query"], "--include-drafts", "--limit", "100"])
        if answer["scope"] != contract["project"] or answer["include_drafts"] is not True or answer["query"] != request["query"] or not isinstance(answer["results"], list) or len(answer["results"]) >= 100:
            raise RuntimeError("search evidence has wrong scope/drafts/query or saturated coverage")
        ranked = [row["digest"] for row in answer["results"]]
        if ranked != data["ranked"] or len(ranked) != len(set(ranked)) or not set(ranked) <= set(data["known"]) or any(row["scope"] != contract["project"] for row in answer["results"]):
            raise RuntimeError("search result identity differs from carried consultation coverage")
    except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
        errors.append(f"case search evidence gap: {exc}")
    for case_digest in data.get("known", []):
        try:
            verify_reference(data["shown"][case_digest])
            answer = _read_json(data["shown"][case_digest]["path"])
            _validate_shown(answer, case_digest, state["contract"]["project"])
            _helper_receipt(answer, state["contract"], "show", ["--digest", case_digest, "--include-drafts"])
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"case show evidence gap: {exc}")
        decision = _latest(state, "case_decision", lambda e: e["seq"] > consultation["seq"] and e["data"].get("consultation") == consultation["id"] and e["data"].get("digest") == case_digest)
        if decision is None or decision["data"].get("applicability") not in {"APPLIES", "NOT_APPLICABLE"} or not decision["data"].get("reason"):
            errors.append("each shown case requires explicit applicability and reason")
        elif decision["data"]["applicability"] == "APPLIES" and not decision["data"].get("checks"):
            errors.append("applicable case requires direct proof obligations")
    return errors


def _knowledge_errors(state, candidate, *, proofs=True, deferred=frozenset()):
    errors, linked = [], {e["data"].get("intent") for e in _events(state, "case_link")}
    for event in _events(state, "capture_intent"):
        try:
            verify_reference(event["data"]["input"])
            if digest(_read_json(event["data"]["input"]["path"])) != event["data"]["expected_digest"]:
                raise RuntimeError("frozen capture bytes no longer match expected digest")
            _capture_validation(event, state["contract"])
            failure = event["data"]["request"]["failure"]
            for ref in [failure["output"], *failure["inputs"], *failure["broken_files"].values()]:
                verify_reference(ref)
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"preserved capture evidence gap: {exc}")
        if event["id"] not in linked:
            errors.append("pending or failed canonical capture remains a gap")
    for event in _events(state, "case_link"):
        try:
            verify_reference(event["data"]["show"])
            _validate_shown(_read_json(event["data"]["show"]["path"]), event["data"]["digest"], state["contract"]["project"])
            verify_reference(event["data"]["capture"])
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"canonical capture linkage gap: {exc}")
    for event in _events(state, "operation_gap"):
        if event["data"].get("operation") == "capture" and event["data"].get("started", True) and event["data"].get("intent") not in linked:
            errors.append("failed canonical capture operation remains unresolved")
    effective = [e for e in _events(state, "consultation") if e["data"].get("state") == "COMPLETE" and not _consultation_errors(state, e)]
    recovered = {e["data"].get("recovery_for") for e in effective}
    for intent in _events(state, "lookup_intent"):
        if not any(e["data"].get("intent") == intent["id"] for e in effective) and intent["data"]["request"]["id"] not in recovered:
            errors.append("pending or failed canonical lookup remains unresolved")
    for event in _events(state, "consultation"):
        if event["data"].get("state") != "COMPLETE" and event["id"] not in recovered:
            errors.append("failed or saturated case consultation remains unresolved")
    obligations = set()
    for event in _events(state, "case_decision"):
        if event["data"].get("applicability") == "APPLIES":
            obligations.update(check for check in event["data"].get("checks", []) if (event["data"].get("digest"), check) not in deferred)
    for check_id in obligations if proofs else ():
        proof = _latest(state, "proof", lambda e: e["data"].get("check") == check_id and e["data"].get("phase") != "RED")
        plan = _latest(state, "plan")
        if proof is None or plan is None or _proof_errors(state, proof, "PASS", candidate, plan["data"]["revision"]):
            errors.append(f"carried case regression proof missing: {check_id}")
    for failure in _events(state, "failure"):
        try:
            f = failure["data"]
            _label(f["defect"], "stable defect")
            verify_reference(f["output"])
            if type(f["exit"]) is not int or f["exit"] == 0 or not f["command"] or f["broken"] != failure.get("observed_source"):
                raise RuntimeError("recorded failure source/command/exit is malformed")
            matched = [e for e in _events(state, "capture_intent") if e["data"]["defect"] == f["defect"] and e["data"]["request"]["case"]["origin"]["failure_id"] == f.get("failure_id", failure["id"]) and e["data"]["request"]["failure"]["output"] == f["output"] and e["data"]["request"]["failure"]["broken"] == f["broken"] and e["id"] in linked]
            if not matched:
                errors.append("recorded real failure is missing its source-bound canonical capture")
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"recorded failure evidence gap: {exc}")
    return errors


def _finding_errors(state, candidate, deferred=frozenset()):
    errors = []
    for review in [e for e in state["events"] if e["type"] in REVIEW_TYPES]:
        try:
            _validate_review(review, v2=_is_v2(state))
        except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"typed review evidence gap {review['id']}: {exc}")
            continue
        for finding in review["data"].get("findings", []):
            if finding.get("actionable") is not True:
                continue
            if (review["id"], finding["id"]) in deferred:
                continue
            disposition = _latest(state, "disposition", lambda e: e["seq"] > review["seq"] and e["data"].get("review") == review["id"] and e["data"].get("finding") == finding["id"])
            valid = False
            if disposition:
                data = disposition["data"]
                try:
                    verify_reference(data["evidence"])
                    proof = next(e for e in state["events"] if e["id"] == data["recheck"])
                    plan = _latest(state, "plan")
                    valid_proof = proof["type"] == "proof" and review["seq"] < proof["seq"] < disposition["seq"] and not _proof_errors(state, proof, "PASS", candidate, plan["data"]["revision"])
                    if _is_v2(state):
                        valid_proof = valid_proof and proof["data"].get("check") == finding["validation"]
                    valid = bool(data["reason"]) and valid_proof and data["action"] in {"FIXED", "NOT_APPLICABLE"}
                    if data["action"] == "FIXED":
                        recheck = next(e for e in _events(state, "recheck") if e["id"] == data["review_recheck"])
                        valid = valid and proof["seq"] < recheck["seq"] < disposition["seq"] and recheck["data"].get("proof") == proof["id"] and recheck["data"].get("plan") == plan["data"]["revision"] and recheck["data"].get("candidate") == candidate and recheck["data"].get("verdict") == "APPROVE" and not _review_errors(state, recheck, "sol", _contributors(state) | {review["data"]["reviewer"]["session"]})
                    if data["action"] == "RISK_ACCEPTED":
                        human = next(e for e in state["events"] if e["id"] == data["human_decision"])
                        hd = human["data"]
                        verify_reference(hd["source"])
                        plan = _latest(state, "plan")
                        valid = bool(data["reason"]) and valid_proof and finding.get("material") is True and hd.get("actor") == "human" and hd.get("kind") == "RISK_ACCEPTANCE" and bool(hd.get("statement")) and hd.get("plan") == plan["data"]["revision"] and hd.get("review") == review["id"] and hd.get("finding") == finding["id"] and review["seq"] < human["seq"] < disposition["seq"]
                except (RuntimeError, KeyError, TypeError, StopIteration, OSError):
                    valid = False
            if not valid:
                errors.append(f"unresolved actionable finding {review['id']}/{finding['id']}")
    return errors


def _proof_errors(state, proof, phase, candidate, revision):
    if _is_v2(state):
        return _v2().proof_errors(state, proof, phase, candidate, revision)
    try:
        data = proof["data"]
        verify_reference(data["output"])
        receipt = _read_json(data["output"]["path"])
        if not isinstance(receipt, dict) or set(receipt) != {"argv", "cwd", "exit", "stdout", "stderr"} or receipt["argv"] != data.get("command") or receipt["exit"] != data.get("exit") or receipt["cwd"] != state["contract"]["repo"]:
            raise RuntimeError("proof output must be the receipt of its captured command")
        for stream in ("stdout", "stderr"):
            verify_reference(receipt[stream])
        if data.get("plan") != revision or data.get("candidate") != candidate or type(data.get("exit")) is not int:
            raise RuntimeError("proof plan, source candidate or exit status is stale/malformed")
        observed = proof["observed_source"]
        if observed["sha256"] != candidate or proof.get("observed_profile") is None:
            raise RuntimeError("proof must match the actual server-observed source/profile")
        start = next(e for e in _events(state, "start") if e["id"] == data["start"] and e["seq"] < proof["seq"])
        prefix = dict(state, events=[e for e in state["events"] if e["seq"] < start["seq"]], seq=start["seq"] - 1, sha256=start["previous_sha256"])
        if start["data"].get("prefix") != start["previous_sha256"] or start["data"].get("plan") != revision or proof["observed_profile"] != start["data"].get("profile"):
            raise RuntimeError("proof does not bind its earlier exact-plan/profile/prefix start")
        issues = _start_errors(prefix, start["data"], proof_guard=True)
        if issues:
            raise RuntimeError("proof earlier start prerequisites failed: " + "; ".join(issues))
        before_proof = dict(state, events=[e for e in state["events"] if e["seq"] <= proof["seq"]])
        issues = _phase_errors(before_proof, observed, proof["observed_profile"])
        if issues:
            raise RuntimeError("proof phase/source transition failed: " + "; ".join(issues))
        latest_start = _latest(dict(state, events=[e for e in state["events"] if e["seq"] < proof["seq"]]), "start")
        if latest_start is None or latest_start["id"] != start["id"]:
            raise RuntimeError("proof must belong to the active latest work cycle")
        if phase == "RED":
            verify_reference(data["test"])
            if data.get("phase") != "RED" or data.get("outcome") != "INTENDED_ASSERTION_FAILURE" or data.get("failure_kind") != "ASSERTION" or data["exit"] == 0:
                raise RuntimeError("meaningful intended assertion RED is required; setup/import/syntax failure is insufficient")
            if start["data"]["mode"] != "TEST_ONLY" or start["seq"] >= proof["seq"]:
                raise RuntimeError("RED must follow its TEST_ONLY start")
        else:
            mode = start["data"]["mode"]
            if mode == "VERIFY":
                if data.get("phase") != "CHECK" or observed != start["data"]["candidate"]:
                    raise RuntimeError("VERIFY permits only CHECK on its unchanged full source/instructions")
            elif mode != "PRODUCTION" or data.get("phase") not in {"GREEN", "CHECK"}:
                raise RuntimeError("passing proof requires active VERIFY/CHECK or PRODUCTION/GREEN/CHECK")
            if phase == "GREEN":
                verify_reference(data["test"])
                if data.get("phase") != "GREEN":
                    raise RuntimeError("behavioral proof must be GREEN")
            if data.get("outcome") != "PASS" or data["exit"] != 0:
                raise RuntimeError("passing proof is required")
        if phase in {"RED", "GREEN"}:
            if data["acceptance"] not in start["data"]["acceptance"]:
                raise RuntimeError("proof acceptance is outside the earlier start")
            test_path = data.get("test_path")
            if test_path is None:
                test_path = str(Path(data["test"]["path"]).relative_to(Path(state["contract"]["repo"])))
            if test_path not in state["contract"]["test_scope"] or observed["files"].get(test_path) != data["test"]["sha256"]:
                raise RuntimeError("proof test bytes are not a declared server-observed test source")
        plan = next(e for e in _events(state, "plan") if e["data"]["revision"] == revision)
        if data["check"] not in plan["data"]["content"]["checks"]:
            raise RuntimeError("proof check is outside the approved plan")
        return []
    except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
        return [str(exc)]


def _write_scope(state, data):
    if _is_v2(state):
        return _v2().write_scope(state, data)
    content = _latest(state, "plan")["data"]["content"]
    tests = set(_paths(content["test_scope"]))
    ceiling = set(_paths(state["contract"]["test_scope"]))
    if not tests <= ceiling or not tests <= set(content["scope"]):
        raise RuntimeError("reviewed test subset exceeds immutable intake test roles")
    if data.get("mode") == "TEST_ONLY":
        selected = tests
    elif data.get("mode") == "PRODUCTION":
        selected = set(content["scope"]) - ceiling
    elif data.get("mode") == "VERIFY":
        selected = set()
    else:
        raise RuntimeError("unknown write mode")
    if "remediation" in data:
        selected &= set(_paths(data["remediation"]["scope"]))
    return sorted(selected)


def _source_snapshot(state, additional=()):
    if _is_v2(state):
        return _v2().snapshot(state, additional)
    contract = state["contract"]
    return snapshot(contract["repo"], contract["scope"], contract["instructions"])


def _phase_errors(state, current, current_profile=None, *, opening=()):
    errors = []
    try:
        contract = state["contract"]
        anchor = state["initial_source"]
        runtime = _v2() if _is_v2(state) else None
        if runtime:
            runtime.contract.validate_snapshot(anchor, runtime.core)
        active, open_test = None, None
        paths = set(contract["scope"])
        production = paths - set(contract["test_scope"])

        def observe(source, label, profile=None, manifest=()):
            nonlocal anchor
            registered = {row["path"]: row["baseline"] for row in manifest if row["path"] not in paths}
            paths.update(registered)
            production.update(row["path"] for row in manifest if row["role"] == "production")
            before = anchor["files"] | registered
            if runtime:
                runtime.contract.validate_snapshot(source, runtime.core)
                valid = set(source["instructions"]) == set(contract["instructions"])
                before_modes = anchor["modes"] | {name: source["modes"][name] for name in registered}
            else:
                check = dict(source)
                claimed = check.pop("sha256")
                valid = digest(check) == claimed
            if not valid or source["repo"] != contract["repo"] or set(source["files"]) != paths:
                errors.append(label + ": malformed full-intake source observation")
                return
            allowed = set(active["data"].get("write_scope", [])) if active else set()
            if active and active["data"].get("mode") == "VERIFY":
                if source["instructions"] != active["data"]["candidate"]["instructions"] or (profile is not None and profile != active["data"]["profile"]):
                    errors.append(label + ": source-preserving VERIFY instruction/profile identity changed")
            if runtime and any(source["modes"][name] != anchor["modes"][name] for name in contract["instructions"]):
                errors.append(label + ": instruction mode changed outside its authorized phase/write scope")
            if any(source["files"][name] != before[name]
                   or (runtime and source["modes"][name] != before_modes[name])
                   for name in paths - allowed):
                errors.append(label + ": source changed outside its authorized phase/write scope")
            if open_test and any(source["files"][name] != open_test["files"][name]
                                 or (runtime and source["modes"][name] != open_test["modes"][name])
                                 for name in production & set(open_test["files"])):
                errors.append(label + ": earliest open TEST_ONLY production baseline changed")
            anchor = source
        for event in state["events"]:
            if event["type"] == "start":
                observe(event["data"]["candidate"], event["id"], event["data"].get("profile"),
                        event["data"].get("observe_manifest", []) if runtime else ())
                mode = event["data"].get("mode")
                if mode == "TEST_ONLY" and open_test is None:
                    open_test = event["data"]["candidate"]
                elif mode == "PRODUCTION":
                    open_test = None
                active = event
            elif event["type"] in {"proof", "plan", "failure"}:
                observe(event["observed_source"], event["id"], event.get("observed_profile"))
            elif runtime and event["type"] == "proof_attempt":
                observe(event["data"]["broken"], event["id"])
        observe(current, "current", current_profile, opening)
        return errors
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        return errors + ["phase history gap: " + str(exc)]


def _remediation_errors(state, data):
    remediation = data.get("remediation")
    if remediation is None:
        return [], set(), set()
    try:
        required = {"findings", "defects", "scope", "acceptance", "checks", "before", "reason"}
        if _is_v2(state):
            required.add("case_pairs")
            if isinstance(remediation, dict) and "repair_actor" in remediation:
                required.add("repair_actor")
        if not isinstance(remediation, dict) or set(remediation) != required or not isinstance(remediation["reason"], str) or not remediation["reason"].strip() or remediation["before"] != data["candidate"]["sha256"]:
            raise RuntimeError("remediation must bind exact findings/defects/scope/checks/before-source and reason")
        content = _latest(state, "plan")["data"]["content"]
        selection = {k: remediation[k] for k in required - {"before", "reason"}}
        if selection not in content.get("remediations", []) or remediation["acceptance"] != data["acceptance"] or not remediation["defects"]:
            raise RuntimeError("remediation is not the exact approved plan mapping or omits captured defects")
        if not set(_paths(remediation["scope"])) <= set(content["scope"]) or not set(remediation["checks"]) <= set(content["checks"]) or not remediation["checks"]:
            raise RuntimeError("remediation paths/checks exceed approved ownership")
        findings = set()
        for item in remediation["findings"]:
            if not isinstance(item, dict) or set(item) != {"review", "finding"}:
                raise RuntimeError("remediation finding reference must use review and finding IDs")
            review = next(e for e in state["events"] if e["id"] == item["review"])
            _validate_review(review, v2=_is_v2(state))
            if not any(f["id"] == item["finding"] and f.get("actionable") is True for f in review["data"].get("findings", [])):
                raise RuntimeError("remediation names an unknown earlier actionable finding")
            findings.add((item["review"], item["finding"]))
        defects = set(remediation["defects"])
        for defect in defects:
            _label(defect, "remediation defect")
            if not any(e["data"].get("defect") == defect for e in _events(state, "case_link")):
                raise RuntimeError("remediation defect lacks an earlier canonical capture")
        return [], findings, defects
    except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
        return [str(exc)], set(), set()


def _rollout_extract(path, *, include_context=False):
    """Read the session id, model and effort Codex recorded in one session log."""
    source = _safe_path(path)
    if not source.is_file() or not source.name.startswith("rollout-") or source.suffix != ".jsonl":
        raise RuntimeError("identity evidence must be a Codex rollout-*.jsonl session log")
    hasher, size, session, identities = hashlib.sha256(), 0, None, set()
    synthetic, tiers, contexts = False, set(), set()
    with source.open("rb") as stream:
        for index, line in enumerate(stream):
            size += len(line)
            if size > MAX_ROLLOUT_BYTES:
                raise RuntimeError("Codex session log exceeds byte limit")
            hasher.update(line)
            # Logs reach hundreds of MiB; only the first record and turn contexts carry identity.
            if index and b'"turn_context"' not in line:
                continue
            record = json.loads(line)
            record = record if isinstance(record, dict) else {}
            payload = record.get("payload")
            if index == 0 and record.get("type") == "session_meta" and isinstance(payload, dict):
                session = _label(payload.get("id"), "logged session")
                if include_context:
                    synthetic = payload.get("synthetic") is True
            elif record.get("type") == "turn_context" and isinstance(payload, dict):
                identities.add((payload.get("model"), payload.get("effort")))
                if include_context:
                    tier = payload.get("service_tier")
                    tiers.add(tier if tier in ("Fast", "Standard") else None)
                    if "context" in payload:
                        contexts.add(digest(payload["context"]))
    if session is None:
        raise RuntimeError("unsupported Codex session log: the first record must be session_meta")
    if not source.name.endswith("-" + session + ".jsonl"):
        raise RuntimeError("Codex session log name does not match its session id")
    if len(identities) != 1:
        raise RuntimeError("Codex session log must show exactly one model and effort")
    (model, effort), = identities
    extract = {"schema": ROLLOUT_SCHEMA, "source": {"path": str(source), "size": size, "sha256": hasher.hexdigest()},
               "session": session, "model": _label(model, "logged model"), "effort": _label(effort, "logged effort")}
    if include_context:
        extract.update(synthetic=synthetic, observed_tier=next(iter(tiers)) if len(tiers) == 1 else None,
                       context_sha256=sorted(contexts))
    return extract


def _verify_identity(state, ref, identity):
    """Bind a recorded session, model and effort to this run's `rollout` extract."""
    verify_reference(ref)
    path = Path(ref["path"])
    if path.parent != Path(state["evidence_root"]) or path.name != ref["sha256"] + ".json":
        raise RuntimeError("identity evidence must be a session-log extract from `i2e.py rollout` for this run")
    extract = _read_json(ref["path"])
    if not isinstance(extract, dict) or extract.get("schema") != ROLLOUT_SCHEMA or any(extract.get(k) != identity.get(k) for k in ("session", "model", "effort")):
        raise RuntimeError("session, model and effort must match the observed Codex session log")


def _routing_errors(state, plan):
    if not _historical(state) and evaluate_policy(plan["data"]["content"]["policy"]).get("workflow") == "critical-four-v1":
        return ["transfer the scoped work to i2e.py critical before starting the Critical plan"]
    try:
        if _is_v2(state):
            _v2().routing(state, plan)
            return []
        routing = _latest(state, "observation", lambda e: e["data"].get("kind") == "ROUTING")
        if routing is None or routing["seq"] >= plan["seq"]:
            raise RuntimeError("observed read-only probe and selected-owner routing must precede the owner plan")
        policy = evaluate_policy(plan["data"]["content"]["policy"], historical=_historical(state))
        expected = V1_MODELS["astra"] if policy.get("owner") == "astra" else V1_MODELS["sol"]
        for lane, model in (("owner", expected), ("probe", V1_MODELS["sol"])):
            observed = routing["data"][lane]
            if set(observed) != {"session", "model", "effort", "evidence"} or observed["model"] != model or observed["effort"] != "max":
                raise RuntimeError("actual owner/probe model observation does not match selected policy")
            _label(observed["session"], lane + " session")
            _verify_identity(state, observed["evidence"], observed)
        if routing["data"]["owner"]["session"] not in plan["data"]["content"]["contributors"]:
            raise RuntimeError("selected observed delivery owner must be a plan contributor")
        return []
    except (RuntimeError, KeyError, TypeError, ValueError, OSError) as exc:
        return [str(exc)]


def _pending_defects(state, candidate):
    result = set()
    for intent in _events(state, "capture_intent"):
        data = intent["data"]
        resolved = any(e["data"].get("defect") == data["defect"] and e["seq"] > intent["seq"] and e["data"].get("outcome") == "PASS" for e in _events(state, "repair"))
        if not resolved and data["request"]["failure"]["broken"]["sha256"] == candidate:
            result.add(data["defect"])
    return result


def _repair_prerequisites(state, candidate, defect):
    errors = []
    links = [e for e in _events(state, "case_link") if e["data"].get("defect") == defect]
    intents = [e for e in _events(state, "capture_intent") if e["data"].get("defect") == defect and any(link["data"]["intent"] == e["id"] for link in links)]
    intent = next((e for e in reversed(intents) if e["data"]["request"]["failure"]["broken"]["sha256"] == candidate), None)
    if intent is None:
        errors.append("repair requires an earlier canonical capture of the actual current broken source")
    consultation = _latest(state, "consultation", lambda e: e["data"].get("stage") == "repair" and e["data"].get("target") == candidate)
    errors.extend(_consultation_errors(state, consultation))
    if intent and consultation and consultation["seq"] <= max(e["seq"] for e in links if e["data"]["intent"] == intent["id"]):
        errors.append("repair consultation must follow the current failure capture/link")
    failures = [e for e in _events(state, "repair") if e["data"].get("defect") == defect and e["data"].get("outcome") == "FAIL"]
    inherited = _v2().prior_failures(state, candidate, defect) if _is_v2(state) else 0
    if len(failures) + inherited >= 2:
        boundary = failures[-1]["seq"] if failures else 0
        if inherited:
            boundary = max(boundary, *(e["seq"] for e in _events(state, "case_binding")
                                       if e["data"]["request"]["defect"] == defect))
        diagnosis = _latest(state, "escalation", lambda e: e["data"].get("defect") == defect)
        if diagnosis is None or diagnosis["seq"] <= boundary or diagnosis["data"].get("verdict") != "DIAGNOSED":
            errors.append("two failed repairs of the same defect require prior fresh Astra Max diagnosis")
        else:
            errors.extend(_review_errors(state, diagnosis, "astra", _contributors(state) | _participants(state, before=diagnosis["seq"])))
    return errors


def _repair_errors(state, data):
    errors = []
    defects = _pending_defects(state, data["candidate"]["sha256"]) | set(data.get("pending_defects", []))
    if data.get("repair_defect"):
        defects.add(data["repair_defect"])
    latest_start = _latest_work_start(state)
    if data.get("mode") == "PRODUCTION" and latest_start and latest_start["data"]["mode"] == "TEST_ONLY":
        defects.update(latest_start["data"].get("pending_defects", []))
        if latest_start["data"].get("repair_defect"):
            defects.add(latest_start["data"]["repair_defect"])
    for defect in defects:
        errors.extend(_repair_prerequisites(state, data["candidate"]["sha256"], defect))
    for repair in _events(state, "repair"):
        try:
            record = repair["data"]
            verify_reference(record["output"])
            if record.get("outcome") not in {"PASS", "FAIL"}:
                raise RuntimeError("repair outcome is unknown")
            start = next(e for e in _events(state, "start") if e["id"] == record["start"] and e["seq"] < repair["seq"])
            if start["data"].get("mode") != "PRODUCTION" or start["data"]["candidate"]["sha256"] != record["before"]:
                raise RuntimeError("repair must bind its earlier production start and broken source")
            prefix = dict(state, events=[e for e in state["events"] if e["seq"] < start["seq"]])
            errors.extend(_repair_prerequisites(prefix, record["before"], record["defect"]))
        except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
            errors.append(f"repair history gap {repair['id']}: {str(exc) or 'earlier work start is missing'}")
    return errors


def _start_errors(state, data, *, proof_guard=False):
    errors = []
    try:
        contract = state["contract"]
        if "edit" not in contract["authority"]["actions"]:
            errors.append("run has no edit authority")
        verify_reference(contract["authority"]["evidence"])
        verify_reference({"path": contract["case_helper"], "sha256": contract["case_helper_sha256"]})
        if data.get("mode") not in {"TEST_ONLY", "PRODUCTION", "VERIFY"}:
            errors.append("unknown write mode")
        plans = _events(state, "plan")
        if not plans:
            return errors + ["finalized plan is missing"]
        plan = plans[-1]
        p, content = plan["data"], plan["data"]["content"]
        if _is_v2(state):
            _v2().validate_start(state, data)
        errors.extend(_routing_errors(state, plan))
        if data.get("profile") != plan.get("observed_profile"):
            errors.append("active profile instructions/runtime changed since plan review")
        if p["revision"] != digest(content) or data.get("plan") != p["revision"]:
            errors.append("start must bind the exact latest immutable plan")
        if p.get("supersedes") != (plans[-2]["data"]["revision"] if len(plans) > 1 else None):
            errors.append("plan revision must retain its immediate predecessor")
        verify_reference(content["artifact"])
        if not set(_paths(content["scope"])) <= set(contract["scope"]):
            errors.append("plan source scope exceeds owned contract")
        opening = data.get("observe_manifest", []) if _is_v2(state) else ()
        paths = _v2().owned_paths(state) | {row["path"] for row in opening} if _is_v2(state) else set(contract["scope"])
        if set(data["candidate"]["files"]) != paths or data["candidate"]["instructions"] != plan.get("observed_instructions"):
            errors.append("source manifest or instruction identity changed")
        if data.get("write_scope") != _write_scope(state, data):
            errors.append("start does not bind its declared test/production write scope")
        errors.extend(_phase_errors(state, data["candidate"], data.get("profile"), opening=opening))
        claimed = dict(data["candidate"])
        sha = claimed.pop("sha256")
        if digest(claimed) != sha:
            errors.append("candidate digest mismatch")
        acceptance = {a["id"]: a for a in content["acceptance"]}
        if not isinstance(data.get("acceptance"), list) or not data["acceptance"] or not set(data["acceptance"]) <= set(acceptance):
            errors.append("start acceptance must be explicit and owned")
        if any(type(a["behavior"]) is not bool for a in acceptance.values()):
            errors.append("acceptance behavior classification is unknown")
        if not acceptance or len(acceptance) != len(content["acceptance"]) or any(a["behavior"] is False and not a.get("reason", "").strip() for a in acceptance.values()):
            errors.append("nonbehavior acceptance requires a concrete justification; IDs must be unique")
        if not isinstance(content["checks"], list) or not content["checks"] or len(content["checks"]) != len(set(content["checks"])):
            errors.append("relevant required checks must be explicit and unique")
        if evaluate_policy(content["policy"], historical=_historical(state))["state"] != "PASS":
            errors.append("plan policy is unknown")
        preplan = next((e for e in state["events"] if e["id"] == p["consultation"] and e["seq"] < plan["seq"] and e["type"] == "consultation" and e["data"].get("stage") == "plan"), None)
        preplan_state = dict(state, events=[e for e in state["events"] if e["seq"] < plan["seq"]])
        errors.extend(_consultation_errors(preplan_state, preplan))
        reviews = [e for e in _events(state, "plan_review") if e["data"].get("plan") == p["revision"]]
        # The light lane may omit plan approval; a recorded rejection still governs.
        if not _is_v2(state) and not reviews and evaluate_policy(content["policy"], historical=_historical(state))["lane"] != "light":
            errors.append("fresh exact-plan Astra approval is missing")
        elif reviews and not _is_v2(state):
            review = reviews[-1]
            exclusions = _contributors(state) | {e["data"]["reviewer"]["session"] for e in _events(state, "plan_review") if e["seq"] < review["seq"]}
            errors.extend(_review_errors(state, review, "astra", exclusions))
            if review["seq"] <= plan["seq"] or review["data"].get("verdict") != "APPROVE":
                errors.append("latest exact-plan review is not qualifying APPROVE")
        decisions = {}
        for event in _events(state, "decision"):
            decisions[event["data"]["lineage"]] = event
        required = set(content["decisions"])
        for lineage, decision in decisions.items():
            if set(decision["data"].get("acceptance", [])) & set(data["acceptance"]):
                required.add(lineage)
        if not required and not content.get("decision_reason"):
            errors.append("empty decision selection requires an applicability reason")
        for lineage in required:
            decision = decisions.get(lineage)
            if decision is None:
                errors.append("required decision is missing")
                continue
            d = decision["data"]
            verify_reference(d["artifact"])
            substantive = dict(d)
            decision_sha = substantive.pop("revision")
            if decision_sha != digest(substantive):
                errors.append("decision revision digest mismatch")
            lineage_events = [e for e in _events(state, "decision") if e["data"]["lineage"] == lineage]
            if d.get("supersedes") != (lineage_events[-2]["data"]["revision"] if len(lineage_events) > 1 else None):
                errors.append("decision lineage must retain its immediate predecessor")
            if d.get("kind") not in {"ordinary", "architecture", "critical"}:
                errors.append("decision risk classification is unknown")
            reviews = [e for e in _events(state, "doubt_review") if e["data"].get("decision") == lineage]
            unresolved = 0
            for review in reviews:
                resolved = review["data"].get("verdict") == "SUPPORTED" and not _decision_resolution_errors(state, review)
                unresolved = 0 if resolved else unresolved + 1
            if unresolved >= 3:
                errors.append("three unresolved decision cycles stop dependent work; surface the stable lineage to the coordinator")
            latest = next((e for e in reversed(reviews) if e["data"].get("revision") == d["revision"]), None)
            if d.get("kind") == "ordinary" and d.get("strategy") == "TDD_RED" and data["mode"] in {"TEST_ONLY", "VERIFY"}:
                continue
            if d.get("kind") == "ordinary" and d.get("strategy") == "TDD_RED" and latest is None:
                red_proofs = [_latest(state, "proof", lambda e: e["data"].get("acceptance") == behavior and e["data"].get("phase") == "RED") for behavior in d["acceptance"]]
                if red_proofs and all(proof and not _proof_errors(state, proof, "RED", data["candidate"]["sha256"], p["revision"]) for proof in red_proofs):
                    continue
            if latest is None or latest["data"].get("verdict") != "SUPPORTED":
                errors.append(f"decision {lineage} requires a current supported fresh challenge")
                continue
            role = "sol" if d.get("kind") == "ordinary" else "astra"
            excluded = _contributors(state) | {e["data"]["reviewer"]["session"] for e in reviews if e["seq"] < latest["seq"]}
            errors.extend(_review_errors(state, latest, role, excluded))
        remediation_errors, deferred_findings, remediation_defects = _remediation_errors(state, data)
        errors.extend(remediation_errors)
        if data["mode"] == "VERIFY":
            # Evidence collection leaves these findings OPEN; it cannot produce
            # their disposition or authorize a source mutation.
            for event in state["events"]:
                if event["type"] in REVIEW_TYPES:
                    _validate_review(event, v2=_is_v2(state))
                    deferred_findings.update((event["id"], finding["id"]) for finding in event["data"].get("findings", []) if finding["actionable"])
        errors.extend(_finding_errors(state, data["candidate"]["sha256"], deferred_findings))
        if _is_v2(state):
            deferred_cases = _v2().deferred_cases(state, data, remediation_defects)
        else:
            deferred_cases = {(event["data"]["digest"], check) for event in _events(state, "case_link")
                              if event["data"]["defect"] in remediation_defects for check in data["remediation"]["checks"]}
        errors.extend(_knowledge_errors(state, data["candidate"]["sha256"], proofs=data["mode"] != "VERIFY", deferred=deferred_cases))
        for defect in remediation_defects:
            errors.extend(_repair_prerequisites(state, data["candidate"]["sha256"], defect))
        errors.extend(_repair_errors(state, data))
        if data["mode"] == "PRODUCTION":
            for acceptance_id in data["acceptance"]:
                if acceptance[acceptance_id]["behavior"]:
                    red = _latest(state, "proof", lambda e: e["data"].get("acceptance") == acceptance_id and e["data"].get("phase") == "RED")
                    if red is None:
                        errors.append(f"meaningful RED missing for {acceptance_id}")
                    else:
                        errors.extend(_proof_errors(state, red, "RED", data["candidate"]["sha256"], p["revision"]))
                        work = _latest_work_start(state)
                        if work is None or work["data"]["mode"] != "TEST_ONLY" or work["id"] != red["data"].get("start"):
                            errors.append("RED must belong to the latest TEST_ONLY cycle")
        return errors
    except (RuntimeError, KeyError, TypeError, ValueError, StopIteration, OSError) as exc:
        return errors + [str(exc)]


def _teaching_errors(state, candidate, revision, allow_partial=False):
    teaching = _latest(state, "teaching")
    if teaching is None:
        return ["source-grounded engineering brief is missing"]
    try:
        data = teaching["data"]
        report = next(e for e in state["events"] if e["id"] == data["report"])
        if report["type"] != "observation" or report["seq"] >= teaching["seq"] or report["data"].get("status") not in {"COMPLETED", "FAILED", "INTERRUPTED"}:
            raise RuntimeError("brief must follow an actual delivery/status report")
        if data["candidate"] != candidate or data["plan"] != revision:
            raise RuntimeError("engineering brief is stale")
        if not allow_partial and (report["data"].get("status") != "COMPLETED" or report["data"].get("candidate") != candidate):
            raise RuntimeError("completion requires a COMPLETED status report for the current candidate")
        for name in ("problem", "path", "principle", "example", "limits"):
            if not isinstance(data[name], str) or not data[name].strip():
                raise RuntimeError("engineering brief requires factual problem/path/principle/example/limits")
        partial = allow_partial and report["data"].get("status") in {"FAILED", "INTERRUPTED"}
        if not data["sources"] or (not data["proofs"] and not partial):
            raise RuntimeError("brief source and proof references are required")
        for ref in data["sources"]:
            verify_reference(ref)
        for event_id in data["proofs"]:
            proof = next(e for e in state["events"] if e["id"] == event_id and e["type"] == "proof")
            if proof["seq"] >= teaching["seq"] or proof["data"].get("candidate") != candidate:
                raise RuntimeError("brief cites unavailable or stale proof")
        for event_id in data["decisions"]:
            if not any(e["id"] == event_id and e["type"] == "decision" and e["seq"] < teaching["seq"] for e in state["events"]):
                raise RuntimeError("brief cannot invent a decision")
        decisions = [e for e in state["events"] if e["id"] in data["decisions"]]
        actual_alternatives = [a for e in decisions for a in e["data"].get("alternatives", [])]
        if data["alternatives"] != actual_alternatives:
            raise RuntimeError("brief alternatives must reference the actual recorded decisions")
        return []
    except (RuntimeError, KeyError, TypeError, StopIteration, OSError) as exc:
        return [str(exc)]


def _blocked(errors: list[str]) -> dict:
    return {
        "schema": POLICY_SCHEMA,
        "state": "BLOCK",
        "owner": None,
        "final_review": None,
        "lane": None,
        "errors": errors,
    }


def _historical(state):
    return state.get("critical_workflow") != "critical-four-v1"


def evaluate_policy(request: object, *, historical=False) -> dict:
    if isinstance(request, dict) and request.get("schema") == "i2e-team-policy-v2":
        return _v2().contract.policy(request, TRIGGERS, historical=historical)
    result = _original_policy(request)
    if historical or result["state"] != "PASS":
        return result
    architecture = request.get("significant_architecture", False)
    if type(architecture) is not bool:
        return _blocked(["significant_architecture must be a boolean"])
    if request.get("risk") in ("High", "Critical") or architecture:
        rules = runpy.run_path(str(Path(__file__).with_name("critical_routing.py")))
        return rules["apply"](result)
    result["owner"] = "sol"
    return result


def _original_policy(request: object) -> dict:
    """Separate implementation ownership from the seven final-review triggers.

    Unknown values leave both routing decisions unavailable. Resource telemetry
    is optional context and does not participate in either decision. The light
    assurance lane is opt-in and limited to P2/P3, Low/Medium, untriggered work.
    """
    if not isinstance(request, dict):
        return _blocked(["policy must be an object"])
    if "schema" in request and request["schema"] != POLICY_SCHEMA:
        return _blocked(["policy schema is unsupported"])

    errors = []
    priority, risk, triggers = (
        request.get("priority"), request.get("risk"), request.get("triggers")
    )
    lane = request.get("lane", "full")
    if not isinstance(priority, str) or priority not in {"P0", "P1", "P2", "P3"}:
        errors.append("priority must be P0, P1, P2 or P3; unknown priority blocks routing")
    if not isinstance(risk, str) or risk not in {"Low", "Medium", "High", "Critical"}:
        errors.append("risk must be Low, Medium, High or Critical; unknown risk blocks routing")
    if not isinstance(triggers, dict) or set(triggers) != set(TRIGGERS):
        errors.append("triggers must explicitly contain exactly the seven named assessments")
    if isinstance(triggers, dict):
        for name in TRIGGERS:
            if name in triggers and type(triggers[name]) is not bool:
                errors.append(f"trigger {name} must be true or false; unknown blocks routing")
    if not isinstance(lane, str) or lane not in {"full", "light"}:
        errors.append("lane must be full or light; unknown lane blocks routing")
    if errors:
        return _blocked(errors)
    if lane == "light" and (priority not in {"P2", "P3"} or risk not in {"Low", "Medium"} or any(triggers.values())):
        return _blocked(["light lane requires P2 or P3 priority, Low or Medium risk and no true trigger"])

    return {
        "schema": POLICY_SCHEMA,
        "state": "PASS",
        "owner": "astra" if priority == "P0" or risk == "Critical" else "sol",
        "final_review": "astra" if any(triggers.values()) else None,
        "lane": lane,
        "errors": [],
    }


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _read_json(input_path: str) -> object:
    if input_path == "-":
        data = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
    else:
        with Path(input_path).open("rb") as source:
            data = source.read(MAX_JSON_BYTES + 1)
    return _parse_json(data)


def _parse_json(data: bytes) -> object:
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON input exceeds byte limit")
    return json.loads(
        data.decode("utf-8", errors="strict"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_reject_constant,
    )


E2E_DRIVERS = {
    "web": "chrome-devtools-mcp", "api": "public-api-harness",
    "cli": "cli-subprocess", "mobile": "simulator-or-emulator", "desktop": "computer-use",
}
PROPERTY_LIBRARIES = {
    "typescript": "fast-check", "javascript": "fast-check",
    "python": "hypothesis", "rust": "proptest",
}


def _checkout_catalog(path, feature):
    if not feature:
        raise ValueError("--catalog requires --feature")
    root = Path.cwd().resolve()
    source = (root / path).resolve(strict=True)
    if not source.is_relative_to(root):
        raise ValueError("run from the checkout containing the catalog")
    raw = _file_bytes(source, reject_links=False)
    catalog = _parse_json(raw)
    if not isinstance(catalog, dict) or catalog.get("schema") != "i2e-verification-catalog/v1":
        raise ValueError("unsupported verification catalog schema")
    features = catalog.get("features")
    if not isinstance(features, dict) or feature not in features:
        raise ValueError(f"unknown verification feature: {feature}")
    spec = features[feature]
    if not isinstance(spec, dict) or not isinstance(spec.get("entrypoint"), str) or not spec["entrypoint"].strip():
        raise ValueError("the selected feature requires an entrypoint")
    if not isinstance(spec.get("checks"), list) or not spec["checks"]:
        raise ValueError("the selected feature requires at least one check")
    check_ids = []
    for check in spec["checks"]:
        if not isinstance(check, dict) or not all(
            isinstance(check.get(key), str) and check[key].strip() for key in ("claim", "oracle")
        ):
            raise ValueError("each selected check requires a claim and an oracle")
        check_ids.append(_label(check.get("id"), "check ID"))
    rules = []
    if not isinstance(catalog.get("rules"), list):
        raise ValueError("catalog rules must be an array")
    for rule in catalog["rules"]:
        if not isinstance(rule, dict) or _label(rule.get("feature"), "rule feature") not in features:
            raise ValueError("rule refers to an unknown feature")
        if rule["feature"] != feature:
            continue
        rule_id = _label(rule.get("id"), "rule ID")
        if rule.get("status") not in ("observe", "enforced"):
            raise ValueError(f"unknown rule status for {rule_id}")
        if not isinstance(rule.get("case_digest"), str) or not re.fullmatch("[0-9a-f]{64}", rule["case_digest"]):
            raise ValueError(f"rule {rule_id} requires its source case digest")
        examples = rule.get("examples")
        if not isinstance(examples, list) or not examples or not all(
            isinstance(row, dict) and {"input", "expected"} <= row.keys() for row in examples
        ):
            raise ValueError(f"rule {rule_id} requires an input and expected result for each example")
        rules.append({"id": rule_id, "status": rule["status"]})
    ids = check_ids + [rule["id"] for rule in rules]
    if len(set(ids)) != len(ids):
        raise ValueError("check and rule IDs must be unique within the selected feature")
    return {"feature": feature, "root": "checkout", "path": source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(), "entrypoint": spec["entrypoint"],
            "checks": check_ids, "rules": rules}


def select_tools(surface, language, feature, catalog_path=None):
    if not (surface or language):
        raise ValueError("select an E2E surface, a property-test language, or both")
    selection = {"schema": "i2e-verification-tools/v1", "state": "SELECTED"}
    if surface:
        selection["e2e"] = {"surface": surface, "driver": E2E_DRIVERS[surface]}
    if language:
        selection["properties"] = {"language": language, "library": PROPERTY_LIBRARIES[language]}
    if catalog_path is not None:
        selection["catalog"] = _checkout_catalog(catalog_path, feature)
    elif feature:
        relative = "references/label-verification.json"
        catalog = (Path(__file__).resolve().parents[1] / relative).read_bytes()
        if feature not in json.loads(catalog)["features"]:
            raise ValueError(f"unknown verification feature: {feature}")
        selection["catalog"] = {"feature": feature, "path": relative,
                                "sha256": hashlib.sha256(catalog).hexdigest()}
    return selection


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    components = {"critical": "critical_flow.py", "setup-speckit": "critical_speckit.py"}
    if argv and argv[0] in components:
        return subprocess.run([sys.executable, "-B", str(Path(__file__).with_name(components[argv[0]])), *argv[1:]]).returncode
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("critical", help="run the four-round Critical workflow")
    commands.add_parser("setup-speckit", help="prepare an isolated Codex Spec Kit planning workspace")
    selection = commands.add_parser("select-tools", help="select local verification tools for a plan")
    selection.add_argument("--surface", choices=E2E_DRIVERS)
    selection.add_argument("--language", choices=PROPERTY_LIBRARIES)
    selection.add_argument("--feature", help="bind the shared catalog for an applicable feature")
    selection.add_argument("--catalog", help="feature catalog in the current checkout; requires --feature")
    policy = commands.add_parser("policy", help="validate explicit owner and final-review policy")
    policy.add_argument("--input", required=True, help="JSON path, or - for stdin")
    for name in ("run", "check", "case", "brief", "preflight", "proof", "rollout", "worker", "delivery"):
        command = commands.add_parser(name)
        if name in {"run", "case"}:
            command.add_argument("operation", choices=("init", "append", "show", "search") if name == "run" else ("capture", "consult", "bind"))
        if name == "worker":
            command.add_argument("operation", choices=("prepare", "qualify", "run", "status", "revoke", "submit", "admit", "cleanup"))
        if name == "delivery":
            command.add_argument("operation", choices=("inspect", "prepare", "execute", "reconcile"))
        command.add_argument("--db", required=True)
        command.add_argument("--run")
        command.add_argument("--expect", type=int)
        command.add_argument("--input")
        if name == "run":
            command.add_argument("--project")
            command.add_argument("--query")
        if name == "preflight":
            command.add_argument("--mode", required=True, choices=("TEST_ONLY", "PRODUCTION", "VERIFY"))
        if name == "rollout":
            command.add_argument("--log", required=True, help="Codex rollout-*.jsonl session log")
    args = parser.parse_args(argv)
    try:
        if args.command == "select-tools":
            result = select_tools(args.surface, args.language, args.feature, args.catalog)
        elif args.command == "policy":
            result = evaluate_policy(_read_json(args.input))
        else:
            ledger = Ledger(args.db)
            if args.command == "run" and args.operation == "init":
                result = ledger.init_run(_read_json(args.input))
            elif args.command == "run" and args.operation == "search":
                result = {"results": ledger.search(args.project, args.query)}
            else:
                if not args.run:
                    raise RuntimeError("--run is required")
                if args.command == "run" and args.operation == "show":
                    result = ledger.show(args.run)
                elif args.command == "run" and args.operation == "append":
                    result = ledger.append(args.run, _read_json(args.input), args.expect)
                elif args.command == "preflight":
                    result = ledger.preflight(args.run, args.mode, args.expect, _read_json(args.input))
                elif args.command == "proof":
                    result = ledger.prove(args.run, args.expect, _read_json(args.input))
                elif args.command == "worker":
                    result = ledger.worker(args.run, args.operation, args.expect, _read_json(args.input))
                elif args.command == "delivery":
                    result = ledger.delivery(args.run, args.operation, args.expect, _read_json(args.input))
                elif args.command == "rollout":
                    result = ledger.rollout(args.run, args.log)
                elif args.command == "case":
                    method = {"capture": ledger.capture, "consult": ledger.consult, "bind": ledger.bind_case}[args.operation]
                    result = method(args.run, args.expect, _read_json(args.input))
                elif args.command == "check":
                    result = ledger.check(args.run)
                elif args.command == "brief":
                    result = ledger.brief(args.run)
                else:
                    raise RuntimeError("unsupported operation")
    except (RuntimeError, OSError, ValueError, UnicodeError, RecursionError, TypeError, KeyError) as exc:
        result = _blocked([f"local input or evidence operation failed: {exc}"])
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    blocked = result.get("state") == "BLOCK"
    held_effect = args.command in {"worker", "delivery"} and result.get("state") == "HOLD"
    return 1 if blocked or held_effect else 0


if __name__ == "__main__":
    raise SystemExit(main())
