#!/usr/bin/env python3
"""Exercise the staged tool selection on disposable copies of the TypeScript label form."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/typescript-labels"
SPELLING_RULE = "labels.normalize.preserve_unicode_spelling.v1"


def save(path, content):
    path.write_text(json.dumps(content, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def execute(output, name, cwd, argv, expected_exit=0, env=None):
    command = list(map(str, argv))
    receipt = output / name
    receipt.mkdir()
    save(receipt / "command.json", {"cwd": str(cwd), "argv": command})
    with (receipt / "stdout").open("wb") as stdout, (receipt / "stderr").open("wb") as stderr:
        proc = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, timeout=180, env=env)
    save(receipt / "exit.json", proc.returncode)
    if proc.returncode != expected_exit:
        raise RuntimeError(f"{name} exited {proc.returncode}, expected {expected_exit}. See {receipt}")
    return receipt / "stdout"


def check_outcome(report, expected):
    checks = report["checks"]
    spelling = next(rule for rule in checks["rules"] if rule["id"] == SPELLING_RULE)
    actual = [report["state"], checks["e2e"]["state"], checks["properties"]["state"], spelling["state"]]
    if actual != expected:
        raise RuntimeError(f"Unexpected outcomes {actual}, expected {expected}")
    return {"state": actual[0], "e2e": actual[1], "properties": actual[2], "spelling_rule": actual[3]}


def replay_project_rule(output, skill, npm, shared_catalog):
    project = output / "project-rules"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("node_modules", "dist", "tool-plan.json"))
    execute(output, "project-rules-install", project, [npm, "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"])
    rule = next(row for row in shared_catalog["rules"] if row["id"] == SPELLING_RULE)
    feature = rule["feature"]
    checks = [
        {"id": "labels.form.e2e", "claim": "Submitting replaces the ordered labels.", "oracle": "Read the rendered list."},
        {"id": "labels.normalize.properties", "claim": "Only whitespace changes.", "oracle": "Rejoin the original words."},
    ]
    library = {"schema": "i2e-verification-catalog/v1",
               "features": {feature: {"entrypoint": "normalizeLabels", "checks": checks}}, "rules": [dict(rule)]}
    src = project / "src/labels.ts"
    working = src.read_text(encoding="utf-8")
    faulty = working.replace("label.trim()", 'label.replaceAll("Ａ", "A").trim()')
    if faulty == working:
        raise RuntimeError("The compatibility spelling control no longer matches the fixture")
    outcomes = {}
    for name, mode, source, expected in [
        ("observe-fault", "observe", faulty, ["PASS", "PASS", "PASS", "OBSERVED"]),
        ("enforce-fault", "enforced", faulty, ["FAIL", "PASS", "PASS", "FAIL"]),
        ("enforce-working", "enforced", working, ["PASS", "PASS", "PASS", "PASS"]),
    ]:
        src.write_text(source, encoding="utf-8")
        library["rules"][0]["status"] = mode
        catalog = project / (name + ".json")
        save(catalog, library)
        selection = execute(output, name + "-selection", project, [
            sys.executable, "-B", skill / "scripts/i2e.py", "select-tools", "--surface", "web",
            "--language", "typescript", "--feature", feature, "--catalog", catalog.name,
        ])
        raw = execute(output, name, project, [npm, "run", "--silent", "verify", "--", "--plan", selection,
                                              "--catalog", catalog], 1 if expected[0] == "FAIL" else 0)
        report = json.loads(raw.read_text())
        outcomes[name] = check_outcome(report, expected)
        failures = report["checks"]["rules"][0]["failures"]
        if bool(failures) != (source == faulty):
            raise RuntimeError(f"{name} did not record the expected spelling observation")
    return outcomes


def pilot(skill, output):
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required for the local TypeScript fixture")
    selection = execute(output, "selection", ROOT, [
        sys.executable, "-B", skill / "scripts/i2e.py", "select-tools",
        "--surface", "web", "--language", "typescript", "--feature", "labels.normalize",
    ])
    plan = json.loads(selection.read_text())
    catalog = output / "label-verification.json"
    shutil.copyfile(skill / plan["catalog"]["path"], catalog)
    verify = [npm, "run", "--silent", "verify", "--", "--plan", selection, "--catalog", catalog]
    controls = [
        ("working", None, ["PASS", "PASS", "PASS", "PASS"]),
        ("ui-order", ("src/app.ts", "results.replaceChildren(...items)", "results.replaceChildren(...items.reverse())"),
         ["FAIL", "FAIL", "PASS", "PASS"]),
        ("unicode-spelling", ("src/labels.ts", "label.trim()", 'label.normalize("NFC").trim()'),
         ["FAIL", "PASS", "FAIL", "FAIL"]),
    ]
    rows = {}
    for name, mutation, expected in controls:
        project = output / name
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("node_modules", "dist", "tool-plan.json"))
        if mutation:
            file, original, faulty = mutation
            src = project / file
            source = src.read_text(encoding="utf-8")
            if source.count(original) != 1:
                raise RuntimeError(f"The {name} control no longer matches the fixture")
            src.write_text(source.replace(original, faulty), encoding="utf-8")
        execute(output, name + "-install", project, [npm, "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"])
        raw = execute(output, name + "-check", project, verify, 1 if mutation else 0)
        report = json.loads(raw.read_text())
        rows[name] = check_outcome(report, expected)

        if name == "working":
            missing = {**os.environ, "CHROME_EXECUTABLE": str(output / "no-such-chrome")}
            unavailable = execute(output, "missing-chrome", project, verify, 2, missing)
            error = json.loads(unavailable.read_text())
            if error["state"] != "ERROR" or str(output / "no-such-chrome") not in error["error"]:
                raise RuntimeError("The missing-browser control did not report the intended setup failure")
            rows["missing-chrome"] = {"state": error["state"], "error": error["error"]}

        if name == "unicode-spelling":
            found = report["checks"]["properties"]
            replay = execute(output, "shrink-replay", project, [
                *verify, "--seed", str(found["seed"]), "--path", found["path"],
            ], 1)
            replayed = json.loads(replay.read_text())["checks"]["replay"]
            if replayed["state"] != "FAIL" or replayed["counterexample"] != found["counterexample"]:
                raise RuntimeError("Replay did not reproduce the reduced counterexample")
            rows["shrink-replay"] = {"state": "REPRODUCED", "seed": found["seed"], "path": found["path"],
                                     "counterexample": found["counterexample"]}

    return {"scope": "Local verification-tool pilot", "selection": plan, "controls": rows,
            "checkout_catalog": replay_project_rule(output, skill, npm, json.loads(catalog.read_text()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="a new directory for fixtures and receipts")
    parser.add_argument("--skill", type=Path, default=ROOT / "skills/i2e-astra-sol", help="pinned staged skill or package readback")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(EXAMPLE.resolve()):
        parser.error("choose an output directory outside the example being copied")
    output.mkdir(mode=0o700)
    summary = pilot(args.skill.resolve(strict=True), output)
    save(output / "summary.json", summary)
    print(output / "summary.json")


if __name__ == "__main__":
    main()
