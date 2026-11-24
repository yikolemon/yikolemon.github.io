"""基金快照校验与模板回归测试；只在临时目录写入数据。"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import fund


class FundSnapshotTests(unittest.TestCase):
    def setUp(self):
        fund.errors.clear()
        fund.warnings.clear()
        self.ids = ["held", "sold"]

    def snapshot(self, realized=None):
        return {
            "file": "2026-11-24.json", "date": "2026-11-24", "note": "",
            "holdings": [{"id": "held", "invested": 100, "value": 90}],
            "realized": {} if realized is None else realized,
        }

    def test_old_snapshot_without_realized_loads_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            body = self.snapshot()
            del body["realized"]
            with open(os.path.join(directory, body["file"]), "w", encoding="utf-8") as fh:
                json.dump(body, fh)
            with patch.object(fund, "SNAP_DIR", directory):
                self.assertEqual(fund.read_snapshots()[0]["realized"], {})

    def test_closed_and_negative_realized_are_valid(self):
        fund.check_snapshot(self.snapshot({"sold": -63.11}), None, self.ids)
        self.assertEqual(fund.errors, [])

    def test_invalid_realized_is_rejected(self):
        for value in ([], {"unknown": 1}, {"sold": "63.11"},
                      {"sold": True}, {"sold": float("nan")}, {"sold": float("inf")}):
            with self.subTest(value=value):
                fund.errors.clear()
                body = self.snapshot()
                body["realized"] = value
                fund.check_snapshot(body, None, self.ids)
                self.assertTrue(fund.errors)

    def test_realized_cannot_silently_disappear(self):
        fund.check_snapshot(self.snapshot(), self.snapshot({"sold": 63.11}), self.ids)
        self.assertTrue(any("realized" in msg for msg in fund.errors))

    def test_partial_sale_cost_reduction_is_allowed(self):
        current = self.snapshot({"held": 5})
        current["holdings"][0]["invested"] = 50
        fund.check_snapshot(current, self.snapshot(), self.ids)
        self.assertEqual(fund.errors, [])

    def test_new_template_preserves_realized_without_touching_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshots = os.path.join(directory, "snapshots")
            os.mkdir(snapshots)
            previous = self.snapshot({"sold": 63.11})
            path = os.path.join(snapshots, previous["file"])
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(previous, fh)
            with open(os.path.join(directory, "funds.json"), "w", encoding="utf-8") as fh:
                json.dump([{"id": fid} for fid in self.ids], fh)
            with patch.object(fund, "DATA_DIR", directory), patch.object(fund, "SNAP_DIR", snapshots):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(fund.cmd_new("2026-11-25"), 0)
                result = fund.load(os.path.join(snapshots, "2026-11-25.json"))
                self.assertEqual(result["realized"], {"sold": 63.11})
                self.assertEqual(result["holdings"], previous["holdings"])
                self.assertEqual(fund.load(path), previous)


if __name__ == "__main__":
    unittest.main()
