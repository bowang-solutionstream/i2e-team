#!/usr/bin/env python3
"""Install the i2e skills without dependencies or network access."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import NoReturn

# --check and --dry-run must not create an import cache in the source package.
sys.dont_write_bytecode = True

from validate import REPO_ROOT, SKILLS, ValidationError, selected_skills, tree_snapshot, validate_suite


def real_directory_or_missing(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValidationError(f"Expected a real directory or missing path: {path}")


def plan_skill(destination: Path, name: str, *, update: bool, check: bool) -> tuple[list, list[Path]]:
    """Describe what installing one skill would change, without writing anything."""
    main = REPO_ROOT / "skills" / name
    # Claude Code discovers skills by directory and subagent definitions recursively.
    bundles = [(main, destination / "skills" / name),
               (main / "agents", destination / "agents" / name)]
    package_root = REPO_ROOT.resolve()
    plans = []
    conflicts = []
    for source, target in bundles:
        real_directory_or_missing(target.parent)
        resolved_target = target.resolve()
        if (resolved_target.is_relative_to(package_root / "skills")
                or package_root.is_relative_to(resolved_target)):
            raise ValidationError(f"Installation target overlaps package source: {target}")
        real_directory_or_missing(target)
        expected = tree_snapshot(source)
        current = tree_snapshot(target) if target.exists() else None
        action = "unchanged" if current == expected else "update" if current is not None else "install"
        plans.append((source, target, expected, current, action))
        if action == "update" and not update and not check:
            conflicts.append(target)
    return plans, conflicts


@dataclass
class Applied:
    """What installing one skill replaced, so that it can be put back."""
    replaced: list[tuple[Path, Path | None]] = field(default_factory=list)
    backup_run: Path | None = None
    new_backup_root: Path | None = None


def remove_empty_dirs(top: Path) -> None:
    """Remove top and the folders under it, deepest first, when they are empty."""
    if top.is_symlink() or not top.is_dir():
        return
    for folder, _, _ in os.walk(top, topdown=False):
        try:
            Path(folder).rmdir()
        except OSError:
            pass


def roll_back(results: list[Applied], error: Exception) -> NoReturn:
    """Put back everything these installations replaced, newest first, then re-raise error."""
    problems = []
    for result in reversed(results):
        for target, backup in reversed(result.replaced):
            try:
                if target.exists():
                    shutil.rmtree(target)
                if backup is not None:
                    backup.rename(target)
            except OSError as exc:
                problems.append(f"{target}: {exc}")
        for folder in (result.backup_run, result.new_backup_root):
            if folder is not None:
                remove_empty_dirs(folder)
    if problems:
        raise ValidationError(f"{error}; restoring the previous installation also failed for "
                              + "; ".join(problems)) from error
    raise error


def apply_skill(destination: Path, name: str, plans: list) -> Applied:
    """Replace one skill's bundles together, restoring both if either replacement fails."""
    result = Applied()
    changed = [plan for plan in plans if plan[-1] != "unchanged"]
    if not changed:
        return result
    # Backups and staging stay outside skill and agent discovery.
    backup_root = destination / f".{name}-backups"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".i2e-install-", dir=destination) as staging_name:
        staging = Path(staging_name)
        for source, target, expected, _, _ in changed:
            staged = staging / target.parent.name
            shutil.copytree(source, staged, symlinks=True)
            if tree_snapshot(staged) != expected:
                raise ValidationError(f"Source changed while staging; retry: {source}")
        try:
            for _, target, _, current, action in changed:
                real_directory_or_missing(target)
                if (tree_snapshot(target) if target.exists() else None) != current:
                    raise ValidationError(f"Target changed during installation; retry: {target}")
                backup = None
                if action == "update":
                    if result.backup_run is None:
                        if not backup_root.exists():
                            result.new_backup_root = backup_root
                        backup_root.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
                        result.backup_run = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_root))
                    backup = result.backup_run / target.parent.name / target.name
                    backup.parent.mkdir()
                    target.rename(backup)
                result.replaced.append((target, backup))
                target.parent.mkdir(exist_ok=True)
                (staging / target.parent.name).rename(target)
        except (OSError, ValidationError) as exc:
            roll_back([result], exc)
    return result


def install(destination: Path, *, dry_run: bool, check: bool, update: bool,
            skills: list[str] | None = None) -> int:
    names = selected_skills(REPO_ROOT, skills)
    validate_suite(REPO_ROOT, names)
    destination = Path(os.path.abspath(destination.expanduser()))

    # Preflight every selected skill before writing anything.
    planned = []
    conflicts = []
    for name in names:
        plans, skill_conflicts = plan_skill(destination, name, update=update, check=check)
        planned.append((name, plans))
        conflicts.extend(skill_conflicts)

    if check:
        for _, plans in planned:
            for _, target, _, _, action in plans:
                print(f"{'OK' if action == 'unchanged' else 'DIFFERS' if action == 'update' else 'MISSING'}: {target}")
        return int(any(plan[-1] != "unchanged" for _, plans in planned for plan in plans))
    if conflicts:
        raise ValidationError("Existing installation differs; use --update to back it up and replace: "
                              + ", ".join(str(path) for path in conflicts))
    for name, plans in planned:
        if any(plan[-1] == "update" for plan in plans):
            real_directory_or_missing(destination / f".{name}-backups")
    if dry_run or all(plan[-1] == "unchanged" for _, plans in planned for plan in plans):
        for name, plans in planned:
            for _, target, _, _, action in plans:
                print(f"{'Would ' if dry_run and action != 'unchanged' else ''}{action}: {target}")
                if action == "update":
                    print(f"  Would preserve exact previous tree under: {destination / f'.{name}-backups'}")
        return 0

    # A failure in a later skill puts back the skills already installed in this run.
    results: list[Applied] = []
    try:
        for name, plans in planned:
            results.append(apply_skill(destination, name, plans))
    except (OSError, ValidationError) as exc:
        roll_back(results, exc)
    for (_, plans), result in zip(planned, results):
        for _, target, _, _, action in plans:
            print(f"{action}: {target}")
        for target, backup in result.replaced:
            if backup is not None:
                print(f"Backup of {target}: {backup}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dest = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    parser.add_argument("--skill", action="append", choices=sorted(SKILLS),
                        help="Skill to install; repeat for more (default: every skill in this repository)")
    parser.add_argument("--dest", type=Path, default=default_dest,
                        help="Claude config directory (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--update", action="store_true", help="Back up and replace differing installed bundles")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate and show actions without writing")
    mode.add_argument("--check", action="store_true", help="Read-only content check; exit 1 if missing or different")
    args = parser.parse_args()
    if args.check and args.update:
        parser.error("--check cannot be combined with --update")
    try:
        return install(args.dest, dry_run=args.dry_run, check=args.check, update=args.update,
                       skills=args.skill)
    except (ValidationError, OSError, UnicodeError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
