"""Tests for the chain and the freeze.

Run: python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from precheck import core  # noqa: E402

PY = sys.executable.replace("\\", "/")
OK_CHECK = '"%s" -c "pass"' % PY


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="precheck-test-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _commitments(self):
        return {"version": 1, "commitments": [
            {"id": "C1", "statement": "the trivial thing is true",
             "check": OK_CHECK, "artifacts": ["a.txt"]}]}

    def test_register_then_verify_is_clean(self):
        core.save_commitments(self.root, self._commitments())
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("hello\n")
        core.append(self.root, "register",
                    {"commitments_sha256": core.commitments_hash(self.root)})
        res = core.verify(self.root)
        self.assertTrue(res["ok"], res["findings"])
        self.assertEqual(res["entries"], 1)

    def test_chain_links_hold_over_several_entries(self):
        core.save_commitments(self.root, self._commitments())
        core.append(self.root, "register",
                    {"commitments_sha256": core.commitments_hash(self.root)})
        for i in range(3):
            core.append(self.root, "settle", {"results": [{"id": "C1", "exit": 0}]})
        entries = core.read_ledger(self.root)
        self.assertEqual([e["seq"] for e in entries], [1, 2, 3, 4])
        self.assertIsNone(entries[0]["prev"])
        for prev, cur in zip(entries, entries[1:]):
            self.assertEqual(cur["prev"], prev["hash"])
        self.assertEqual(len({e["hash"] for e in entries}), 4)
        self.assertTrue(core.verify(self.root)["ok"])

    def test_editing_commitments_after_register_is_detected(self):
        core.save_commitments(self.root, self._commitments())
        core.append(self.root, "register",
                    {"commitments_sha256": core.commitments_hash(self.root)})
        self.assertTrue(core.verify(self.root)["ok"])

        # the actor rewrites its own exam after the fact
        data = self._commitments()
        data["commitments"][0]["check"] = '"%s" -c "pass"' % PY
        data["commitments"][0]["statement"] = "a much easier thing"
        core.save_commitments(self.root, data)

        res = core.verify(self.root)
        self.assertFalse(res["ok"])
        self.assertIn("COMMITMENTS_MODIFIED", [f["code"] for f in res["findings"]])

    def test_editing_a_ledger_entry_is_detected(self):
        core.save_commitments(self.root, self._commitments())
        core.append(self.root, "register",
                    {"commitments_sha256": core.commitments_hash(self.root)})
        core.append(self.root, "settle", {"results": [{"id": "C1", "verdict": "FAIL"}]})

        path = core.ledger_path(self.root)
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        # rewrite the recorded verdict to look like a pass, leave the hash alone
        entry = json.loads(lines[-1])
        entry["results"][0]["verdict"] = "PASS"
        lines[-1] = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")

        res = core.verify(self.root)
        self.assertFalse(res["ok"])
        self.assertIn("HASH_MISMATCH", [f["code"] for f in res["findings"]])

    def test_deleting_an_entry_breaks_a_link(self):
        core.save_commitments(self.root, self._commitments())
        for i in range(3):
            core.append(self.root, "settle", {"results": [], "n": i})
        path = core.ledger_path(self.root)
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        del lines[2]  # remove a middle entry, renumber nothing
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        res = core.verify(self.root)
        self.assertFalse(res["ok"])
        codes = [f["code"] for f in res["findings"]]
        self.assertTrue("SEQ_GAP" in codes or "BROKEN_LINK" in codes, codes)

    def test_unregistered_ledger_is_flagged(self):
        core.save_commitments(self.root, self._commitments())
        core.append(self.root, "settle", {"results": []})
        res = core.verify(self.root)
        self.assertFalse(res["ok"])
        self.assertIn("NOT_REGISTERED", [f["code"] for f in res["findings"]])

    def test_canonical_is_order_independent(self):
        a = core.canonical({"x": 1, "y": [2, {"b": 1, "a": 2}]})
        b = core.canonical({"y": [2, {"a": 2, "b": 1}], "x": 1})
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
