"""V2 authorization, current proof, and inherited repair evidence."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess


def _before(state, event):
    index = event["seq"] - 1
    return dict(state, events=state["events"][:index], seq=index, sha256=event["previous_sha256"])


def _through(state, event):
    return dict(state, events=state["events"][:event["seq"]], seq=event["seq"], sha256=event["sha256"])


def _event(state, event_id, kind):
    for event in state["events"]:
        if event["id"] == event_id and event["type"] == kind:
            return event
    raise ValueError(f"{kind} witness {event_id} is missing")


def _identities(event):
    yield event["id"]
    if event["type"] in {"plan", "decision"}:
        yield event["data"]["revision"]
    if event["type"] == "decision":
        yield event["data"]["lineage"]


def _live(state, witnesses, acceptances=()):
    created = {}
    for witness in witnesses:
        if witness is None:
            continue
        for name in _identities(witness):
            created[name] = min(created.get(name, witness["seq"]), witness["seq"])
    for acceptance in acceptances:
        plans = [e["seq"] for e in witnesses if e is not None and e["type"] == "plan"]
        if plans:
            created[acceptance] = min(plans)
    for event in state["events"]:
        if event["type"] in {"withdrawal", "supersession"}:
            sequence = created.get(event["data"].get("target"))
            if sequence is not None and sequence < event["seq"]:
                raise ValueError("selected proof dependency was withdrawn or superseded")


def _unittest_selected_result(report, identity, paths, failed):
    """Match the direct-script unittest result and its selected failure block."""
    method = identity.rsplit(".", 1)[1]
    description = f"{method} (__main__.{identity})"
    lines = report.splitlines()
    rows = [(index, line) for index, line in enumerate(lines)
            if re.fullmatch(r"[^()\s]+ \(__main__\.[^()\s]+\)(?: \.\.\. .+)?", line)]
    summaries = [line for line in lines if re.fullmatch(r"Ran \d+ tests? in \d+(?:\.\d+)?s", line)]
    if len(rows) != 1 or len(summaries) != 1 or not summaries[0].startswith("Ran 1 test in "):
        return False
    outcome = "FAIL" if failed else "ok"
    index, row = rows[0]
    long_description = description
    if row == description and index + 1 < len(lines):
        detail, separator, reported_outcome = lines[index + 1].rpartition(" ... ")
        if not detail.strip() or not separator or reported_outcome != outcome:
            return False
        long_description += "\n" + detail
    elif row != f"{description} ... {outcome}":
        return False
    if lines.index(summaries[0]) <= index or not lines or report.rstrip().splitlines()[-1] != (
        "FAILED (failures=1)" if failed else "OK"
    ):
        return False
    if not failed:
        return not any(line.startswith(("FAIL: ", "ERROR: ")) for line in lines)

    sections = report.split("\n" + "=" * 70 + "\n")
    if len(sections) != 2:
        return False
    header, divider, rest = sections[1].partition("\n" + "-" * 70 + "\n")
    trace, end, _ = rest.partition("\n" + "-" * 70 + "\n")
    if (not divider or not end or header != "FAIL: " + long_description
            or not trace.startswith("Traceback (most recent call last):\n")
            or not re.search(r"(?m)^AssertionError(?::[^\r\n]*)?$", trace)):
        return False
    frames = re.findall(r'(?m)^  File "([^\r\n]+)", line \d+, in ([^\r\n]+)$', trace)
    lifecycle = {"setUp", "setUpClass", "setUpModule", "tearDown", "tearDownClass", "tearDownModule",
                 "_callSetUp", "_callTearDown", "_callCleanup", "doCleanups", "doClassCleanups"}
    return (any(name == method and path in paths for path, name in frames)
            and not any(name in lifecycle for _, name in frames))


def _node_selected_result(report, identity, paths, failed):
    """Match the observed non-TTY spec report for one top-level test."""
    summary = re.findall(r"(?m)^ℹ (tests|suites|pass|fail|cancelled|skipped|todo) (\d+)$", report)
    expected = {"tests": "1", "suites": "0", "pass": "0" if failed else "1", "fail": "1" if failed else "0",
                "cancelled": "0", "skipped": "0", "todo": "0"}
    if len(summary) != len(expected) or dict(summary) != expected:
        return False
    main, failure_header, detail = report.partition("\n✖ failing tests:\n")
    rows = re.findall(r"(?m)^([✔✖]) ([^\r\n]+) \(\d+(?:\.\d+)?ms\)$", main)
    if rows != [("✖" if failed else "✔", identity)]:
        return False
    if not failed:
        return not failure_header
    if not failure_header:
        return False
    failure = re.match(
        r"\n*test at ([^\r\n]+):(\d+):\d+\n✖ ([^\r\n]+) \(\d+(?:\.\d+)?ms\)\n"
        r"  AssertionError \[ERR_ASSERTION\]:", detail,
    )
    if (failure is None or failure[1] not in paths or failure[3] != identity
            or re.search(r"(?m)^(?:test at |✖ failing tests:)", detail[failure.end():])
            or re.search(r"(?m)^ +at (?:async )?(?:TestHook\.|Test\.runHook\b)", detail)):
        return False
    first_frame = re.search(r"(?m)^ +at ", detail[failure.end():])
    if first_frame is None:
        return False
    stack = detail[failure.end() + first_frame.start():]
    origin = re.match(
        r" +at TestContext\.(<anonymous>|[A-Za-z_$][A-Za-z0-9_$]*) \(([^\r\n]+):(\d+):\d+\)\n",
        stack,
    )
    if origin is None or origin[2] not in paths or int(origin[3]) < int(failure[2]):
        return False
    caller = stack[origin.end():]
    synchronous = re.match(
        r" +at Test\.runInAsyncScope \(node:async_hooks:\d+:\d+\)\n"
        r" +at Test\.run \(node:internal/test_runner/test:\d+:\d+\)(?=\n|$)",
        caller,
    )
    after_await = origin[1] == "<anonymous>" and re.match(
        r" +at async Test\.run \(node:internal/test_runner/test:\d+:\d+\)(?=\n|$)", caller,
    )
    return bool(synchronous or after_await)


class Runtime:
    def __init__(self, core, contract, executor, github):
        self.core = core
        self.contract = contract
        self.executor = executor
        self.github = github

    def plan_witnesses(self, state, plan=None):
        core = self.core
        plan = core._latest(state, "plan") if plan is None else plan
        if plan is None:
            raise ValueError("effective v2 plan is missing")
        data = plan["data"]
        prior = _before(state, plan)
        self.contract.validate_plan(prior, data["content"], core)
        if data["revision"] != core.digest(data["content"]):
            raise ValueError("exact plan revision digest differs")
        previous = core._latest(prior, "plan")
        if data["supersedes"] != (previous["data"]["revision"] if previous else None):
            raise ValueError("plan revision does not retain its immediate predecessor")
        lookup = _event(prior, data["consultation"], "consultation")
        if lookup["data"]["stage"] != "plan" or lookup["data"]["target"] != plan["id"]:
            raise ValueError("each plan requires its own preceding target-bound consultation")
        issues = core._consultation_errors(prior, lookup)
        if not core._known_cases(prior) <= set(lookup["data"]["shown"]):
            issues.append("plan consultation omitted cases known before that plan")
        if issues:
            raise ValueError("plan consultation: " + "; ".join(issues))
        approval = core._latest(
            state, "plan_review", lambda e: e["seq"] > plan["seq"] and e["data"].get("plan") == data["revision"],
        )
        lane = self.contract.policy(data["content"]["policy"], core.TRIGGERS, historical=core._historical(state))["lane"]
        if approval is None and lane == "Direct":
            witnesses = [plan, lookup, None]
            _live(state, witnesses)
            return witnesses
        if approval is None:
            raise ValueError("fresh exact-plan Astra approval is missing for this plan event")
        if approval["data"]["verdict"] != "APPROVE" or any(
            f["actionable"] for f in approval["data"].get("findings", [])
        ):
            raise ValueError("latest exact-plan review is not qualifying APPROVE")
        excluded = core._contributors(state) | {
            e["data"]["reviewer"]["session"] for e in core._events(state, "plan_review") if e["seq"] < approval["seq"]
        }
        issues = core._review_errors(state, approval, "astra", excluded)
        if issues:
            raise ValueError("plan review: " + "; ".join(issues))
        witnesses = [plan, lookup, approval]
        _live(state, witnesses)
        return witnesses

    def _selected_decisions(self, state, plan, acceptances):
        decisions, predecessors = {}, {}
        for event in self.core._events(state, "decision"):
            lineage = event["data"]["lineage"]
            predecessors[lineage] = decisions.get(lineage)
            decisions[lineage] = event
        acceptances = set(acceptances)
        required = set(plan["data"]["content"]["decisions"])
        required.update(lineage for lineage, event in decisions.items()
                        if not acceptances.isdisjoint(event["data"]["acceptance"]))
        selected = []
        for lineage in sorted(required):
            decision = decisions.get(lineage)
            if decision is None:
                raise ValueError("required decision is missing")
            data = decision["data"]
            content = dict(data)
            revision = content.pop("revision", None)
            if revision != self.core.digest(content):
                raise ValueError("decision revision digest mismatch")
            predecessor = predecessors[lineage]
            previous_revision = predecessor["data"].get("revision") if predecessor is not None else None
            if (predecessor is not None and previous_revision is None) or data.get("supersedes") != previous_revision:
                raise ValueError("decision lineage must retain its immediate predecessor")
            selected.append(decision)
        return selected

    def decision_witnesses(self, state, plan, acceptances, *, defer_red=False):
        core = self.core
        witnesses = []
        for decision in self._selected_decisions(state, plan, acceptances):
            lineage = decision["data"]["lineage"]
            review = core._latest(state, "doubt_review", lambda e: e["data"].get("decision") == lineage
                                  and e["data"].get("revision") == decision["data"]["revision"])
            witnesses.append(decision)
            core.verify_reference(decision["data"]["artifact"])
            if (decision["data"]["kind"] == "ordinary" and decision["data"]["strategy"] == "TDD_RED"
                    and (defer_red or review is None)):
                continue
            if review is None or core._decision_resolution_errors(state, review) or any(
                f["actionable"] for f in review["data"]["findings"]
            ):
                raise ValueError("required decision lacks current qualifying support")
            witnesses.append(review)
        _live(state, witnesses)
        return witnesses

    def _tier_alternates(self, state, plan):
        core = self.core
        request = plan["data"]["content"]["policy"]
        if request.get("tier_policy", "require_match") != "record_unknown":
            return None
        choice = core._latest(_before(state, plan), "human_decision", lambda e: e["data"].get("kind") == "TIER_POLICY")
        if choice is None:
            raise ValueError("record_unknown requires actual owner selection")
        human = choice["data"]
        self.contract.fields(human, {"actor", "kind", "policy", "source", "statement", "alternates"},
                             "owner tier selection")
        if human["actor"] != "human" or human["policy"] != "record_unknown" or not isinstance(human["alternates"], dict):
            raise ValueError("tier exception requires explicit human selection")
        core.verify_reference(human["source"])
        self.contract.text(human["statement"], "owner tier selection")
        _live(state, [choice])
        return human["alternates"]

    def _verify_actor(self, state, actor, requested, alternates):
        core = self.core
        self.contract.validate_actor(actor, core)
        if (actor["model"], actor["effort"], actor["requested_tier"]) != (
            requested["model"], requested["effort"], requested["tier"]
        ):
            raise ValueError("observed actor differs from the requested model, effort or tier")
        core._verify_identity(state, actor["evidence"], actor)
        extract = core._read_json(actor["evidence"]["path"])
        observed = actor["observed_tier"]
        if (extract.get("synthetic") is not state["contract"]["synthetic"]
                or not extract.get("context_sha256") or extract.get("observed_tier") != observed):
            raise ValueError("observed actor context or tier evidence does not match")
        if observed != requested["tier"] and (
            alternates is None or (observed is not None and alternates.get(actor["session"]) != observed)
        ):
            raise ValueError("unknown or mismatched effective tier holds this actor")

    def _route(self, state, plan):
        core = self.core
        routed = core._latest(_before(state, plan), "observation", lambda e: e["data"].get("kind") == "ROUTING")
        if routed is None:
            raise ValueError("actual routed participants must precede the plan")
        _live(state, [routed])
        return routed["data"]

    def routing(self, state, plan):
        core = self.core
        data = self._route(state, plan)
        policy = self.contract.policy(plan["data"]["content"]["policy"], core.TRIGGERS, historical=core._historical(state))
        if policy["state"] != "PASS":
            raise ValueError("selected route is not eligible")
        roles = policy["requested_settings"]
        self.contract.fields(data, {"kind"} | set(roles), "routed role inventory")
        alternates = self._tier_alternates(state, plan)
        sessions = {state["contract"].get("coordinator")}
        for role, requested in roles.items():
            actor = data[role]
            self._verify_actor(state, actor, requested, alternates)
            if actor["session"] in sessions:
                raise ValueError("planning, implementation and probe identities must be separate")
            sessions.add(actor["session"])
        contributors = {data[role]["session"] for role in ("owner", "lead") if role in data}
        if not contributors <= set(plan["data"]["content"]["contributors"]):
            raise ValueError("actual planning and implementation actors must be recorded as contributors")
        return data["owner"]

    def effective_actor(self, state, plan, start):
        """Resolve one actor from the exact reviewed phase and its named repair mapping."""
        core = self.core
        owner = self.routing(state, plan)
        remediation = start.get("remediation")
        if start["mode"] == "VERIFY" or remediation is None:
            return owner
        issues, findings, _ = core._remediation_errors(state, start)
        if issues:
            raise ValueError("invalid repair actor scope: " + "; ".join(issues))
        selected = [(event, item) for event in state["events"] if event["type"] in core.REVIEW_TYPES
                    for item in event["data"].get("findings", []) if (event["id"], item["id"]) in findings]
        high = [event for event, item in selected if item["severity"] == "High"]
        actor = remediation.get("repair_actor")
        if not core._historical(state):
            if actor is not None and actor != owner:
                raise ValueError("repairs belong to the assigned Sol implementation owner")
            _live(state, high)
            return owner
        if not high:
            if actor is not None:
                raise ValueError("Astra repair actor requires a named High finding")
            return owner
        if actor is None:
            raise ValueError("named High remediation requires its observed Astra repair actor")
        self._verify_actor(state, actor, self.contract.settings("astra"), self._tier_alternates(state, plan))
        route = self._route(state, plan)
        excluded = {entry["session"] for role, entry in route.items() if role != "kind"}
        excluded.add(state["contract"].get("coordinator"))
        excluded.update(core._participants(state))
        if actor["session"] in excluded or actor["session"] not in plan["data"]["content"]["contributors"]:
            raise ValueError("repair actor must be a separate observed contributor outside conflicting roles and reviewers")
        _live(state, high)
        return actor

    def write_scope(self, state, data):
        core = self.core
        content = core._latest(state, "plan")["data"]["content"]
        mode = data["mode"]
        if mode == "VERIFY":
            return []
        if mode not in {"TEST_ONLY", "PRODUCTION"}:
            raise ValueError("unknown write mode")
        role = "test" if mode == "TEST_ONLY" else "production"
        ids = self.contract.labels(data["acceptance"], "start acceptance", core, nonempty=True)
        if not ids <= self.active_acceptance(state):
            raise ValueError("start acceptance exceeds the active approved result map")
        if "write_manifest" in data:
            selected = {row["path"] for row in data["write_manifest"]}
        else:
            selected = {name for item in ids for name in content["result_map"][item][role]}
        routine = content["policy"].get("routine_worker")
        if routine and not selected <= set(routine["paths"]):
            raise ValueError("selected writes exceed the bounded routine worker assignment")
        if "remediation" in data:
            selected &= set(core._paths(data["remediation"]["scope"]))
        return sorted(selected)

    def validate_start(self, state, data):
        self.require_resolved_admissions(state)
        witnesses = self.plan_witnesses(state)
        plan = witnesses[0]
        if data["profile"] != state["initial_profile"]:
            raise ValueError("run profile changed after initialization")
        if data.get("source") != self.contract.read_only_source(state, data["candidate"], self.core):
            raise ValueError("start does not bind the pinned source base, harness and dependencies")
        if not set(data["acceptance"]) <= self.active_acceptance(state):
            raise ValueError("start acceptance exceeds the active ticket membership")
        self.validate_phase_paths(state, data)
        self._validate_removed_baselines(state, data["candidate"], plan=plan, start=data)
        self.validate_predecessor(state)
        if data["mode"] != "VERIFY":
            if "remediation" in data:
                self.effective_actor(state, plan, data)
            if self.required_lane(state) is not None:
                raise ValueError("failed Direct repair requires the receiving lane's plan and approval")
            if any(row["state"] == "CANONICAL_REQUIRED" for row in self.failure_obligations(state).values()):
                raise ValueError("preserved real failure requires a canonical capture before dependent writes")
        self.decision_witnesses(state, plan, data["acceptance"], defer_red=data["mode"] != "PRODUCTION")
        _live(state, witnesses, data["acceptance"])

    def _context(self, state, request, candidate, profile, *, consumption=None):
        """Validate effect prerequisites against the prefix before a command can launch."""
        self.require_resolved_admissions(state)
        core = self.core
        plan, _, _ = self.plan_witnesses(state)
        content = plan["data"]["content"]
        core.verify_reference(state["contract"]["authority"]["evidence"])
        if "edit" not in state["contract"]["authority"]["actions"]:
            raise ValueError("proof requires recorded local action authority")
        start = core._latest(state, "start")
        if start is None or request["start"] != start["id"]:
            raise ValueError("proof requires the current earlier work start")
        actor = self.effective_actor(state, plan, start["data"])
        if request["actor"] != actor["session"]:
            raise ValueError("proof actor differs from the observed phase assignment")
        _live(state, [start])
        if (start["data"]["plan"] != plan["data"]["revision"] or start["data"]["profile"] != profile
                or profile != state["initial_profile"] or profile != plan["observed_profile"]):
            raise ValueError("proof start, exact plan or profile is stale")
        if candidate["instructions"] != plan["observed_instructions"]:
            raise ValueError("proof source instruction or harness identity changed")
        source = self.contract.read_only_source(state, candidate, core)
        if source != start["data"]["source"]:
            raise ValueError("proof source base, harness or dependencies changed")
        if start["data"]["prefix"] != start["previous_sha256"]:
            raise ValueError("proof start prefix does not match")
        before_start = _before(state, start)
        self.validate_start(before_start, start["data"])
        if start["data"]["write_scope"] != self.write_scope(before_start, start["data"]):
            raise ValueError("proof start write authority differs from its original prefix")
        self._validate_removed_baselines(state, candidate, plan=plan)
        issues = core._phase_errors(state, candidate, profile)
        if issues:
            raise ValueError("proof phase/source transition failed: " + "; ".join(issues))
        phase = request["phase"]
        mode = start["data"]["mode"]
        if phase == "RED" and mode != "TEST_ONLY":
            raise ValueError("RED requires TEST_ONLY")
        if phase == "GREEN" and mode != "PRODUCTION":
            raise ValueError("GREEN requires PRODUCTION")
        if phase == "CHECK" and mode not in {"PRODUCTION", "VERIFY"}:
            raise ValueError("CHECK requires PRODUCTION or VERIFY")
        if mode == "VERIFY" and candidate != start["data"]["candidate"]:
            raise ValueError("VERIFY must preserve the entire source")
        if request["check"] not in content["checks"]:
            raise ValueError("proof check is outside the approved plan")
        if phase in {"RED", "GREEN"}:
            item = request["acceptance"]
            row = content["result_map"].get(item)
            if row is None or request["check"] != row["check"] or request["test_path"] not in row["test"]:
                raise ValueError("behavior proof differs from its exact acceptance, check or test map")
            if phase == "RED" and item not in start["data"]["acceptance"]:
                raise ValueError("RED acceptance is outside its TEST_ONLY write ownership")
            self.decision_witnesses(state, plan, [item], defer_red=phase == "RED")
        elif "acceptance" in request:
            item = request["acceptance"]
            mapping = content.get("verification_map", {}).get(item)
            if (mode != "VERIFY" or mapping is None or item not in start["data"]["acceptance"]
                    or request["check"] != content["result_map"][item]["check"]
                    or any(request[key] != mapping[key] for key in ("test_path", "test_id", "command"))):
                raise ValueError("mapped CHECK requires its exact approved acceptance, test and VERIFY boundary")
            self._mapped_check_decisions(state, plan, item)
        elif "results" in request:
            self.decision_witnesses(state, plan, content["aggregate_checks"].get(request["check"], []))
        else:
            mapped = {content["result_map"][row["id"]]["check"] for row in content["acceptance"] if row["behavior"]}
            if request["check"] in mapped or request["check"] in content["aggregate_checks"]:
                raise ValueError("mapped checks require their actual native acceptance coverage")
            self._validate_unscoped_check_support(state, plan, start, consumption)
        return plan, start, source

    @staticmethod
    def admission_resolved(result):
        return result["data"]["outcome"] in {"INTENDED", "NO_EFFECT"}

    def require_resolved_admissions(self, state, *, own_intent=None):
        core = self.core
        resolved = {event["data"]["intent"] for event in core._events(state, "worker_admission_result")
                    if self.admission_resolved(event)}
        if any(event["id"] != own_intent and event["id"] not in resolved
               for event in core._events(state, "worker_admission_intent")):
            raise ValueError("unresolved worker admission requires guarded reconciliation")

    def worker_phase(self, state, start_id, actor, ticket, *, own_intent=None, resolved_readback=False):
        """Resolve live worker grants from the same reviewed phase as native proof."""
        self.require_resolved_admissions(state, own_intent=own_intent)
        core = self.core
        contract = state["contract"]
        witnesses = self.plan_witnesses(state)
        plan, _, _ = witnesses
        start = core._latest(state, "start")
        if start is None or start["id"] != start_id:
            raise ValueError("worker attempt requires the current work start")
        data, content = start["data"], plan["data"]["content"]
        if actor != self.effective_actor(state, plan, data)["session"]:
            raise ValueError("worker actor differs from the observed phase assignment")
        candidate, profile = self.snapshot(state), core.profile_identity()
        if (data["profile"] != profile or state["initial_profile"] != profile
                or plan["observed_profile"] != profile or data["plan"] != plan["data"]["revision"]
                or data["prefix"] != start["previous_sha256"]
                or candidate["instructions"] != plan["observed_instructions"]
                or self.contract.read_only_source(state, candidate, core, observe=True) != data["source"]):
            raise ValueError("worker source, start, plan or profile changed")
        if data["mode"] == "VERIFY" and candidate != data["candidate"]:
            raise ValueError("VERIFY worker requires source-preserving work")
        prior = _before(state, start)
        errors = core._start_errors(prior, data) + core._phase_errors(state, candidate, profile)
        if errors:
            raise ValueError("worker phase prerequisites failed: " + "; ".join(errors))
        members, _ = self.membership(state)
        ticket_map = {row["id"]: set(row["acceptance"]) for row in contract["tickets"]}
        accepted = set(data["acceptance"]) & ticket_map.get(ticket, set())
        if ticket not in members or not accepted:
            raise ValueError("worker ticket has no active acceptance in this phase")
        defer_red = data["mode"] != "PRODUCTION"
        issued = self.decision_witnesses(prior, plan, accepted, defer_red=defer_red)
        current = self.decision_witnesses(state, plan, accepted, defer_red=defer_red)
        _live(state, [start, *self.plan_witnesses(prior), *issued], accepted)
        if self._decision_revisions(issued) != self._decision_revisions(current):
            raise ValueError("worker decision revision changed after its phase start")
        _live(state, [start, *witnesses, *current], accepted)
        if data["mode"] == "PRODUCTION":
            self._validate_production_red_support(state, prior, start, issued)
            for item in accepted:
                if any(row["id"] == item and row["behavior"] for row in content["acceptance"]):
                    self._own_red(state, start, item)
        if data["mode"] == "VERIFY":
            owned = set()
        elif "write_manifest" in data:
            owned = {row["path"] for row in data["write_manifest"] if row["ticket"] == ticket}
        else:
            role = "test" if data["mode"] == "TEST_ONLY" else "production"
            owned = {path for item in accepted for path in content["result_map"][item][role]}
        paths = sorted(owned & set(data["write_scope"]))
        if not resolved_readback:
            self._validate_removed_baselines(state, candidate, plan=plan,
                                             grant={path: {ticket} for path in paths})
        return {"start": start["id"], "start_sha256": start["sha256"], "plan": plan["id"],
                "profile": profile["sha256"], "candidate": candidate, "mode": data["mode"],
                "acceptance": sorted(accepted), "paths": paths}

    def _mapped_check_decisions(self, state, plan, acceptance):
        if acceptance not in self.active_acceptance(state):
            raise ValueError("mapped CHECK acceptance is outside the active ticket membership")
        decisions = self.decision_witnesses(state, plan, [acceptance], defer_red=True)
        _live(state, [plan, *decisions], [acceptance])
        return decisions

    def _test_identity(self, proof):
        core = self.core
        data = proof["data"]
        observed = proof["observed_source"]
        path = data["test_path"]
        core.verify_reference(data["test"])
        if observed["files"].get(path) != data["test"]["sha256"]:
            raise ValueError("proof test bytes differ from server-observed source")
        return (data["check"], path, data["test_id"], data["test"]["sha256"], observed["modes"][path],
                data["command"], data["runner"], data["source"])

    def _execution_identity(self, data, candidate, runner, source):
        path = data["test_path"]
        checksum = candidate["files"].get(path)
        if not checksum:
            raise ValueError("declared test source is absent")
        return (data["check"], path, data["test_id"], checksum, candidate["modes"][path], data["command"], runner, source)

    @staticmethod
    def _decision_revisions(witnesses):
        return {event["data"]["lineage"]: event["data"]["revision"]
                for event in witnesses if event["type"] == "decision"}

    def _boundary_witnesses(self, state, boundary, acceptance):
        prefix = _before(state, boundary)
        selected = self.plan_witnesses(prefix)
        data = boundary["data"]
        defer_red = data.get("mode") in {"TEST_ONLY", "VERIFY"} or data.get("phase") == "RED"
        return selected + self.decision_witnesses(prefix, selected[0], [acceptance], defer_red=defer_red)

    def _live_original_witnesses(self, state, acceptance, *boundaries):
        selected = [event for boundary in boundaries
                    for event in self._boundary_witnesses(state, boundary, acceptance)]
        _live(state, [*boundaries, *selected], [acceptance])

    def _latest_red(self, state, acceptance):
        return self.core._latest(state, "proof", lambda e: e["data"].get("acceptance") == acceptance
                                 and e["data"]["phase"] == "RED")

    def _select_own_red(self, earlier, acceptance):
        start = self.core._latest_work_start(earlier)
        red = self._latest_red(earlier, acceptance)
        if (start is None or start["data"]["mode"] != "TEST_ONLY" or red is None
                or red["data"]["start"] != start["id"]):
            raise ValueError("GREEN requires the original intended RED from its own TEST_ONLY cycle")
        return start, red

    def _own_red(self, state, production, acceptance):
        earlier = _before(state, production)
        start, red = self._select_own_red(earlier, acceptance)
        self._validate_proof(earlier, red, "RED", production["data"]["candidate"]["sha256"], production["data"]["plan"])
        self._live_original_witnesses(state, acceptance, start, red, production)
        return start, red

    def _validate_red_support(self, state, admission, production, acceptance, red):
        """Check a selected admitted RED without re-entering source chronology."""
        if red is None:
            raise ValueError("production admission lacks its original intended RED support")
        data = red["data"]
        phase = production["data"]
        candidate = phase["candidate"]["sha256"]
        prefix = _before(admission, red)
        test_start = self.core._latest(prefix, "start")
        plan = self.core._latest(prefix, "plan")
        if (test_start is None or test_start["data"]["mode"] != "TEST_ONLY"
                or data["start"] != test_start["id"] or acceptance not in test_start["data"]["acceptance"]
                or plan is None or data["plan_event"] != plan["id"] or data["plan"] != phase["plan"]
                or data["candidate"] != candidate or red["observed_source"]["sha256"] != candidate):
            raise ValueError("original intended RED differs from its admitted acceptance, plan or candidate")
        self._live_original_witnesses(state, acceptance, test_start, red)
        self._validate_native(admission, data, plan, test_start)
        self._test_identity(red)

    def _validate_production_red_support(self, state, admission, production, witnesses, *, own_acceptance=None):
        """Validate admitted REDs and report whether they were required."""
        reviewed = {event["data"]["decision"] for event in witnesses if event["type"] == "doubt_review"}
        reds = {}
        for event in witnesses:
            if event["type"] != "decision":
                continue
            data = event["data"]
            if data["kind"] == "ordinary" and data["strategy"] == "TDD_RED" and data["lineage"] not in reviewed:
                reds.update({item: self._latest_red(admission, item) for item in data["acceptance"]})
        if own_acceptance is not None:
            _, reds[own_acceptance] = self._select_own_red(admission, own_acceptance)
        for item, red in reds.items():
            self._validate_red_support(state, admission, production, item, red)
        return bool(reds)

    def _validate_unscoped_check_support(self, issuance, plan, start, consumption):
        issued = self.decision_witnesses(issuance, plan, ())
        current = issuance if consumption is None else consumption
        if consumption is not None:
            self._selected_decisions(current, plan, ())
            _live(current, issued)
        if start["data"]["mode"] == "PRODUCTION":
            admission = _before(issuance, start)
            plan_witnesses = self.plan_witnesses(admission)
            admitted = self.decision_witnesses(admission, plan_witnesses[0], ())
            if self._validate_production_red_support(current, admission, start, admitted):
                _live(current, [start, *plan_witnesses, *admitted])

    def _carry_pair(self, state, start, acceptance):
        earlier = _before(state, start)
        core = self.core
        production = core._latest(earlier, "start", lambda e: e["data"]["mode"] != "VERIFY"
                                  and acceptance in e["data"]["acceptance"])
        if production is None or production["data"]["mode"] != "PRODUCTION":
            raise ValueError("carried proof requires the latest own cycle to be completed")
        green = core._latest(earlier, "proof", lambda e: e["data"].get("acceptance") == acceptance
                            and e["data"]["phase"] == "GREEN" and e["data"]["start"] == production["id"])
        if green is None:
            raise ValueError("carried proof is missing a genuine own GREEN")
        self._validate_proof(_through(earlier, green), green, "GREEN", green["data"]["candidate"],
                             production["data"]["plan"])
        test_start, red = self._own_red(earlier, production, acceptance)
        return test_start, red, production, green

    def _carry_interval(self, state, acceptance, pair, start, current_proof=None):
        """Require continuous relevant authority and unchanged test inputs through consumption."""
        core = self.core
        test_start, red, production, green = pair
        original_prefix = _before(state, test_start)
        initial_witnesses = self.plan_witnesses(original_prefix)
        original = initial_witnesses[0]
        required = set(original["data"]["content"]["decisions"])
        active_decisions = {e["data"]["lineage"]: e for e in core._events(original_prefix, "decision")}
        interval = state["events"][test_start["seq"] - 1:]
        relevant_decisions = list(active_decisions.values()) + [e for e in interval if e["type"] == "decision"]
        required.update(e["data"]["lineage"] for e in relevant_decisions if acceptance in e["data"]["acceptance"])
        contract = {k: v for k, v in original["data"]["content"].items() if k != "remediations"}
        active_plan, active_approval = original, initial_witnesses[-1]
        witnesses = [test_start, red, production, green, start, *initial_witnesses]
        if current_proof is not None:
            witnesses.append(current_proof)
        for boundary in (test_start, red, production, green, start, current_proof):
            if boundary is None:
                continue
            witnesses.extend(self._boundary_witnesses(state, boundary, acceptance))
        current_witnesses = self.plan_witnesses(state)
        witnesses.extend(current_witnesses)
        witnesses.extend(self.decision_witnesses(state, current_witnesses[0], [acceptance]))
        active_support = {}
        for lineage in required:
            decision = active_decisions.get(lineage)
            if decision is not None:
                review = core._latest(original_prefix, "doubt_review", lambda e: e["data"]["decision"] == lineage
                                      and e["data"]["revision"] == decision["data"]["revision"])
                if review is not None and not core._decision_resolution_errors(original_prefix, review):
                    active_support[lineage] = review
        defer_support = True
        original_source = test_start["data"]["candidate"]
        instruction_paths = original_source["instructions"]
        test_path = red["data"]["test_path"]
        test_mode = red["observed_source"]["modes"][test_path]
        for event in interval:
            data = event["data"]
            kind = event["type"]
            if kind == "plan":
                witnesses.extend(self.plan_witnesses(_before(state, event), active_plan))
                current = data["content"]
                old_remediations = active_plan["data"]["content"]["remediations"]
                if ({k: v for k, v in current.items() if k != "remediations"} != contract
                        or current["remediations"][:len(old_remediations)] != old_remediations
                        or event["observed_profile"] != original["observed_profile"]
                        or event["observed_instructions"] != original["observed_instructions"]):
                    raise ValueError("carried proof has changed plan, profile, instructions or remediation contract")
                active_plan, active_approval = event, None
            if kind == "plan_review" and data.get("plan") == active_plan["data"]["revision"]:
                chosen = self.plan_witnesses(_through(state, event), active_plan)
                active_approval = chosen[-1]
            if kind == "start":
                mode = data["mode"]
                if mode != "VERIFY" and acceptance in data["acceptance"]:
                    if event["seq"] > production["seq"]:
                        raise ValueError("carried proof was superseded by a later explicit own cycle")
                    defer_support = mode == "TEST_ONLY"
                candidate, profile = data["candidate"], data["profile"]
            elif kind == "proof_attempt":
                candidate, profile = data["broken"], None
            else:
                candidate, profile = event.get("observed_source"), event.get("observed_profile")
            if candidate is not None:
                self.contract.validate_snapshot(candidate, core)
                modes = candidate["modes"]
                if (candidate["instructions"] != instruction_paths
                        or any(modes[name] != original_source["modes"][name] for name in instruction_paths)):
                    raise ValueError("carried proof instruction or harness history changed")
                if event["seq"] >= red["seq"] and (candidate["files"].get(test_path) != red["data"]["test"]["sha256"]
                                                    or modes.get(test_path) != test_mode):
                    raise ValueError("carried proof whole test bytes or mode changed after its original RED")
            if profile is not None and profile != test_start["data"]["profile"]:
                raise ValueError("carried proof profile history changed")
            if kind == "decision":
                if data["lineage"] in required:
                    raise ValueError("carried proof relevant decision changed after TEST_ONLY")
                active_decisions[data["lineage"]] = event
                active_support.pop(data["lineage"], None)
            if kind == "doubt_review" and data["decision"] in required:
                decision = active_decisions.get(data["decision"])
                if decision and data["revision"] == decision["data"]["revision"]:
                    if core._decision_resolution_errors(_through(state, event), event) or any(
                        finding["actionable"] for finding in data["findings"]
                    ):
                        raise ValueError("carried proof relevant decision support was rejected")
                    active_support[data["decision"]] = event
            if kind in {"withdrawal", "supersession"}:
                effective = [active_approval] if active_approval is not None else []
                for lineage, review in active_support.items():
                    decision = active_decisions[lineage]["data"]
                    if not (defer_support and decision["kind"] == "ordinary" and decision["strategy"] == "TDD_RED"):
                        effective.append(review)
                if any(e["id"] == data.get("target") and e["seq"] < event["seq"] for e in effective):
                    raise ValueError("carried proof effective support was withdrawn during its cycle")
        _live(state, witnesses, [acceptance])

    def _native_object(self, state, ref):
        core = self.core
        core.verify_reference(ref)
        path = Path(ref["path"])
        if path.parent != Path(state["evidence_root"]) or path.name != ref["sha256"] + ".json":
            raise ValueError("native proof evidence must come from this run's private artifact store")
        return core._read_json(path)

    def _native_stream(self, state, ref):
        core = self.core
        core.verify_reference(ref)
        path = Path(ref["path"])
        if path.parent != Path(state["evidence_root"]) or path.name != ref["sha256"] + ".json":
            raise ValueError("native proof stream does not belong to this run")
        return core._file_bytes(path)

    @staticmethod
    def _assertion_failure(stdout, stderr):
        python = b"Traceback (most recent call last):" in stderr and re.search(
            rb"^AssertionError(?::[^\r\n]*)?\r?$", stderr, re.MULTILINE,
        )
        node = re.search(rb"^not ok ", stdout, re.MULTILINE) and re.search(
            rb"^\s+code: ['\"]ERR_ASSERTION['\"]", stdout, re.MULTILINE,
        )
        # Node can emit a spec report instead of TAP for the same test argv.
        node_spec = (
            re.search(rb"^\xe2\x84\xb9 fail [1-9]\d*\r?$", stdout, re.MULTILINE)
            and re.search(rb"^test at [^\r\n]+:\d+:\d+\r?$", stdout, re.MULTILINE)
            and re.search(rb"^[ \t]+AssertionError \[ERR_ASSERTION\]:", stdout, re.MULTILINE)
        )
        return bool(python or node or node_spec)

    def _selected_native_result(self, state, data, stdout, stderr):
        repo, test_path = state["contract"]["repo"], data["test_path"]
        identity = data["test_id"]
        runner = self.contract.native_test_runner(repo, test_path, identity, data["command"])
        paths = {test_path, str(Path(repo) / test_path)}
        failed = data["phase"] == "RED"
        if runner == "unittest":
            return _unittest_selected_result(stderr.decode("utf-8"), identity, paths, failed)
        return _node_selected_result(stdout.decode("utf-8"), identity, paths, failed)

    def _validate_native(self, state, data, plan, start):
        receipt = self._native_object(state, data["output"])
        expected = {
            "schema": "i2e-team-command-v2", "run": state["contract"]["run_id"],
            "plan": data["plan"], "plan_event": plan["id"], "start": start["id"],
            "candidate": data["candidate"], "source": data["source"], "actor": data["actor"],
            "argv": data["command"], "cwd": state["contract"]["repo"], "runner": data["runner"],
            "exit": data["exit"], "timed_out": False, "launch_error": None,
        }
        if any(receipt.get(k) != v for k, v in expected.items()):
            raise ValueError("proof does not bind its actual current native command receipt")
        if self.executor.executable(data["command"][0]) != data["runner"]:
            raise ValueError("proof runner executable identity changed")
        executor = receipt["executor"]
        self.executor.verify_executor(executor, Path(state["evidence_root"]).parents[1])
        qualification = self._native_object(state, receipt["qualification"])
        if (qualification["exit"] != 0 or qualification["timed_out"] or qualification["launch_error"] is not None
                or self._native_stream(state, qualification["stdout"]) != b"qualified read-only\n"):
            raise ValueError("proof executor lacks a qualifying native probe")
        self._native_stream(state, qualification["stderr"])
        prefix = [str(self.executor.SANDBOX), "-p", self.executor._profile(Path(executor["scratch"]))]
        if receipt["wrapper_argv"] != prefix + data["command"] or qualification["argv"][:3] != prefix:
            raise ValueError("proof used a different executable sandbox profile")
        stdout = self._native_stream(state, receipt["stdout"])
        stderr = self._native_stream(state, receipt["stderr"])
        if data["phase"] == "RED":
            if (data["exit"] <= 0 or data.get("failure_kind") != "ASSERTION"
                    or data["outcome"] != "INTENDED_ASSERTION_FAILURE"):
                raise ValueError("meaningful intended assertion RED is required")
        elif data["exit"] != 0 or data.get("failure_kind") is not None or data["outcome"] != "PASS":
            raise ValueError("proof requires an actual passing result")
        if "acceptance" in data and not self._selected_native_result(state, data, stdout, stderr):
            raise ValueError("native receipt lacks a qualifying result for the exact selected test")

    def _aggregate(self, state, data, plan, start, *, issued_before=None):
        core = self.core
        required = plan["data"]["content"]["aggregate_checks"].get(data["check"])
        if required is None or not isinstance(data.get("results"), list):
            raise ValueError("aggregate coverage requires exact mapped native results")
        required = set(required) & self.active_acceptance(state)
        coverage, selected = set(), set()
        native = []
        phase = "CHECK" if start["data"]["mode"] == "VERIFY" else "GREEN"
        for row in data["results"]:
            self.contract.fields(row, {"acceptance", "proof"}, "aggregate native result")
            acceptance = core._label(row["acceptance"], "aggregate acceptance")
            proof_id = core._label(row["proof"], "aggregate proof")
            if acceptance not in required or acceptance in coverage or proof_id in selected:
                raise ValueError("aggregate coverage has duplicate, unknown or misattributed results")
            coverage.add(acceptance)
            selected.add(proof_id)
            proof = _event(state, proof_id, "proof")
            facts = proof["data"]
            if (facts.get("phase") != phase or "results" in facts or facts.get("acceptance") != acceptance
                    or facts.get("start") != start["id"] or facts.get("source") != data["source"]
                    or (issued_before is not None and proof["seq"] >= issued_before)):
                raise ValueError("aggregate coverage must use current exact acceptance results from its start")
            self._validate_proof(state, proof, phase, data["candidate"], data["plan"])
            native.append({"acceptance": acceptance, "proof": proof_id, "event_sha256": proof["sha256"],
                           "output": facts["output"]})
        if coverage != set(required):
            raise ValueError("aggregate coverage omits required acceptance results")
        return {"schema": "i2e-team-aggregate-v2", "run": state["contract"]["run_id"],
                "plan": data["plan"], "plan_event": plan["id"], "start": start["id"],
                "candidate": data["candidate"], "source": data["source"], "check": data["check"], "results": native}

    def _validate_proof(self, state, proof, phase, candidate, revision):
        core = self.core
        if _event(state, proof["id"], "proof") != proof:
            raise ValueError("proof is not its immutable ledger event")
        data = proof["data"]
        observed = proof["observed_source"]
        if (data["candidate"] != candidate or data["plan"] != revision
                or observed["sha256"] != candidate or type(data["exit"]) is not int):
            raise ValueError("proof candidate, exact plan or exit status is stale")
        self._validate_removed_baselines(state, observed)
        if phase == "PASS":
            if data["phase"] not in {"GREEN", "CHECK"} or data["exit"] != 0:
                raise ValueError("proof is not a passing result")
        elif data["phase"] != phase:
            raise ValueError("proof is for a different phase")
        prefix = _before(state, proof)
        plan, start, source = self._context(prefix, data, observed, proof["observed_profile"], consumption=state)
        if data.get("source") != source or data.get("plan_event") != plan["id"]:
            raise ValueError("proof source or exact plan-event identity differs")
        _live(state, [proof, start, *self.plan_witnesses(prefix)])
        if "results" in data:
            if data["phase"] != "CHECK" or data["outcome"] != "PASS":
                raise ValueError("aggregate proof requires passing CHECK results")
            expected = self._aggregate(state, data, plan, start, issued_before=proof["seq"])
            if self._native_object(state, data["output"]) != expected:
                raise ValueError("aggregate proof evidence differs from its native subresults")
            return
        self._validate_native(state, data, plan, start)
        if data["phase"] == "CHECK" and "acceptance" in data:
            acceptance = data["acceptance"]
            mapping = plan["data"]["content"]["verification_map"][acceptance]
            self._test_identity(proof)
            if data["runner"] != mapping["runner"]:
                raise ValueError("mapped CHECK runner differs from its approved verification map")
            issued = self._mapped_check_decisions(prefix, plan, acceptance)
            _live(state, [plan, *issued], [acceptance])
            current = self._mapped_check_decisions(state, plan, acceptance)
            if self._decision_revisions(issued) != self._decision_revisions(current):
                raise ValueError("mapped CHECK relevant decision revision changed since issuance")
        if data["phase"] in {"RED", "GREEN"}:
            identity = self._test_identity(proof)
            acceptance = data["acceptance"]
            if data["phase"] == "RED":
                self._live_original_witnesses(state, acceptance, start, proof)
            else:
                self._live_original_witnesses(state, acceptance, proof)
                if acceptance in start["data"]["acceptance"]:
                    _, red = self._own_red(state, start, acceptance)
                    if identity != self._test_identity(red):
                        raise ValueError("GREEN changed its original RED test, mode, runner or command")
                    issued = self.decision_witnesses(prefix, plan, [acceptance])
                    current = self.decision_witnesses(state, plan, [acceptance])
                    if self._decision_revisions(issued) != self._decision_revisions(current):
                        raise ValueError("own GREEN relevant decision revision changed since issuance")
                else:
                    pair = self._carry_pair(state, start, acceptance)
                    if any(identity != self._test_identity(e) for e in (pair[1], pair[3])):
                        raise ValueError("carried proof changed its whole test, runner or command")
                    self._carry_interval(state, acceptance, pair, start, current_proof=proof)

    def proof_errors(self, state, proof, phase, candidate, revision):
        try:
            self._validate_proof(state, proof, phase, candidate, revision)
            return []
        except (self.core.RuntimeError, ValueError, TypeError, KeyError, OSError, StopIteration) as exc:
            return [str(exc) or "v2 proof evidence is missing"]

    def _request(self, request):
        core = self.core
        common = {"id", "phase", "check", "start", "actor"}
        if not isinstance(request, dict) or not common <= set(request):
            raise ValueError("proof requires id, phase, check, earlier start and actor")
        for field in common:
            core._label(request[field], "proof " + field)
        if request["id"].startswith("i2e/"):
            raise ValueError("internal proof operation identity is reserved")
        phase = request["phase"]
        if phase not in {"RED", "GREEN", "CHECK"}:
            raise ValueError("proof phase is unsupported")
        if "results" in request:
            self.contract.fields(request, common | {"results"}, "aggregate proof request")
            if phase != "CHECK":
                raise ValueError("only CHECK can aggregate native results")
            return
        required = common | {"command"}
        if phase in {"RED", "GREEN"} or "acceptance" in request:
            required |= {"acceptance", "test_id", "test_path"}
            core._label(request.get("acceptance"), "acceptance")
            self.contract.validate_test_id(request.get("test_id"))
            core._paths([request.get("test_path")])
        if phase == "RED":
            required.add("failure_kind")
            if request.get("failure_kind") != "ASSERTION":
                raise ValueError("RED requires a declared intended assertion")
        if set(request) not in (required, required | {"timeout_seconds"}):
            raise ValueError("command proof has missing or unsupported fields")
        command = request["command"]
        if not isinstance(command, list) or not command or any(
            not isinstance(arg, str) or not arg or "\0" in arg for arg in command
        ):
            raise ValueError("proof command must be a nonempty argument array")
        timeout = request.get("timeout_seconds", core.PROOF_TIMEOUT_SECONDS)
        if type(timeout) is not int or not 1 <= timeout <= core.PROOF_TIMEOUT_SECONDS:
            raise ValueError("proof timeout is outside the allowed range")

    def _capture_stream(self, ledger, run_id, content):
        maximum = self.core.MAX_FILE_BYTES
        if len(content) <= maximum:
            return ledger._artifact(run_id, content)
        return {"bytes": len(content),
                "chunks": [ledger._artifact(run_id, content[i:i + maximum]) for i in range(0, len(content), maximum)]}

    def _capture_output(self, ledger, run_id, result):
        captured = dict(result)
        for stream in ("stdout", "stderr"):
            captured[stream] = self._capture_stream(ledger, run_id, result[stream])
        return captured

    def _failed_attempt(self, ledger, state, data, reason, candidate):
        """Retain raw output and recoverable scoped bytes even when proof is refused."""
        core = self.core
        run_id = state["contract"]["run_id"]
        preserved = {}
        gaps = []
        for name, checksum in (candidate["files"] | candidate["instructions"]).items():
            if checksum is None:
                continue
            try:
                body = core._file_bytes(Path(candidate["repo"]) / name)
                ref = ledger._artifact(run_id, body)
                if ref["sha256"] != checksum:
                    raise ValueError("source changed during preservation")
                preserved[name] = ref
            except (core.RuntimeError, ValueError, OSError) as exc:
                gaps.append({"path": name, "error": str(exc)})
        ledger._append(run_id, {
            "id": core._internal_id("proof-attempt", data["id"]), "type": "proof_attempt",
            "data": {"request": data, "error": reason, "broken": candidate,
                     "broken_files": preserved, "preservation_gaps": gaps},
        }, None, internal=True)

    def prove(self, ledger, state, expected_seq, request):
        core = self.core
        receipt = None
        try:
            self._request(request)
            if type(expected_seq) is not int or state["seq"] != expected_seq:
                raise ValueError("expected sequence conflict")
            if any(e["id"] == request["id"] or e["id"] == core._internal_id("proof-attempt", request["id"])
                   for e in state["events"]):
                raise ValueError("proof request identity is already recorded")
            run_id, contract = state["contract"]["run_id"], state["contract"]
            candidate = self.snapshot(state)
            profile = core.profile_identity()
            self.contract.read_only_source(state, candidate, core, observe=True)
            plan, start, source = self._context(state, request, candidate, profile)
            data = {k: v for k, v in request.items() if k not in {"id", "timeout_seconds"}}
            data.update(plan=plan["data"]["revision"], plan_event=plan["id"], candidate=candidate["sha256"], source=source)
            if "results" in data:
                aggregate = self._aggregate(state, data, plan, start)
                data.update(output=ledger._artifact(run_id, core.canonical(aggregate)), exit=0, outcome="PASS")
            else:
                runner = self.executor.executable(data["command"][0])
                test_bytes = None
                if "acceptance" in data:
                    test_bytes = core._file_bytes(Path(contract["repo"]) / data["test_path"])
                    identity = self._execution_identity(data, candidate, runner, source)
                    if data["phase"] == "RED":
                        self._live_original_witnesses(state, data["acceptance"], start)
                    elif data["phase"] == "CHECK":
                        mapping = plan["data"]["content"]["verification_map"][data["acceptance"]]
                        if runner != mapping["runner"]:
                            raise ValueError("mapped CHECK runner differs from its approved verification map")
                    elif data["phase"] == "GREEN":
                        acceptance = data["acceptance"]
                        if acceptance in start["data"]["acceptance"]:
                            _, red = self._own_red(state, start, acceptance)
                            if identity != self._test_identity(red):
                                raise ValueError("GREEN changed its original RED test, runner or command")
                        else:
                            pair = self._carry_pair(state, start, acceptance)
                            if any(identity != self._test_identity(e) for e in (pair[1], pair[3])):
                                raise ValueError("carried proof changed its whole test, runner or command")
                            self._carry_interval(state, acceptance, pair, start)
                attempt = self.executor.run_read_only(
                    Path(contract["repo"]), ledger.db.parent, data["command"],
                    request.get("timeout_seconds", core.PROOF_TIMEOUT_SECONDS),
                )
                qualification = self._capture_output(ledger, run_id, attempt["qualification"])
                qualified_ref = ledger._artifact(run_id, core.canonical(qualification))
                observed = attempt["result"]
                native = {
                    "schema": "i2e-team-command-v2", "run": run_id, "plan": data["plan"],
                    "plan_event": plan["id"], "start": start["id"], "candidate": candidate["sha256"],
                    "source": source, "actor": data["actor"], "argv": data["command"], "cwd": contract["repo"],
                    "runner": attempt["runner"], "executor": attempt["executor"], "qualification": qualified_ref,
                }
                if observed is not None:
                    actual = self._capture_output(ledger, run_id, observed)
                    native.update(actual, argv=data["command"], wrapper_argv=actual["argv"])
                receipt = ledger._artifact(run_id, core.canonical(native))
                after = self.snapshot(state)
                reason = None
                if observed is None:
                    reason = "read-only executor did not qualify"
                elif after != candidate or attempt["runner"] != runner:
                    reason = "proof command source, instructions or runner identity changed"
                elif observed["timed_out"]:
                    reason = "proof command timed out"
                elif observed["launch_error"] is not None:
                    reason = "proof command could not launch"
                elif any("chunks" in native[stream] for stream in ("stdout", "stderr")):
                    reason = "proof command output exceeds a supported evidence stream"
                elif data["phase"] == "RED":
                    if observed["exit"] <= 0:
                        reason = "intended assertion RED requires a command failure"
                elif observed["exit"] != 0:
                    reason = "passing proof requires a command that exited zero"
                if test_bytes is not None and reason is None:
                    try:
                        selected = self._selected_native_result(state, data, observed["stdout"], observed["stderr"])
                    except ValueError:
                        selected = False
                    if not selected:
                        reason = "native command did not establish the exact selected test result"
                if reason is not None:
                    self._failed_attempt(ledger, state, dict(data, id=request["id"], output=receipt), reason, after)
                    return {"state": "BLOCK", "errors": [reason], "receipt": receipt}
                data.update(output=receipt, exit=observed["exit"], runner=runner,
                            outcome="INTENDED_ASSERTION_FAILURE" if data["phase"] == "RED" else "PASS")
                if test_bytes is not None:
                    data["test"] = ledger._artifact(run_id, test_bytes)

            def guard(prefix):
                current = self.snapshot(prefix)
                if current != candidate or core.profile_identity() != profile:
                    raise ValueError("source or profile changed before native proof admission")
                self.contract.read_only_source(prefix, current, core, observe=True)
                self._validate_removed_baselines(prefix, current, plan=plan)

            saved = ledger._append(run_id, {"id": request["id"], "type": "proof", "data": data},
                                   expected_seq, internal=True, guard=guard)
            return {"state": "PASS", "errors": [], "proof": saved}
        except (core.RuntimeError, ValueError, TypeError, KeyError, OSError, StopIteration) as exc:
            result = {"state": "BLOCK", "errors": [str(exc) or "required v2 proof evidence is missing"]}
            if receipt is not None:
                result["receipt"] = receipt
            return result

    def _capture_witness(self, state, link, defect, check, *, failure_id=None, candidate=None):
        core = self.core
        if link["data"]["defect"] != defect:
            raise ValueError("canonical case link does not belong to the named stable defect")
        intent = _event(_before(state, link), link["data"]["intent"], "capture_intent")
        captured = intent["data"]["request"]
        case = captured["case"]
        if case["check_id"] != check or core.digest(case) != link["data"]["digest"]:
            raise ValueError("canonical case does not carry the exact regression check")
        failure_id = case["origin"]["failure_id"] if failure_id is None else failure_id
        if failure_id != case["origin"]["failure_id"]:
            raise ValueError("case origin does not match its source-bound recorded failure")
        failure = _event(_before(state, intent), failure_id, "failure")
        data = failure["data"]
        frozen = captured["failure"]
        if (data["defect"] != defect or type(data["exit"]) is not int or data["exit"] == 0
                or data["broken"] != failure["observed_source"] or data["broken"] != frozen["broken"]
                or data["command"] != frozen["command"] or data["output"] != frozen["output"]
                or (candidate is not None and data["broken"]["sha256"] != candidate)):
            raise ValueError("case link lacks an exact actual failed command and broken source")
        core.verify_reference(data["output"])
        core.verify_reference(link["data"]["show"])
        shown = core._read_json(link["data"]["show"]["path"])
        core._validate_shown(shown, link["data"]["digest"], state["contract"]["project"])
        core._capture_validation(intent, state["contract"])
        _live(state, [failure, intent, link])
        return case, failure

    def _binding(self, ledger, state, request):
        core = self.core
        self.contract.fields(request, {"id", "digest", "check", "defect", "failure", "case_link",
                                       "consultation", "before", "plan", "prior_run", "prior_prefix",
                                       "relation"}, "inherited case binding")
        for name in ("id", "check", "defect", "failure", "case_link", "consultation", "prior_run"):
            core._label(request[name], "case binding " + name)
        if request["id"].startswith("i2e/"):
            raise ValueError("internal case binding identity is reserved")
        for name in ("digest", "before", "plan", "prior_prefix"):
            self.contract.sha256(request[name], "case binding " + name)
        relation = request["relation"]
        self.contract.fields(relation, {"source", "reason"}, "case relation")
        self.contract.text(relation["reason"], "case relation")
        core.verify_reference(relation["source"])
        plan = self.plan_witnesses(state)[0]
        pair = request["digest"], request["check"]
        if (request["plan"] != plan["data"]["revision"] or not any(
            request["defect"] in mapping["defects"] and pair in self.contract.pairs(mapping["case_pairs"], core)
            for mapping in plan["data"]["content"]["remediations"]
        )):
            raise ValueError("inherited case pair is outside exact reviewed remediation")
        lookup = _event(state, request["consultation"], "consultation")
        if (lookup["data"]["stage"] != "repair" or lookup["data"]["target"] != request["before"]
                or core._consultation_errors(state, lookup)):
            raise ValueError("case binding requires complete current broken-source repair consultation")
        applicability = core._latest(state, "case_decision", lambda e: e["seq"] > lookup["seq"]
                                     and e["data"]["consultation"] == lookup["id"]
                                     and e["data"]["digest"] == request["digest"])
        if (applicability is None or applicability["data"]["applicability"] != "APPLIES"
                or request["check"] not in applicability["data"]["checks"]):
            raise ValueError("inherited pair lacks its current exact applicability decision")
        shown_ref = lookup["data"]["shown"][request["digest"]]
        core.verify_reference(shown_ref)
        shown = core._read_json(shown_ref["path"])
        core._validate_shown(shown, request["digest"], state["contract"]["project"])
        parent = shown["record"]
        if parent["origin"]["task_id"] != request["prior_run"] or request["prior_run"] == state["contract"]["run_id"]:
            raise ValueError("inherited canonical origin differs from the named prior run")
        current_link = _event(state, request["case_link"], "case_link")
        if current_link["seq"] >= lookup["seq"] or current_link["data"]["digest"] == request["digest"]:
            raise ValueError("current canonical reproduction must precede lookup and preserve distinct origin")
        _, current_failure = self._capture_witness(
            state, current_link, request["defect"], request["check"],
            failure_id=request["failure"], candidate=request["before"],
        )
        prior = ledger.show(request["prior_run"])
        if (prior["sha256"] != request["prior_prefix"] or prior["contract"]["project"] != state["contract"]["project"]
                or prior["contract"]["case_store"] != state["contract"]["case_store"]
                or prior["contract"]["case_helper_sha256"] != state["contract"]["case_helper_sha256"]):
            raise ValueError("prior repair history is unknown, changed or outside this canonical scope")
        prior_link = core._latest(prior, "case_link", lambda e: e["data"]["digest"] == request["digest"])
        if prior_link is None:
            raise ValueError("prior ledger does not preserve the inherited canonical origin")
        prior_case, prior_failure = self._capture_witness(prior, prior_link, request["defect"], request["check"])
        if prior_case["origin"] != parent["origin"] or prior_failure["data"]["command"] != current_failure["data"]["command"]:
            raise ValueError("prior origin or current defect reproduction differs")
        if core._knowledge_errors(prior, prior_failure["data"]["broken"]["sha256"], proofs=False):
            raise ValueError("prior failure and case history has unresolved evidence gaps")
        _live(state, [lookup, applicability, current_link, current_failure, plan])
        failures = []
        for event in core._events(prior, "repair"):
            if event["data"].get("defect") == request["defect"] and event["data"].get("outcome") == "FAIL":
                failures.append({"run": request["prior_run"], "event": event["id"], "sha256": event["sha256"]})
        return {"request": request, "parent": shown_ref, "prior_link": prior_link["id"],
                "prior_failures": failures, "plan_event": plan["id"], "applicability": applicability["id"]}

    def bind_case(self, ledger, state, expected_seq, request):
        core = self.core
        try:
            if type(expected_seq) is not int or state["seq"] != expected_seq:
                raise ValueError("case binding expected sequence conflict")
            contract = state["contract"]
            current = self.snapshot(state)
            self.contract.read_only_source(state, current, core, observe=True)
            if not isinstance(request, dict) or request.get("before") != current["sha256"]:
                raise ValueError("case binding must observe the exact current broken source")
            if any(e["id"] == request.get("id") for e in state["events"]):
                raise ValueError("case binding identity is already recorded")
            data = self._binding(ledger, state, request)

            def guard(prefix):
                if (self.snapshot(prefix) != current
                        or self._binding(ledger, prefix, request) != data):
                    raise ValueError("case binding source or historical lineage changed")

            saved = ledger._append(contract["run_id"], {"id": request["id"], "type": "case_binding", "data": data},
                                   expected_seq, internal=True, guard=guard)
            return {"state": "PASS", "binding": saved, "errors": []}
        except (core.RuntimeError, ValueError, TypeError, KeyError, OSError, StopIteration) as exc:
            return {"state": "BLOCK", "errors": [str(exc) or "inherited case evidence is missing"]}

    def deferred_cases(self, state, start, defects):
        if not defects:
            return set()
        core = self.core
        data = start["remediation"]
        result = set()
        for event in core._events(state, "case_link"):
            if event["data"]["defect"] not in defects:
                continue
            core.verify_reference(event["data"]["show"])
            shown = core._read_json(event["data"]["show"]["path"])
            core._validate_shown(shown, event["data"]["digest"], state["contract"]["project"])
            check = shown["record"]["check_id"]
            if check in data["checks"]:
                result.add((event["data"]["digest"], check))
        inherited = self.contract.pairs(data["case_pairs"], core)
        if not inherited:
            return result
        ledger = core.Ledger(state["ledger_path"])
        for digest, check in inherited:
            binding = core._latest(state, "case_binding", lambda e:
                                   e["data"]["request"]["digest"] == digest and e["data"]["request"]["check"] == check)
            if binding is None:
                raise ValueError(f"inherited case binding missing for {check}")
            request = binding["data"]["request"]
            if request["defect"] not in defects or request["before"] != start["candidate"]["sha256"]:
                raise ValueError(f"inherited case binding for {check} does not match current broken source")
            _live(state, [binding])
            if self._binding(ledger, state, request) != binding["data"]:
                raise ValueError(f"inherited case binding for {check} changed")
            result.add((digest, check))
        return result

    def prior_failures(self, state, candidate, defect):
        """Count only lineage bound to this defect and broken source."""
        seen = {}
        for event in self.core._events(state, "case_binding"):
            request = event["data"]["request"]
            if request["defect"] == defect and request["before"] == candidate:
                for failure in event["data"]["prior_failures"]:
                    seen[failure["sha256"]] = failure
        return len(seen)

    def membership_record(self, state):
        initial = [row["id"] for row in state["contract"]["tickets"]]
        event = self.core._latest(state, "batch_membership")
        if event is None:
            return {"event": None, "members": initial, "continuations": {}}
        _live(state, [event])
        data = event["data"]
        plan = self.core._latest(state, "plan")
        batch = plan["data"]["content"].get("batch") if plan else None
        if (not batch or not batch["subset_delivery"] or data["members"] not in batch["allowed_subsets"]
                or any(not set(batch["dependencies"][name]) <= set(data["members"]) for name in data["members"])):
            raise ValueError("current batch membership lacks reviewed subset authority or dependency closure")
        return {"event": {"id": event["id"], "sha256": event["sha256"]},
                "members": data["members"], "continuations": data["continuations"]}

    def membership(self, state):
        record = self.membership_record(state)
        return record["members"], record["continuations"]

    def active_acceptance(self, state):
        members, _ = self.membership(state)
        return {a for ticket in state["contract"]["tickets"] if ticket["id"] in members for a in ticket["acceptance"]}

    def required_checks(self, state, content):
        active = self.active_acceptance(state)
        removed_checks = {row["check"] for item, row in content["result_map"].items() if item not in active}
        retained = [check for check in content["required_checks"] if check not in removed_checks]
        interactions = content.get("batch", {}).get("interaction_checks", [])
        return list(dict.fromkeys(retained + interactions))

    def required_check_proof(self, state, content, check):
        proof = self.core._latest(state, "proof", lambda e: e["data"].get("check") == check
                                  and e["data"].get("phase") != "RED")
        if proof is not None and check in content.get("batch", {}).get("interaction_checks", []):
            issued = self.membership_record(_before(state, proof))
            if issued != self.membership_record(state):
                raise ValueError(f"interaction check {check} requires proof issued for the current membership")
        return proof

    def _first_observations(self, state):
        intake = set(state["contract"]["scope"])
        result = {}
        for event in self.core._events(state, "start"):
            data = event["data"]
            if "observe_manifest" not in data:
                continue
            if data["mode"] != "VERIFY" or data["write_scope"] or data["write_manifest"]:
                raise ValueError("historical observation carried a write grant")
            for row in data["observe_manifest"]:
                if row["path"] in intake:
                    continue
                previous, _ = result.setdefault(row["path"], (row, data["candidate"]))
                if previous != row:
                    raise ValueError("historical observation changed an established binding")
        return result

    def _removal_members(self, plan, body, members, previous, continuations):
        core = self.core
        self.contract.fields(body, {"plan", "previous", "members", "candidate", "continuations", "reason"},
                             "batch membership")
        batch = plan["data"]["content"].get("batch")
        remaining = self.contract.labels(body["members"], "remaining ticket", core, nonempty=True)
        if (not batch or not batch["subset_delivery"] or body["members"] not in batch["allowed_subsets"]
                or not remaining < members or body["plan"] != plan["data"]["revision"]
                or body["previous"] != previous):
            raise ValueError("batch removal lacks exact approved subset or predecessor")
        if any(not set(batch["dependencies"][name]) <= remaining for name in remaining):
            raise ValueError("remaining batch ticket depends on a removed ticket")
        self.contract.fields(body["continuations"], (members - remaining) | set(continuations),
                             "removed ticket continuations")
        for name, value in body["continuations"].items():
            core._label(value, "continuation")
            if name in continuations and value != continuations[name]:
                raise ValueError("existing continuation cannot be replaced")
        self.contract.sha256(body["candidate"], "removed ticket candidate")
        self.contract.text(body["reason"], "batch removal reason")
        return remaining

    def _removal_baselines(self, state, plan, removed):
        contract = state["contract"]
        initial = state["initial_source"]
        self.contract.validate_snapshot(initial, self.core)
        if initial["repo"] != contract["repo"] or initial["files"].keys() != set(contract["scope"]):
            raise ValueError("removed ticket baseline lacks the exact intake source")
        owners = self.contract.initial_owners(contract, plan["data"]["content"])
        for path, tickets in sorted(owners.items()):
            if removed & tickets.keys():
                if path not in initial["files"]:
                    raise ValueError(f"removed ticket baseline is missing from intake: {path}")
                yield path, (initial["files"][path], initial["modes"][path]), set(tickets)
        for path, (row, first) in sorted(self._first_observations(state).items()):
            if row["ticket"] in removed:
                self.contract.validate_snapshot(first, self.core)
                if (first["repo"] != contract["repo"] or path not in first["files"]
                        or row["baseline"] != first["files"][path]):
                    raise ValueError(f"removed ticket baseline differs from its first observation: {path}")
                yield path, (first["files"][path], first["modes"][path]), set()

    @staticmethod
    def _start_grant_owners(start, owners):
        paths = start["write_scope"]
        if "write_manifest" in start:
            explicit = {row["path"]: {row["ticket"]} for row in start["write_manifest"]}
            return {path: explicit[path] for path in paths}
        accepted = set(start["acceptance"])
        return {
            path: {ticket for ticket, items in owners.get(path, {}).items() if accepted & items}
            for path in paths
        }

    def _transition_grants(self, state, start, plan):
        """Resolve the recorded phase and its still-live owners at an observation."""
        if start is None or plan is None or not start["data"]["write_scope"]:
            return {}
        data = start["data"]
        prior = _before(state, start)
        if self.core._latest(prior, "plan") != plan or data["plan"] != plan["data"]["revision"]:
            return {}
        try:
            witnesses = self.plan_witnesses(prior)
            self.plan_witnesses(state)
            _live(state, [start, *witnesses])
            if (data["prefix"] != prior["sha256"]
                    or data["profile"] != prior["initial_profile"]
                    or data["profile"] != plan["observed_profile"]):
                return {}
            self.validate_phase_paths(prior, data)
            if data["write_scope"] != self.write_scope(prior, data):
                return {}
        except (self.core.RuntimeError, ValueError):
            return {}

        accepted = set()
        production = data["mode"] == "PRODUCTION"
        behaviors = {row["id"] for row in plan["data"]["content"]["acceptance"] if row["behavior"]}
        for item in data["acceptance"]:
            try:
                issued = self.decision_witnesses(prior, plan, [item], defer_red=not production)
                current = self.decision_witnesses(state, plan, [item], defer_red=not production)
                _live(state, [start, *witnesses, *issued, *current], [item])
                if self._decision_revisions(issued) != self._decision_revisions(current):
                    continue
                if production:
                    self._validate_production_red_support(state, prior, start, issued,
                                                          own_acceptance=item if item in behaviors else None)
            except (self.core.RuntimeError, ValueError, OSError):
                continue
            accepted.add(item)
        owners = self.contract.initial_owners(state["contract"], plan["data"]["content"])
        grants = self._start_grant_owners(data, owners)
        return {
            path: {ticket for ticket in tickets if accepted & owners.get(path, {}).get(ticket, set())}
            for path, tickets in grants.items()
        }

    def _validate_removed_chronology(self, state, candidate, removals):
        """Track only path values witnessed after their first removal obligation."""
        if not removals:
            return
        core, contract = self.core, state["contract"]
        members = {ticket["id"] for ticket in contract["tickets"]}
        baselines, original_owners, observed = {}, {}, {}
        held = {}
        active = plan = None
        mapped = {}

        def coowners(path, original):
            return members & original & mapped.get(path, {}).keys()

        def requires_baseline(path):
            return any(not coowners(path, original) for original in original_owners[path])

        def observe(snapshot, event=None):
            if not baselines:
                return
            self.contract.validate_snapshot(snapshot, core)
            if snapshot["repo"] != contract["repo"]:
                raise ValueError("removed ticket history observes a different repository")
            changed = []
            for path, baseline in baselines.items():
                if path not in snapshot["files"]:
                    raise ValueError(f"removed ticket baseline lacks a historical path observation: {path}")
                value = snapshot["files"][path], snapshot["modes"][path]
                if value == baseline:
                    held.pop(path, None)
                elif requires_baseline(path):
                    held.setdefault(path, "shared path carry lost its retained original-owner mapping")
                elif value != observed[path] and path not in held:
                    changed.append(path)
                observed[path] = value
            if changed:
                prefix = state if event is None else _before(state, event)
                grants = self._transition_grants(prefix, active, plan)
                for path in changed:
                    allowed = grants.get(path, set())
                    if any(allowed.isdisjoint(coowners(path, original)) for original in original_owners[path]):
                        held[path] = "shared path change lacks an applicable retained original-owner grant"

        for event in state["events"]:
            kind, body = event["type"], event["data"]
            if kind == "batch_membership":
                members, newly_removed = removals[event["seq"]]
                # Admission proves just these path values at the digest-only boundary.
                for path, baseline, owners in newly_removed:
                    if baselines.setdefault(path, baseline) != baseline:
                        raise ValueError(f"removed ticket history changes the first baseline: {path}")
                    original_owners.setdefault(path, []).append(owners)
                    observed[path] = baseline
                    held.pop(path, None)
                for path, baseline in baselines.items():
                    if requires_baseline(path):
                        observed[path] = baseline
                        held.pop(path, None)
            elif kind == "start":
                observe(body["candidate"], event)
                eligible = not held and all(
                    observed[path] == baseline or not requires_baseline(path)
                    for path, baseline in baselines.items()
                )
                active = event if eligible else None
            elif kind == "plan":
                observe(event["observed_source"], event)
                plan = event
                mapped = self.contract.initial_owners(contract, body["content"])
            elif kind in {"proof", "failure"}:
                observe(event["observed_source"], event)
            elif kind == "proof_attempt":
                observe(body["broken"], event)

        observe(candidate)
        if held:
            path = min(held)
            raise ValueError(f"{held[path]}: {path}")

    def _validate_removed_baselines(self, state, candidate, *, plan=None, start=None, grant=None, removal=None):
        """Apply each removal against the supplied candidate and membership prefix."""
        core = self.core
        history = core._events(state, "batch_membership")
        if not history and removal is None:
            return
        contract = state["contract"]
        self.contract.validate_snapshot(candidate, core)
        if candidate["repo"] != contract["repo"]:
            raise ValueError("removed ticket baseline candidate belongs to a different repository")
        if plan is None:
            plan = self.plan_witnesses(state)[0]
        members, continuations = self.membership(state)
        selected = set(members)
        retained = selected
        if removal is not None:
            previous = history[-1]["id"] if history else None
            retained = self._removal_members(plan, removal, selected, previous, continuations)
            if removal["candidate"] != candidate["sha256"]:
                raise ValueError("batch removal lacks the exact current source")
        current_owners = self.contract.initial_owners(contract, plan["data"]["content"])
        granted = self._start_grant_owners(start, current_owners) if start is not None else grant or {}

        def compare(path, baseline, coowners):
            if path not in candidate["files"]:
                raise ValueError(f"removed ticket baseline lacks a candidate path: {path}")
            actual = candidate["files"][path], candidate["modes"][path]
            if not coowners and actual != baseline:
                raise ValueError(f"removed ticket baseline differs in bytes, presence or Git mode: {path}")

        members = {ticket["id"] for ticket in contract["tickets"]}
        previous, continuations = None, {}
        removals = {}
        obligations = []
        for event in history:
            prefix = _before(state, event)
            original_plan = self.plan_witnesses(prefix)[0]
            body = event["data"]
            remaining = self._removal_members(original_plan, body, members, previous, continuations)
            added = list(self._removal_baselines(prefix, original_plan, members - remaining))
            removals[event["seq"]] = remaining, added
            obligations.extend(added)
            members, previous, continuations = remaining, event["id"], body["continuations"]
        if members != selected:
            raise ValueError("removed ticket history differs from the selected membership")
        for path, baseline, original in obligations:
            compare(path, baseline, selected & original & current_owners.get(path, {}).keys())
        self._validate_removed_chronology(state, candidate, removals)

        for path, baseline, original in obligations:
            eligible = retained & original & current_owners.get(path, {}).keys()
            if removal is not None:
                compare(path, baseline, eligible)
            if path in granted and granted[path].isdisjoint(eligible):
                raise ValueError(f"removed ticket baseline path cannot receive this fresh write grant: {path}")
        if removal is not None:
            for path, baseline, _ in self._removal_baselines(state, plan, members - retained):
                compare(path, baseline, ())

    def observations(self, state):
        return {name: row for name, (row, _) in self._first_observations(state).items()}

    def owned_paths(self, state):
        return set(state["contract"]["scope"]) | set(self.observations(state))

    def _observe_source(self, contract, paths):
        core = self.core
        identities = self.contract.observe_path_domain(contract, paths, core)
        candidate = core.snapshot(contract["repo"], paths, contract["instructions"])
        if self.contract.observe_path_domain(contract, paths, core) != identities:
            raise ValueError("source path or mode changed while observing its bytes")
        candidate["modes"] = {
            name: None if identity["leaf"] is None else self.contract.git_mode(identity["leaf"]["mode"])
            for name, identity in identities.items()
        }
        del candidate["sha256"]
        candidate["sha256"] = core.digest(candidate)
        self.contract.validate_snapshot(candidate, core)
        return candidate, identities

    def snapshot(self, state, additional=()):
        contract = state["contract"]
        paths = sorted(self.owned_paths(state) | set(additional))
        candidate, _ = self._observe_source(contract, paths)
        return candidate

    def observe_plan(self, state, content):
        for path in content.get("expected_files", []):
            self.contract.path_identity(state["contract"]["repo"], path, self.core)
        for row in content.get("verification_map", {}).values():
            if self.executor.executable(row["command"][0]) != row["runner"]:
                raise ValueError("mapped verification runner differs from the actual executable")

    def _manifest_rows(self, rows):
        if not isinstance(rows, list) or len(rows) > 128:
            raise ValueError("actual path manifest must be a bounded array")
        for row in rows:
            self.contract.fields(row, {"path", "ticket", "role", "baseline", "impact"}, "actual path")
        return self.core._paths([row["path"] for row in rows])

    def observe_start(self, state, mode, acceptance, request):
        contract = state["contract"]
        data = {key: request[key] for key in ("observe_manifest", "write_manifest") if key in request}
        observing = "observe_manifest" in data
        if observing:
            if mode != "VERIFY" or data.get("write_manifest", []) != []:
                raise ValueError("path observation requires source-preserving VERIFY with zero write grants")
            data["write_manifest"] = []
        rows = data.get("observe_manifest", data.get("write_manifest", []))
        names = self._manifest_rows(rows)
        additions = set(names) if observing else set()
        known = self.owned_paths(state)
        if not observing and not set(names) <= known:
            raise ValueError("additional write paths require an earlier valid observation")
        paths = sorted(known | additions)
        data["candidate"], identities = self._observe_source(contract, paths)
        if observing or "write_manifest" in data:
            data["path_identities"] = {name: identities[name] for name in names}
        self.validate_phase_paths(state, dict(data, mode=mode, acceptance=acceptance), live=True)
        return data

    def validate_phase_paths(self, state, data, *, live=False):
        core = self.core
        contract = state["contract"]
        content = core._latest(state, "plan")["data"]["content"]
        observing = "observe_manifest" in data
        rows = data.get("observe_manifest", data.get("write_manifest", []))
        mode = data["mode"]
        if observing and (mode != "VERIFY" or data.get("write_manifest") != []):
            raise ValueError("VERIFY observation cannot grant a source write")
        if mode == "VERIFY" and not observing and rows:
            raise ValueError("VERIFY cannot grant a source write")
        names = self._manifest_rows(rows)
        initial = set(contract["scope"])
        observations = self.observations(state)
        known = initial | set(observations)
        if not observing and not set(names) <= known:
            raise ValueError("additional write paths require an earlier valid observation")
        candidate = data["candidate"]
        self.contract.validate_snapshot(candidate, core)
        domain = known | (set(names) if observing else set())
        if set(candidate["files"]) != domain:
            raise ValueError("candidate does not bind the complete observed source domain")
        self.contract.validate_file_domain(domain | set(contract["instructions"]), core)
        explicit = observing or "write_manifest" in data
        identities = data.get("path_identities", {})
        self.contract.fields(identities, set(names), "explicit path identity set")
        if explicit != ("path_identities" in data):
            raise ValueError("explicit paths require server-observed physical identity")
        accepted = self.contract.labels(data["acceptance"], "start acceptance", core, nonempty=True)
        if not accepted <= self.active_acceptance(state):
            raise ValueError("path manifest exceeds active acceptance")
        tickets = {ticket["id"]: set(ticket["acceptance"]) for ticket in contract["tickets"]}
        owners = self.contract.initial_owners(contract, content)
        leaves = set()
        for row in rows:
            name, role, ticket = row["path"], row["role"], row["ticket"]
            self.contract.require_writable_name(contract, name, core)
            if (role not in ("test", "production") or not (accepted & tickets.get(ticket, set()))
                    or (not observing and role != ("test" if mode == "TEST_ONLY" else "production"))):
                raise ValueError("actual path does not match the active ticket and phase role")
            if name in initial:
                declared_role = "test" if name in contract["test_scope"] else "production"
                if role != declared_role or not accepted & owners.get(name, {}).get(ticket, set()):
                    raise ValueError("actual path conflicts with the initial mapped role or ticket ownership")
            elif name in observations:
                original = observations[name]
                if (ticket, role) != (original["ticket"], original["role"]) or (observing and row != original):
                    raise ValueError("actual path changes its established observation baseline or ownership")
            elif not any(
                rule["ticket"] == ticket and rule["role"] == role
                and (name == rule["path"] if rule["kind"] == "file"
                     else name.startswith(rule["path"] + "/"))
                for rule in contract["write_boundary"].get("surfaces", [])
            ):
                raise ValueError("new path is outside its reviewed literal write surface")
            impact = row["impact"]
            self.contract.fields(impact, {"callers", "dependencies", "checks", "technical_risk", "contract_unchanged"},
                                 "before-write impact")
            if (impact["contract_unchanged"] is not True
                    or impact["technical_risk"] != content["policy"]["technical_risk"]
                    or not self.contract.labels(impact["checks"], "impact check", core, nonempty=True) <= set(content["checks"])):
                raise ValueError("actual path changes approved impact or lacks affected checks")
            if not set(core._paths(impact["callers"])) <= known:
                raise ValueError("actual path has an unreviewed caller")
            if not set(core._paths(impact["dependencies"])) <= set(contract["source"]["dependencies"]):
                raise ValueError("actual path has an unreviewed dependency")
            baseline = row["baseline"]
            if baseline is not None:
                self.contract.sha256(baseline, "actual path baseline")
            if baseline != candidate["files"][name]:
                raise ValueError("actual path baseline differs from phase-before bytes")
            candidate_mode = candidate["modes"][name]
            if observing and name not in known and live and (baseline, candidate_mode) != self._tree_entry(
                contract["repo"], contract["source"]["base"], name,
            ):
                raise ValueError("new observation bytes or mode differ from the pinned Git base")
            identity = identities[name]
            self.contract.validate_path_record(name, identity, baseline is not None)
            if identity["leaf"] is not None:
                if self.contract.git_mode(identity["leaf"]["mode"]) != candidate_mode:
                    raise ValueError("physical path mode differs from the before candidate")
                leaf = (identity["leaf"]["device"], identity["leaf"]["inode"])
                if leaf in leaves:
                    raise ValueError("explicit paths share a physical file identity")
                leaves.add(leaf)

    def _tree_entry(self, repo, commit, path):
        core = self.core
        argv = ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "--literal-pathspecs"]
        env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
               "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": ""}
        try:
            tree = subprocess.run(argv + ["ls-tree", "-z", "--full-tree", commit, "--", path], cwd=repo,
                                  env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False)
            if tree.returncode:
                raise ValueError("named Git tree cannot be observed")
            if not tree.stdout:
                return None, None
            header, separator, name = tree.stdout.partition(b"\t")
            match = re.fullmatch(rb"(100(?:644|755)) blob ([a-f0-9]{40}|[a-f0-9]{64})", header)
            if not separator or name != path.encode("utf-8") + b"\0" or match is None:
                raise ValueError("named Git path is not an exact regular blob")
            blob = subprocess.run(argv + ["cat-file", "blob", match[2].decode("ascii")], cwd=repo,
                                  env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("named Git tree cannot be observed") from exc
        if blob.returncode or len(blob.stdout) > core.MAX_FILE_BYTES:
            raise ValueError("named Git blob cannot be observed within source bounds")
        return core.hashlib.sha256(blob.stdout).hexdigest(), match[1].decode("ascii")

    def validate_predecessor(self, state):
        core = self.core
        contract = state["contract"]
        pin = contract["source"].get("predecessor")
        if pin is None:
            return
        core.verify_reference(pin["acceptance"])
        ledger = core.Ledger(state["ledger_path"])
        prior = ledger.show(pin["run"])
        if prior["sha256"] != pin["prefix"] or prior["contract"]["project"] != contract["project"]:
            raise ValueError("accepted predecessor ledger prefix changed or belongs to a different project")
        receipt = core._read_json(pin["acceptance"]["path"])
        current = ledger.check(pin["run"])
        if (receipt != current or current.get("state") != "PASS" or current.get("lifecycle") != "ACCEPTED_LOCAL"
                or current["candidate"]["sha256"] != pin["candidate"]):
            raise ValueError("predecessor acceptance is no longer current")
        candidate = current["candidate"]
        self.contract.validate_snapshot(candidate, core)
        if any(self._tree_entry(contract["repo"], pin["commit"], name) != (checksum, candidate["modes"][name])
               for name, checksum in (candidate["files"] | candidate["instructions"]).items()):
            raise ValueError("accepted predecessor commit differs from its reviewed bytes or modes")

    def required_lane(self, state):
        plan = self.core._latest(state, "plan")
        if (plan and plan["data"]["content"]["policy"]["execution_lane"] == "Direct"
                and any(event["data"].get("outcome") == "FAIL" for event in self.core._events(state, "repair"))):
            return "Standard"
        return None

    def validate_event(self, state, event):
        core = self.core
        kind, body = event["type"], event["data"]
        if kind == "audit" and body.get("kind") == "architecture":
            plan = core._latest(state, "plan")
            if plan is None or "architecture" not in plan["data"]["content"]["policy"]["specialists"]:
                raise ValueError("architecture audit requires the selected specialist obligation")
        elif kind == "failure_classification":
            self.contract.fields(body, {"attempt", "defect", "kind", "reason"}, "failure classification")
            core._label(body["defect"], "stable failure defect")
            self.contract.text(body["reason"], "failure classification")
            attempt = _event(state, body["attempt"], "proof_attempt")
            if any(e["data"]["attempt"] == attempt["id"] for e in core._events(state, kind)):
                raise ValueError("failure attempt already has immutable classification")
            if body["kind"] not in ("MATERIAL", "ROUTINE_SETUP"):
                raise ValueError("unknown failure classification")
            if body["kind"] == "ROUTINE_SETUP":
                receipt = self._native_object(state, attempt["data"]["request"]["output"])
                stdout = self._native_stream(state, receipt["stdout"])
                stderr = self._native_stream(state, receipt["stderr"])
                if self._assertion_failure(stdout, stderr) or not re.search(
                    rb"^(?:ImportError|ModuleNotFoundError|SyntaxError|IndentationError):", stderr, re.MULTILINE
                ):
                    raise ValueError("actual command evidence does not establish an isolated routine setup failure")
        elif kind == "handoff":
            self.contract.fields(body, {"prior_plan", "target_lane", "candidate", "defect", "prior_actor",
                                        "next_action", "reason"}, "lane handoff")
            plan = self.plan_witnesses(state)[0]
            owner = self.routing(state, plan)
            self.contract.text(body["reason"], "handoff reason")
            if (body["prior_plan"] != plan["data"]["revision"] or self.required_lane(state) is None
                    or body["target_lane"] not in ("Standard", "Critical")
                    or body["candidate"] != self.snapshot(state)["sha256"] or body["prior_actor"] != owner["session"]
                    or body["next_action"] != "PLAN_REVIEW" or not any(
                        e["data"].get("outcome") == "FAIL" and e["data"].get("defect") == body["defect"]
                        for e in core._events(state, "repair")
                    )):
                raise ValueError("receiving lane handoff lacks its exact actual failed repair and authority")
        elif kind == "batch_membership":
            plan = self.plan_witnesses(state)[0]
            self._validate_removed_baselines(state, self.snapshot(state), plan=plan, removal=body)

    def failure_obligations(self, state):
        core = self.core
        classified = {e["data"]["attempt"]: e["data"] for e in core._events(state, "failure_classification")}
        links = {e["data"]["intent"] for e in core._events(state, "case_link")}
        captured = [e["data"]["request"] for e in core._events(state, "capture_intent") if e["id"] in links]
        groups, required = {}, {}
        for attempt in core._events(state, "proof_attempt"):
            selected = classified.get(attempt["id"])
            defect = selected["defect"] if selected else attempt["id"]
            output = attempt["data"]["request"]["output"]
            row = groups.setdefault(defect, {"state": "ITERATION", "attempts": [], "first_output": output})
            row["attempts"].append(attempt["id"])
            if selected is None or selected["kind"] == "MATERIAL":
                required.setdefault(defect, []).append(output)
            if len(row["attempts"]) > 1:
                refs = required.setdefault(defect, [])
                if row["first_output"] not in refs:
                    refs.append(row["first_output"])
        for defect, refs in required.items():
            observed = [item["failure"]["output"] for item in captured if item["defect"] == defect]
            groups[defect]["state"] = "CAPTURED" if all(ref in observed for ref in refs) else "CANONICAL_REQUIRED"
        return groups

    def audit_errors(self, state, audit, candidate):
        core = self.core
        data = audit["data"]
        architecture = data["kind"] == "architecture"
        try:
            _live(state, [audit])
            inspected = set(core._paths(data.get("inspected", [])))
            owned = self.owned_paths(state)
            if (not isinstance(data.get("executed"), list) or not data["executed"]
                    or not inspected & owned):
                raise ValueError("independent audit must distinguish actual executions and inspected paths")
            if architecture and data.get("specialists") != ["architecture"]:
                raise ValueError("architecture audit lacks its exact specialist evidence")
            if not inspected <= owned | set(state["contract"]["instructions"]):
                raise ValueError("independent audit inspected paths exceed the observed source")
            plan = core._latest(state, "plan")["data"]["content"]
            for row in data["executed"]:
                self.contract.fields(row, {"check", "argv", "exit", "candidate", "stdout", "stderr"},
                                     "independent executed result")
                if (row["check"] not in plan["checks"] or row["candidate"] != candidate or type(row["exit"]) is not int
                        or row["exit"] != 0 or not isinstance(row["argv"], list) or not row["argv"]
                        or any(not isinstance(arg, str) or not arg for arg in row["argv"])):
                    raise ValueError("independent executed check is unbound or failed")
                core.verify_reference(row["stdout"])
                core.verify_reference(row["stderr"])
            if not isinstance(data.get("specialists", []), list) or any(
                role != data["kind"] for role in data.get("specialists", [])
            ):
                raise ValueError("specialist coverage is outside the auditor's observed work")
            return []
        except (core.RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
            return [str(exc)]

    def final_review_errors(self, state, review):
        try:
            _live(state, [review])
        except ValueError:
            return ["selected final review was withdrawn or superseded"]
        return []

    def _delivered(self, state, candidate, membership):
        core = self.core
        result = core._latest(state, "delivery_result")
        if result is None or result["data"].get("outcome") != "INTENDED":
            return False
        data = result["data"]
        intent = core._latest(state, "delivery_intent", lambda e: e["id"] == data.get("operation"))
        dispatch = core._latest(state, "delivery_dispatch", lambda e: e["id"] == data.get("dispatch"))
        if intent is None or dispatch is None or not intent["seq"] < dispatch["seq"] < result["seq"]:
            return False
        local = intent["data"]["local"]
        plan = core._latest(state, "plan")
        return (dispatch["data"].get("operation") == intent["id"]
                and dispatch["data"].get("intent_sha256") == intent["sha256"]
                and data.get("candidate") == dispatch["data"].get("candidate") == intent["data"].get("candidate")
                == local.get("candidate") == candidate
                and local.get("plan") == plan["data"]["revision"]
                and local.get("membership") == membership)

    def check_fields(self, state, policy, candidate, errors, handoff):
        core = self.core
        membership = self.membership_record(state)
        members, continuations = membership["members"], membership["continuations"]
        route = core._latest(state, "observation", lambda e: e["data"].get("kind") == "ROUTING")
        roles = {role: actor.get("session") for role, actor in (route["data"].items() if route else ())
                 if role in ("owner", "lead", "probe") and isinstance(actor, dict)}
        roles["coordinator"] = state["contract"].get("coordinator")
        open_findings = {error.removeprefix("unresolved actionable finding ") for error in errors
                         if error.startswith("unresolved actionable finding ")}
        owners = {}
        for event in state["events"]:
            for finding in event["data"].get("findings", []) if event["type"] in core.REVIEW_TYPES else ():
                key = event["id"] + "/" + finding["id"]
                if key in open_findings:
                    role = "astra" if core._historical(state) and finding.get("severity") == "High" else policy["owner"]
                    owners[key] = self.contract.MODELS.get(role)
        if not errors and not handoff:
            lifecycle = "ACCEPTED_LOCAL"
            if self._delivered(state, candidate, membership):
                lifecycle = "DELIVERED"
        elif not errors:
            lifecycle = "VERIFYING"
        elif self.required_lane(state) or open_findings:
            lifecycle = "REWORK"
        else:
            lifecycle = "HOLD"
        return {"lifecycle": lifecycle, "parent_complete": not continuations and not errors and not handoff,
                "active_tickets": members, "continuations": continuations,
                "lane": policy["lane"], "roles": roles, "required_lane": self.required_lane(state),
                "repair_owners": owners, "failure_obligations": self.failure_obligations(state)}
