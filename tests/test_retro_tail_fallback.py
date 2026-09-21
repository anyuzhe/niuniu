"""Opt-in raw-daily retro tail fallback: pointer parsing + MQC integration.

All fixtures are synthetic TemporaryDirectory parquet/frames; no real data root or
retro pack is read. Verifies: pointer validation, raw-only tail append with
per-symbol dedup, snapshot identity absorbing the retro source, qfq guard, and
byte-identical behaviour when no pointer/retro_tail is configured.
"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.data.base import DataRequest
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.provider import local_data_provider
from quantlab.data.retro_tail import RetroTail, load_pointer, pointer_path
from quantlab.domain import Timeframe

TZ = ZoneInfo("Asia/Shanghai")


def _baostock_daily(path: Path, symbol: str, days):
    rows = {
        "date": days,
        "code": [symbol] * len(days),
        "open": [10.0 + i for i in range(len(days))],
        "high": [11.0 + i for i in range(len(days))],
        "low": [9.0 + i for i in range(len(days))],
        "close": [10.5 + i for i in range(len(days))],
        "volume": [1000.0 + i for i in range(len(days))],
        "amount": [10500.0 + i for i in range(len(days))],
        "adjustflag": ["3"] * len(days),
        "factor": [1.0] * len(days),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


def _tail_frame(symbol, day_tuples):
    # day_tuples: list of (date, close); one row on/after coverage boundary
    dates = [d for d, _ in day_tuples]
    closes = [c for _, c in day_tuples]
    dt = [datetime(d.year, d.month, d.day, 15, tzinfo=TZ) for d in dates]
    return pl.DataFrame({
        "date": dates,
        "symbol": [symbol] * len(dates),
        "exchange": [symbol[:2]] * len(dates),
        "datetime": dt,
        "available_at": dt,
        "timeframe": ["1d"] * len(dates),
        "open": [c - 0.5 for c in closes],
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [2000.0] * len(dates),
        "turnover": [21000.0] * len(dates),
        "adj_factor": [1.0] * len(dates),
    })


class StubTail:
    def __init__(self, frame, files):
        self._frame = frame
        self._files = files
        self.called = False

    def tail_bars(self, request):
        self.called = True
        return self._frame, self._files


class PointerTests(unittest.TestCase):
    def test_absent_pointer_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_pointer(d))

    def test_invalid_or_symlink_pointer_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = pointer_path(root)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"format": "wrong"}))
            self.assertIsNone(load_pointer(root))  # bad format
            p.write_text("not json")
            self.assertIsNone(load_pointer(root))  # bad json
            p.unlink()
            # symlinked pointer must be rejected
            real = root / "real.json"
            real.write_text(json.dumps({"format": "retro-daily-tail-pointer-v1", "capture_path": str(root)}))
            p.symlink_to(real)
            self.assertIsNone(load_pointer(root))

    def test_valid_pointer_but_missing_capture_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = pointer_path(root)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"format": "retro-daily-tail-pointer-v1",
                                     "capture_path": str(root / "nope" / "cap")}))
            self.assertIsNone(load_pointer(root))


class MqcFallbackTests(unittest.TestCase):
    def _root_with_daily(self, symbol="sh.600000", days=(date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4))):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        _baostock_daily(root / "lake/bronze/provider=baostock/stock_kline_daily" / f"{symbol.replace('.', '_')}.parquet", symbol, list(days))
        return root

    def test_raw_tail_appended_and_deduped(self):
        root = self._root_with_daily()
        # tail includes a duplicate 09-04 (== coverage) that must be dropped
        tail = _tail_frame("sh.600000", [(date(2026, 9, 4), 99.0), (date(2026, 9, 5), 20.0), (date(2026, 9, 8), 23.0)])
        stub = StubTail(tail, [{"role": "raw_daily_tail", "retro_capture_id": "cap"}])
        prov = MQCParquetProvider(root, "raw", retro_tail=stub)
        batch = prov.load(DataRequest(("sh.600000",), Timeframe.DAILY, date(2026, 9, 1), date(2026, 9, 8)))
        bars = batch.bars
        self.assertTrue(stub.called)
        dates = sorted({d.date() for d in bars["datetime"].to_list()})
        self.assertEqual(dates, [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 8)])
        # 09-04 came from Baostock (close 13.5), not the tail stub (99.0)
        sep4 = bars.filter(pl.col("datetime").dt.date() == date(2026, 9, 4))["close"].to_list()
        self.assertEqual(sep4, [13.5])
        # snapshot identity absorbed the retro source
        self.assertTrue(any(isinstance(f, dict) and f.get("role") == "raw_daily_tail" for f in batch.snapshot.files))

    def test_qfq_never_uses_tail(self):
        root = self._root_with_daily()
        # build a qfq file too (adjustflag irrelevant for qfq path)
        _baostock_daily(root / "lake/silver/qfq_kline_daily" / "sh_600000.parquet", "sh.600000",
                        [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)])
        stub = StubTail(_tail_frame("sh.600000", [(date(2026, 9, 5), 20.0)]), [{"role": "raw_daily_tail"}])
        prov = MQCParquetProvider(root, "qfq", retro_tail=stub)
        batch = prov.load(DataRequest(("sh.600000",), Timeframe.DAILY, date(2026, 9, 1), date(2026, 9, 8)))
        self.assertFalse(stub.called)  # qfq must not consult the retro tail
        self.assertEqual(batch.bars["datetime"].max().date(), date(2026, 9, 4))

    def test_no_tail_is_unchanged(self):
        root = self._root_with_daily()
        prov = MQCParquetProvider(root, "raw")  # retro_tail defaults None
        batch = prov.load(DataRequest(("sh.600000",), Timeframe.DAILY, date(2026, 9, 1), date(2026, 9, 4)))
        self.assertEqual(batch.bars.height, 4)
        self.assertFalse(any(isinstance(f, dict) and f.get("role") == "raw_daily_tail" for f in batch.snapshot.files))

    def test_local_provider_wires_pointer(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cap = root / "ws" / "_market_data" / "retro_daily" / "cap-id"
            cap.mkdir(parents=True)
            _baostock_daily(root / "lake/bronze/provider=baostock/stock_kline_daily" / "sh_600000.parquet", "sh.600000",
                            [date(2026, 9, 4)])
            p = pointer_path(root)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"format": "retro-daily-tail-pointer-v1",
                                     "capture_path": str(cap), "coverage_end": "2026-09-15", "digest": "0" * 64}))
            prov = local_data_provider(root, "raw")
            self.assertIsInstance(prov.retro_tail, RetroTail)
            self.assertEqual(prov.retro_tail.coverage_end, "2026-09-15")
            # qfq path leaves retro_tail unset
            self.assertIsNone(local_data_provider(root, "qfq").retro_tail)


if __name__ == "__main__":
    unittest.main()
