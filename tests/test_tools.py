"""Exercise the actual CLI against disposable packages and destinations."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
MAIN_NAME = "i2e-fable-opus"
SONNET_NAME = "i2e-opus-sonnet"
# Each skill has its own branch of i2e-team, and every branch carries these tests.
PRESENT = {path.name for path in (REPO / "skills").iterdir() if path.is_dir()} if (REPO / "skills").is_dir() else set()
SONNET_AGENTS = {"i2e-opus-lead": "claude-opus-5-5", "i2e-sonnet-implementer": "claude-sonnet-5-5"}
LIFECYCLE = Path("references") / "lifecycle"
SHARED_GUIDE = Path("references") / "library.md"
PLANNER = "i2e-fable-planner"
IMPLEMENTER = "i2e-opus-implementer"
AUDITOR = "i2e-opus-security-auditor"
READ_ONLY = "Read, Grep, Glob"
REPORT_DENY = "Edit, Write, NotebookEdit, Bash, Agent, WebFetch, WebSearch"
# Agent name -> (model, tools, disallowedTools); None omits the tools field.
AGENTS = {
    PLANNER: ("claude-fable-5-2", READ_ONLY, REPORT_DENY),
    "i2e-fable-final-reviewer": ("claude-fable-5-2", READ_ONLY, REPORT_DENY),
    IMPLEMENTER: ("claude-opus-5-5", None, "Agent"),
    "i2e-opus-doubt-reviewer": ("claude-opus-5-5", READ_ONLY, REPORT_DENY),
    AUDITOR: ("claude-opus-5-5", READ_ONLY, REPORT_DENY),
}
VALID_PROPERTY = """---
id: prop-json-round-trip
kind: property
type: round-trip
status: candidate
tags: json, config
applies-to: python
seen-in: example change
updated: 2026-11-19
---

# Round trip

## Statement

Decoding what was encoded returns the original value.
"""
VALID_RULE = """---
id: rule-reload-keeps-draft
kind: rule
type: blind-spot
status: adopted
tags: forms, state
applies-to: any
seen-in: first change, second change
updated: 2026-11-19
---

# Reload keeps a draft

## Trigger

A form component changes how it stores unsaved input.

## Check

Reload the page with a draft open and confirm the draft returns.

## Why it flags

Lost drafts were missed twice before.
"""


class ToolTestCase(unittest.TestCase):
    """A disposable package folder with the scripts and library template, and CLI helpers."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "package"
        self.dest = self.base / "claude"
        shutil.copytree(SCRIPTS, self.repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "library-template", self.repo / "library-template")
        self.environment = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.base / "default-claude"))
        self.environment.pop("PYTHONDONTWRITEBYTECODE", None)

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def cli(self, script: str, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(self.repo / "scripts" / script), *args],
                                cwd=self.base, env=self.environment, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        return self.cli("install.py", "--dest", str(self.dest), *args, success=success)

    @staticmethod
    def snapshot(root: Path) -> dict[str, tuple[bytes | None, int, int]]:
        """Capture bytes and mtimes, including directories, to detect writes."""
        return {str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None,
                                             path.stat().st_mtime_ns, path.stat().st_mode)
                for path in root.rglob("*")}

    @staticmethod
    def contents(root: Path) -> dict[str, bytes]:
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def install_with_failing_rename(self, skill: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the installer with the move of a skill's staged agents into place failing."""
        runner = f"""
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, {str(self.repo / 'scripts')!r})
original_rename = Path.rename
def fail_agents(source, target):
    if (source.parent.name.startswith('.i2e-install-') and source.name == 'agents'
            and target.name == {skill!r}):
        raise OSError('Simulated replacement failure')
    return original_rename(source, target)
with patch.object(Path, 'rename', fail_agents):
    runpy.run_path({str(self.repo / 'scripts' / 'install.py')!r}, run_name='__main__')
"""
        result = subprocess.run([sys.executable, "-c", runner, "--dest", str(self.dest), *args],
                                cwd=self.base, env=self.environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Simulated replacement failure", result.stderr)
        return result


@unittest.skipUnless(MAIN_NAME in PRESENT, f"{MAIN_NAME} is on its own branch")
class PackageToolsTests(ToolTestCase):
    """The installer and validator, on a package built around the pinned i2e-fable-opus guides."""

    def setUp(self) -> None:
        super().setUp()
        self.skill = self.dest / "skills" / MAIN_NAME
        self.agents = self.dest / "agents" / MAIN_NAME
        self.main = self.repo / "skills" / MAIN_NAME
        self.write(self.main / "SKILL.md", """---
name: i2e-fable-opus
description: Coordinate issue implementation with explicit model roles.
---
# Workflow

Follow the [role instructions](references/roles.md) and [task form](templates/task.md).
""")
        for name, (model, tools, denied) in AGENTS.items():
            self.write_agent(name, model, tools=tools, denied=denied)
        self.write(self.main / "references" / "roles.md", "# Roles\n\nCoordinate work using the approved role contract.\n")
        # The pinned guides link back to the adaptation boundary.
        self.write(self.main / "references" / "native-adaptation.md", "# Adaptation\n\nGuides are references only.\n")
        self.lifecycle = self.main / LIFECYCLE
        shutil.copytree(REPO / "skills" / MAIN_NAME / LIFECYCLE, self.lifecycle)
        # Every skill bundles the same library guide.
        shutil.copy2(REPO / "skills" / MAIN_NAME / SHARED_GUIDE, self.main / SHARED_GUIDE)
        self.write(self.main / "references" / "verification-loops.md", "# Loops\n\nDisprove rules first.\n")
        self.write(self.main / "templates" / "task.md", "# Task\n\nRecord the concrete goal and acceptance evidence.\n")

    def write_agent(self, name: str, model: str, effort: str = "max", tools: str | None = None,
                    denied: str | None = None, extra: str = "") -> None:
        tools_line = f"tools: {tools}\n" if tools is not None else ""
        denied_line = f"disallowedTools: {denied}\n" if denied is not None else ""
        self.write(self.main / "agents" / f"{name}.md", f"""---
name: {name}
description: Perform one role in the issue workflow.
model: {model}
effort: {effort}
{tools_line}{denied_line}{extra}---
Follow the delegated contract.
""")

    def test_valid_package_and_cwd_independent_install(self) -> None:
        self.cli("validate.py")
        self.install()
        self.assertEqual((self.skill / "SKILL.md").read_bytes(),
                         (self.main / "SKILL.md").read_bytes())
        self.assertEqual(sorted(path.name for path in self.agents.iterdir()), sorted(f"{name}.md" for name in AGENTS))
        for name in AGENTS:
            self.assertEqual((self.agents / f"{name}.md").read_bytes(),
                             (self.main / "agents" / f"{name}.md").read_bytes())
        self.assertEqual(sorted(path.name for path in self.dest.iterdir()), ["agents", "skills"])
        self.assertEqual([path.name for path in (self.dest / "skills").iterdir()], [MAIN_NAME])
        self.assertEqual([path.name for path in (self.dest / "agents").iterdir()], [MAIN_NAME])

    def test_default_destination_respects_claude_config_dir(self) -> None:
        self.cli("install.py")
        default = self.base / "default-claude"
        self.assertTrue((default / "skills" / MAIN_NAME / "SKILL.md").is_file())
        self.assertTrue((default / "agents" / MAIN_NAME / f"{PLANNER}.md").is_file())
        self.assertFalse(self.dest.exists())

    def test_identical_install_is_noop(self) -> None:
        self.install()
        before = self.snapshot(self.base)
        result = self.install()
        self.assertIn("unchanged:", result.stdout)
        self.assertEqual(before, self.snapshot(self.base))

    def test_conflict_does_not_overwrite_or_install_agents(self) -> None:
        self.write(self.skill / "private.txt", "Preserve this installed skill.\n")
        before = self.snapshot(self.base)
        result = self.install(success=False)
        self.assertIn("--update", result.stderr)
        self.assertEqual(before, self.snapshot(self.base))

    def test_update_backs_up_exact_trees_and_preserves_unrelated_entries(self) -> None:
        self.install()
        self.write(self.skill / "private.txt", "Original local customization.\n")
        self.write(self.agents / "extra.md", "Original agent customization.\n")
        unrelated_skill = self.dest / "skills" / "unrelated" / "SKILL.md"
        unrelated_agent = self.dest / "agents" / "unrelated.md"
        self.write(unrelated_skill, "Unrelated skill.\n")
        self.write(unrelated_agent, "Unrelated agent.\n")
        previous_skill = self.snapshot(self.skill)
        previous_agents = self.snapshot(self.agents)
        previous_unrelated = (self.snapshot(unrelated_skill.parent), unrelated_agent.read_bytes())
        result = self.install("--update")
        backup_root = self.dest / f".{MAIN_NAME}-backups"
        backups = list(backup_root.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(previous_skill, self.snapshot(backups[0] / "skills" / MAIN_NAME))
        self.assertEqual(previous_agents, self.snapshot(backups[0] / "agents" / MAIN_NAME))
        self.assertEqual(previous_unrelated,
                         (self.snapshot(unrelated_skill.parent), unrelated_agent.read_bytes()))
        self.assertIn(str(backups[0] / "skills" / MAIN_NAME), result.stdout)
        self.assertFalse((self.skill / "private.txt").exists())
        self.assertFalse((self.agents / "extra.md").exists())
        self.install("--check")

    def test_failed_second_replacement_restores_both_previous_bundles(self) -> None:
        self.install()
        self.write(self.skill / "private.txt", "Original skill.\n")
        self.write(self.agents / "private.txt", "Original agents.\n")
        before_skill = self.snapshot(self.skill)
        before_agents = self.snapshot(self.agents)
        # Simulate a filesystem failure after the first replacement succeeded.
        self.install_with_failing_rename(MAIN_NAME, "--update")
        self.assertEqual(before_skill, self.snapshot(self.skill))
        self.assertEqual(before_agents, self.snapshot(self.agents))
        self.assertEqual([path.name for path in (self.dest / "skills").iterdir()], [MAIN_NAME])
        self.assertEqual([path.name for path in (self.dest / "agents").iterdir()], [MAIN_NAME])
        # No staging folder or empty backup folder is left behind.
        self.assertEqual(sorted(path.name for path in self.dest.iterdir()), ["agents", "skills"])

    def test_dry_run_never_creates_destination(self) -> None:
        before = self.snapshot(self.base)
        result = self.install("--dry-run")
        self.assertIn("Would install:", result.stdout)
        self.assertEqual(before, self.snapshot(self.base))

    def test_update_dry_run_never_creates_backups_or_changes_target(self) -> None:
        self.write(self.skill / "local.txt", "Keep me.\n")
        before = self.snapshot(self.base)
        result = self.install("--update", "--dry-run")
        self.assertIn("Would update:", result.stdout)
        self.assertIn("Would preserve exact previous tree", result.stdout)
        self.assertEqual(before, self.snapshot(self.base))

    def test_check_missing_is_read_only(self) -> None:
        before = self.snapshot(self.base)
        result = self.install("--check", success=False)
        self.assertIn("MISSING:", result.stdout)
        self.assertEqual(before, self.snapshot(self.base))

    def test_check_identical_and_different_are_read_only(self) -> None:
        self.install()
        before = self.snapshot(self.base)
        self.install("--check")
        self.assertEqual(before, self.snapshot(self.base))
        self.write(self.agents / f"{PLANNER}.md", "Local change.\n")
        before = self.snapshot(self.base)
        result = self.install("--check", success=False)
        self.assertIn(f"OK: {self.skill}", result.stdout)
        self.assertIn(f"DIFFERS: {self.agents}", result.stdout)
        self.assertEqual(before, self.snapshot(self.base))

    def test_symlink_source_entry_is_rejected(self) -> None:
        external = self.base / "external.txt"
        self.write(external, "External content.\n")
        (self.main / "references" / "external.md").symlink_to(external)
        self.install(success=False)
        self.assertFalse(self.dest.exists())

    def test_symlink_source_directory_is_rejected(self) -> None:
        original = self.repo / "original-main"
        self.main.rename(original)
        self.main.symlink_to(original, target_is_directory=True)
        self.install(success=False)
        self.assertFalse(self.dest.exists())

    def test_symlink_target_and_nested_entry_are_rejected(self) -> None:
        outside = self.base / "outside"
        self.write(outside / "keep.txt", "Original.\n")
        self.skill.parent.mkdir(parents=True)
        self.skill.symlink_to(outside, target_is_directory=True)
        self.install("--update", success=False)
        self.assertEqual((outside / "keep.txt").read_text(), "Original.\n")
        self.skill.unlink()
        self.skill.mkdir()
        (self.skill / "linked.txt").symlink_to(outside / "keep.txt")
        self.install("--update", success=False)
        self.assertTrue((self.skill / "linked.txt").is_symlink())

    def test_symlink_skill_and_agent_directories_are_rejected(self) -> None:
        for kind in ("skills", "agents"):
            with self.subTest(kind=kind):
                outside = self.base / f"outside-{kind}"
                outside.mkdir()
                self.dest.mkdir(exist_ok=True)
                (self.dest / kind).symlink_to(outside, target_is_directory=True)
                self.install(success=False)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertEqual([path.name for path in self.dest.iterdir()], [kind])
                (self.dest / kind).unlink()

    def test_invalid_source_does_not_touch_existing_install(self) -> None:
        self.install()
        (self.main / "agents" / f"{IMPLEMENTER}.md").unlink()
        before = self.snapshot(self.base)
        self.install("--update", success=False)
        self.assertEqual(before, self.snapshot(self.base))

    def test_missing_source_directory_is_rejected(self) -> None:
        self.main.rename(self.repo / "hidden-main")
        self.install(success=False)
        self.assertFalse(self.dest.exists())

    def test_agent_definitions_must_pin_model_and_max_effort(self) -> None:
        for model, effort in (("fable", "max"), ("claude-fable-5-1", "max"), ("claude-fable-5-2", "high"),
                              ("inherit", "max")):
            with self.subTest(model=model, effort=effort):
                self.write_agent(PLANNER, model, effort, tools=READ_ONLY, denied=REPORT_DENY)
                result = self.cli("validate.py", success=False)
                self.assertIn(f"Subagent {PLANNER} must pin", result.stderr)
        self.write_agent(PLANNER, "claude-fable-5-2", tools=READ_ONLY, denied=REPORT_DENY)
        self.cli("validate.py")
        self.write_agent(IMPLEMENTER, "claude-fable-5-2", denied="Agent")
        self.cli("validate.py", success=False)

    def test_report_only_agents_cannot_edit_run_commands_or_fetch(self) -> None:
        for tools in ("Read, Grep, Glob, Edit", "Read, Bash", "Read, Write", "Read,", "Agent", "Read, WebFetch"):
            with self.subTest(tools=tools):
                self.write_agent(AUDITOR, "claude-opus-5-5", tools=tools, denied=REPORT_DENY)
                result = self.cli("validate.py", success=False)
                self.assertIn(f"Subagent {AUDITOR} must be report-only", result.stderr)
        self.write_agent(AUDITOR, "claude-opus-5-5", tools="Read, Grep", denied=REPORT_DENY)
        self.cli("validate.py")

    def test_agents_must_deny_their_excluded_tools(self) -> None:
        cases = ((AUDITOR, READ_ONLY, "Edit, Write, NotebookEdit"), (AUDITOR, READ_ONLY, "Bash, Agent"),
                 (IMPLEMENTER, None, "Bash"))
        for name, tools, denied in cases:
            with self.subTest(name=name, denied=denied):
                self.write_agent(name, AGENTS[name][0], tools=tools, denied=denied)
                result = self.cli("validate.py", success=False)
                self.assertIn(f"Subagent {name} must list", result.stderr)
            self.write_agent(name, AGENTS[name][0], tools=tools, denied=AGENTS[name][2])
        self.cli("validate.py")

    def test_agents_cannot_declare_access_widening_fields(self) -> None:
        cases = ((AUDITOR, READ_ONLY, REPORT_DENY, "permissionMode: bypassPermissions\n"),
                 (AUDITOR, READ_ONLY, REPORT_DENY, "mcpServers:\n  github:\n    command: gh\n"),
                 (AUDITOR, None, REPORT_DENY, ""),
                 (IMPLEMENTER, None, None, ""),
                 (IMPLEMENTER, None, "Agent", "memory: user\n"))
        for name, tools, denied, extra in cases:
            with self.subTest(name=name, extra=extra, tools=tools, denied=denied):
                self.write_agent(name, AGENTS[name][0], tools=tools, denied=denied, extra=extra)
                result = self.cli("validate.py", success=False)
                self.assertIn(f"Subagent {name} must declare exactly", result.stderr)
            self.write_agent(name, AGENTS[name][0], tools=AGENTS[name][1], denied=AGENTS[name][2])
        self.cli("validate.py")

    def test_stale_agent_definition_is_rejected(self) -> None:
        self.write_agent("i2e-fable-lead", "claude-fable-5-1")
        result = self.cli("validate.py", success=False)
        self.assertIn("Unexpected entries in the agents directory: i2e-fable-lead.md", result.stderr)

    def test_lifecycle_files_must_match_the_manifest(self) -> None:
        guide = self.lifecycle / "skills" / "test-driven-development" / "GUIDE.md"
        original = guide.read_bytes()
        guide.write_bytes(original + b"\nUnreviewed addition.\n")
        result = self.cli("validate.py", success=False)
        self.assertIn("Missing or modified lifecycle resource", result.stderr)
        guide.write_bytes(original)
        self.write(self.lifecycle / "skills" / "extra" / "GUIDE.md", "# Extra\n")
        result = self.cli("validate.py", success=False)
        self.assertIn("Unlisted lifecycle file", result.stderr)
        shutil.rmtree(self.lifecycle / "skills" / "extra")
        self.cli("validate.py")

    def test_lifecycle_manifest_is_strict_and_complete(self) -> None:
        path = self.lifecycle / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        first, *rest = manifest["resources"]
        variants = {
            "missing guide": dict(manifest, capabilities=manifest["capabilities"][1:]),
            "other revision": dict(manifest, upstream=dict(manifest["upstream"], revision="0" * 40)),
            "escaping path": dict(manifest, resources=[dict(first, bundled_path="../" + first["bundled_path"])] + rest),
            "dropped resource": dict(manifest, resources=rest),
        }
        for label, value in variants.items():
            with self.subTest(label):
                path.write_text(json.dumps(value), encoding="utf-8")
                self.cli("validate.py", success=False)
        path.write_text(json.dumps(manifest)[:-1] + ', "schema_version": 1}', encoding="utf-8")
        result = self.cli("validate.py", success=False)
        self.assertIn("Duplicate JSON key", result.stderr)
        # A guide removed consistently from the manifest and the tree is still missing.
        guide = manifest["capabilities"][0]["bundled_path"]
        (self.lifecycle / guide).unlink()
        path.write_text(json.dumps(dict(
            manifest, capabilities=manifest["capabilities"][1:],
            resources=[item for item in manifest["resources"] if item["bundled_path"] != guide])), encoding="utf-8")
        result = self.cli("validate.py", success=False)
        self.assertIn("guides once", result.stderr)

    def test_lifecycle_code_span_references_must_resolve(self) -> None:
        # Keep the manifest hash current so only the reference check can fail.
        relative = "references/testing-patterns.md"
        resource = self.lifecycle / relative
        resource.write_text(resource.read_text(encoding="utf-8") + "\nSee `../missing-checklist.md`.\n",
                            encoding="utf-8")
        path = self.lifecycle / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for item in manifest["resources"]:
            if item["bundled_path"] == relative:
                item["sha256"] = hashlib.sha256(resource.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.cli("validate.py", success=False)
        self.assertIn("Broken lifecycle reference", result.stderr)

    def test_main_links_cannot_escape_bundle(self) -> None:
        self.write(self.repo / "README.md", "Outside bundle.\n")
        self.write(self.main / "references" / "roles.md", "[Outside](../../../README.md)\n")
        result = self.cli("validate.py", success=False)
        self.assertIn("escapes the bundle", result.stderr)

    def test_broken_relative_link_is_rejected(self) -> None:
        self.write(self.main / "references" / "roles.md", "[Missing](missing.md)\n")
        self.cli("validate.py", success=False)

    def test_absolute_and_file_links_are_rejected(self) -> None:
        for target in (str(self.main / "SKILL.md"), (self.main / "SKILL.md").as_uri()):
            with self.subTest(target=target):
                self.write(self.main / "references" / "roles.md", f"[Machine path]({target})\n")
                self.cli("validate.py", success=False)

    def test_reference_style_links_and_encoded_paths_are_checked(self) -> None:
        self.write(self.main / "references" / "extra notes.md", "Useful notes.\n")
        self.write(self.main / "references" / "roles.md", "[Notes][notes]\n\n[notes]: extra%20notes.md\n")
        self.cli("validate.py")
        self.write(self.main / "references" / "roles.md", "[Bad][bad]\n\n[bad]: %2e%2e/%2e%2e/elsewhere.md\n")
        self.cli("validate.py", success=False)

    def test_frontmatter_and_matching_names_are_required(self) -> None:
        self.write(self.main / "agents" / f"{PLANNER}.md", "Follow the delegated contract.\n")
        self.cli("validate.py", success=False)
        self.write(self.main / "agents" / f"{PLANNER}.md", "---\nname: i2e-other\ndescription: Plan.\n"
                   f"model: claude-fable-5-2\neffort: max\ntools: {READ_ONLY}\n"
                   f"disallowedTools: {REPORT_DENY}\n---\nFollow the delegated contract.\n")
        self.cli("validate.py", success=False)
        self.write_agent(PLANNER, "claude-fable-5-2", tools=READ_ONLY, denied=REPORT_DENY)
        self.write(self.main / "SKILL.md", "# No frontmatter\n")
        self.cli("validate.py", success=False)

    def test_block_strings_are_supported(self) -> None:
        self.write(self.main / "agents" / f"{PLANNER}.md", """---
name: 'i2e-fable-planner'
description: >-
  Plan
  issue implementation.
model: "claude-fable-5-2"
effort: max
tools: Read, Grep
disallowedTools: >-
  Edit, Write, NotebookEdit, Bash,
  Agent, WebFetch, WebSearch
---
Follow the delegated contract.
""")
        self.cli("validate.py")

    def test_scaffolds_are_rejected_outside_pinned_guides(self) -> None:
        self.assertIn("TODO", (self.lifecycle / "skills" / "documentation-and-adrs" / "GUIDE.md").read_text())
        self.cli("validate.py")
        self.write(self.main / "references" / "roles.md", "TODO: fill this in.\n")
        self.cli("validate.py", success=False)

    def test_source_cannot_be_installation_target(self) -> None:
        before = self.snapshot(self.base)
        self.cli("install.py", "--dest", str(self.repo), "--update", success=False)
        self.assertEqual(before, self.snapshot(self.base))

    def test_checkout_and_ancestor_cannot_be_installation_targets(self) -> None:
        for nested_checkout in (False, True):
            with self.subTest(nested_checkout=nested_checkout):
                destination = self.base / ("ancestor-case" if nested_checkout else "checkout-case")
                target = destination / "skills" / MAIN_NAME
                checkout = target / "checkout" if nested_checkout else target
                shutil.copytree(self.repo, checkout)
                self.write(checkout / ".git" / "HEAD", "ref: refs/heads/main\n")
                self.write(destination / "skills" / "sibling-data" / "keep.txt", "Preserve sibling data.\n")
                if nested_checkout:
                    self.write(target / "other-project" / "keep.txt", "Preserve adjacent project.\n")
                before = self.snapshot(self.base)
                result = subprocess.run(
                    [sys.executable, str(checkout / "scripts" / "install.py"),
                     "--dest", str(destination), "--update"],
                    cwd=self.base, env=self.environment, text=True, capture_output=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("overlaps package source", result.stderr)
                self.assertEqual(before, self.snapshot(self.base))
                self.assertTrue((checkout / "scripts" / "install.py").is_file())
                self.assertTrue((checkout / "skills" / MAIN_NAME / "SKILL.md").is_file())

    def add_sonnet(self) -> Path:
        """Add a minimal valid i2e-opus-sonnet bundle; the real one is on its own branch."""
        target = self.repo / "skills" / SONNET_NAME
        self.write(target / "SKILL.md", f"""---
name: {SONNET_NAME}
description: Lead with Opus and implement with Sonnet.
---
# Workflow

Follow the [task form](templates/task.md).
""")
        for name, model in SONNET_AGENTS.items():
            self.write(target / "agents" / f"{name}.md", f"""---
name: {name}
description: Perform one role in the issue workflow.
model: {model}
effort: max
---
Follow the delegated contract.
""")
        self.write(target / "references" / "verification-loops.md", "# Loops\n\nDisprove rules first.\n")
        shutil.copy2(self.main / SHARED_GUIDE, target / SHARED_GUIDE)
        self.write(target / "templates" / "task.md", "# Task\n\nRecord the concrete goal and acceptance evidence.\n")
        return target

    def test_opus_sonnet_installs_and_updates_alongside_fable_opus(self) -> None:
        self.add_sonnet()
        self.install("--skill", MAIN_NAME)
        fable_opus = (self.snapshot(self.skill), self.snapshot(self.agents))
        result = self.cli("validate.py", "--skill", SONNET_NAME)
        self.assertIn(f"Validated: {SONNET_NAME}", result.stdout)
        self.install("--skill", SONNET_NAME)
        agents = self.dest / "agents" / SONNET_NAME
        self.assertEqual({file.name for file in agents.iterdir()},
                         {"i2e-opus-lead.md", "i2e-sonnet-implementer.md"})
        extra = self.dest / "skills" / SONNET_NAME / "private.txt"
        self.write(extra, "Original local customization.\n")
        self.install("--skill", SONNET_NAME, "--update")
        backups = list((self.dest / f".{SONNET_NAME}-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / extra.relative_to(self.dest)).is_file())
        self.install("--check")
        self.assertEqual(fable_opus, (self.snapshot(self.skill), self.snapshot(self.agents)))

    def test_default_install_covers_every_skill_present(self) -> None:
        self.add_sonnet()
        self.install()
        for kind in ("skills", "agents"):
            self.assertEqual(sorted(path.name for path in (self.dest / kind).iterdir()), [MAIN_NAME, SONNET_NAME])
        self.install("--check")

    def test_failed_later_skill_restores_the_skills_installed_before_it(self) -> None:
        self.add_sonnet()
        self.install()
        folders = [self.skill, self.agents, self.dest / "skills" / SONNET_NAME, self.dest / "agents" / SONNET_NAME]
        for folder in folders:
            self.write(folder / "private.txt", f"Original {folder.parent.name} customization.\n")
        before = [self.snapshot(folder) for folder in folders]
        self.install_with_failing_rename(SONNET_NAME, "--update")
        self.assertEqual(before, [self.snapshot(folder) for folder in folders])
        self.assertEqual(sorted(path.name for path in self.dest.iterdir()), ["agents", "skills"])
        # The same update succeeds once nothing fails.
        self.install("--update")
        self.install("--check")
        for name in (MAIN_NAME, SONNET_NAME):
            self.assertEqual(len(list((self.dest / f".{name}-backups").iterdir())), 1)

    def test_invalid_later_skill_blocks_every_write(self) -> None:
        sonnet = self.add_sonnet()
        self.install()
        self.write(self.main / "references" / "extra.md", "# Extra\n\nA newer reference.\n")
        lead = sonnet / "agents" / "i2e-opus-lead.md"
        lead.write_text(lead.read_text(encoding="utf-8").replace("model: claude-opus-5-5", "model: claude-sonnet-5-5", 1),
                        encoding="utf-8")
        before = self.snapshot(self.dest)
        result = self.install("--update", success=False)
        self.assertIn("Subagent i2e-opus-lead must pin", result.stderr)
        self.assertEqual(before, self.snapshot(self.dest))

    def test_unknown_skill_directory_is_rejected(self) -> None:
        self.write(self.repo / "skills" / "i2e-other" / "SKILL.md",
                   "---\nname: i2e-other\ndescription: Other.\n---\nOther.\n")
        result = self.cli("validate.py", success=False)
        self.assertIn("Unknown skill directory: i2e-other", result.stderr)
        self.install(success=False)
        self.assertFalse(self.dest.exists())

    def test_shared_library_guide_must_match_across_skills(self) -> None:
        guide = self.add_sonnet() / SHARED_GUIDE
        self.cli("validate.py")
        guide.write_text(guide.read_text(encoding="utf-8") + "\nA local variation.\n", encoding="utf-8")
        result = self.cli("validate.py", success=False)
        self.assertIn("differs between skills", result.stderr)
        self.cli("validate.py", "--skill", SONNET_NAME)

    def test_second_skill_agents_keep_their_exact_fields_and_pins(self) -> None:
        lead = self.add_sonnet() / "agents" / "i2e-opus-lead.md"
        original = lead.read_text(encoding="utf-8")
        lead.write_text(original.replace("effort: max\n", "effort: max\npermissionMode: bypassPermissions\n", 1),
                        encoding="utf-8")
        result = self.cli("validate.py", "--skill", SONNET_NAME, success=False)
        self.assertIn("Subagent i2e-opus-lead must declare exactly", result.stderr)
        lead.write_text(original.replace("model: claude-opus-5-5", "model: claude-sonnet-5-5", 1), encoding="utf-8")
        result = self.cli("validate.py", "--skill", SONNET_NAME, success=False)
        self.assertIn("Subagent i2e-opus-lead must pin", result.stderr)



@unittest.skipUnless(SONNET_NAME in PRESENT, f"{SONNET_NAME} is on its own branch")
class SonnetPackageTests(ToolTestCase):
    """The real i2e-opus-sonnet bundle validates, installs, updates, and rolls back."""

    def setUp(self) -> None:
        super().setUp()
        self.main = self.repo / "skills" / SONNET_NAME
        shutil.copytree(REPO / "skills" / SONNET_NAME, self.main)
        self.skill = self.dest / "skills" / SONNET_NAME
        self.agents = self.dest / "agents" / SONNET_NAME

    def test_sonnet_validates_installs_and_checks(self) -> None:
        result = self.cli("validate.py")
        self.assertIn(f"Validated: {SONNET_NAME}", result.stdout)
        self.install()
        self.assertEqual(self.contents(self.skill), self.contents(self.main))
        self.assertEqual(self.contents(self.agents), self.contents(self.main / "agents"))
        self.assertEqual(sorted(path.name for path in self.agents.iterdir()),
                         sorted(f"{name}.md" for name in SONNET_AGENTS))
        self.assertIn("unchanged", self.install().stdout)
        self.install("--check")

    def test_sonnet_failed_update_restores_and_later_update_keeps_a_backup(self) -> None:
        self.install()
        self.write(self.skill / "private.txt", "Original skill.\n")
        self.write(self.agents / "private.txt", "Original agents.\n")
        before = (self.snapshot(self.skill), self.snapshot(self.agents))
        self.install_with_failing_rename(SONNET_NAME, "--update")
        self.assertEqual(before, (self.snapshot(self.skill), self.snapshot(self.agents)))
        self.assertEqual(sorted(path.name for path in self.dest.iterdir()), ["agents", "skills"])
        self.install("--update")
        backups = list((self.dest / f".{SONNET_NAME}-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "skills" / SONNET_NAME / "private.txt").is_file())
        self.install("--check")

    def test_sonnet_agents_keep_their_exact_fields_and_pins(self) -> None:
        lead = self.main / "agents" / "i2e-opus-lead.md"
        original = lead.read_text(encoding="utf-8")
        changes = {
            "must declare exactly": original.replace("effort: max\n", "effort: max\npermissionMode: bypassPermissions\n", 1),
            "must pin": original.replace("model: claude-opus-5-5", "model: claude-sonnet-5-5", 1),
        }
        for message, changed in changes.items():
            with self.subTest(message):
                self.assertNotEqual(changed, original)
                lead.write_text(changed, encoding="utf-8")
                result = self.cli("validate.py", success=False)
                self.assertIn(f"Subagent i2e-opus-lead {message}", result.stderr)
                self.install(success=False)
                self.assertFalse(self.dest.exists())
        lead.write_text(original, encoding="utf-8")
        self.cli("validate.py")


class LibraryToolTests(ToolTestCase):
    """The shared library tool, which every branch carries."""

    def test_library_init_creates_layout_and_refuses_existing(self) -> None:
        library = self.base / "library"
        result = self.cli("library.py", "init", "--path", str(library))
        self.assertIn("nothing is committed", result.stdout)
        for name in ("README.md", "properties/README.md", "rules/README.md",
                     "templates/property.md", "templates/rule.md"):
            self.assertTrue((library / name).is_file(), name)
        if shutil.which("git"):
            self.assertTrue((library / ".git").is_dir())
        self.cli("library.py", "check", "--path", str(library))
        before = self.snapshot(library)
        self.cli("library.py", "init", "--path", str(library), success=False)
        self.assertEqual(before, self.snapshot(library))
        occupied = self.base / "occupied"
        self.write(occupied / "keep.txt", "Keep me.\n")
        self.cli("library.py", "init", "--path", str(occupied), success=False)
        self.assertEqual([path.name for path in occupied.iterdir()], ["keep.txt"])
        self.environment["I2E_LIBRARY"] = str(self.base / "from-env")
        self.cli("library.py", "init")
        self.assertTrue((self.base / "from-env" / "README.md").is_file())

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_library_init_supports_older_git_and_cleans_up_after_a_failure(self) -> None:
        real_git = shutil.which("git")
        fake_git = self.base / "bin" / "git"
        # Git before 2.28 rejects --initial-branch.
        self.write(fake_git, f"""#!/bin/sh
for arg in "$@"; do
  if [ "$arg" = "--initial-branch" ]; then echo "unknown option: initial-branch" >&2; exit 129; fi
done
exec {shlex.quote(real_git)} "$@"
""")
        fake_git.chmod(0o755)
        self.environment["PATH"] = f"{fake_git.parent}{os.pathsep}{self.environment.get('PATH', '')}"
        library = self.base / "older-git" / "library"
        self.cli("library.py", "init", "--path", str(library))
        head = subprocess.run([real_git, "-C", str(library), "symbolic-ref", "HEAD"],
                              text=True, capture_output=True, check=True)
        self.assertEqual(head.stdout.strip(), "refs/heads/main")
        self.assertTrue((library / "templates" / "rule.md").is_file())
        self.write(fake_git, "#!/bin/sh\necho 'simulated git failure' >&2\nexit 1\n")
        missing = self.base / "new-parent" / "library"
        result = self.cli("library.py", "init", "--path", str(missing), success=False)
        self.assertIn("simulated git failure", result.stderr)
        self.assertFalse((self.base / "new-parent").exists())
        empty = self.base / "empty"
        empty.mkdir()
        self.cli("library.py", "init", "--path", str(empty), success=False)
        self.assertEqual(list(empty.iterdir()), [])

    def test_library_check_accepts_valid_entries_and_rejects_bad_ones(self) -> None:
        library = self.base / "library"
        self.cli("library.py", "init", "--path", str(library))
        prop = library / "properties" / "prop-json-round-trip.md"
        rule = library / "rules" / "rule-reload-keeps-draft.md"
        self.write(prop, VALID_PROPERTY)
        self.write(rule, VALID_RULE)
        result = self.cli("library.py", "check", "--path", str(library))
        self.assertIn(": 1 candidate property, 1 adopted rule; 0 problems.", result.stdout)
        # Counts other than one use each kind's plural.
        extra = {library / "properties" / "prop-csv-round-trip.md":
                 VALID_PROPERTY.replace("prop-json-round-trip", "prop-csv-round-trip"),
                 library / "rules" / "rule-reload-keeps-scroll.md":
                 VALID_RULE.replace("rule-reload-keeps-draft", "rule-reload-keeps-scroll")}
        for path, text in extra.items():
            self.write(path, text)
        result = self.cli("library.py", "check", "--path", str(library))
        self.assertIn(": 2 candidate properties, 2 adopted rules; 0 problems.", result.stdout)
        for path in extra:
            path.unlink()
        cases = {
            "must match the file name": (prop, VALID_PROPERTY.replace("id: prop-json-round-trip", "id: prop-other-name")),
            "status must be": (prop, VALID_PROPERTY.replace("status: candidate", "status: approved")),
            "at least two separate changes": (rule, VALID_RULE.replace("first change, second change", "first change")),
            "missing the '## Check' section": (rule, VALID_RULE.replace("## Check", "## Verify")),
            "looks like a secret": (prop, VALID_PROPERTY + "\npassword = hunter2-long-value\n"),
            "kind must be": (prop, VALID_PROPERTY.replace("kind: property", "kind: rule")),
            "seen-in lists the same item more than once: first change": (
                rule, VALID_RULE.replace("first change, second change", "first change, First  change")),
            "front matter repeats the field 'tags'": (prop, VALID_PROPERTY.replace("tags:", "tags: a\ntags:")),
            "front matter lines must be": (prop, VALID_PROPERTY.replace("kind: property", "kind:property")),
        }
        for expected, (entry, text) in cases.items():
            with self.subTest(expected):
                original = entry.read_text(encoding="utf-8")
                self.write(entry, text)
                result = self.cli("library.py", "check", "--path", str(library), success=False)
                self.assertIn(expected, result.stderr)
                self.write(entry, original)
        # A rule seen in two changes stays adopted, with `#` kept inside each reference.
        self.write(rule, VALID_RULE.replace("first change, second change", "example/repo #12, example/repo #13"))
        self.cli("library.py", "check", "--path", str(library))
        self.write(rule, VALID_RULE.replace("first change, second change", "example/repo #12, example/repo #12"))
        result = self.cli("library.py", "check", "--path", str(library), success=False)
        self.assertIn("at least two separate changes", result.stderr)
        self.write(rule, VALID_RULE)
        self.write(library / "rules" / "prop-json-round-trip.md", VALID_PROPERTY)
        result = self.cli("library.py", "check", "--path", str(library), success=False)
        self.assertIn("duplicate id", result.stderr)

if __name__ == "__main__":
    unittest.main()
