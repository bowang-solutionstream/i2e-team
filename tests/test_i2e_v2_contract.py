"""Public policy and contract regressions for the staged v2 lanes."""
from __future__ import annotations

import json
import shlex
import subprocess
import tomllib
import unittest
from pathlib import Path

import test_four_behavior_repair as a1
import test_i2e_team as legacy


SOL_SETTINGS = {"model": a1.SOL_MODEL, "effort": "max", "tier": "Fast"}
ASTRA_SETTINGS = {"model": a1.ASTRA_MODEL, "effort": "max", "tier": "Standard"}


def assurance(*, ticket_count=1, **overrides):
    return dict({
        "ticket_count": ticket_count,
        "clear_authority": True,
        "bounded_scope": True,
        "observable_acceptance": True,
        "adequate_regression": True,
        "interaction_coverage": True,
        "checks": {"baseline": {"state": "PASS", "reason": "Relevant native baseline ran."}},
    }, **overrides)


def policy_request(lane="Standard", *, risk="Medium", priority="normal", **overrides):
    return dict({
        "schema": a1.POLICY_SCHEMA,
        "queue_priority": priority,
        "technical_risk": risk,
        "execution_lane": lane,
        "significant_architecture": False,
        "triggers": legacy.ordinary_policy()["triggers"],
        "direct_eligible": lane == "Direct",
        "reproducible_acceptance": True,
        "specialists": [],
        "tier_policy": "require_match",
    }, **overrides)


class PolicyV2Tests(unittest.TestCase):
    def test_separate_root_commands_pin_both_roles(self):
        guide = Path(__file__).resolve().parents[1] / "skills/i2e-astra-sol/references/policy.md"
        commands = [shlex.split(line) for line in guide.read_text().splitlines() if line.startswith("codex exec ")]
        seen = {}
        for command in commands:
            model = command[command.index("--model") + 1]
            options = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
            config = tomllib.loads("\n".join(options))
            self.assertEqual("read-only", command[command.index("--sandbox") + 1])
            self.assertEqual("-", command[-1])
            seen[model] = (config["model_reasoning_effort"], config["service_tier"])
        self.assertEqual({"gpt-6.2-sol": ("max", "priority"), "gpt-6.2-astra": ("max", "default")}, seen)

    def test_discovered_role_presets_match_selected_model_effort_and_speed(self):
        repo = Path(__file__).resolve().parents[1]
        config = repo / ".codex/config.toml"
        roles = tomllib.loads(config.read_text())["agents"]
        for role, settings in (("sol", SOL_SETTINGS), ("astra", ASTRA_SETTINGS)):
            name = "i2e_team_" + role
            with self.subTest(role=role):
                path = (config.parent / roles[name]["config_file"]).resolve(strict=True)
                self.assertEqual(repo / "skills/i2e-astra-sol/agents" / (name + ".toml"), path)
                preset = tomllib.loads(path.read_text())
                self.assertEqual((name, settings["model"], settings["effort"],
                                  {"Fast": "priority", "Standard": "default"}[settings["tier"]]),
                                 (preset["name"], preset["model"], preset["model_reasoning_effort"],
                                  preset["service_tier"]))

    def policy(self, request):
        return a1.runtime.evaluate_policy(request)

    def test_public_policy_admits_eligible_direct(self):
        request = policy_request("Direct", risk="Low", priority="P2", assurance=assurance())
        command = [a1.PYTHON, "-B", str(legacy.SCRIPT), "policy", "--input", "-"]
        cli = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True, timeout=15, check=False)
        result = json.loads(cli.stdout)
        self.assertEqual(0, cli.returncode, f"Eligible Direct should pass the existing policy CLI: {result}")
        self.assertEqual(("PASS", "Direct", None, "sol", None, ["combined"]),
                         tuple(result[key] for key in ("state", "lane", "lead", "owner", "final_review", "audits")))
        self.assertEqual({"owner": SOL_SETTINGS, "probe": SOL_SETTINGS}, result["requested_settings"])

    def test_queue_urgency_does_not_select_models(self):
        outputs = []
        for priority in ("urgent", "normal", "deferred", "P0", "P2"):
            request = policy_request("Direct", risk="Low", priority=priority, assurance=assurance())
            result = self.policy(request)
            self.assertEqual("PASS", result["state"], result)
            outputs.append(tuple(result[k] for k in ("lane", "lead", "owner", "final_review")))
        self.assertEqual([("Direct", None, "sol", None)] * len(outputs), outputs)

    def test_direct_refuses_risk_batch_unexplained_checks_specialists_and_unknowns(self):
        choices = [
            {"technical_risk": "Medium"}, {"technical_risk": None},
            {"direct_eligible": False}, {"reproducible_acceptance": False},
            {"assurance": assurance(ticket_count=2)},
            {"assurance": assurance(clear_authority=False)},
            {"assurance": assurance(bounded_scope=False)},
            {"assurance": assurance(adequate_regression=False)},
            {"assurance": assurance(checks={"baseline": {"state": "NOT_RUN", "reason": ""}})},
            {"assurance": assurance(checks={"baseline": {"state": "FAIL", "reason": "Failure remains open."}})},
            {"specialists": ["security"]},
        ]
        for changes in choices:
            with self.subTest(changes=changes):
                request = dict(policy_request("Direct", risk="Low", assurance=assurance()), **changes)
                result = self.policy(request)
                self.assertEqual("BLOCK", result["state"], result)
                self.assertIsNone(result["owner"])

    def test_standard_reduction_requires_complete_combined_candidate_assessment(self):
        for interaction, expected in (
            (True, ["combined"]), (False, ["code", "security", "tests"]), (None, ["code", "security", "tests"]),
        ):
            with self.subTest(interaction=interaction):
                result = self.policy(policy_request(
                    risk="Low", direct_eligible=True, assurance=assurance(ticket_count=2, interaction_coverage=interaction),
                ))
                self.assertEqual(("PASS", "sol", "sol", expected),
                                 (result["state"], result["lead"], result["owner"], result["audits"]), result)
        default = self.policy(policy_request(priority="P2"))
        self.assertEqual(("PASS", ["code", "security", "tests"]), (default["state"], default["audits"]))
        self.assertEqual({"lead": SOL_SETTINGS, "owner": SOL_SETTINGS, "probe": SOL_SETTINGS},
                         default["requested_settings"])

    def test_high_critical_and_significant_architecture_use_four_rounds(self):
        for risk, architecture in (("High", False), ("Critical", False), ("Medium", True)):
            with self.subTest(risk=risk, architecture=architecture):
                request = policy_request("Critical", risk=risk, significant_architecture=architecture,
                                         specialists=["security"])
                result = self.policy(request)
                self.assertEqual(("PASS", "astra", "sol", "sol", ["combined"]),
                                 tuple(result[k] for k in ("state", "lead", "owner", "final_review", "audits")), result)
                self.assertEqual({"lead": ASTRA_SETTINGS, "owner": SOL_SETTINGS, "probe": SOL_SETTINGS, "verifier": SOL_SETTINGS},
                                 result["requested_settings"])
                self.assertEqual(["probe", "plan", "implement", "verify"], [r["role"] for r in result["rounds"]])
                self.assertEqual("BLOCK", self.policy(dict(request, execution_lane="Standard"))["state"])

    def test_all_final_triggers_are_assessed_even_when_another_is_true(self):
        for trigger in legacy.ordinary_policy()["triggers"]:
            request = policy_request()
            request["triggers"][trigger] = True
            self.assertEqual("astra", self.policy(request)["final_review"], trigger)
            unknown = dict(request["triggers"], **{trigger: None})
            self.assertEqual("BLOCK", self.policy(dict(request, triggers=unknown))["state"], trigger)
            direct = policy_request("Direct", risk="Low", assurance=assurance(), triggers=request["triggers"])
            self.assertEqual("BLOCK", self.policy(direct)["state"], trigger)

    def test_routine_work_uses_sol_and_keeps_path_and_lane_limits(self):
        selected = {"model": a1.SOL_MODEL, "paths": ["reader.py"], "bounded": True}
        request = policy_request("Direct", risk="Low", assurance=assurance(), routine_worker=selected)
        for allowed in (request, policy_request("Standard", routine_worker=selected)):
            with self.subTest(lane=allowed["execution_lane"]):
                result = self.policy(allowed)
                self.assertEqual(("PASS", "sol"), (result["state"], result["owner"]), result)
                self.assertEqual(SOL_SETTINGS, result["requested_settings"]["owner"])
        critical = policy_request("Critical", risk="High", routine_worker=selected)
        self.assertEqual("BLOCK", self.policy(critical)["state"])
        for changed in (dict(selected, bounded=False), dict(selected, paths=[]),
                        dict(selected, paths=["*.py"]), dict(selected, model="gpt-6-luna"),
                        dict(selected, model="gpt-6.1-terra"), dict(selected, model="gpt-6.1-sol")):
            self.assertEqual("BLOCK", self.policy(dict(request, routine_worker=changed))["state"])
