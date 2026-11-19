#!/usr/bin/env python3
"""Create and check the shared i2e property and rule library (standard library only)."""

from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# init and check must not create an import cache in the source package.
sys.dont_write_bytecode = True

from validate import REPO_ROOT, ValidationError

TEMPLATE = REPO_ROOT / "library-template"
FOLDERS = {"properties": "property", "rules": "rule"}
PREFIXES = {"property": "prop-", "rule": "rule-"}
TYPES = {
    "property": {"round-trip", "invariant", "idempotency", "equivalence", "other"},
    "rule": {"review", "blind-spot", "test", "hook", "instruction"},
}
STATUSES = {"candidate", "adopted", "retired"}
FIELDS = {"id", "kind", "type", "status", "tags", "applies-to", "seen-in", "updated"}
HEADINGS = {"property": ("## Statement",), "rule": ("## Trigger", "## Check", "## Why it flags")}
FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
# Flat `key: value` lines; a value is kept as written, so `#` in a reference survives.
FIELD_LINE = re.compile(r"([a-z][a-z-]*):(?:[ \t]+(.*?))?[ \t]*")
LISTS = ("tags", "applies-to", "seen-in")
# Text that looks like a pasted secret; entries must stay safe to push.
SECRETS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+"),
)


def default_path() -> Path:
    """The library location every i2e skill uses: I2E_LIBRARY, else the XDG data folder."""
    if os.environ.get("I2E_LIBRARY"):
        return Path(os.environ["I2E_LIBRARY"]).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home).expanduser() / "i2e" / "library"


def git_init(path: Path) -> None:
    """Start a repository whose first branch is main, also with Git older than 2.28."""
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], text=True, capture_output=True)

    if git("init", "--quiet", "--initial-branch", "main", str(path)).returncode == 0:
        return
    for args in (("init", "--quiet", str(path)), ("-C", str(path), "symbolic-ref", "HEAD", "refs/heads/main")):
        result = git(*args)
        if result.returncode != 0:
            raise ValidationError(f"git {' '.join(args)} failed: {result.stderr.strip()}")


def init(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise ValidationError(f"Refusing to create the library in an existing, non-empty location: {path}")
    # If a step fails, remove only what this call created.
    created = None if path.exists() else path
    while created is not None and not created.parent.exists():
        created = created.parent
    path.mkdir(parents=True, exist_ok=True)
    has_git = bool(shutil.which("git"))
    try:
        if has_git:
            git_init(path)
        shutil.copytree(TEMPLATE, path, dirs_exist_ok=True)
    except BaseException:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        else:
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        raise
    note = "" if has_git else " Git was not found; run git init there before committing."
    print(f"Created the library at {path}; nothing is committed or pushed.{note}")


def front_matter(block: str) -> tuple[dict[str, str], list[str]]:
    """Read flat `key: value` front matter exactly as written."""
    values: dict[str, str] = {}
    problems = []
    for line in block.splitlines():
        if not line.strip():
            continue
        match = FIELD_LINE.fullmatch(line)
        if not match:
            problems.append(f"front matter lines must be `field: value`, not {line.strip()!r}")
        elif match[1] in values:
            problems.append(f"front matter repeats the field {match[1]!r}")
        else:
            values[match[1]] = match[2] or ""
    return values, problems


def same_change(reference: str) -> str:
    """Compare references without case or spacing differences."""
    return " ".join(reference.casefold().split())


def entry_problems(entry: Path, kind: str) -> tuple[dict[str, str], list[str]]:
    """Return the entry's front matter and every problem found in it."""
    text = entry.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, ["missing front matter"]
    values, problems = front_matter(match[1])
    if problems:
        return values, problems
    if set(values) != FIELDS:
        return values, ["front matter must have exactly: " + ", ".join(sorted(FIELDS))]
    entry_id = values["id"]
    if entry_id != entry.stem:
        problems.append(f"id {entry_id!r} must match the file name {entry.stem!r}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry_id) or not entry_id.startswith(PREFIXES[kind]):
        problems.append(f"id must be lowercase words joined by hyphens, starting {PREFIXES[kind]!r}")
    if values["kind"] != kind:
        problems.append(f"kind must be {kind!r} in this folder")
    if values["type"] not in TYPES[kind]:
        problems.append(f"type must be one of: {', '.join(sorted(TYPES[kind]))}")
    if values["status"] not in STATUSES:
        problems.append(f"status must be one of: {', '.join(sorted(STATUSES))}")
    lists = {key: [item.strip() for item in values[key].split(",")] for key in LISTS}
    for key, items in lists.items():
        if not all(items):
            problems.append(f"{key} must be a comma-separated list without empty items")
        counts = Counter(same_change(item) for item in items if item)
        repeated = sorted(item for item, count in counts.items() if count > 1)
        if repeated:
            problems.append(f"{key} lists the same item more than once: {', '.join(repeated)}")
    distinct_changes = {same_change(item) for item in lists["seen-in"] if item}
    if kind == "rule" and values["status"] == "adopted" and len(distinct_changes) < 2:
        problems.append("an adopted rule needs at least two separate changes in seen-in")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["updated"]):
        problems.append("updated must be a date written as YYYY-MM-DD")
    body = text[match.end():]
    for heading in HEADINGS[kind]:
        if not re.search(rf"(?m)^{re.escape(heading)}\s*$", body):
            problems.append(f"missing the {heading!r} section")
    if any(pattern.search(text) for pattern in SECRETS):
        problems.append("contains text that looks like a secret")
    return values, problems


def check(path: Path) -> int:
    if not path.is_dir():
        raise ValidationError(f"No library at {path}")
    owners: dict[str, Path] = {}
    failures = []
    counts: dict[tuple[str, str], int] = {}
    for folder, kind in FOLDERS.items():
        directory = path / folder
        if not directory.is_dir():
            raise ValidationError(f"Missing library folder: {directory}")
        for entry in sorted(directory.glob("*.md")):
            if entry.name == "README.md":
                continue
            values, problems = entry_problems(entry, kind)
            entry_id = values.get("id")
            if entry_id and entry_id in owners:
                problems.append(f"duplicate id, also used by {owners[entry_id].relative_to(path)}")
            if entry_id:
                owners.setdefault(entry_id, entry)
            failures += [f"{entry.relative_to(path)}: {problem}" for problem in problems]
            if not problems:
                counts[(kind, values["status"])] = counts.get((kind, values["status"]), 0) + 1
    for failure in failures:
        print(failure, file=sys.stderr)
    summary = ", ".join(f"{count} {status} {kind}{'s' if count != 1 else ''}"
                        for (kind, status), count in sorted(counts.items())) or "no entries"
    print(f"Checked {path}: {summary}; {len(failures)} problem{'s' if len(failures) != 1 else ''}.")
    return int(bool(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "check"))
    parser.add_argument("--path", type=Path, default=None,
                        help="Library folder (default: $I2E_LIBRARY, else $XDG_DATA_HOME/i2e/library)")
    args = parser.parse_args()
    path = Path(os.path.abspath((args.path or default_path()).expanduser()))
    try:
        if args.command == "init":
            init(path)
            return 0
        return check(path)
    except (ValidationError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"Library {args.command} failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
