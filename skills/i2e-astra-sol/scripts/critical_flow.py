#!/usr/bin/env python3
"""Run the four Critical rounds against one private, checkout-bound record."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

from critical_issues import parse_tasks, sync_tasks, task_board
from critical_routing import routing
from critical_speckit import planner_argv, ready as spec_kit_ready


SCHEMA = "i2e-critical-run-v1"
CHECKS = ("lint", "e2e")
ARTIFACTS = ("spec.md", "plan.md", "tasks.md")
CRITERION = re.compile(r"\s*[-*]\s+\*\*(SC-[0-9]{3,})\*\*:\s*(\S.*)")
TASK_PROGRESS = re.compile(rb"(?m)^(\s*[-*][ \t]+\[)[ xX](\][ \t]+T[0-9]{3,}[ \t])")
SESSION_ID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
TIER = {"priority": "priority", "fast": "priority", "default": "default", "standard": "default"}
CHECK_TIMEOUT = 1800


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("session timestamp must include a timezone")
    return instant


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


def reference(path):
    with path.open("rb") as data:
        value = hashlib.file_digest(data, "sha256").hexdigest()
        size = data.tell()
    return {"path": str(path), "sha256": value, "bytes": size}


def verify_reference(ref):
    if reference(Path(ref["path"])) != ref:
        raise ValueError(f"recorded evidence changed: {ref['path']}")


def git(repo, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, env=env, timeout=60,
    ).stdout


def candidate(repo):
    """Bind HEAD, the index, and current tracked and nonignored source bytes."""
    head = git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
    index = git(repo, "ls-files", "--stage", "-z")
    names = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = {}
    for name in sorted(set(names.split(b"\0")) - {b""}):
        relative = os.fsdecode(name)
        path = repo / relative
        if not path.parent.resolve().is_relative_to(repo):
            raise ValueError(f"candidate path escapes checkout: {relative}")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            files[relative] = None
            continue
        if stat.S_ISLNK(mode):
            files[relative] = ["symlink", os.readlink(path)]
        elif stat.S_ISDIR(mode):
            if (path / ".git").exists():
                files[relative] = ["repository", candidate(path)["sha256"]]
            else:
                files[relative] = ["directory"]
        elif stat.S_ISREG(mode):
            files[relative] = ["file", mode & 0o111, reference(path)["sha256"]]
        else:
            raise ValueError(f"unsupported candidate entry: {relative}")
    return {"head": head, "sha256": sha(encode([head, sha(index), files]))}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, path):
        self.path = path.parent.resolve() / path.name
        self.private = self.path.with_name(self.path.name + ".d")

    def outside(self, repo):
        for root in (repo, Path(__file__).resolve().parents[1]):
            if self.path.is_relative_to(root) or self.private.is_relative_to(root) or root.is_relative_to(self.private):
                raise ValueError("Critical state and its sidecar must live outside the checkout and skill")

    @staticmethod
    def private_file(path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError(f"expected an owner-only regular file: {path}")

    @contextmanager
    def locked(self, create=False):
        if create:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.private.mkdir(mode=0o700, exist_ok=True)
        info = self.private.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Critical state sidecar must be an owner-only directory")
        lock = self.private / "state.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self.private_file(lock)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield fd
        except BlockingIOError as exc:
            raise ValueError("Critical run is busy") from exc
        finally:
            os.close(fd)

    def load(self):
        self.private_file(self.path)
        state = json.loads(self.path.read_bytes())
        if state.get("schema") != SCHEMA:
            raise ValueError("unrecognized Critical state schema")
        self.outside(Path(state["repo"]))
        return state

    def save(self, state):
        atomic_write(self.path, encode(state))

    def capture(self, path, name=None):
        origin = path.resolve(strict=True)
        if not origin.is_file():
            raise ValueError(f"evidence must be a regular file: {origin}")
        data = origin.read_bytes()
        if not data.strip():
            raise ValueError(f"evidence is empty: {origin}")
        directory = self.private / sha(data)
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / (name or "evidence")
        atomic_write(target, data)
        return reference(target) | {"origin": str(origin)}


def dispatch_request(record, session, role):
    argv = record.get("argv")
    if record.get("session") != session or not isinstance(argv, list) or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("dispatch record must match the rollout session and contain its Codex argv")
    if len(argv) < 2 or Path(argv[0]).name != "codex" or "exec" not in argv:
        raise ValueError("dispatch record must contain a Codex exec launch")
    config = {}
    model = None
    for index, arg in enumerate(argv[:-1]):
        if arg in ("--model", "-m"):
            model = argv[index + 1]
        if arg in ("--config", "-c"):
            key, _, value = argv[index + 1].partition("=")
            config[key] = value.strip('"\'')
    if (model, config.get("model_reasoning_effort"), config.get("service_tier")) != (
        role["model"], role["reasoning_effort"], role["service_tier"],
    ):
        raise ValueError("dispatch argv does not request the required model, Max effort and service tier")
    return argv


def check_planner_dispatch(argv, workspace, store, repo):
    effective = [Path(argv[0]).name, *argv[1:]]
    outputs = [index for index, value in enumerate(effective) if value in ("-o", "--output-last-message")]
    if len(outputs) > 1 or outputs and outputs[0] == len(effective) - 1:
        raise ValueError("Astra dispatch may name one private output file")
    if outputs:
        index = outputs[0]
        destination = Path(effective[index + 1])
        output = destination.resolve()
        if (not destination.is_absolute() or not output.is_relative_to(store.path.parent)
                or output in (store.path, store.path.parent) or output.is_relative_to(repo)
                or output.is_relative_to(store.private)):
            raise ValueError("Astra output must be an absolute private file beside this run's state")
        del effective[index:index + 2]
    if effective != planner_argv(workspace):
        raise ValueError("Astra dispatch must match the canonical offline Spec Kit launch")


def actor(store, args, state, role, planner_workspace=None):
    target = next(row for row in routing() if row["role"] == role)
    source = args.rollout.resolve(strict=True)
    sessions = (Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions").resolve()
    if not source.is_relative_to(sessions) or not source.is_file() or not source.name.startswith("rollout-"):
        raise ValueError("actor evidence must be a Codex rollout under the host sessions directory")
    identity = set()
    requests = set()
    hasher = hashlib.sha256()
    size = 0
    with source.open("rb") as log:
        for index, line in enumerate(log):
            if not line.endswith(b"\n"):
                break  # Codex may still be writing the last record.
            size += len(line)
            if size > 512 * 1024 * 1024:
                raise ValueError("Codex rollout exceeds the evidence limit")
            hasher.update(line)
            if index and b'"turn_context"' not in line:
                continue
            record = json.loads(line)
            payload = record.get("payload", {})
            if index == 0:
                if record.get("type") != "session_meta" or payload.get("synthetic") or not payload.get("originator"):
                    raise ValueError("expected host session metadata")
                metadata = payload
            elif record.get("type") == "turn_context":
                identity.add((payload.get("model"), payload.get("effort"), str(Path(payload["cwd"]).resolve())))
                if payload.get("service_tier") is not None:
                    requests.add(TIER.get(str(payload["service_tier"]).lower(), "UNKNOWN"))
                if planner_workspace and "sandbox_policy" in payload:
                    policy = payload["sandbox_policy"]
                    if (policy.get("type") != "workspace-write" or policy.get("network_access") is not False
                            or payload.get("approval_policy", "never") != "never"
                            or any(Path(path).resolve() != planner_workspace for path in policy.get("writable_roots", []))):
                        raise ValueError("Astra rollout records sandbox or network permissions beyond its private workspace")
    if not size:
        raise ValueError("empty Codex rollout")
    session = metadata.get("id", "")
    if not SESSION_ID.fullmatch(session) or not source.name.endswith(f"-{session}.jsonl"):
        raise ValueError("Codex rollout filename and logged thread ID disagree")
    expected_cwd = str(planner_workspace) if planner_workspace else state["repo"]
    if identity != {(target["model"], target["reasoning_effort"], expected_cwd)}:
        raise ValueError(f"Codex rollout must show {target['model']} Max in the selected workspace")
    standalone = metadata.get("source") in ("exec", "cli", "vscode") and not any(
        metadata.get(key) for key in ("forked_from_id", "parent_thread_id", "attached_thread")
    )
    if planner_workspace and (not standalone or metadata.get("source") != "exec"
                              or Path(metadata["cwd"]).resolve() != planner_workspace):
        raise ValueError("Astra requires a standalone Codex exec session in the prepared workspace")
    started = timestamp(metadata["timestamp"])
    if started > timestamp(now()):
        raise ValueError("Codex session start is in the future")
    if requests and requests != {target["service_tier"]}:
        raise ValueError("host records a different service tier request from the role policy")
    dispatch = None
    if args.dispatch:
        dispatch = store.capture(args.dispatch, "dispatch.json")
        argv = dispatch_request(json.loads(Path(dispatch["path"]).read_bytes()), session, target)
        if planner_workspace:
            check_planner_dispatch(argv, planner_workspace, store, Path(state["repo"]))
    elif planner_workspace:
        raise ValueError("Astra plan requires the captured offline --dispatch record")
    elif not requests:
        raise ValueError("host tier request is absent; supply the captured --dispatch record")
    return target | {
        "session": session, "started_at": started.isoformat(),
        "cwd": expected_cwd,
        "rollout": {"path": str(source), "sha256": hasher.hexdigest(), "bytes": size},
        "dispatch": dispatch, "tier_request_evidence": "host" if requests else "dispatch",
        "effective_service_tier": "UNKNOWN",
        "standalone": standalone,
    }


def previous(state, role):
    return next((item for item in reversed(state["rounds"]) if item["role"] == role), None)


def append(state, role, identity, **fields):
    record = {"role": role, "actor": identity, "recorded_at": now(), **fields}
    state["rounds"].append(record)
    return record


def read_criteria(path):
    criteria = {}
    fence = None
    for line in path.read_text().splitlines():
        prefix = line.lstrip()[:3]
        if prefix in ("```", "~~~"):
            fence = None if fence == prefix else fence or prefix
        elif not fence and (match := CRITERION.fullmatch(line)):
            case, requirement = match.groups()
            if case in criteria or requirement.startswith("["):
                raise ValueError(f"duplicate or unfilled Spec Kit criterion: {case}")
            criteria[case] = requirement
    if not criteria:
        raise ValueError("spec.md must define measurable Spec Kit success criteria (SC-001 etc.)")
    return criteria


def argv_value(raw):
    value = json.loads(raw)
    if not isinstance(value, list) or not value or any(
        not isinstance(arg, str) or "\0" in arg for arg in value
    ) or not value[0].strip():
        raise ValueError("checks require JSON arrays of executable argv")
    return value


def planning_inputs(store, args, repo):
    root = store.path.parent
    paths = {name: getattr(args, name[:-3]).resolve(strict=True) for name in ARTIFACTS}
    if any(path.name != name or path.is_relative_to(repo) or not path.is_relative_to(root)
           for name, path in paths.items()) or len({path.parent for path in paths.values()}) != 1:
        raise ValueError("plan artifacts must share a private feature directory under the state's parent outside the checkout")
    directory = paths["spec.md"].parent
    if any(ancestor != store.private and (ancestor / "state.lock").is_file()
           for ancestor in (directory, *directory.parents) if ancestor.is_relative_to(root)):
        raise ValueError("plan artifacts belong to another Critical run")
    for workspace in (directory, *directory.parents):
        if not workspace.is_relative_to(root):
            break
        if (workspace / ".specify/init-options.json").is_file():
            spec_kit_ready(workspace)
            if directory.parent == workspace / "specs":
                return paths, workspace
    raise ValueError("plan artifacts must be under specs/<feature> in the prepared local Codex Spec Kit workspace")


def plan_round(store, args, state, identity, repo, paths, workspace):
    old = previous(state, "plan")
    reason = (args.replan_reason or "").strip()
    if (old and not reason) or (not old and (state["phase"] != "plan" or reason)):
        raise ValueError("a first plan follows the probe; a replan requires the changed design or criteria reason")
    base = candidate(repo)
    if old is None and base != state["initial_candidate"]:
        raise ValueError("preserve the probed checkout through the first plan")
    artifacts = {name: store.capture(path, name) for name, path in paths.items()}
    if old and all(artifacts[name]["sha256"] == old["artifacts"][name]["sha256"] for name in ("spec.md", "plan.md")):
        raise ValueError("replanning requires a changed specification or design plan")
    criteria = read_criteria(Path(artifacts["spec.md"]["path"]))
    commands = {name: argv_value(getattr(args, name + "_argv")) for name in CHECKS}
    if commands["lint"] == commands["e2e"]:
        raise ValueError("plan must identify distinct project lint and end-to-end checks")
    checklist = Path(artifacts["tasks.md"]["path"])
    task_ids = list(parse_tasks(checklist))
    if candidate(repo) != base:
        raise ValueError("checkout changed while recording the plan")
    tasks = sync_tasks(checklist, store.private)
    if [item["task"] for item in tasks] != task_ids or len({item["ref"] for item in tasks}) != len(tasks):
        raise ValueError("each planned task needs a distinct local task reference in task order")
    files = {name: item["sha256"] for name, item in artifacts.items()}
    binding = sha(encode([files, commands, tasks, base, identity["session"]]))
    append(state, "plan", identity, plan_sha256=binding, base=base, artifacts=artifacts,
           criteria=criteria, commands=commands, tasks=tasks, replan_reason=reason or None,
           spec_kit_workspace=str(workspace))
    state["phase"] = "implement"


def bound_plan(state):
    plan = previous(state, "plan")
    for name, artifact in plan["artifacts"].items():
        verify_reference({key: artifact[key] for key in ("path", "bytes", "sha256")})
        origin = Path(artifact["origin"])
        current = origin.read_bytes()
        if sha(current) == artifact["sha256"]:
            continue
        if name == "tasks.md" and TASK_PROGRESS.sub(rb"\1 \2", current) == TASK_PROGRESS.sub(
            rb"\1 \2", Path(artifact["path"]).read_bytes(),
        ):
            continue
        raise ValueError(f"approved {name} changed; replan before proceeding")
    return plan


def implement_round(store, args, state, identity, repo):
    current = candidate(repo)
    earlier = previous(state, "implement")
    phase = state["phase"]
    if phase not in ("implement", "repair") and not (
        phase in ("verify", "assess", "complete") and current != earlier["candidate"]
    ):
        raise ValueError("implementation requires an approved plan, a failed check or a changed candidate")
    if any(item["role"] == "verify" and item["actor"]["session"] == identity["session"] for item in state["rounds"]):
        raise ValueError("an independent verifier cannot implement or repair this run")
    plan = bound_plan(state)
    verification = previous(state, "verify")
    failure = verification.get("verification_sha256") if verification and phase == "repair" else None
    append(state, "implement", identity, plan_sha256=plan["plan_sha256"], candidate=current,
           evidence=store.capture(args.evidence), repair_of=failure)
    state["phase"] = "verify"


def executable_check(repo, directory, name, argv, lock_fd):
    stdout = directory / (name + ".stdout")
    stderr = directory / (name + ".stderr")
    code = None
    error = None
    started = now()
    with stdout.open("xb") as output, stderr.open("xb") as diagnostic:
        os.fchmod(output.fileno(), 0o600)
        os.fchmod(diagnostic.fileno(), 0o600)
        try:
            with subprocess.Popen(argv, cwd=repo, stdin=subprocess.DEVNULL, stdout=output, stderr=diagnostic,
                                  start_new_session=True, pass_fds=(lock_fd,)) as process:
                try:
                    code = process.wait(timeout=CHECK_TIMEOUT)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait()
                    error = "check timed out"
        except (OSError, ValueError) as exc:
            error = str(exc)
        for stream in (output, diagnostic):
            stream.flush()
            os.fsync(stream.fileno())
    return {"argv": argv, "exit_code": code, "result": "PASS" if code == 0 and error is None else "FAIL",
            "error": error, "started_at": started, "finished_at": now(),
            "stdout": reference(stdout), "stderr": reference(stderr)}


def close_verification(record, result):
    record["result"] = result
    record["verification_sha256"] = sha(encode(record))


def verify_round(store, state, identity, repo, lock_fd):
    if state["phase"] != "verify":
        raise ValueError("verification requires the integrated implementation handoff")
    implementation = previous(state, "implement")
    session = identity["session"]
    used = {item["actor"]["session"] for item in state["rounds"]}
    if (not identity["standalone"] or session in used or session == state["coordinator_session"]
            or timestamp(identity["started_at"]) < timestamp(implementation["recorded_at"])):
        raise ValueError("verification requires a fresh standalone Sol session started after this implementation")
    plan = bound_plan(state)
    integrated = implementation["candidate"]
    if candidate(repo) != integrated:
        raise ValueError("integrated candidate changed; refresh the implementation handoff")
    directory = Path(tempfile.mkdtemp(prefix="verify-", dir=store.private))
    record = append(state, "verify", identity, plan_sha256=plan["plan_sha256"], candidate=integrated,
                    result="RUNNING", checks={}, output_directory=str(directory))
    state["phase"] = "verifying"
    store.save(state)
    unchanged = True
    for name in CHECKS:
        if unchanged:
            check = executable_check(repo, directory, name, plan["commands"][name], lock_fd)
            try:
                unchanged = candidate(repo) == integrated
                bound_plan(state)
            except (OSError, ValueError, subprocess.SubprocessError):
                unchanged = False
            check["candidate_unchanged"] = unchanged
        else:
            check = {"result": "NOT_RUN", "error": "candidate or approved plan changed during verification"}
        record["checks"][name] = check
        store.save(state)
    passed = unchanged and all(item["result"] == "PASS" for item in record["checks"].values())
    close_verification(record, "CHECKS_PASSED" if passed else "FAIL")
    state["phase"] = "assess" if passed else "repair"
    return passed


def accept_round(store, args, state, identity, repo):
    if state["phase"] != "assess":
        raise ValueError("acceptance requires successful checks for the integrated candidate")
    record = previous(state, "verify")
    if record["actor"]["session"] != identity["session"]:
        raise ValueError("acceptance must be recorded by the same independent verifier")
    try:
        plan = bound_plan(state)
        if candidate(repo) != record["candidate"]:
            raise ValueError("integrated candidate changed")
        for check in record["checks"].values():
            verify_reference(check["stdout"])
            verify_reference(check["stderr"])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        record["assessment"] = {"result": "STALE", "reason": str(exc)}
        state["phase"] = "repair"
        return False
    ref = store.capture(args.acceptance, "acceptance.json")
    evidence = json.loads(Path(ref["path"]).read_bytes())
    for key, expected in {
        "plan_sha256": plan["plan_sha256"], "candidate_sha256": record["candidate"]["sha256"],
        "verification_sha256": record["verification_sha256"],
    }.items():
        if evidence.get(key) != expected:
            raise ValueError("acceptance must bind the plan, integrated candidate and exact verification receipt")
    cases = evidence.get("cases")
    if not isinstance(cases, list) or any(
        not isinstance(case, dict) or set(case) != {"id", "verdict", "check", "observation"}
        or not isinstance(case["id"], str) or case["verdict"] not in ("PASS", "FAIL")
        or case["check"] not in (*CHECKS, "inspection")
        or not isinstance(case["observation"], str) or not case["observation"].strip()
        for case in cases
    ) or len(cases) != len(plan["criteria"]) or {case["id"] for case in cases} != set(plan["criteria"]):
        raise ValueError("acceptance needs one observed PASS or FAIL against each planned success criterion")
    passed = all(case["verdict"] == "PASS" for case in cases)
    record["assessment"] = {"result": "PASS" if passed else "FAIL", "cases": cases, "evidence": ref,
                            "session": identity["session"], "recorded_at": now()}
    state["phase"] = "complete" if passed else "repair"
    return passed


def status(state):
    plan = previous(state, "plan")
    implementation = previous(state, "implement")
    verification = previous(state, "verify")
    active = implementation if plan and implementation and implementation["plan_sha256"] == plan["plan_sha256"] else None
    checked = verification if active and verification and state["rounds"].index(verification) > state["rounds"].index(active) else None
    current = None
    candidate_error = None
    try:
        current = candidate(Path(state["repo"]))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        candidate_error = str(exc)
    plan_error = None
    if plan:
        try:
            bound_plan(state)
        except (OSError, ValueError) as exc:
            plan_error = str(exc)
    candidate_current = active["candidate"] == current if active else None
    acceptance_current = None
    if state["phase"] == "complete":
        acceptance_current = bool(candidate_current and plan_error is None)
        if acceptance_current:
            try:
                for check in checked["checks"].values():
                    verify_reference(check["stdout"])
                    verify_reference(check["stderr"])
                ref = checked["assessment"]["evidence"]
                verify_reference({key: ref[key] for key in ("path", "bytes", "sha256")})
            except (OSError, ValueError):
                acceptance_current = False
    return state | {
        "plan_sha256": plan["plan_sha256"] if plan else None,
        "criteria": plan["criteria"] if plan else {},
        "commands": plan["commands"] if plan else {},
        "tasks": plan["tasks"] if plan else [],
        "candidate_sha256": active["candidate"]["sha256"] if active else None,
        "candidate_current": candidate_current,
        "candidate_error": candidate_error,
        "plan_current": plan_error is None if plan else None,
        "plan_error": plan_error,
        "acceptance_current": acceptance_current,
        "verification_sha256": checked.get("verification_sha256") if checked else None,
        "checks": checked["checks"] if checked else {},
    }


def execute(store, args):
    action = args.action
    if action == "init":
        repo = args.repo.resolve(strict=True)
        if Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel").rstrip())).resolve() != repo:
            raise ValueError("--repo must name the Git checkout root")
        store.outside(repo)
    with store.locked(create=action == "init") as lock_fd:
        if action == "init":
            if store.path.exists() or store.path.is_symlink():
                state = store.load()
                if state["repo"] != str(repo):
                    raise ValueError("Critical state already belongs to another checkout")
            else:
                state = {"repo": str(repo), "schema": SCHEMA, "phase": "probe", "rounds": [], "created_at": now(),
                         "initial_candidate": candidate(repo), "coordinator_session": os.getenv("CODEX_THREAD_ID")}
                store.save(state)
            return status(state), True
        state = store.load()
        repo = Path(state["repo"])
        if action == "status":
            return status(state), True
        phase = state["phase"]
        if action in ("tasks", "task"):
            plan = previous(state, "plan")
            if plan is None:
                raise ValueError("local tasks require an approved plan")
            if action == "task" and phase not in ("implement", "repair"):
                raise ValueError("local task updates require an active implementation or repair")
            return task_board(plan["tasks"], store.private, getattr(args, "id", None), getattr(args, "status", None)), True
        role = "verify" if action == "accept" else action
        paths, workspace = planning_inputs(store, args, repo) if action == "plan" else (None, None)
        identity = actor(store, args, state, role, workspace)
        if role == "verify" and os.getenv("CODEX_THREAD_ID") != identity["session"]:
            raise ValueError("run this command from the recorded Sol verifier session")
        if phase == "verifying" and action in ("implement", "verify", "plan"):
            close_verification(previous(state, "verify"), "INTERRUPTED")
            state["phase"] = "repair" if action == "implement" else "verify"
            store.save(state)
        passed = True
        if action == "probe":
            if phase != "probe" or candidate(repo) != state["initial_candidate"]:
                raise ValueError("the read-only probe must precede planning and preserve the initial checkout")
            append(state, "probe", identity, candidate=state["initial_candidate"], evidence=store.capture(args.evidence))
            state["phase"] = "plan"
        elif action == "plan":
            plan_round(store, args, state, identity, repo, paths, workspace)
        elif action == "implement":
            implement_round(store, args, state, identity, repo)
        elif action == "verify":
            passed = verify_round(store, state, identity, repo, lock_fd)
        elif action == "accept":
            passed = accept_round(store, args, state, identity, repo)
        store.save(state)
        return status(state), passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=lambda value: Path(value).expanduser())
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("routing")
    actions.add_parser("status")
    actions.add_parser("tasks")
    task = actions.add_parser("task")
    task.add_argument("--id", required=True)
    task.add_argument("--status", required=True, choices=("OPEN", "IN_PROGRESS", "DONE"))
    init = actions.add_parser("init")
    init.add_argument("--repo", required=True, type=Path)
    for action in ("probe", "plan", "implement", "verify", "accept"):
        command = actions.add_parser(action)
        command.add_argument("--rollout", required=True, type=Path)
        command.add_argument("--dispatch", type=Path)
        if action in ("probe", "implement"):
            command.add_argument("--evidence", required=True, type=Path)
        if action == "plan":
            for name in ARTIFACTS:
                command.add_argument("--" + name[:-3], required=True, type=Path)
            for name in CHECKS:
                command.add_argument("--" + name + "-argv", required=True)
            command.add_argument("--replan-reason")
        if action == "accept":
            command.add_argument("--acceptance", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        if args.action != "routing" and args.state is None:
            parser.error("--state is required for this action")
    except SystemExit as exc:
        return int(exc.code)
    if args.action == "routing":
        print(encode(routing()).decode(), end="")
        return 0
    try:
        state, passed = execute(Store(args.state), args)
        print(encode(state).decode(), end="")
        return 0 if passed else 1
    except (OSError, ValueError, TypeError, AttributeError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Critical: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
