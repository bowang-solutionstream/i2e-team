#!/usr/bin/env python3
"""Portable, bounded checks of the disposable labels.normalize public API.

This is a feature verifier, not an I2E controller or a security sandbox.
Exit codes: 0 PASS, 1 behavioral FAIL, 2 harness/catalog ERROR, 3 NOT_APPLICABLE.
The caller must explicitly select a disposable repository with --repo.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCHEMA = "i2e-label-verification/v1"
CATALOG_SCHEMA = "i2e-label-catalog/v1"
FEATURE = "labels.normalize"
CHECKS = {
    "public_api_e2e": "labels.normalize.public_api_e2e.v1",
    "whitespace_content": "labels.normalize.whitespace_content.v1",
    "shape_input_idempotence": "labels.normalize.shape_input_idempotence.v1",
}
MAX_CATALOG_BYTES = 1_048_576
CHILD_TIMEOUT_SECONDS = 20

# Keep target imports and execution out of the trusted verifier process. -I and
# -S exclude inherited Python paths and site packages; only this repo is added.
CHILD = r'''
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys

def value_snapshot(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return {"unserializable_type": type(value).__name__}

def call(fn, values):
    try:
        result = fn(values)
        return result, {"result": value_snapshot(result),
                        "result_type": type(result).__name__,
                        "input_after": value_snapshot(values), "error": None}
    except Exception as exc:
        return None, {"result": None, "result_type": None,
                      "input_after": value_snapshot(values),
                      "error": {"type": type(exc).__name__, "message": str(exc)[:300]}}

request = json.load(sys.stdin)
repo = Path(sys.argv[1])
path = repo / "reader.py"
try:
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != request["target_sha256"]:
        raise ValueError("reader.py changed before child execution")
    sys.path.insert(0, str(repo))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        reader = importlib.import_module("reader")
        if Path(reader.__file__).resolve() != path.resolve():
            raise ValueError("imported reader did not come from the selected repo")
        fn = reader.read
        if not callable(fn):
            raise TypeError("reader.read is not callable")
        observations = []
        for original in request["inputs"]:
            result, first = call(fn, original.copy())
            if type(result) is list and all(type(item) is str for item in result):
                _, repeated = call(fn, result.copy())
            else:
                repeated = None
            observations.append({"first": first, "repeated": repeated})
    response = {"observations": observations, "error": None}
except Exception as exc:
    response = {"observations": [],
                "error": {"type": type(exc).__name__, "message": str(exc)[:300]}}
print(json.dumps(response, ensure_ascii=True, allow_nan=False, sort_keys=True))
'''


class HarnessError(Exception):
    """Invalid or unavailable local verification evidence."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise HarnessError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HarnessError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(data):
    def reject_constant(value):
        raise HarnessError(f"invalid JSON constant: {value}")
    try:
        return json.loads(data, object_pairs_hook=strict_object,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HarnessError(f"invalid JSON: {exc}") from exc


def require(condition, message):
    if not condition:
        raise HarnessError(message)


def text(value):
    return type(value) is str and bool(value.strip())


def string_list(value):
    return type(value) is list and all(type(item) is str for item in value)


def validate_catalog(catalog):
    require(type(catalog) is dict, "catalog must be an object")
    require(catalog.get("schema") == CATALOG_SCHEMA, "unsupported catalog schema")
    features = catalog.get("features")
    require(type(features) is dict and bool(features), "catalog.features must be nonempty")
    seen = set()
    for feature_id, feature in features.items():
        require(text(feature_id) and type(feature) is dict, "invalid catalog feature")
        acceptance = feature.get("acceptance")
        require(string_list(acceptance) and bool(acceptance)
                and all(text(item) for item in acceptance)
                and len(set(acceptance)) == len(acceptance), "invalid feature acceptance IDs")
        require(text(feature.get("entrypoint")), "missing feature entrypoint")
        checks = feature.get("checks")
        require(type(checks) is list and bool(checks), "feature checks must be nonempty")
        for check in checks:
            require(type(check) is dict, "check must be an object")
            check_id = check.get("id")
            require(text(check_id) and check_id not in seen, "missing or duplicate check ID")
            seen.add(check_id)
            for field in ("kind", "claim", "trigger", "input_domain", "oracle", "owner"):
                require(text(check.get(field)), f"check {check_id}: missing {field}")
        if feature_id == FEATURE:
            require(acceptance == ["A1"] and feature["entrypoint"] == "reader.read",
                    "labels.normalize must select A1 and reader.read")
            require(len(checks) == len(CHECKS)
                    and {check["kind"]: check["id"] for check in checks} == CHECKS,
                    "labels.normalize must select the three supported baseline checks")
    rules = catalog.get("rules")
    require(type(rules) is list, "catalog.rules must be a list")
    for rule in rules:
        require(type(rule) is dict, "rule must be an object")
        rule_id = rule.get("id")
        require(text(rule_id) and rule_id not in seen, "missing or duplicate rule ID")
        seen.add(rule_id)
        require(text(rule.get("feature")) and rule["feature"] in features,
                f"rule {rule_id}: unknown feature")
        require(rule.get("status") in ("observe", "pilot_enforced"),
                f"rule {rule_id}: invalid status")
        case_digest = rule.get("case_digest")
        require(type(case_digest) is str and len(case_digest) == 64
                and all(char in "0123456789abcdef" for char in case_digest),
                f"rule {rule_id}: case_digest must be 64 lowercase SHA256 hex characters")
        require(text(rule.get("claim")), f"rule {rule_id}: missing claim")
        examples = rule.get("examples")
        require(type(examples) is list and bool(examples),
                f"rule {rule_id}: examples must be nonempty")
        for example in examples:
            require(type(example) is dict and string_list(example.get("input"))
                    and string_list(example.get("expected")),
                    f"rule {rule_id}: each example needs input and expected string lists")


def generated_cases():
    # The expected value comes from the known tokens, never from normalizing raw.
    unique = {(): []}
    gaps = (" ", "  ", "\t", "\u00a0", "\u2003")
    edges = ("", "  ", "\u2003")
    for count in range(4):
        tokens = ("a", "B", "猫")[:count]
        for separators in itertools.product(gaps, repeat=max(count - 1, 0)):
            raw = "".join(token + (separators[i] if i < len(separators) else "")
                          for i, token in enumerate(tokens))
            for left, right in itertools.product(edges, repeat=2):
                source = left + raw + right
                normalized = " ".join(tokens)
                values = (source, "", source)
                expected = [normalized, "", normalized]
                require(values not in unique or unique[values] == expected,
                        "generator has conflicting expected values")
                unique[values] = expected
    require(len(unique) == 287, "generator did not produce 287 distinct inputs")
    return [(list(values), expected) for values, expected in unique.items()]


def user_scenario():
    return [(["  urgent\t \nreview  ", "", "\u2003", "猫\u00a0 \tB",
              "  repeat ", "  repeat ", "already clean"],
             ["urgent review", "", "", "猫 B", "repeat", "repeat", "already clean"])]


def order_cases():
    tokens = ((" green  leaf ", "green leaf"), ("blue", "blue"), ("\t猫", "猫"))
    cases = []
    for first, second, third in itertools.permutations(tokens):
        labels = (first, second, first, third)
        cases.append(([raw for raw, _ in labels], [expected for _, expected in labels]))
    return cases


def observe(repo, target_hash, inputs):
    request = json.dumps({"target_sha256": target_hash, "inputs": inputs}, ensure_ascii=True)
    try:
        # -B alone prevents writes but still permits stale pyc reads. A new,
        # unused prefix prevents both reading repo caches and writing new ones.
        with tempfile.TemporaryDirectory(prefix="i2e-label-pycache-") as scratch:
            completed = subprocess.run(
                [sys.executable, "-IBS", "-X", f"pycache_prefix={scratch}/unused",
                 "-c", CHILD, str(repo)], cwd=repo,
                env={"PATH": os.defpath}, input=request, text=True, encoding="utf-8",
                capture_output=True, timeout=CHILD_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessError(f"child execution unavailable: {type(exc).__name__}") from exc
    require(completed.returncode == 0,
            f"child exited {completed.returncode}: {completed.stderr[:300]}")
    response = parse_json(completed.stdout)
    require(type(response) is dict, "child response must be an object")
    require(response.get("error") is None, f"target could not load: {response.get('error')}")
    observations = response.get("observations")
    require(type(observations) is list and len(observations) == len(inputs),
            "child observation count does not match requests")
    require(sha256((repo / "reader.py").read_bytes()) == target_hash,
            "reader.py changed during verification")
    return observations


def content_reasons(observation, expected):
    first = observation["first"]
    if first["error"] is not None:
        return ["reader.read raised on valid input"]
    reasons = []
    if first["result_type"] != "list" or not string_list(first["result"]):
        reasons.append("result must be a list of strings")
    if first["result"] != expected:
        reasons.append("result differs from exact expected values")
    return reasons


def shape_reasons(observation, values, expected):
    first = observation["first"]
    reasons = []
    if first["input_after"] != values:
        reasons.append("input was mutated")
    if first["error"] is not None:
        reasons.append("reader.read raised on valid input")
    elif first["result_type"] != "list" or not string_list(first["result"]):
        reasons.append("result must be a list of strings")
    elif len(first["result"]) != len(values):
        reasons.append("list length changed")
    elif first["result"] != expected:
        reasons.append("ordered values or duplicates differ from expected")
    repeated = observation["repeated"]
    if repeated is None:
        reasons.append("repeated application unavailable for invalid result")
    elif repeated["error"] is not None:
        reasons.append("repeated application raised")
    else:
        if repeated["result_type"] != "list" or repeated["result"] != first["result"]:
            reasons.append("repeated application changed the result")
        if repeated["input_after"] != first["result"]:
            reasons.append("repeated application mutated its input")
    return reasons


def check_result(check_id, cases, observations, mode):
    failures = 0
    counterexample = None
    for (values, expected), observation in zip(cases, observations):
        reasons = []
        if mode != "shape_input_idempotence":
            reasons.extend(content_reasons(observation, expected))
        if mode in ("public_api_e2e", "shape_input_idempotence"):
            reasons.extend(shape_reasons(observation, values, expected))
        if reasons:
            failures += 1
            if counterexample is None:
                counterexample = {"input": values, "expected": expected,
                                  "observed": observation, "reasons": reasons}
    return {"id": check_id, "state": "FAIL" if failures else "PASS",
            "samples": len(cases), "failures": failures, "counterexample": counterexample}


def main(argv=None):
    report = {"schema": SCHEMA, "feature": None, "acceptance": [], "state": "ERROR",
              "checks": [], "rules": [], "errors": [],
              "provenance": {"harness_sha256": None, "catalog_sha256": None,
                             "target_source_sha256": None}}
    code = 2
    try:
        script = Path(__file__).resolve()
        report["provenance"]["harness_sha256"] = sha256(script.read_bytes())
        parser = Parser(description=__doc__)
        parser.add_argument("--repo", required=True, type=Path)
        parser.add_argument("--feature", required=True)
        parser.add_argument("--catalog", type=Path,
                            default=script.parent.parent / "references" / "label-verification.json")
        args = parser.parse_args(argv)
        report["feature"] = args.feature
        catalog_bytes = args.catalog.expanduser().read_bytes()
        report["provenance"]["catalog_sha256"] = sha256(catalog_bytes)
        require(len(catalog_bytes) <= MAX_CATALOG_BYTES, "catalog exceeds byte limit")
        catalog = parse_json(catalog_bytes)
        validate_catalog(catalog)
        if args.feature != FEATURE or args.feature not in catalog["features"]:
            report["state"] = "NOT_APPLICABLE"
            code = 3
        else:
            report["acceptance"] = catalog["features"][FEATURE]["acceptance"]
            repo = args.repo.expanduser().resolve(strict=True)
            require(repo.is_dir(), "--repo must select a disposable directory")
            reader_path = repo / "reader.py"
            require(reader_path.is_file() and not reader_path.is_symlink(),
                    "selected repo needs a regular reader.py, not a symlink")
            target_hash = sha256(reader_path.read_bytes())
            report["provenance"]["target_source_sha256"] = target_hash
            generated = generated_cases()
            groups = [(CHECKS["public_api_e2e"], user_scenario(), "public_api_e2e"),
                      (CHECKS["whitespace_content"], generated, "whitespace_content"),
                      (CHECKS["shape_input_idempotence"], generated + order_cases(), "shape_input_idempotence")]
            rules = [rule for rule in catalog["rules"] if rule["feature"] == FEATURE]
            groups.extend((rule["id"], [(example["input"], example["expected"])
                                        for example in rule["examples"]], "rule") for rule in rules)
            inputs = [values for _, cases, _ in groups for values, _ in cases]
            observations = observe(repo, target_hash, inputs)
            offset = 0
            for check_id, cases, mode in groups:
                row = check_result(check_id, cases, observations[offset:offset + len(cases)], mode)
                offset += len(cases)
                if mode == "rule":
                    rule = rules[len(report["rules"])]
                    row.update(status=rule["status"], case_digest=rule["case_digest"],
                               would_fail=row["state"] == "FAIL")
                    report["rules"].append(row)
                else:
                    report["checks"].append(row)
            failed = any(row["state"] == "FAIL" for row in report["checks"])
            failed |= any(row["would_fail"] and row["status"] == "pilot_enforced"
                          for row in report["rules"])
            report["state"] = "FAIL" if failed else "PASS"
            code = 1 if failed else 0
    except (HarnessError, OSError, UnicodeError, ValueError, RecursionError) as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    print(json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
