"""Public-command checks for the opt-in label verification pack."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills/i2e-astra-sol"
VERIFIER = SKILL / "scripts/verify_labels.py"
CATALOG = SKILL / "references/label-verification.json"
CORRECT = "def read(values):\n    return [' '.join(s.split()) for s in values]\n"


class LabelPackTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.target = Path(scratch.name)
        self.reader = self.target / "reader.py"
        self.reader.write_text(CORRECT)

    def verify(self, feature="labels.normalize", catalog=None):
        cmd = [sys.executable, "-IB", str(VERIFIER), "--repo", str(self.target), "--feature", feature]
        if catalog is not None:
            path = self.target / "catalog.json"
            path.write_text(json.dumps(catalog))
            cmd.extend(["--catalog", str(path)])
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return process.returncode, json.loads(process.stdout)

    def test_generated_inputs_and_mutation_are_observable(self):
        code, report = self.verify()
        self.assertEqual((0, "PASS"), (code, report["state"]))
        self.assertEqual([1, 287, 293], [check["samples"] for check in report["checks"]])
        self.reader.write_text("import re\ndef read(values):\n    return [re.sub(r'\\s+', ' ', s.strip(), count=1) for s in values]\n")
        code, report = self.verify()
        self.assertEqual((1, "FAIL"), (code, report["state"]))
        self.assertEqual(180, report["checks"][1]["failures"])
        self.reader.write_text("def read(values):\n    values[:] = [' '.join(s.split()) for s in values]\n    return values\n")
        code, report = self.verify()
        self.assertEqual(1, code)
        self.assertEqual("FAIL", report["checks"][2]["state"])

    def test_order_property_rejects_reversal_without_relying_on_the_user_scenario(self):
        self.reader.write_text("def read(values):\n    return [' '.join(s.split()) for s in reversed(values)]\n")
        code, report = self.verify()
        shape = next(row for row in report["checks"] if row["id"] == "labels.normalize.shape_input_idempotence.v1")
        self.assertEqual(1, code)
        self.assertEqual("FAIL", shape["state"])
        self.assertGreater(shape["failures"], 0)

    def test_wrong_feature_missing_target_and_empty_catalog_do_not_pass(self):
        code, report = self.verify("unrelated.feature")
        self.assertEqual((3, "NOT_APPLICABLE", []), (code, report["state"], report["checks"]))
        self.reader.unlink()
        code, report = self.verify()
        self.assertEqual((2, "ERROR", []), (code, report["state"], report["checks"]))
        self.reader.write_text(CORRECT)
        catalog = json.loads(CATALOG.read_text())
        catalog["features"]["labels.normalize"]["checks"] = []
        code, report = self.verify(catalog=catalog)
        self.assertEqual((2, "ERROR"), (code, report["state"]))

    def test_example_rule_attributes_only_an_output_mismatch(self):
        catalog = json.loads(CATALOG.read_text())
        catalog["rules"] = [{"id": "label-example-test", "feature": "labels.normalize",
                             "status": "observe", "claim": "Whitespace leaves the original text intact.",
                             "case_digest": "0" * 64, "examples": [{"input": ["  a "], "expected": ["a"]}]}]
        self.reader.write_text("def read(values):\n    values[:] = [' '.join(s.split()) for s in values]\n    return values\n")
        code, report = self.verify(catalog=catalog)
        self.assertEqual((1, "FAIL"), (code, report["checks"][2]["state"]))
        self.assertEqual(("PASS", False), (report["rules"][0]["state"], report["rules"][0]["would_fail"]))

    def test_checked_in_unicode_rule_distinguishes_observation_and_enforcement(self):
        self.reader.write_text("import unicodedata\ndef read(values):\n    return [unicodedata.normalize('NFC', ' '.join(s.split())) for s in values]\n")
        code, report = self.verify()
        row = next(item for item in report["rules"] if item["id"] == "labels.normalize.preserve_unicode_spelling.v1")
        self.assertEqual((1, "FAIL", "pilot_enforced"), (code, row["state"], row["status"]))
        self.assertGreater(row["failures"], 0)
        catalog = json.loads(CATALOG.read_text())
        next(item for item in catalog["rules"] if item["id"] == row["id"])["status"] = "observe"
        code, observed = self.verify(catalog=catalog)
        self.assertEqual((0, "PASS"), (code, observed["state"]))
        self.assertTrue(next(item for item in observed["rules"] if item["id"] == row["id"])["would_fail"])


if __name__ == "__main__":
    unittest.main()
