"""Exercise project-owned properties and learned rules through the shipped CLI."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / "skills/i2e-astra-sol/scripts/i2e.py"


class CatalogSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.file = self.root / "verification" / "library.json"
        self.file.parent.mkdir()
        self.catalog = {
            "schema": "i2e-verification-catalog/v1",
            "features": {
                "words.count": {"entrypoint": "words.count", "checks": [
                    {"id": "append", "claim": "One extra word increases the count by one.",
                     "oracle": "Compare counts before and after appending the word."}]},
                "words.first": {"entrypoint": "words.first", "checks": [
                    {"id": "first", "claim": "The first word survives.", "oracle": "Compare with the first input."}]},
            },
            "rules": [{"id": "blank", "feature": "words.count", "status": "observe",
                       "case_digest": "a"*64, "examples": [{"input": [], "expected": 0}]},
                      {"id": "repeat", "feature": "words.count", "status": "enforced",
                       "case_digest": "b"*64, "examples": [{"input": ["a", "a"], "expected": 2}]}],
        }

    def select(self, *args):
        self.file.write_text(json.dumps(self.catalog), encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", str(CLI), "select-tools", "--surface", "api",
                              "--language", "python", "--catalog", "verification/library.json", *args],
                             cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertTrue(run.stdout.strip(), run.stderr)
        return run.returncode, json.loads(run.stdout)

    def test_project_feature_pins_portable_path_properties_and_rule_modes(self):
        code, plan = self.select("--feature", "words.count")
        self.assertEqual(0, code, plan)
        expected = {"feature": "words.count", "path": "verification/library.json", "root": "checkout",
                    "sha256": hashlib.sha256(self.file.read_bytes()).hexdigest(), "entrypoint": "words.count",
                    "checks": ["append"], "rules": [{"id": "blank", "status": "observe"},
                                                    {"id": "repeat", "status": "enforced"}]}
        self.assertEqual(expected, plan["catalog"])
        self.assertEqual("hypothesis", plan["properties"]["library"])
        code, other = self.select("--feature", "words.first")
        self.assertEqual((0, [], ["first"]), (code, other["catalog"]["rules"], other["catalog"]["checks"]))

    def test_unknown_or_unscoped_feature_does_not_select(self):
        for args in [[], ["--feature", "absent"]]:
            with self.subTest(args=args):
                code, record = self.select(*args)
                self.assertEqual((1, "BLOCK"), (code, record["state"]))

    def test_invalid_rule_cannot_drop_out_or_become_enforced(self):
        for field, value in [("feature", "typo"), ("status", "any"), ("case_digest", "unknown"), ("examples", [])]:
            with self.subTest(field=field):
                original = self.catalog["rules"][0][field]
                self.catalog["rules"][0][field] = value
                code, record = self.select("--feature", "words.count")
                self.assertEqual((1, "BLOCK"), (code, record["state"]))
                self.catalog["rules"][0][field] = original
