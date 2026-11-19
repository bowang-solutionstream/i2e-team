"""Stage and verify exact package bytes through the public packaging CLI."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import test_four_behavior_repair as a1
import test_i2e_team as legacy


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "package_v2.py"
SOURCE = ROOT / "skills" / "i2e-team"
INVENTORY = {
    "SKILL.md", "agents/openai.yaml", "agents/i2e_team_sol.toml", "agents/i2e_team_astra.toml",
    "scripts/i2e.py", "scripts/v2_contract.py", "scripts/v2_runtime.py",
    "scripts/worker_adapter.py", "scripts/github_adapter.py", "scripts/verify_labels.py",
    "scripts/critical_flow.py", "scripts/critical_issues.py", "scripts/critical_routing.py",
    "scripts/critical_speckit.py", "references/critical-four-rounds.md",
    "references/runtime.md", "references/runtime-v1.md", "references/settings.md",
    "references/teaching.md", "references/records-v2.md", "references/policy.md",
    "references/execution.md", "references/verification.md", "references/delivery.md", "references/adoption.md",
    "references/label-verification.json",
    "prompts/plan-review.md", "prompts/implementation.md", "prompts/verification.md",
}


def digest(body):
    return hashlib.sha256(body).hexdigest()


class PackageV2Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="i2e-v2-package-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def invoke(self, *args, passing=True):
        command = [a1.PYTHON, "-B", str(PACKAGER), *map(str, args)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(passing, result.returncode == 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("PASS" if passing else "BLOCK", payload["state"], payload)
        return payload

    def stage(self, destination, *, source=SOURCE, passing=True):
        return self.invoke("stage", "--source", source, "--dest", destination, passing=passing)

    def test_exact_archive_manifest_and_extraction_readback(self):
        dest, extraction = self.root / "staged", self.root / "readback"
        staged = self.stage(dest)
        self.assertEqual("STAGED_NOT_INSTALLED", staged["status"])
        manifest = json.loads((dest / "manifest.json").read_bytes())
        self.assertEqual("i2e-team-package-v2", manifest["schema"])
        self.assertEqual("STAGED_NOT_INSTALLED", manifest["status"])
        self.assertEqual(INVENTORY, set(manifest["files"]))
        dependency = manifest["external_dependencies"]["canonical_case_helper"]
        self.assertEqual(("shared_cases.py", True, False),
                         (dependency["entrypoint"], dependency["required"], dependency["bundled"]))
        archive = dest / manifest["archive"]["path"]
        self.assertEqual(manifest["archive"]["sha256"], digest(archive.read_bytes()))
        with tarfile.open(archive, "r:gz") as tar:
            self.assertTrue(all(member.isfile() or member.isdir() for member in tar.getmembers()))
            contents = {member.name.removeprefix("i2e-team/"): tar.extractfile(member).read()
                        for member in tar.getmembers() if member.isfile()}
        self.assertEqual(INVENTORY, set(contents))
        for name, body in contents.items():
            self.assertEqual((SOURCE / name).read_bytes(), body, name)
            self.assertEqual({"sha256": digest(body), "size": len(body)}, manifest["files"][name])
        checked = self.invoke("verify", "--package", dest, "--extract", extraction)
        self.assertEqual("STAGED_NOT_INSTALLED", checked["status"])
        for name, body in contents.items():
            self.assertEqual(body, (extraction / "i2e-team" / name).read_bytes(), name)

    def test_older_complete_package_verifies_but_partial_role_pair_is_rejected(self):
        packager = runpy.run_path(str(PACKAGER))
        previous = {p for p in INVENTORY if not p.startswith(("scripts/critical_", "references/critical-"))}
        legacy_names = previous - {"agents/i2e_team_sol.toml", "agents/i2e_team_astra.toml"}
        for label, names, valid in (("previous", previous, True), ("original", legacy_names, True),
                                    ("partial", legacy_names | {"agents/i2e_team_sol.toml"}, False)):
            with self.subTest(label=label):
                dest, extraction = self.root / label, self.root / (label + "-readback")
                dest.mkdir()
                payload = {name: b"fixture\n" for name in names}
                archive = gzip.compress(packager["tar_bytes"](payload), mtime=0)
                (dest / "i2e-team.tar.gz").write_bytes(archive)
                (dest / "manifest.json").write_text(json.dumps(packager["manifest_for"](payload, archive)))
                self.invoke("verify", "--package", dest, "--extract", extraction, passing=valid)
                if valid:
                    self.assertEqual({Path(n).name for n in names if n.startswith("agents/")},
                                     {p.name for p in (extraction / "i2e-team/agents").iterdir()})
                else:
                    self.assertFalse(extraction.exists())

    def test_readback_selects_tools_and_pins_the_actual_catalog(self):
        dest, extracted = self.root / "package", self.root / "readback"
        self.stage(dest)
        self.invoke("verify", "--package", dest, "--extract", extracted)
        skill = extracted / "i2e-team"
        command = [a1.PYTHON, "-B", str(skill / "scripts/i2e.py"), "select-tools"]

        def select(*args, expected=0):
            result = subprocess.run([*command, *args], cwd=self.root, capture_output=True, text=True, timeout=15)
            self.assertEqual(expected, result.returncode, (result.stdout, result.stderr))
            return json.loads(result.stdout)

        selected = select("--surface", "web", "--language", "typescript", "--feature", "labels.normalize")
        self.assertEqual("SELECTED", selected["state"])
        self.assertEqual("chrome-devtools-mcp", selected["e2e"]["driver"])
        self.assertEqual("fast-check", selected["properties"]["library"])
        catalog = selected["catalog"]
        self.assertEqual(digest((skill / catalog["path"]).read_bytes()), catalog["sha256"])
        self.assertEqual("BLOCK", select("--surface", "web", "--feature", "absent", expected=1)["state"])
        self.assertEqual("BLOCK", select(expected=1)["state"])
        self.assertNotIn("e2e", select("--language", "python"))
        self.assertNotIn("properties", select("--surface", "api"))

    def test_refuses_conflicting_destination_and_preserves_existing_bytes(self):
        dest = self.root / "existing"
        dest.mkdir()
        marker = dest / "owner-file"
        marker.write_bytes(b"preserve")
        self.stage(dest, passing=False)
        self.assertEqual([marker], list(dest.iterdir()))
        self.assertEqual(b"preserve", marker.read_bytes())
        fresh = self.root / "once"
        self.stage(fresh)
        before = (fresh / "manifest.json").read_bytes()
        self.stage(fresh, passing=False)
        self.assertEqual(before, (fresh / "manifest.json").read_bytes())

    def test_refuses_broken_link_secret_and_unsafe_file_aliases(self):
        for scenario in ("broken-link", "secret", "symlink", "hardlink"):
            with self.subTest(scenario=scenario):
                source = self.root / ("skill-" + scenario)
                shutil.copytree(SOURCE, source)
                protected = self.root / ("outside-" + scenario)
                protected.write_text("Synthetic protected bytes.")
                if scenario == "broken-link":
                    entry = source / "SKILL.md"
                    entry.write_text(entry.read_text() + "\n[Missing reference](references/missing.md)\n")
                elif scenario == "secret":
                    (source / ".env").write_text("SYNTHETIC_PLACEHOLDER=fixture\n")
                else:
                    target = source / "references" / "settings.md"
                    target.unlink()
                    if scenario == "symlink":
                        target.symlink_to(protected)
                    else:
                        os.link(protected, target)
                dest = self.root / ("rejected-" + scenario)
                self.stage(dest, source=source, passing=False)
                self.assertFalse(dest.exists())
                self.assertEqual("Synthetic protected bytes.", protected.read_text())

    def test_verify_refuses_tampered_archive_before_extraction(self):
        dest, extraction = self.root / "staged", self.root / "unused-extraction"
        self.stage(dest)
        manifest = json.loads((dest / "manifest.json").read_bytes())
        archive = dest / manifest["archive"]["path"]
        archive.write_bytes(archive.read_bytes() + b"synthetic trailing bytes")
        self.invoke("verify", "--package", dest, "--extract", extraction, passing=False)
        self.assertFalse(extraction.exists())

    def test_platform_var_alias_is_canonicalized_but_user_alias_is_refused(self):
        if sys.platform != "darwin" or self.root.parts[:3] != ("/", "private", "var"):
            self.skipTest("Host fixture has no applicable macOS /var alias")
        via_var = Path("/var", *self.root.parts[3:]) / "macos-stage"
        self.stage(via_var)
        self.assertTrue((self.root / "macos-stage" / "manifest.json").is_file())
        other = self.root / "target"
        other.mkdir()
        alias = self.root / "user-alias"
        alias.symlink_to(other, target_is_directory=True)
        self.stage(alias / "no-write", passing=False)
        self.assertEqual([], list(other.iterdir()))

    def test_public_cli_exposes_worker_and_delivery_operations(self):
        for command, operations in (
            ("worker", ("prepare", "qualify", "run", "status", "revoke", "submit", "admit", "cleanup")),
            ("delivery", ("inspect", "prepare", "execute", "reconcile")),
        ):
            with self.subTest(command=command):
                result = subprocess.run([a1.PYTHON, "-B", str(legacy.SCRIPT), command, "--help"],
                                        cwd=self.root, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                for operation in operations:
                    self.assertIn(operation, result.stdout)

    def test_verify_refuses_link_member_even_with_matching_archive_digest(self):
        dest, extraction = self.root / "staged", self.root / "unused-extraction"
        self.stage(dest)
        manifest_path = dest / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        archive = dest / manifest["archive"]["path"]
        replacement = self.root / "replacement.tar.gz"
        with tarfile.open(archive, "r:gz") as original, tarfile.open(replacement, "w:gz") as changed:
            for member in original.getmembers():
                if member.name == "i2e-team/references/settings.md":
                    link = tarfile.TarInfo(member.name)
                    link.type = tarfile.SYMTYPE
                    link.linkname = "runtime.md"
                    changed.addfile(link)
                else:
                    changed.addfile(member, original.extractfile(member) if member.isfile() else None)
        archive.write_bytes(replacement.read_bytes())
        manifest["archive"]["sha256"] = digest(archive.read_bytes())
        if "size" in manifest["archive"]:
            manifest["archive"]["size"] = archive.stat().st_size
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        sibling = self.root / "sibling-marker"
        sibling.write_bytes(b"preserve synthetic sibling")
        blocked = self.invoke("verify", "--package", dest, "--extract", extraction, passing=False)
        self.assertTrue(any(word in " ".join(blocked["errors"]).casefold()
                            for word in ("link", "member", "regular")), blocked)
        self.assertFalse(extraction.exists())
        self.assertEqual(b"preserve synthetic sibling", sibling.read_bytes())
