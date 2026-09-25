"""Tests for the vacuity audit -- the part that asks whether a check can fail.

Run: python -m unittest discover -s tests -v
"""
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from precheck import core, vacuity  # noqa: E402

PY = sys.executable.replace("\\", "/")

WEAK = (
    "import os, sys\n"
    "sys.exit(0 if os.path.exists('data.txt') else 1)\n"
)
STRONG = (
    "import sys\n"
    "t = open('data.txt', encoding='utf-8').read()\n"
    "n = len([l for l in t.split('\\n') if l.strip()])\n"
    "sys.exit(0 if n == 3 else 1)\n"
)


class MutationTest(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(0)

    def test_drop_line_removes_one_filled_line(self):
        out, detail = vacuity.mutate("drop-line", "a\nb\nc\n", random.Random(0))
        self.assertIsNotNone(out)
        self.assertEqual(len([l for l in out.split("\n") if l.strip()]), 2)
        self.assertIn("dropped line", detail)

    def test_truncate_shortens_the_file(self):
        out, detail = vacuity.mutate("truncate", "a\nb\nc\nd\n", random.Random(0))
        self.assertIsNotNone(out)
        self.assertLess(len(out), len("a\nb\nc\nd\n"))
        self.assertIn("truncated", detail)

    def test_flip_number_changes_the_number_and_says_so(self):
        out, detail = vacuity.mutate("flip-number", "timeout = 30\n", random.Random(0))
        self.assertIsNotNone(out)
        self.assertNotEqual(out.strip(), "timeout = 30")
        self.assertRegex(out, r"\d+")
        self.assertIn("30 ->", detail)

    def test_blank_value_neuters_a_json_scalar(self):
        out, detail = vacuity.mutate("blank-value", '{"replicas": 3}\n', random.Random(0))
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out)["replicas"], 0)
        self.assertIn("replicas", detail)
        out, detail = vacuity.mutate("blank-value", '{"name": "prod"}\n', random.Random(0))
        self.assertIsNotNone(out)
        self.assertEqual(json.loads(out)["name"], "")

    def test_mutations_are_deterministic_for_a_seed(self):
        a = vacuity.mutate("drop-line", "a\nb\nc\n", random.Random(7))
        b = vacuity.mutate("drop-line", "a\nb\nc\n", random.Random(7))
        self.assertEqual(a, b)

    def test_not_applicable_returns_none(self):
        self.assertEqual(vacuity.mutate("flip-number", "no digits here\n",
                                        random.Random(0)), (None, None))
        self.assertEqual(vacuity.mutate("drop-line", "\n\n", random.Random(0)),
                         (None, None))

    def test_binary_is_never_mutated(self):
        self.assertIsNone(vacuity.decode(b"\x00\x01\xff\xfe"))


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="precheck-vac-")
        with open(os.path.join(self.root, "check_weak.py"), "w") as f:
            f.write(WEAK)
        with open(os.path.join(self.root, "check_strong.py"), "w") as f:
            f.write(STRONG)
        self.original = "one\ntwo\nthree\n"
        with open(os.path.join(self.root, "data.txt"), "w", newline="") as f:
            f.write(self.original)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _commitments(self, script):
        return {"version": 1, "commitments": [
            {"id": "C1", "statement": "data.txt holds three records",
             "check": '"%s" %s' % (PY, script), "artifacts": ["data.txt"]}]}

    def test_weak_check_survives_mutation_and_is_reported(self):
        res = vacuity.audit(self.root, self._commitments("check_weak.py"), seed=0)
        self.assertGreater(res["examined"], 0)
        self.assertTrue(res["escaped"], "a check that only tests existence "
                                        "should survive at least one mutation")
        for e in res["escaped"]:
            self.assertIn("question", e)
            self.assertIn(e["mutation"], vacuity.MUTATIONS)

    def test_strong_check_catches_every_mutation(self):
        res = vacuity.audit(self.root, self._commitments("check_strong.py"), seed=0)
        self.assertGreater(res["examined"], 0)
        self.assertEqual(res["escaped"], [],
                         "a content-aware check must notice mutated content")

    def test_audit_restores_the_artifact_byte_for_byte(self):
        path = os.path.join(self.root, "data.txt")
        with open(path, "rb") as f:
            before = f.read()
        vacuity.audit(self.root, self._commitments("check_weak.py"), seed=0)
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_missing_artifact_is_skipped_not_crashed(self):
        c = {"version": 1, "commitments": [
            {"id": "C9", "statement": "x", "check": "true",
             "artifacts": ["nope.txt"]}]}
        res = vacuity.audit(self.root, c, seed=0)
        self.assertEqual(res["examined"], 0)
        self.assertEqual(res["skipped"][0]["artifact"], "nope.txt")

    def test_audit_can_be_recorded_in_the_chain(self):
        core.save_commitments(self.root, self._commitments("check_weak.py"))
        core.append(self.root, "register",
                    {"commitments_sha256": core.commitments_hash(self.root)})
        res = vacuity.audit(self.root, core.load_commitments(self.root), seed=0)
        core.append(self.root, "audit", {"escaped": res["escaped"]})
        self.assertTrue(core.verify(self.root)["ok"])


if __name__ == "__main__":
    unittest.main()
