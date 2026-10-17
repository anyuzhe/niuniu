from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect import fundamentals_history as fh  # noqa: E402


class ValuationFreshnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bronze = Path(tmp.name)
        self.base = self.bronze / "provider=baostock" / "valuation_daily_v1"
        self.base.mkdir(parents=True)
        patch = mock.patch.object(fh, "BRONZE", self.bronze)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, code, *days):
        pd.DataFrame({"date": list(days), "code": code}).to_parquet(self.base / f"{code}.parquet", index=False)

    def update(self, through, min_age=0):
        args = argparse.Namespace(dataset="valuation", through=through, shard=None, min_age_days=min_age)
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(fh, "update_valuation", return_value={"done": 3, "failed": 0}) as run:
            code = fh.update_cmd(args)
        return code, json.loads(out.getvalue().strip().splitlines()[-1]), run

    def test_the_freshest_file_in_the_sample_stands_for_the_last_update(self):
        self.write("sh_600001", "2026-10-15", "2026-10-16")
        self.write("sh_600002", "2026-09-10")            # suspended long ago
        self.assertEqual(fh.valuation_last_date(), date(2026, 10, 16))

    def test_nothing_to_read_gives_none_and_an_unreadable_file_is_passed_over(self):
        self.assertIsNone(fh.valuation_last_date())
        (self.base / "sh_600009.parquet").write_bytes(b"not a parquet file")
        self.write("sh_600001", "2026-10-14")
        self.assertEqual(fh.valuation_last_date(), date(2026, 10, 14))

    def test_fresh_valuation_is_skipped_and_says_how_far_it_reaches(self):
        self.write("sh_600001", "2026-10-16")
        code, result, run = self.update("2026-10-19", min_age=7)
        run.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual((result["skipped"], result["last_date"], result["done"]), ("fresh", "2026-10-16", 0))

    def test_valuation_a_week_old_is_updated(self):
        self.write("sh_600001", "2026-10-16")
        code, result, run = self.update("2026-10-23", min_age=7)
        run.assert_called_once()
        self.assertEqual((code, result["done"]), (0, 3))

    def test_without_the_option_every_run_updates(self):
        self.write("sh_600001", "2026-10-16")
        _, _, run = self.update("2026-10-17")
        run.assert_called_once()

    def test_an_empty_dataset_is_always_updated(self):
        _, _, run = self.update("2026-10-17", min_age=7)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
