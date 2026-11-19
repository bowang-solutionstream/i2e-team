"""Validate the workflow's existing local acceptance immediately before publication."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

WORKFLOWS = ("i2e-astra-sol", "i2e-fable-opus", "i2e-opus-sonnet")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def check_file(item, *, deletion=False):
    require(isinstance(item, dict) and isinstance(item.get("path"), str), "missing local evidence path")
    path = Path(item["path"])
    require(path.is_absolute() and "sha256" in item, "use an absolute evidence path and recorded sha256")
    if deletion and item["sha256"] is None:
        require(not path.exists() and not path.is_symlink(), "a delivered deletion is stale")
        return
    require(path.is_file() and not path.is_symlink(), "a delivery or evidence file is missing")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    require(digest.hexdigest() == item["sha256"], "delivered bytes or acceptance evidence changed")


def accepted(args):
    if args.workflow == WORKFLOWS[0]:
        require(args.i2e and not args.handoff, "select the run's native I2E controller and evidence")
        if args.state and not (args.db or args.run):
            command = ["critical", "--state", str(args.state.resolve()), "status"]
        else:
            require(args.db and args.run and not args.state, "select one Critical state or one Direct/Standard ledger")
            require(args.db.is_file(), "the local I2E ledger is missing")
            command = ["check", "--db", str(args.db.resolve()), "--run", args.run]
        result = subprocess.run([sys.executable, "-B", str(args.i2e.resolve()), *command],
                                capture_output=True, check=False)
        require(result.returncode == 0, "native I2E delivery check did not pass")
        status = json.loads(result.stdout)
        require(isinstance(status, dict), "the native I2E controller returned an invalid status")
        if args.state:
            require(status.get("schema") == "i2e-critical-run-v1" and status.get("phase") == "complete"
                    and status.get("acceptance_current") is True,
                    "Critical acceptance is incomplete or stale")
            checks = status.get("checks")
            require(isinstance(checks, dict) and all(isinstance(checks.get(k), dict)
                    and checks[k].get("result") == "PASS" and checks[k].get("exit_code") == 0
                    for k in ("lint", "e2e")), "the final lint or end-to-end check did not pass")
        else:
            schema = status.get("schema")
            candidate = status.get("candidate")
            require(schema in ("i2e-team-check-v1", "i2e-team-check-v2") and status.get("state") == "PASS"
                    and status.get("errors") == [] and status.get("ready", schema == "i2e-team-check-v1") is True
                    and isinstance(candidate, dict) and isinstance(candidate.get("sha256"), str)
                    and re.fullmatch("[0-9a-f]{64}", candidate["sha256"]),
                    "the I2E ledger does not confirm current acceptance")
        return
    require(args.handoff and not any((args.i2e, args.state, args.db, args.run)),
            "select the completed local Claude handoff")
    evidence = json.loads(args.handoff.read_bytes())
    require(isinstance(evidence, dict) and evidence.get("workflow") == args.workflow and evidence.get("status") == "PASS",
            "the workflow's handoff must report PASS")
    for group in ("sources", "checks"):
        items = evidence.get(group)
        require(isinstance(items, list) and items, "record the final deliverables and required check evidence")
        for item in items:
            if group == "checks":
                require(isinstance(item, dict) and item.get("status") == "PASS" and item.get("name"),
                        "a required check did not pass")
            check_file(item, deletion=group == "sources")
    review = evidence.get("review")
    require(isinstance(review, dict) and review.get("verdict") == "APPROVE", "the required final review is missing")
    check_file(review)
