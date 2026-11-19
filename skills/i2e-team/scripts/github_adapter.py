"""Exact-candidate, synchronous GitHub merge delivery for explicit v2 runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote


API_HOST = "github.com"
API_VERSION = "2026-03-10"
_TIMEOUT = 15
_BINDING = {"repository", "target", "pr", "head", "base", "candidate", "actor", "action", "authority"}
_OPERATION = {"operation", "actor", "authority"}


class DeliveryHold(ValueError):
    pass


class Delivery:
    def __init__(self, ledger, runtime, transport):
        self.ledger = ledger
        self.runtime = runtime
        self.core = runtime.core
        self.contract = runtime.contract
        self.native = runtime.executor
        self.transport = transport
        self.executable = None
        self.evidence = None
        self.receipts = []

    def apply(self, state, operation, expected_seq, request):
        try:
            if operation not in {"inspect", "prepare", "execute", "reconcile"}:
                raise ValueError("unsupported delivery operation")
            names = _BINDING if operation in {"inspect", "prepare"} else _OPERATION
            self.contract.fields(request, {"id"} | names, "delivery request")
            self.core.canonical(request)
            self.core._label(request["id"], "delivery request ID")
            if request["id"].startswith("i2e/") or type(expected_seq) is not int or expected_seq != state["seq"]:
                raise ValueError("delivery requires a public request ID and exact current sequence")
            boundary = self._authority(state, request)
            if self.transport is not None:
                if state["contract"]["synthetic"] is not True or not callable(self.transport):
                    raise ValueError("injected provider transport requires an explicit synthetic run")
            else:
                installed = shutil.which("gh")
                if installed is None:
                    raise DeliveryHold("the GitHub CLI executable is unavailable")
                self.executable = self.native.executable(Path(installed).resolve(strict=True))
            parent = self.core._safe_path(state["evidence_root"])
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.evidence = Path(tempfile.mkdtemp(prefix="delivery-", dir=parent))
            return getattr(self, "_" + operation)(state, boundary, request)
        except DeliveryHold as exc:
            return {"state": "HOLD", "errors": [str(exc)], "receipts": self.receipts}
        except (self.core.RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)], "receipts": self.receipts}

    def _authority(self, state, request):
        contract = state["contract"]
        boundary = contract.get("delivery")
        if boundary is None:
            raise ValueError("no reviewed delivery boundary")
        self.contract.validate_delivery(boundary, self.core)
        authority = contract["authority"]
        self.core.verify_reference(authority["evidence"])
        if ("merge_github" not in authority["actions"] or not boundary["rules_admin_trust"]
                or request["actor"] != boundary["actor"] or request["authority"] != boundary["authority"]):
            raise ValueError("delivery lacks exact recorded actor, authority or trusted rules administration")
        if any(part in {".", ".."} for part in boundary["repository"].split("/")):
            raise ValueError("delivery repository path is ambiguous")
        return boundary

    def _json(self, content):
        if len(content) > self.core.MAX_JSON_BYTES:
            raise DeliveryHold("GitHub JSON body exceeds the evidence limit")
        return json.loads(content, object_pairs_hook=self.core._unique_pairs, parse_constant=self.core._reject_constant)

    def _native_call(self, argv):
        if self.native.executable(Path(argv[0])) != self.executable:
            raise DeliveryHold("GitHub CLI executable changed after selection")
        env = {key: os.environ[key] for key in ("PATH", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
               if key in os.environ}
        env.update(GH_HOST=API_HOST, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1",
                   GH_NO_EXTENSION_UPDATE_NOTIFIER="1", PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
        deadline = time.monotonic() + _TIMEOUT
        stdout, stderr = self.native._PipeCapture(deadline), self.native._PipeCapture(deadline)
        status = {"exit": None, "timed_out": False, "launch_error": None, "interruption": None,
                  "cwd": str(self.evidence), "timeout_seconds": _TIMEOUT, "executable": self.executable}
        try:
            completed = subprocess.run(argv, cwd=self.evidence, env=env, input=b"", stdout=stdout.write, stderr=stderr.write,
                                       close_fds=True, timeout=_TIMEOUT, check=False)
            status["exit"] = completed.returncode
        except subprocess.TimeoutExpired:
            status["timed_out"] = True
        except KeyboardInterrupt:
            status["interruption"] = "KeyboardInterrupt during GitHub request"
        except OSError as exc:
            status["launch_error"] = str(exc)
        finally:
            status.update(stdout=stdout.finish(), stderr=stderr.finish())
        status["stream_error"] = stdout.error or stderr.error
        status["interruption"] = status["interruption"] or stdout.interruption or stderr.interruption
        return status

    def _request(self, method, path, fields=()):
        executable = self.executable["path"] if self.executable is not None else "gh"
        argv = [executable, "api", "--hostname", API_HOST, "--method", method,
                "--header", "Accept: application/vnd.github+json",
                "--header", "X-GitHub-Api-Version: " + API_VERSION, path]
        for key, value in fields:
            argv.extend(("--raw-field", f"{key}={value}"))
        if self.transport is None:
            status = self._native_call(argv)
        else:
            try:
                result = self.transport(argv)
            except (OSError, subprocess.TimeoutExpired) as exc:
                status = {"exit": None, "stdout": getattr(exc, "stdout", None) or b"",
                          "stderr": getattr(exc, "stderr", None) or b"", "launch_error": str(exc),
                          "timed_out": isinstance(exc, subprocess.TimeoutExpired), "stream_error": None,
                          "interruption": None}
            else:
                if (not isinstance(result, subprocess.CompletedProcess) or result.args != argv
                        or type(result.returncode) is not int
                        or not all(isinstance(stream, bytes) for stream in (result.stdout, result.stderr))):
                    raise ValueError("synthetic transport did not return the actual command outcome shape")
                status = {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                          "launch_error": None, "timed_out": False, "stream_error": None, "interruption": None}
        index = len(self.receipts) + 1
        record = {key: value for key, value in status.items() if key not in {"stdout", "stderr"}}
        for stream in ("stdout", "stderr"):
            path = self.evidence / f"{index:02d}.{stream}"
            contents = status[stream]
            if len(contents) > self.core.MAX_FILE_BYTES:
                record["stream_error"] = "provider output exceeded the raw evidence limit"
                contents = contents[:self.core.MAX_FILE_BYTES]
            self.native._write_private(path, contents)
            record[stream] = self.core.reference(path)
        record.update(argv=argv, host=API_HOST, api_version=API_VERSION,
                      transport="SYNTHETIC_INJECTED" if self.transport is not None else "GH_CLI")
        receipt = self.evidence / f"{index:02d}.json"
        self.native._write_private(receipt, self.core.canonical(record))
        self.core._sync_directory(self.evidence)
        ref = self.core.reference(receipt)
        self.receipts.append(ref)
        try:
            body = self._json(status["stdout"]) if status["stdout"] and record["stream_error"] is None else None
        except (DeliveryHold, ValueError, UnicodeError):
            body = None
        return record, body, ref

    def _get(self, path):
        record, body, _ = self._request("GET", path)
        if record["exit"] != 0 or record["stream_error"] or record["interruption"] or body is None:
            raise DeliveryHold("required GitHub state is unavailable for " + path)
        return body

    def _local(self, state, request):
        core = self.core
        run_id, contract = state["contract"]["run_id"], state["contract"]
        check = self.ledger.check(run_id)
        if (check["state"] != "PASS" or check["lifecycle"] not in {"ACCEPTED_LOCAL", "DELIVERED"}
                or check["seq"] != state["seq"]
                or check["candidate"]["sha256"] != request["candidate"]):
            raise ValueError("delivery requires exact current local acceptance")
        membership = self.runtime.membership_record(state)
        if not check["parent_complete"] and membership["event"] is None:
            raise ValueError("delivery requires a complete parent or exact reviewed subset acceptance")
        candidate = check["candidate"]
        source = self.contract.read_only_source(state, candidate, core, observe=True)
        if source["base"] != request["base"]:
            raise ValueError("delivery target base differs from the locally accepted Git base")
        head = self.native._oid(request["head"], length=len(source["base"]))
        repo = Path(contract["repo"])
        env = self.native._git_env(self.evidence)
        self.native._git_metadata(repo)
        self.native._raw_commit(repo, head, source["base"], env)
        base_tree = self.native._tree(repo, source["base"], env, self.contract, core)
        head_tree = self.native._tree(repo, head, env, self.contract, core)
        changed = {name for name in base_tree.keys() | head_tree.keys() if base_tree.get(name) != head_tree.get(name)}
        if not changed <= self.runtime.owned_paths(state) or changed & set(contract["instructions"]):
            raise ValueError("delivery head has changes outside the accepted local source scope")
        for name, checksum in (candidate["files"] | candidate["instructions"]).items():
            row = head_tree.get(name)
            if checksum is None:
                if row is not None:
                    raise ValueError("delivery head contains a file absent from the accepted candidate")
                continue
            if row is None or self.native._sha(self.native._blob(repo, row["oid"], env)) != checksum:
                raise ValueError("delivery head bytes differ from the accepted candidate")
            if candidate["modes"][name] != self.contract.git_mode(row["mode"]):
                raise ValueError("delivery head file mode differs from the accepted candidate")
        plan = core._latest(state, "plan")
        content = plan["data"]["content"]
        active = self.runtime.active_acceptance(state)
        proofs = {}
        for row in content["acceptance"]:
            if row["behavior"] and row["id"] in active:
                proof = core._latest(state, "proof", lambda event: event["data"].get("acceptance") == row["id"]
                                     and event["data"]["phase"] == "GREEN")
                proofs[proof["id"]] = proof
        for name in self.runtime.required_checks(state, content):
            proof = self.runtime.required_check_proof(state, content, name)
            if proof is None:
                raise ValueError("delivery lacks current required check " + name)
            proofs[proof["id"]] = proof
        checks = [{"check": proof["data"]["check"], "event": proof["id"], "sha256": proof["sha256"]}
                  for proof in sorted(proofs.values(), key=lambda event: event["seq"])]
        policy = core.evaluate_policy(content["policy"])
        kinds = set(policy["audits"])
        if "architecture" in content["policy"].get("specialists", []):
            kinds.add("architecture")
        reviews = [core._latest(state, "audit", lambda event: event["data"]["kind"] == kind) for kind in kinds]
        if policy["final_review"] == "astra":
            reviews.append(core._latest(state, "final_review"))
        return {"schema": "i2e-team-github-check-v2", "repository": request["repository"], "target": request["target"],
                "head": head, "base": request["base"], "candidate": request["candidate"], "source": source,
                "plan": plan["data"]["revision"], "checks": checks, "membership": membership,
                "reviews": [{"event": row["id"], "sha256": row["sha256"]}
                            for row in sorted(reviews, key=lambda event: event["seq"])]}

    def _paths(self, boundary):
        repository = "repos/" + boundary["repository"]
        target = quote(boundary["target"], safe="")
        return repository, f"{repository}/pulls/{boundary['pr']}", f"{repository}/branches/{target}"

    def _pull_identity(self, pull, boundary):
        repo = boundary["repository"]
        return (pull["number"] == boundary["pr"] and pull["base"]["ref"] == boundary["target"]
                and pull["base"]["repo"]["full_name"] == repo and pull["head"]["repo"]["full_name"] == repo)

    def _eligible(self, boundary, expected):
        repository, pull_path, branch_path = self._paths(boundary)
        actor = boundary["actor"]
        repo = self._get(repository)
        user = self._get("user")
        permission = self._get(repository + "/collaborators/" + quote(actor, safe="") + "/permission")
        if (repo["full_name"] != boundary["repository"] or repo["allow_merge_commit"] is not True
                or repo["archived"] is not False or user["login"] != actor
                or type(user["id"]) is not int or user["id"] <= 0 or user.get("site_admin") is True
                or permission["permission"] != "write" or permission["role_name"] != "write"
                or permission["user"]["login"] != actor):
            raise DeliveryHold("GitHub repository or actor is outside the supported nonbypass merge route")
        pull, branch = self._get(pull_path), self._get(branch_path)
        if (not self._pull_identity(pull, boundary) or pull["state"] != "open" or pull["draft"] is not False
                or pull["merged"] is not False or pull["mergeable"] is not True or pull.get("auto_merge") is not None
                or pull["head"]["sha"] != expected["head"] or pull["base"]["sha"] != expected["base"]
                or branch["name"] != boundary["target"] or branch["protected"] is not True
                or branch["commit"]["sha"] != expected["base"]):
            raise DeliveryHold("current pull head, protected target or mergeability differs from the approved operation")
        protection = self._get(branch_path + "/protection")
        check = boundary["trusted_check"]
        required = protection["required_status_checks"]
        review_rule = protection["required_pull_request_reviews"]
        count = review_rule["required_approving_review_count"]
        if (required["strict"] is not True
                or required["checks"] != [{"context": check["name"], "app_id": check["app_id"]}]
                or any(name != check["name"] for name in required.get("contexts", []))
                or protection["enforce_admins"]["enabled"] is not True
                or review_rule["dismiss_stale_reviews"] is not True
                or review_rule["require_last_push_approval"] is not True
                or type(count) is not int or not 1 <= count < 100
                or review_rule["bypass_pull_request_allowances"] != {"users": [], "teams": [], "apps": []}
                or any(protection[key]["enabled"] is not False for key in (
                    "allow_force_pushes", "allow_deletions", "required_linear_history",
                ))):
            raise DeliveryHold("target protection does not enforce the supported current-check/review profile")
        rules = self._get(repository + "/rules/branches/" + quote(boundary["target"], safe=""))
        rulesets = self._get(repository + "/rulesets?includes_parents=true&per_page=100")
        if rules != [] or rulesets != []:
            raise DeliveryHold("additional target rules or inherited rulesets need a qualified route")
        reviews = self._get(pull_path + "/reviews?per_page=100")
        if not isinstance(reviews, list) or len(reviews) >= 100:
            raise DeliveryHold("complete current GitHub review history is unavailable")
        # GitHub returns reviews chronologically. Comments and pending drafts
        # do not replace a reviewer's last decision.
        latest = {}
        for review in reviews:
            if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                reviewer = review["user"]
                if type(reviewer["id"]) is not int or reviewer["id"] <= 0:
                    raise DeliveryHold("GitHub review actor identity is unavailable")
                latest[reviewer["id"]] = review
        approvals = sorted(review["id"] for reviewer, review in latest.items()
                           if reviewer != user["id"] and review["user"]["login"] != actor
                           and review["state"] == "APPROVED" and review["commit_id"] == expected["head"])
        if len(approvals) < count or any(
            row["state"] == "CHANGES_REQUESTED" and row["commit_id"] == expected["head"]
            for row in latest.values()
        ):
            raise DeliveryHold("pull request lacks qualifying current-head approvals")
        check_path = repository + f"/commits/{expected['head']}/check-runs?per_page=100&check_name="
        check_runs = self._get(check_path + quote(check["name"], safe=""))
        if check_runs["total_count"] != 1 or len(check_runs["check_runs"]) != 1:
            raise DeliveryHold("exact trusted current-head check is missing or ambiguous")
        native, = check_runs["check_runs"]
        if (native["name"] != check["name"] or native["head_sha"] != expected["head"]
                or native["status"] != "completed" or native["conclusion"] != "success"
                or native["app"]["id"] != check["app_id"]
                or self._json(native["output"]["summary"]) != expected):
            raise DeliveryHold("GitHub check producer or full accepted head/base evidence differs")
        return {"actor_id": user["id"], "role": permission["role_name"], "head_ref": pull["head"]["ref"],
                "protection_sha256": self.core.digest(protection), "approvals": approvals,
                "check_run": native["id"], "app_id": check["app_id"]}

    def _binding(self, state, boundary, request):
        for key in ("repository", "target", "pr", "actor", "action", "authority"):
            if request[key] != boundary[key] or (key == "pr" and type(request[key]) is not int):
                raise ValueError("request differs from the reviewed delivery boundary")
        self.contract.sha256(request["candidate"], "delivery candidate")
        local = self._local(state, request)
        return local, self._eligible(boundary, local)

    def _inspect(self, state, boundary, request):
        local, provider = self._binding(state, boundary, request)
        if self.ledger.show(state["contract"]["run_id"])["sha256"] != state["sha256"]:
            raise DeliveryHold("ledger changed while inspecting delivery")
        return {"state": "PASS", "errors": [], "candidate": local, "provider": provider,
                "live_qualification": "UNVERIFIED", "receipts": self.receipts}

    def _event(self, kind, request, data):
        return {"id": self.core._internal_id(kind, request["id"]), "type": kind, "data": data}

    def _append(self, state, event, guard=None):
        if any(old["id"] == event["id"] for old in state["events"]):
            raise ValueError("delivery request ID is already recorded")
        return self.ledger._append(state["contract"]["run_id"], event, state["seq"], internal=True, guard=guard)

    def _result(self, state, operation):
        return self.core._latest(state, "delivery_result", lambda row: row["data"]["operation"] == operation)

    def _dispatch(self, state, operation):
        return self.core._latest(state, "delivery_dispatch", lambda row: row["data"]["operation"] == operation)

    def _prepare(self, state, boundary, request):
        for dispatched in self.core._events(state, "delivery_dispatch"):
            prior = self._result(state, dispatched["data"]["operation"])
            if prior is None or prior["data"]["outcome"] != "NO_EFFECT":
                raise DeliveryHold("prior delivery effect is unresolved or the pull request was already merged")
        local, provider = self._binding(state, boundary, request)
        binding = {key: request[key] for key in _BINDING}
        event = self._event("delivery_intent", request, dict(
            binding, boundary=boundary, local=local, provider=provider, receipts=list(self.receipts),
        ))

        def guard(current):
            self._authority(current, request)
            if self._local(current, request) != local:
                raise DeliveryHold("local acceptance changed during delivery preparation")

        saved = self._append(state, event, guard)
        return {"state": "PASS", "errors": [], "intent": saved, "live_qualification": "UNVERIFIED",
                "receipts": self.receipts}

    def _intent(self, state, boundary, request):
        operation = self.core._label(request["operation"], "delivery operation ID")
        event = self.core._latest(state, "delivery_intent", lambda row: row["id"] == operation)
        if event is None or event["data"]["boundary"] != boundary:
            raise ValueError("exact durable delivery intent is missing or stale")
        return event

    def _terminal_rejection(self, record, body):
        if (record["exit"] != 1 or record["timed_out"] or record["interruption"] or record["stream_error"]
                or not isinstance(body, dict) or body.get("merged") is not False):
            return False
        status = str(body.get("status"))
        if status not in {"405", "409", "422"} or not isinstance(body.get("message"), str):
            return False
        raw = self.core._file_bytes(Path(record["stderr"]["path"]))
        return f"(HTTP {status})".encode() in raw

    def _readback(self, boundary, intent, *, terminal=False, acknowledged=None):
        repository, pull_path, branch_path = self._paths(boundary)
        binding = intent["data"]
        try:
            repo = self._get(repository)
            user = self._get("user")
            pull, branch = self._get(pull_path), self._get(branch_path)
            if (repo["full_name"] != boundary["repository"] or user["login"] != boundary["actor"]
                    or user["id"] != binding["provider"]["actor_id"] or not self._pull_identity(pull, boundary)
                    or branch["name"] != boundary["target"]):
                return "UNKNOWN", {"reason": "provider readback identity changed"}
            target = self.native._oid(branch["commit"]["sha"], length=len(binding["base"]))
            head = self.native._oid(pull["head"]["sha"], length=len(binding["head"]))
            report = {"target": target, "head": head, "pr_state": pull["state"], "merged": pull["merged"]}
            if pull["merged"] is True and pull["state"] == "closed":
                merged = self.native._oid(pull["merge_commit_sha"], length=len(binding["head"]))
                commit = self._get(repository + "/commits/" + merged)
                if commit["sha"] != merged or not isinstance(commit["parents"], list):
                    return "UNKNOWN", dict(report, reason="merge commit identity is unavailable")
                parents = [self.native._oid(row["sha"], length=len(merged)) for row in commit["parents"]]
                report.update(merge=merged, parents=parents)
                if head != binding["head"] or parents != [binding["base"], binding["head"]]:
                    return "UNINTENDED", report
                if target != merged or (acknowledged is not None and acknowledged != merged):
                    return "UNKNOWN", dict(report, reason="target or acknowledgment differs from exact merge readback")
                return "INTENDED", report
            if (terminal and pull["merged"] is False and pull["state"] == "open"
                    and pull["merge_commit_sha"] is None and head == binding["head"]
                    and pull["base"]["sha"] == binding["base"] and target == binding["base"]):
                return "NO_EFFECT", report
            return "UNKNOWN", report
        except (DeliveryHold, ValueError, OSError, KeyError, TypeError) as exc:
            return "UNKNOWN", {"reason": str(exc)}

    def _response(self, outcome, readback):
        state = {"INTENDED": "PASS", "UNKNOWN": "HOLD"}.get(outcome, "BLOCK")
        return {"state": state, "outcome": outcome, "readback": readback,
                "errors": [] if state == "PASS" else [readback.get("reason") or "delivery outcome is " + outcome],
                "live_qualification": "UNVERIFIED", "receipts": self.receipts}

    def _outcome_event(self, request, intent, dispatch, outcome, readback, evidence):
        return self._event("delivery_result", request, {
            "operation": intent["id"], "dispatch": dispatch["id"], "candidate": intent["data"]["candidate"],
            "outcome": outcome, "readback": readback, "effect": evidence, "receipts": list(self.receipts),
        })

    def _execute(self, state, boundary, request):
        intent = self._intent(state, boundary, request)
        if self._dispatch(state, intent["id"]) is not None:
            raise DeliveryHold("delivery was already dispatched; use read-only reconciliation")
        if self.core._latest(state, "delivery_intent") != intent:
            raise DeliveryHold("delivery intent is no longer the selected operation")
        binding = intent["data"]
        local, provider = self._binding(state, boundary, binding)
        if local != binding["local"] or provider != binding["provider"]:
            raise DeliveryHold("delivery evidence changed after the original durable intent")
        _, pull, _ = self._paths(boundary)
        endpoint = pull + "/merge"
        fields = [("sha", binding["head"]), ("merge_method", "merge")]
        event = self._event("delivery_dispatch", request, {
            "operation": intent["id"], "intent_sha256": intent["sha256"], "candidate": binding["candidate"],
            "endpoint": endpoint, "host": API_HOST, "api_version": API_VERSION, "fields": dict(fields),
            "receipts": list(self.receipts), "evidence_root": str(self.evidence),
        })

        def guard(current):
            self._authority(current, request)
            if self._local(current, binding) != local:
                raise DeliveryHold("local acceptance changed before durable delivery dispatch")

        dispatch = self._append(state, event, guard)
        try:
            with self.ledger._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = self.ledger._read(conn, state["contract"]["run_id"])
                if current["sha256"] != dispatch["sha256"]:
                    raise DeliveryHold("delivery dispatch prefix changed before invocation")
                effect = {"put": None, "terminal_rejection": False, "acknowledged": None}
                try:
                    self._authority(current, request)
                    if self._binding(current, boundary, binding) != (local, provider):
                        raise DeliveryHold("delivery prerequisites changed before the merge invocation")
                    if self._local(current, binding) != local:
                        raise DeliveryHold("accepted local candidate changed during provider qualification")
                    self._authority(current, request)
                except (DeliveryHold, self.core.RuntimeError, ValueError, OSError, TypeError, KeyError) as exc:
                    outcome, readback = "NO_EFFECT", {"reason": str(exc), "put_started": False}
                else:
                    record, body, receipt = self._request("PUT", endpoint, fields)
                    acknowledged = None
                    if (record["exit"] == 0 and not record["interruption"] and not record["stream_error"]
                            and isinstance(body, dict) and body.get("merged") is True):
                        candidate = body.get("sha")
                        if isinstance(candidate, str) and self.native._OID.fullmatch(candidate):
                            acknowledged = candidate
                    effect = {"put": receipt, "terminal_rejection": self._terminal_rejection(record, body),
                              "acknowledged": acknowledged}
                    outcome, readback = self._readback(boundary, intent, terminal=effect["terminal_rejection"],
                                                       acknowledged=acknowledged)
                self.ledger._insert_event(conn, current, self._outcome_event(
                    request, intent, dispatch, outcome, readback, effect,
                ))
                conn.commit()
            return self._response(outcome, readback)
        except (self.core.RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            raise DeliveryHold("durable delivery dispatch requires reconciliation: " + str(exc)) from exc

    def _reconcile(self, state, boundary, request):
        intent = self._intent(state, boundary, request)
        dispatch = self._dispatch(state, intent["id"])
        if dispatch is None or dispatch["data"]["intent_sha256"] != intent["sha256"]:
            raise ValueError("no exact dispatched operation exists to reconcile")
        prior = self._result(state, intent["id"])
        evidence = (prior["data"]["effect"] if prior else
                    {"put": None, "terminal_rejection": False, "acknowledged": None})
        terminal = False
        if evidence["put"] is not None:
            self.core.verify_reference(evidence["put"])
            record = self.core._read_json(evidence["put"]["path"])
            self.core.verify_reference(record["stdout"])
            self.core.verify_reference(record["stderr"])
            content = self.core._file_bytes(Path(record["stdout"]["path"]))
            try:
                body = self._json(content) if content else None
            except (DeliveryHold, ValueError, UnicodeError):
                body = None
            terminal = self._terminal_rejection(record, body)
        outcome, readback = self._readback(boundary, intent, terminal=terminal,
                                           acknowledged=evidence["acknowledged"])
        if prior and prior["data"]["readback"].get("put_started") is False and evidence["put"] is None:
            outcome, readback = prior["data"]["outcome"], prior["data"]["readback"]
        self._append(state, self._outcome_event(request, intent, dispatch, outcome, readback, evidence),
                     lambda current: self._authority(current, request))
        return self._response(outcome, readback)
