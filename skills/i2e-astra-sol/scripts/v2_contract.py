"""Typed records for the staged v2 proof and repair slice."""
from __future__ import annotations

import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import unicodedata


RUN_SCHEMA = "i2e-team-run-v2"
POLICY_SCHEMA = "i2e-team-policy-v2"
PROFILE = "i2e-team/v2"
EXECUTOR = "macos-sandbox-full-clone-v1"
MODELS = {"sol": "gpt-6.2-sol", "astra": "gpt-6.2-astra"}

_POLICY_FIELDS = {
    "schema", "queue_priority", "technical_risk", "execution_lane", "significant_architecture",
    "triggers", "direct_eligible", "reproducible_acceptance", "specialists", "tier_policy",
}
_RUN_FIELDS = {
    "schema", "profile", "run_id", "project", "repo", "scope", "test_scope", "instructions",
    "contributors", "authority", "policy", "case_store", "case_helper", "case_helper_sha256",
    "known_cases", "objective", "parent_request", "tickets", "write_boundary", "source",
    "executor_mode", "synthetic",
}
_PLAN_FIELDS = {
    "artifact", "scope", "test_scope", "acceptance", "checks", "required_checks", "result_map",
    "aggregate_checks", "decisions", "decision_reason", "contributors", "policy", "remediations",
}


def fields(value, required, description, *, optional=frozenset()):
    if not isinstance(value, dict) or not required <= set(value) <= required | optional:
        raise ValueError(f"{description} has missing or unsupported fields")


def text(value, description):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} requires concrete text")


def validate_test_id(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 512
            or value != value.strip() or not value.isprintable()):
        raise ValueError("test_id must be a printable single-line string of 1 to 512 characters without edge whitespace")


def labels(values, label, core, *, nonempty=False):
    if not isinstance(values, list) or (nonempty and not values):
        raise ValueError(f"{label} must be an explicit list")
    for value in values:
        core._label(value, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} entries must be unique")
    return set(values)


def sha256(value, description):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{description} requires a SHA-256 digest")


def _assurance(row):
    fields(row, {"ticket_count", "clear_authority", "bounded_scope", "observable_acceptance",
                 "adequate_regression", "interaction_coverage", "checks"}, "combined assurance assessment")
    count = row["ticket_count"]
    if type(count) is not int or not 1 <= count <= 5 or not isinstance(row["checks"], dict) or not row["checks"]:
        raise ValueError("assurance requires one to five tickets and named check assessments")
    flags = ("clear_authority", "bounded_scope", "observable_acceptance", "adequate_regression", "interaction_coverage")
    if any(type(row[key]) is not bool and row[key] is not None for key in flags):
        raise ValueError("assurance assessments must be true, false or unknown")
    checked = True
    for name, proof in row["checks"].items():
        text(name, "assessed check")
        fields(proof, {"state", "reason"}, "required check assessment")
        if proof["state"] not in ("PASS", "FAIL", "NOT_RUN") or not isinstance(proof["reason"], str):
            raise ValueError("required check assessment is malformed")
        checked &= proof["state"] == "PASS" or (proof["state"] == "NOT_RUN" and bool(proof["reason"].strip()))
    return checked and all(row[key] is True for key in flags)


def _routine_worker(row):
    fields(row, {"model", "paths", "bounded"}, "routine worker")
    paths = row["paths"]
    if (row["model"] != MODELS["sol"] or row["bounded"] is not True
            or not isinstance(paths, list) or not paths):
        raise ValueError("routine work requires the selected Sol model and explicit bounded paths")
    for path in paths:
        if (not isinstance(path, str) or not path or path.startswith("/")
                or any(character in path for character in "\\*?[]\x00")
                or any(part in ("", ".", "..", ".git") for part in path.split("/"))):
            raise ValueError("routine worker paths must be literal owned paths")
    if len(set(paths)) != len(paths):
        raise ValueError("routine worker paths must be unique")


def settings(role):
    return {"model": MODELS[role], "effort": "max", "tier": "Standard" if role == "astra" else "Fast"}


def policy(request, triggers, *, historical=False):
    result = {"schema": POLICY_SCHEMA, "state": "BLOCK", "owner": None, "lead": None,
              "lane": None, "final_review": None, "audits": [], "errors": []}
    try:
        fields(request, _POLICY_FIELDS - {"tier_policy"}, "v2 policy",
               optional={"tier_policy", "assurance", "routine_worker"})
        if request["schema"] != POLICY_SCHEMA:
            raise ValueError("explicit v2 policy schema is required")
        if request["queue_priority"] not in ("urgent", "normal", "deferred", "P0", "P1", "P2", "P3"):
            raise ValueError("queue priority is unknown")
        risk = request["technical_risk"]
        if risk not in ("Low", "Medium", "High", "Critical"):
            raise ValueError("technical risk is unknown")
        fields(request["triggers"], set(triggers), "final-review triggers")
        assessments = [request[key] for key in ("significant_architecture", "direct_eligible", "reproducible_acceptance")]
        if any(type(value) is not bool for value in assessments + list(request["triggers"].values())):
            raise ValueError("architecture, eligibility and all review triggers require known assessments")
        specialists = request["specialists"]
        if (not isinstance(specialists, list) or any(name not in ("security", "tests", "architecture") for name in specialists)
                or len(specialists) != len(set(specialists))):
            raise ValueError("specialists must be distinct supported assignments")
        if request.get("tier_policy", "require_match") not in ("require_match", "record_unknown"):
            raise ValueError("tier policy must be explicitly supported")
        lane = request["execution_lane"]
        critical = risk in ("High", "Critical") or request["significant_architecture"]
        if lane not in ("Direct", "Standard", "Critical") or (lane == "Critical") != critical:
            raise ValueError("requested lane does not match the assessed technical risk and architecture")
        covered = _assurance(request["assurance"]) if "assurance" in request else False
        final = "astra" if critical or "architecture" in specialists or any(request["triggers"].values()) else None
        reduced = (risk == "Low" and request["direct_eligible"] and request["reproducible_acceptance"]
                   and covered and not specialists and final is None)
        if lane == "Direct" and (not reduced or request["assurance"]["ticket_count"] != 1):
            raise ValueError("Direct requires one bounded eligible Low-risk ticket and current explained checks")
        owner = "astra" if critical else "sol"
        lead = None if lane == "Direct" else owner
        if "routine_worker" in request:
            _routine_worker(request["routine_worker"])
            if critical:
                raise ValueError("routine assignments require the Direct or Standard lane")
        requested = {"owner": settings(owner), "probe": settings("sol")}
        if lead:
            requested["lead"] = settings(lead)
        result.update(state="PASS", owner=owner, lead=lead, lane=lane, final_review=final,
                      audits=["combined"] if reduced else ["code", "security", "tests"],
                      requested_settings=requested)
        if critical and not historical:
            rules = runpy.run_path(str(Path(__file__).with_name("critical_routing.py")))
            return rules["apply"](result)
    except (ValueError, TypeError, KeyError) as exc:
        result["errors"].append(str(exc))
    return result


def git_base(repo):
    """Observe the local Git root and HEAD without loading user Git configuration."""
    argv = ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "rev-parse", "--show-toplevel", "HEAD"]
    env = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(argv, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=8, check=False)
        parts = result.stdout.decode("utf-8").splitlines()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Git base could not be observed") from exc
    if result.returncode or len(parts) != 2 or parts[0] != str(repo):
        raise ValueError("v2 requires the actual local Git repository root")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", parts[1]):
        raise ValueError("Git base is not a full commit identity")
    return parts[1]


def path_key(path):
    return tuple(unicodedata.normalize("NFC", part.casefold()) for part in path.split("/"))


def within(path, parent):
    key = path_key(parent)
    return path_key(path)[:len(key)] == key


def v2_path(path, core):
    core._paths([path])
    for part in path_key(path):
        if part == ".git" or part == ".env" or part.startswith(".env.") or part.endswith((".pem", ".key")):
            raise ValueError("path has a protected or sensitive spelling")
    return path


def reserved_paths(contract, core):
    paths = set(contract["instructions"]) | set(contract["write_boundary"]["excluded"])
    repo = Path(contract["repo"])
    for candidate in (contract["case_helper"], contract["case_store"], contract["authority"]["evidence"]["path"]):
        private = core._safe_path(candidate)
        if private.is_relative_to(repo):
            paths.add(str(private.relative_to(repo)))
    return paths


def require_writable_name(contract, path, core):
    v2_path(path, core)
    if any(within(path, reserved) for reserved in reserved_paths(contract, core)):
        raise ValueError("path is inside a protected input or excluded surface")


def validate_file_domain(paths, core):
    names = set(paths)
    folded = {}
    for path in names:
        v2_path(path, core)
        parts = path.split("/")
        key = path_key(path)
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            old = folded.setdefault(key[:length], prefix)
            if old != prefix:
                raise ValueError("source paths have a case or Unicode spelling collision")
            if length < len(parts) and prefix in names:
                raise ValueError("source paths have a file and directory collision")


def path_identity(repo, path, core, *, kind="file"):
    """Observe exact directory spelling and bind physical ancestry before a grant."""
    v2_path(path, core)
    current = core._safe_path(repo)
    root = current.lstat()
    if not stat.S_ISDIR(root.st_mode):
        raise ValueError("repository root is not a real directory")
    parts = path.split("/")
    ancestry = [{"path": ".", "device": root.st_dev, "inode": root.st_ino}]
    for index, part in enumerate(parts):
        leaf = index == len(parts) - 1
        key = path_key(part)
        with os.scandir(current) as entries:
            matching = [entry.name for entry in entries if path_key(entry.name) == key]
        candidate = current / part
        if matching != [part]:
            if matching:
                raise ValueError("source path is ambiguous or does not use the actual directory spelling")
            try:
                candidate.lstat()
            except FileNotFoundError:
                return {"path": path, "ancestors": ancestry, "leaf": None}
            raise ValueError("source path resolves through a noncanonical filesystem alias")
        info = candidate.lstat()
        if info.st_dev != root.st_dev or stat.S_ISLNK(info.st_mode):
            raise ValueError("source path crosses an unqualified volume or symbolic link")
        relative = "/".join(parts[:index + 1])
        identity = {"device": info.st_dev, "inode": info.st_ino}
        if not leaf:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("source path ancestor is not a real directory")
            ancestry.append(dict(identity, path=relative))
            current = candidate
            continue
        regular, directory = stat.S_ISREG(info.st_mode), stat.S_ISDIR(info.st_mode)
        if regular and info.st_nlink != 1:
            raise ValueError("source path has a foreign hard link")
        allowed = (regular and kind in {"file", "either"}) or (directory and kind in {"directory", "either"})
        if not allowed:
            raise ValueError("source path is not the approved regular file or directory kind")
        return {"path": path, "ancestors": ancestry,
                "leaf": dict(identity, mode=stat.S_IMODE(info.st_mode), links=info.st_nlink)}
    raise ValueError("source path is empty")


def observe_path_domain(contract, paths, core):
    names = set(paths) | set(contract["instructions"])
    validate_file_domain(names, core)
    identities, physical = {}, set()
    for name in sorted(names):
        identity = path_identity(contract["repo"], name, core)
        leaf = identity["leaf"]
        if leaf is not None:
            key = (leaf["device"], leaf["inode"])
            if key in physical:
                raise ValueError("source paths share a physical leaf identity")
            physical.add(key)
        identities[name] = identity
    return identities


def validate_path_record(path, record, present):
    fields(record, {"path", "ancestors", "leaf"}, "physical path observation")
    ancestors = record["ancestors"]
    prefixes = [".", *("/".join(path.split("/")[:i]) for i in range(1, len(path.split("/"))))]
    if (record["path"] != path or not isinstance(ancestors, list) or not 1 <= len(ancestors) <= len(prefixes)
            or (record["leaf"] is not None) != present or (present and len(ancestors) != len(prefixes))):
        raise ValueError("recorded physical path is inconsistent with the before candidate")
    for ancestor, prefix in zip(ancestors, prefixes):
        fields(ancestor, {"path", "device", "inode"}, "physical ancestor")
        if (ancestor["path"] != prefix or ancestor["device"] != ancestors[0]["device"]
                or any(type(ancestor[key]) is not int or ancestor[key] < 0 for key in ("device", "inode"))):
            raise ValueError("recorded physical ancestor is malformed")
    if present:
        leaf = record["leaf"]
        fields(leaf, {"device", "inode", "mode", "links"}, "physical file leaf")
        if (any(type(leaf[key]) is not int or leaf[key] < 0 for key in leaf)
                or leaf["links"] != 1 or leaf["device"] != ancestors[0]["device"] or leaf["mode"] > 0o7777):
            raise ValueError("recorded physical leaf is malformed")


def git_mode(mode):
    if type(mode) is not int or not 0 <= mode <= 0o777:
        raise ValueError("regular source file has an unsupported mode")
    return "100755" if mode & stat.S_IXUSR else "100644"


def validate_snapshot(candidate, core):
    fields(candidate, {"repo", "files", "instructions", "modes", "sha256"}, "v2 mode-bound source snapshot")
    files, instructions, modes = (candidate[key] for key in ("files", "instructions", "modes"))
    if not all(isinstance(group, dict) for group in (files, instructions, modes)):
        raise ValueError("v2 source bytes and modes must be explicit path maps")
    if files.keys() & instructions.keys() or modes.keys() != files.keys() | instructions.keys():
        raise ValueError("v2 modes must cover the exact source and instruction path union")
    for name, checksum in (files | instructions).items():
        if checksum is None and name in files:
            if modes[name] is not None:
                raise ValueError("absent source must have a null Git mode")
        else:
            sha256(checksum, "observed source bytes")
            if modes[name] not in ("100644", "100755"):
                raise ValueError("present source must have a regular Git mode")
    body = {key: value for key, value in candidate.items() if key != "sha256"}
    if candidate["sha256"] != core.digest(body):
        raise ValueError("v2 source snapshot digest does not bind its bytes and modes")


def initial_owners(contract, content):
    owners = {}
    for ticket in contract["tickets"]:
        for acceptance in ticket["acceptance"]:
            result = content["result_map"][acceptance]
            for role in ("test", "production"):
                for path in result[role]:
                    owners.setdefault(path, {}).setdefault(ticket["id"], set()).add(acceptance)
    return owners


def validate_run(contract, core):
    fields(contract, _RUN_FIELDS, "v2 run contract", optional={"coordinator", "delivery", "rollback"})
    if (contract["schema"] != RUN_SCHEMA or contract["profile"] != PROFILE
            or contract["executor_mode"] != EXECUTOR or type(contract["synthetic"]) is not bool):
        raise ValueError("v2 profile, executor and synthetic classification must be explicit")
    for key in ("run_id", "project"):
        core._label(contract[key], key)
    for key in ("objective", "parent_request"):
        text(contract[key], key)
    contributors = labels(contract["contributors"], "contributor", core, nonempty=True)
    if "coordinator" in contract and contract["coordinator"] not in contributors:
        raise ValueError("coordinator requires recorded contributor identity")
    if "rollback" in contract:
        text(contract["rollback"], "rollback intent")
    if "delivery" in contract:
        validate_delivery(contract["delivery"], core)
    scope = set(core._paths(contract["scope"]))
    tests = set(core._paths(contract["test_scope"]))
    instructions = set(core._paths(contract["instructions"]))
    if not scope or not tests <= scope or instructions & scope:
        raise ValueError("owned files, immutable test roles and instructions overlap or are incomplete")
    boundary = contract["write_boundary"]
    fields(boundary, {"test", "production", "excluded"}, "write boundary", optional={"surfaces"})
    if (set(core._paths(boundary["test"])) != tests
            or set(core._paths(boundary["production"])) != scope - tests
            or set(core._paths(boundary["excluded"])) & scope):
        raise ValueError("literal write boundary does not bind owned roles and exclusions")
    source = contract["source"]
    fields(source, {"base", "harness", "dependencies"}, "source identity", optional={"predecessor"})
    harness = set(core._paths(source["harness"]))
    dependencies = set(core._paths(source["dependencies"]))
    if not harness or not dependencies or harness & dependencies or not (harness | dependencies) <= instructions:
        raise ValueError("harness and dependencies must bind disjoint immutable input bytes")
    if git_base(core._safe_path(contract["repo"])) != source["base"]:
        raise ValueError("declared Git base differs from actual HEAD")
    fields(contract["authority"], {"actions", "evidence"}, "action authority")
    labels(contract["authority"]["actions"], "authorized action", core, nonempty=True)
    core.verify_reference(contract["authority"]["evidence"])
    core.verify_reference({"path": contract["case_helper"], "sha256": contract["case_helper_sha256"]})
    if not isinstance(contract["known_cases"], list):
        raise ValueError("known case digests must be an explicit list")
    for digest in contract["known_cases"]:
        sha256(digest, "known case")
    if len(set(contract["known_cases"])) != len(contract["known_cases"]):
        raise ValueError("known case digests must be unique")
    tickets = contract["tickets"]
    if not isinstance(tickets, list) or not 1 <= len(tickets) <= 5:
        raise ValueError("a run requires one to five logical tickets")
    ticket_ids, accepted = set(), set()
    for ticket in tickets:
        fields(ticket, {"id", "acceptance"}, "ticket")
        ticket_id = core._label(ticket["id"], "ticket")
        mapped = labels(ticket["acceptance"], "ticket acceptance", core, nonempty=True)
        if ticket_id in ticket_ids or accepted & mapped:
            raise ValueError("ticket IDs and acceptance ownership must be unique")
        ticket_ids.add(ticket_id)
        accepted.update(mapped)
    validate_surfaces(contract, ticket_ids, core)
    for name in scope:
        require_writable_name(contract, name, core)
    observe_path_domain(contract, scope, core)
    routing = policy(contract["policy"], core.TRIGGERS)
    if routing["state"] != "PASS":
        raise ValueError("v2 run policy refused: " + "; ".join(routing["errors"]))
    assessed = contract["policy"].get("assurance")
    if assessed is not None and assessed["ticket_count"] != len(tickets):
        raise ValueError("route assurance ticket count differs from actual ticket membership")
    if routing["lane"] == "Direct" and ("edit" not in contract["authority"]["actions"] or len(tickets) != 1):
        raise ValueError("Direct requires exact local edit authority for one ticket")
    routine = contract["policy"].get("routine_worker")
    if routine and not set(core._paths(routine["paths"])) <= scope:
        raise ValueError("routine worker exceeds actual owned paths")
    if "predecessor" in source:
        predecessor = source["predecessor"]
        fields(predecessor, {"run", "prefix", "candidate", "commit", "acceptance"}, "accepted predecessor")
        core._label(predecessor["run"], "predecessor run")
        sha256(predecessor["prefix"], "predecessor prefix")
        sha256(predecessor["candidate"], "predecessor candidate")
        if predecessor["commit"] != source["base"] or predecessor["run"] == contract["run_id"]:
            raise ValueError("dependent task must pin a distinct accepted predecessor commit")
        core.verify_reference(predecessor["acceptance"])


def validate_surfaces(contract, tickets, core):
    boundary = contract["write_boundary"]
    rows = boundary.get("surfaces", [])
    if not isinstance(rows, list) or len(rows) > 128:
        raise ValueError("approved write surfaces require a bounded array")
    established = {path_key(name): (name, role) for role in ("test", "production") for name in boundary[role]}
    paths = []
    for row in rows:
        fields(row, {"path", "kind", "role", "ticket"}, "write surface")
        path = row["path"]
        require_writable_name(contract, path, core)
        if row["kind"] not in ("file", "directory") or row["role"] not in ("test", "production") or row["ticket"] not in tickets:
            raise ValueError("write surface requires a literal kind, role and known ticket")
        previous = established.get(path_key(path))
        if previous and (previous != (path, row["role"]) or row["kind"] != "file"):
            raise ValueError("write surface conflicts with an established path role")
        if any(within(path, old) or within(old, path) for old in paths):
            raise ValueError("approved write surfaces overlap")
        path_identity(contract["repo"], path, core, kind=row["kind"])
        paths.append(path)
    for excluded in boundary["excluded"]:
        path_identity(contract["repo"], excluded, core, kind="either")


def validate_delivery(delivery, core):
    fields(delivery, {"repository", "target", "pr", "action", "actor", "trusted_check",
                      "rules_admin_trust", "authority"}, "delivery boundary")
    if (not isinstance(delivery["repository"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", delivery["repository"])
            or delivery["action"] != "merge_commit" or type(delivery["pr"]) is not int or delivery["pr"] < 1
            or type(delivery["rules_admin_trust"]) is not bool):
        raise ValueError("delivery requires one exact GitHub repository, PR and merge-commit action")
    for key in ("target", "actor"):
        core._label(delivery[key], "delivery " + key)
    trusted = delivery["trusted_check"]
    fields(trusted, {"name", "app_id"}, "trusted check")
    core._label(trusted["name"], "trusted check name")
    if type(trusted["app_id"]) is not int or trusted["app_id"] <= 0:
        raise ValueError("trusted check requires a GitHub App ID")
    core.verify_reference(delivery["authority"])


def pairs(rows, core):
    if not isinstance(rows, list):
        raise ValueError("inherited case pairs must be an explicit array")
    result = set()
    for row in rows:
        fields(row, {"digest", "check"}, "inherited case/check pair")
        sha256(row["digest"], "inherited case")
        core._label(row["check"], "inherited check")
        result.add((row["digest"], row["check"]))
    if len(result) != len(rows):
        raise ValueError("inherited case/check pairs must be unique")
    return result


def validate_plan(state, content, core):
    fields(content, _PLAN_FIELDS, "v2 plan",
           optional={"batch", "expected_files", "rollback", "delivery", "verification_map"})
    contract = state["contract"]
    core.verify_reference(content["artifact"])
    scope = set(core._paths(content["scope"]))
    tests = set(core._paths(content["test_scope"]))
    if not scope <= set(contract["scope"]) or tests != scope & set(contract["test_scope"]):
        raise ValueError("plan scope cannot expand ownership or reclassify test paths")
    previous = core._latest(state, "plan")
    earlier_policy = previous["data"]["content"]["policy"] if previous else contract["policy"]
    if content["policy"] != earlier_policy:
        handoff = core._latest(state, "handoff")
        if (not previous or not handoff or handoff["seq"] <= previous["seq"]
                or handoff["data"]["prior_plan"] != previous["data"]["revision"]
                or handoff["data"]["target_lane"] != content["policy"].get("execution_lane")):
            raise ValueError("v2 policy change requires the receiving lane's explicit handoff")
    route = policy(content["policy"], core.TRIGGERS, historical=core._historical(state))
    if route.get("workflow") == "critical-four-v1":
        raise ValueError("transfer the scoped work to i2e.py critical before starting the Critical plan")
    if route["state"] != "PASS":
        raise ValueError("plan policy is unsupported or incomplete")
    if "expected_files" in content:
        for path in core._paths(content["expected_files"]):
            require_writable_name(contract, path, core)
        validate_file_domain(set(content["expected_files"]) | set(contract["scope"]) | set(contract["instructions"]), core)
    if "rollback" in content:
        text(content["rollback"], "plan rollback intent")
    if "delivery" in content and content["delivery"] != contract.get("delivery"):
        raise ValueError("plan delivery exceeds the immutable authorized action")
    contributors = labels(content["contributors"], "plan contributor", core, nonempty=True)
    labels(content["decisions"], "plan decision", core)
    text(content["decision_reason"], "decision selection")
    allowed_ids = {item for ticket in contract["tickets"] for item in ticket["acceptance"]}
    accepted, behavioral = set(), set()
    if not isinstance(content["acceptance"], list):
        raise ValueError("acceptance must be an explicit array")
    for row in content["acceptance"]:
        fields(row, {"id", "behavior"}, "acceptance", optional={"reason"})
        item = core._label(row["id"], "acceptance")
        if type(row["behavior"]) is not bool or item in accepted:
            raise ValueError("acceptance requires a unique ID and explicit behavior classification")
        if row["behavior"]:
            behavioral.add(item)
        else:
            text(row.get("reason"), "nonbehavior classification")
        accepted.add(item)
    if accepted != allowed_ids:
        raise ValueError("plan must map every owned ticket acceptance")
    checks = labels(content["checks"], "allowed check", core, nonempty=True)
    required = labels(content["required_checks"], "required check", core, nonempty=True)
    if not required <= checks:
        raise ValueError("required checks exceed plan")
    fields(content["result_map"], accepted, "acceptance result map")
    used_checks = set()
    for item, row in content["result_map"].items():
        fields(row, {"check", "test", "production"}, "acceptance result")
        check = core._label(row["check"], "mapped check")
        if check not in required or check in used_checks:
            raise ValueError("each acceptance requires a distinct required check")
        used_checks.add(check)
        test_paths = set(core._paths(row["test"]))
        production = set(core._paths(row["production"]))
        if ((item in behavioral and not test_paths) or not test_paths <= tests
                or not production or not production <= scope - tests):
            raise ValueError("acceptance result paths exceed their owned roles")
    owners = initial_owners(contract, content)
    for surface in contract["write_boundary"].get("surfaces", []):
        if surface["path"] in contract["scope"] and surface["ticket"] not in owners.get(surface["path"], {}):
            raise ValueError("write surface cannot assign an initial path to a different ticket")
    validate_verification_map(content, behavioral, contract["repo"], core)
    if not isinstance(content["aggregate_checks"], dict):
        raise ValueError("aggregate checks require a mapping")
    for check, ids in content["aggregate_checks"].items():
        if check not in required - used_checks or not labels(ids, "aggregate acceptance", core, nonempty=True) <= accepted:
            raise ValueError("aggregate check coverage is outside the required plan")
    if "batch" in content:
        validate_batch(content["batch"], contract["tickets"], checks, core)
    remediations = content["remediations"]
    if not isinstance(remediations, list):
        raise ValueError("remediations require an array")
    for mapping in remediations:
        fields(mapping, {"findings", "defects", "scope", "acceptance", "checks", "case_pairs"},
               "remediation", optional={"repair_actor"})
        if "repair_actor" in mapping:
            actor = mapping["repair_actor"]
            validate_actor(actor, core)
            if actor["session"] not in contributors:
                raise ValueError("named repair actor must be an actual plan contributor")
        labels(mapping["defects"], "stable defect", core, nonempty=True)
        if (not set(core._paths(mapping["scope"])) <= scope
                or not labels(mapping["acceptance"], "remediation acceptance", core, nonempty=True) <= accepted
                or not labels(mapping["checks"], "remediation check", core, nonempty=True) <= checks
                or not isinstance(mapping["findings"], list)):
            raise ValueError("remediation exceeds reviewed scope or checks")
        if any(check not in mapping["checks"] for _, check in pairs(mapping["case_pairs"], core)):
            raise ValueError("inherited case pair is outside the remediation checks")


def validate_actor(actor, core):
    fields(actor, {"session", "model", "effort", "evidence", "requested_tier", "observed_tier"}, "observed actor")
    for name in ("session", "model", "effort", "requested_tier"):
        core._label(actor[name], name)
    core.verify_reference(actor["evidence"])


def native_test_runner(repo, test_path, test_id, command):
    """Select the bounded native invocation without changing its argument array."""
    validate_test_id(test_id)
    target = Path(repo) / test_path
    paths = {test_path, str(target)}
    executable, *args = command
    runner = Path(executable).name
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", runner):
        names = test_id.split(".")
        if (len(names) == 2 and all(name.isidentifier() for name in names)
                and len(args) == 4 and args[1] in paths and args[0] == "-B"
                and args[2:] == [test_id, "-v"]):
            return "unittest"
    elif runner == "node" and len(args) in (2, 3) and args[0] == "--test" and args[-1] in paths:
        if len(args) == 3 and (not args[1].startswith("--test-name-pattern=")
                               or args[1] == "--test-name-pattern="):
            raise ValueError("unsupported Node test selection options")
        if test_id in paths | {target.name, "./" + test_path}:
            raise ValueError("Node test identity cannot be a file-level result")
        return "node-spec"
    raise ValueError("unsupported native selected-test command or identity")


def validate_verification_map(content, behavioral, repo, core):
    rows = content.get("verification_map", {})
    if not isinstance(rows, dict) or not set(rows) <= behavioral:
        raise ValueError("verification map must select approved behavioral acceptance")
    for acceptance, row in rows.items():
        fields(row, {"test_path", "test_id", "command", "runner"}, "mapped verification")
        test = v2_path(row["test_path"], core)
        validate_test_id(row["test_id"])
        if test not in content["result_map"][acceptance]["test"]:
            raise ValueError("mapped verification test is outside its acceptance")
        argv, runner = row["command"], row["runner"]
        fields(runner, {"path", "sha256"}, "mapped verification runner")
        sha256(runner["sha256"], "mapped verification runner")
        if (not isinstance(argv, list) or not argv or any(
                not isinstance(arg, str) or not arg or "\0" in arg for arg in argv
        ) or not Path(argv[0]).is_absolute() or argv[0] != runner["path"]):
            raise ValueError("mapped verification requires an exact absolute runner and command")
        native_test_runner(repo, test, row["test_id"], argv)


def validate_batch(batch, tickets, checks, core):
    fields(batch, {"allowed_subsets", "subset_delivery", "dependencies", "interaction_checks"}, "batch delegation")
    members = {ticket["id"] for ticket in tickets}
    fields(batch["dependencies"], members, "batch dependency graph")
    graph = {name: labels(deps, "batch dependency", core) for name, deps in batch["dependencies"].items()}
    if any(name in deps or not deps <= members for name, deps in graph.items()):
        raise ValueError("batch dependencies must be within the other owned tickets")
    pending = {name: set(deps) for name, deps in graph.items()}
    while pending:
        ready = {name for name, deps in pending.items() if not deps}
        if not ready:
            raise ValueError("batch dependency graph contains a cycle")
        pending = {name: deps - ready for name, deps in pending.items() if name not in ready}
    if type(batch["subset_delivery"]) is not bool or not isinstance(batch["allowed_subsets"], list):
        raise ValueError("subset authority requires a boolean and explicit subsets")
    for subset in batch["allowed_subsets"]:
        if not labels(subset, "delegated member", core, nonempty=True) < members:
            raise ValueError("approved removal requires a nonempty proper subset")
    if not labels(batch["interaction_checks"], "interaction check", core, nonempty=True) <= checks:
        raise ValueError("interaction checks exceed approved plan")


def validate_finding(finding, core):
    fields(finding, {"id", "actionable", "material", "text", "severity", "requirement", "evidence",
                     "consequence", "correction", "validation"}, "v2 review finding")
    if finding["severity"] not in ("Low", "Medium", "High"):
        raise ValueError("finding severity must be Low, Medium or High")
    if finding["severity"] == "Low" and finding["actionable"] is True:
        raise ValueError("Low observations cannot supply actionable finding obligations")
    for name in ("requirement", "consequence", "correction"):
        text(finding[name], "finding " + name)
    core._label(finding["validation"], "finding validation check")
    core.verify_reference(finding["evidence"])


def read_only_source(state, candidate, core, *, observe=False):
    contract = state["contract"]
    pinned = contract["source"]
    validate_snapshot(candidate, core)
    validate_snapshot(state["initial_source"], core)
    actual = candidate["instructions"]
    initial = state["initial_source"]["instructions"]
    modes = candidate["modes"]
    initial_modes = state["initial_source"]["modes"]
    paths = pinned["harness"] + pinned["dependencies"]
    if observe and git_base(Path(contract["repo"])) != pinned["base"]:
        raise ValueError("source Git base changed")
    if any(name not in actual or name not in initial or actual[name] != initial[name]
           or modes[name] != initial_modes[name] for name in paths):
        raise ValueError("source harness or dependencies changed in bytes or mode")
    return {"base": pinned["base"],
            "harness": {name: actual[name] for name in pinned["harness"]},
            "dependencies": {name: actual[name] for name in pinned["dependencies"]},
            "modes": {name: modes[name] for name in paths}}
