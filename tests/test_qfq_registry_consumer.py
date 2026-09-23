"""CODE consumes DATA's dataset registry for published qfq; synthetic-only."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import polars as pl

from quantlab.data.base import DataRequest
from quantlab.data.mqc import MQCParquetProvider
from quantlab.domain import Timeframe


class QFQRegistryConsumerTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.symbol = "sh.600000"
        self.old = self.root / "lake/silver/qfq_kline_daily"
        self.new = self.root / "lake/silver/qfq_kline_daily_v2"
        self.min5 = self.root / "lake/silver/qfq_kline_min5_v2"
        self.old.mkdir(parents=True)
        self.new.mkdir(parents=True)
        self.min5.mkdir(parents=True)
        (self.new / "_meta").mkdir()

        self.start = date(2026, 1, 5)
        rows = []
        for n in range(3):
            d = self.start + timedelta(days=n)
            rows.append({
                "date": d, "code": self.symbol, "open": 20.0 + n, "high": 21.0 + n,
                "low": 19.0 + n, "close": 20.5 + n, "volume": 1000.0,
                "amount": 20000.0, "factor": 1.0,
            })
        pl.DataFrame(rows).write_parquet(self.new / "sh_600000.parquet")
        minute_rows = []
        for n in (1, 2):
            d = self.start + timedelta(days=n)
            minute_rows.append({
                "date": d, "time": d.strftime("%Y%m%d") + "093500000",
                "code": self.symbol, "open": 20.0 + n, "high": 21.0 + n,
                "low": 19.0 + n, "close": 20.5 + n, "volume": 1000.0,
                "amount": 20000.0, "factor": 1.0,
            })
        pl.DataFrame(minute_rows).write_parquet(self.min5 / "sh_600000.parquet")
        pl.DataFrame([
            {**row, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5}
            for row in rows
        ]).write_parquet(self.old / "sh_600000.parquet")
        self.write_coverage(truncated=True)
        self.write_registry()

    def write_coverage(self, *, truncated=True, extra=(), include_flag=True):
        rows = [{"code": self.symbol, "valid_from": self.start.isoformat(),
                 "rows_raw": 3, "rows_qfq": 3, "events_accepted": 1,
                 "events_blocked": 0, "history_truncated": truncated}, *extra]
        frame = pl.DataFrame(rows)
        if not include_flag:
            frame = frame.drop("history_truncated")
        frame.write_parquet(self.new / "_meta/coverage.parquet")

    def write_registry(self, *, daily_path="lake/silver/qfq_kline_daily_v2"):
        catalog = self.root / "catalog"
        catalog.mkdir(exist_ok=True)
        body = {
            "format": "niuniu-dataset-registry-v1",
            "datasets": {
                "bars.daily.qfq": {
                    "status": "current", "kind": "per_symbol_parquet", "path": daily_path,
                    "qualification": "research_only", "producer": "DATA-test",
                },
                "bars.min5.qfq": {
                    "status": "current", "kind": "per_symbol_parquet",
                    "path": "lake/silver/qfq_kline_min5_v2",
                    "qualification": "research_only", "producer": "DATA-test",
                },
            },
        }
        (catalog / "dataset_registry.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8")

    def request(self, start=None):
        return DataRequest(
            (self.symbol,), Timeframe.DAILY, start or self.start, self.start + timedelta(days=2))

    def test_registry_selects_published_v2_not_legacy_qfq(self):
        batch = MQCParquetProvider(self.root, "qfq").load(self.request())
        self.assertEqual(batch.bars["close"][0], 20.5)
        self.assertIn("qfq_kline_daily_v2", batch.snapshot.files[0]["path"])

    def test_request_before_data_valid_from_is_blocked_without_fallback(self):
        with self.assertRaisesRegex(ValueError, "DATA未提供.*不会回退旧qfq"):
            MQCParquetProvider(self.root, "qfq").load(
                self.request(self.start - timedelta(days=1)))

    def test_min5_request_before_published_file_start_is_not_silently_truncated(self):
        request = DataRequest(
            (self.symbol,), Timeframe.MIN5, self.start, self.start + timedelta(days=2))
        with self.assertRaisesRegex(ValueError, "DATA未提供.*不会回退旧qfq"):
            MQCParquetProvider(self.root, "qfq").load(request)

    def test_untruncated_history_starts_at_listing_like_raw(self):
        # history_truncated=false: valid_from is only where the security's history begins.
        self.write_coverage(truncated=False)
        batch = MQCParquetProvider(self.root, "qfq").load(self.request(self.start - timedelta(days=10)))
        self.assertEqual(batch.bars.height, 3)
        self.assertEqual(batch.bars["datetime"][0].date(), self.start)

    def test_later_listed_security_does_not_fail_the_whole_request(self):
        late, listed = "sz.000001", self.start + timedelta(days=1)
        pl.DataFrame([{
            "date": listed + timedelta(days=n), "code": late, "open": 5.0, "high": 5.5,
            "low": 4.5, "close": 5.2, "volume": 100.0, "amount": 500.0, "factor": 1.0,
        } for n in range(2)]).write_parquet(self.new / "sz_000001.parquet")
        self.write_coverage(truncated=False, extra=[{
            "code": late, "valid_from": listed.isoformat(), "rows_raw": 2, "rows_qfq": 2,
            "events_accepted": 0, "events_blocked": 0, "history_truncated": False}])
        request = DataRequest((self.symbol, late), Timeframe.DAILY, self.start, self.start + timedelta(days=2))
        bars = MQCParquetProvider(self.root, "qfq").load(request).bars
        self.assertEqual(bars.filter(pl.col("symbol") == late).height, 2)
        self.assertEqual(bars.filter(pl.col("symbol") == self.symbol).height, 3)

    def test_truncated_security_still_blocks_mixed_request(self):
        late = "sz.000001"
        pl.DataFrame([{
            "date": self.start + timedelta(days=1), "code": late, "open": 5.0, "high": 5.5,
            "low": 4.5, "close": 5.2, "volume": 100.0, "amount": 500.0, "factor": 1.0,
        }]).write_parquet(self.new / "sz_000001.parquet")
        self.write_coverage(truncated=False, extra=[{
            "code": late, "valid_from": (self.start + timedelta(days=1)).isoformat(), "rows_raw": 5,
            "rows_qfq": 1, "events_accepted": 0, "events_blocked": 1, "history_truncated": True}])
        request = DataRequest((self.symbol, late), Timeframe.DAILY, self.start, self.start + timedelta(days=2))
        with self.assertRaisesRegex(ValueError, "DATA未提供 sz.000001.*不会回退旧qfq"):
            MQCParquetProvider(self.root, "qfq").load(request)

    def test_coverage_without_truncation_flag_stays_strict(self):
        self.write_coverage(include_flag=False)
        with self.assertRaisesRegex(ValueError, "DATA未提供.*不会回退旧qfq"):
            MQCParquetProvider(self.root, "qfq").load(self.request(self.start - timedelta(days=1)))

    def test_missing_published_path_does_not_fallback_to_legacy(self):
        self.write_registry(daily_path="lake/silver/qfq_missing")
        with self.assertRaisesRegex(ValueError, "current directory missing"):
            MQCParquetProvider(self.root, "qfq").load(self.request())

    def test_legacy_root_without_registry_keeps_explicit_test_layout(self):
        (self.root / "catalog/dataset_registry.json").unlink()
        batch = MQCParquetProvider(self.root, "qfq").load(self.request())
        self.assertEqual(batch.bars["close"][0], 10.5)
        self.assertIn("qfq_kline_daily/sh_600000.parquet", batch.snapshot.files[0]["path"])


if __name__ == "__main__":
    import unittest
    unittest.main()
