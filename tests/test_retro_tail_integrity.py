"""Integrity regression for the raw MQC retro tail (TemporaryDirectory + FakeSDK only)."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import polars as pl

from quantlab.data.base import DataRequest
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.provider import local_data_provider
from quantlab.data.retro_daily import BASIC_FIELDS, CALENDAR_FIELDS, FIELDS, RetroDailyStore
from quantlab.data.retro_tail import load_pointer, pointer_path
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest, encode


class Response:
    def __init__(self, fields, rows):
        self.fields = list(fields)
        self.rows = [list(row) for row in rows]
        self.error_code = "0"
        self.error_msg = "success"
        self.index = -1

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return list(self.rows[self.index])


class FakeSDK:
    __version__ = "synthetic-1"

    def __init__(self, basic, calendar, bars):
        self.basic, self.calendar, self.bars = basic, calendar, bars

    def login(self):
        return Response((), ())

    def logout(self):
        return Response((), ())

    def query_stock_basic(self):
        return Response(BASIC_FIELDS, self.basic)

    def query_trade_dates(self, start_date, end_date):
        return Response(CALENDAR_FIELDS, [row for row in self.calendar if start_date <= row[0] <= end_date])

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        assert fields == ",".join(FIELDS) and frequency == "d" and adjustflag == "3"
        return Response(FIELDS, [row for row in self.bars.get(code, ()) if start_date <= row[0] <= end_date])


def source_bar(day, symbol, value, *, suspended=False, null_amount=False):
    if suspended:
        return (day.isoformat(), symbol, "", "", "", "", str(value), "", "", "3", "", "0", "", "0")
    amount = "" if null_amount else str(value * 1000)
    return (day.isoformat(), symbol, str(value), str(value + 1), str(value - 1), str(value + .5),
            str(value - .5), "1000", amount, "3", "1.0", "1", "1.0", "0")


def write_mqc_daily(path: Path, symbol: str, days, *, base=10.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "date": list(days), "code": [symbol] * len(days),
        "open": [base + i for i in range(len(days))],
        "high": [base + i + 1 for i in range(len(days))],
        "low": [base + i - 1 for i in range(len(days))],
        "close": [base + i + .5 for i in range(len(days))],
        "volume": [1000.0 + i for i in range(len(days))],
        "amount": [10000.0 + i for i in range(len(days))],
        "adjustflag": ["3"] * len(days), "factor": [1.0] * len(days),
    }).write_parquet(path)


def write_mqc_min5(path: Path, symbol: str, day: date):
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "date": [day], "time": [day.strftime("%Y%m%d") + "093000000"], "code": [symbol],
        "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
        "volume": [1000.0], "amount": [10000.0], "adjustflag": ["3"], "factor": [1.0],
    }).write_parquet(path)


class RetroTailIntegrityTests(unittest.TestCase):
    symbols = ("sh.600000", "sz.000001")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.start, self.end = date(2026, 9, 1), date(2026, 9, 15)
        self.calendar_days = [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]
        self.sessions = [day for day in self.calendar_days if day.weekday() < 5]
        self.capture = self.make_capture("source")
        write_mqc_daily(self.data / "lake/bronze/provider=baostock/stock_kline_daily/sh_600000.parquet",
                        self.symbols[0], self.sessions[:4], base=10)
        write_mqc_daily(self.data / "lake/bronze/provider=baostock/stock_kline_daily/sz_000001.parquet",
                        self.symbols[1], self.sessions[:6], base=20)
        self.write_pointer(self.capture)

    def make_capture(self, name, *, bias=100.0, symbols=None, missing=None, suspended=None, null_amount=None):
        symbols = tuple(symbols or self.symbols)
        source = self.root / name
        source.mkdir()
        basic = [(symbol, symbol, "2000-01-01", "", "1", "1") for symbol in symbols]
        calendar = [(day.isoformat(), "1" if day.weekday() < 5 else "0") for day in self.calendar_days]
        missing, suspended, null_amount = missing or set(), suspended or set(), null_amount or set()
        bars = {}
        for position, symbol in enumerate(symbols):
            bars[symbol] = [source_bar(day, symbol, bias + position * 20 + index,
                                       suspended=(symbol, day) in suspended,
                                       null_amount=(symbol, day) in null_amount)
                            for index, day in enumerate(self.sessions) if (symbol, day) not in missing]
        sdk = FakeSDK(basic, calendar, bars)
        store = RetroDailyStore(source, now_fn=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc),
                                today_fn=lambda: date(2026, 9, 16))
        capture_id = store.create_plan(self.start, self.end, sdk=sdk)["capture_id"]
        fetched = store.fetch(capture_id, sdk=sdk)
        self.assertEqual(fetched["failed"], 0)
        store.consolidate(capture_id, confirmed=True, remove_originals=True)
        return source / "_market_data" / "retro_daily" / capture_id

    def write_pointer(self, capture: Path, *, coverage_end=None, digest_value=None, indent=None):
        store = RetroDailyStore(capture.parents[2])
        index_digest = digest(store.pack_index(capture.name))
        value = {"format": "retro-daily-tail-pointer-v1", "capture_path": str(capture.resolve()),
                 "coverage_end": (coverage_end or self.end).isoformat(),
                 "digest": digest_value or index_digest, "scope": "raw_daily_research_only"}
        path = pointer_path(self.data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, indent=indent), encoding="utf-8")
        return value

    def request(self, symbols, start=None, end=None, timeframe=Timeframe.DAILY):
        return DataRequest(tuple(symbols), timeframe, start or self.start, end or self.end)

    def test_tail_only_uses_real_packed_raw_and_typed_bytes(self):
        batch = local_data_provider(self.data, "raw").load(
            self.request((self.symbols[0],), date(2026, 9, 7), self.end)
        )
        self.assertEqual(batch.bars["datetime"].dt.date().to_list(), [day for day in self.sessions if day >= date(2026, 9, 7)])
        evidence = {item["role"]: item for item in batch.snapshot.files if item.get("role", "").startswith("raw_daily_tail")}
        self.assertEqual(set(evidence), {"raw_daily_tail", "raw_daily_tail_pack_index", "raw_daily_tail_symbol"})
        symbol = evidence["raw_daily_tail_symbol"]
        self.assertEqual(symbol["window_start"], "2026-09-07")
        self.assertEqual(len(symbol["raw_sha256"]), 64)
        self.assertEqual(len(symbol["typed_sha256"]), 64)
        self.assertFalse(symbol["historic_available_verified"])
        self.assertIn("source_fetched_at", symbol)

    def test_wrong_digest_and_coverage_overrun_fail_closed(self):
        self.write_pointer(self.capture, digest_value="0" * 64)
        with self.assertRaisesRegex(ValueError, "digest"):
            load_pointer(self.data)
        with self.assertRaisesRegex(ValueError, "digest"):
            local_data_provider(self.data, "raw").load(self.request((self.symbols[0],)))
        self.write_pointer(self.capture, coverage_end=date(2026, 9, 8))
        bounded = local_data_provider(self.data, "raw").load(
            self.request((self.symbols[0],), date(2026, 9, 7), date(2026, 9, 8))
        )
        self.assertEqual(bounded.bars.height, 2)
        with self.assertRaisesRegex(ValueError, "outside pointer coverage"):
            local_data_provider(self.data, "raw").load(self.request((self.symbols[0],)))

    def test_same_instance_revalidates_pointer_and_new_source_changes_fingerprint(self):
        provider = local_data_provider(self.data, "raw")
        first = provider.load(self.request((self.symbols[0],), date(2026, 9, 7), self.end))
        self.write_pointer(self.capture, indent=2)  # same declaration, different actual pointer bytes
        with self.assertRaisesRegex(ValueError, "changed for this provider instance"):
            provider.load(self.request((self.symbols[0],), date(2026, 9, 7), self.end))

        second_capture = self.make_capture("source-two", bias=300.0)
        self.write_pointer(second_capture)
        second = local_data_provider(self.data, "raw").load(
            self.request((self.symbols[0],), date(2026, 9, 7), self.end)
        )
        self.assertNotEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        self.assertNotEqual(first.bars["close"].to_list(), second.bars["close"].to_list())

    def test_missing_day_suspension_and_required_null_are_rejected(self):
        day = date(2026, 9, 9)
        cases = (
            ("source-missing", {("sh.600000", day)}, set(), set(), "missing trading day"),
            ("source-suspended", set(), {("sh.600000", day)}, set(), "suspended session"),
            ("source-null", set(), set(), {("sh.600000", day)}, "null required value"),
        )
        for name, missing, suspended, null_amount, message in cases:
            with self.subTest(name=name):
                capture = self.make_capture(name, symbols=("sh.600000",), missing=missing,
                                            suspended=suspended, null_amount=null_amount)
                self.write_pointer(capture)
                with self.assertRaisesRegex(ValueError, message):
                    local_data_provider(self.data, "raw").load(
                        self.request(("sh.600000",), date(2026, 9, 7), self.end)
                    )

    def test_resigned_bad_ohlc_is_rejected_by_raw_contract(self):
        capture = self.make_capture("source-bad-ohlc", symbols=("sh.600000",))
        self.resign_bad_ohlc(capture, "sh.600000", date(2026, 9, 9))
        self.write_pointer(capture)
        with self.assertRaisesRegex(ValueError, "OHLC"):
            local_data_provider(self.data, "raw").load(
                self.request(("sh.600000",), date(2026, 9, 7), self.end)
            )

    def resign_bad_ohlc(self, capture: Path, symbol: str, day: date):
        store = RetroDailyStore(capture.parents[2])
        index = copy.deepcopy(store.pack_index(capture.name))
        entry = index["symbols"][symbol]
        parts = store._read_slices(capture.name, index, [("raw", entry["raw"]), ("daily", entry["daily"])])
        raw = json.loads(gzip.decompress(parts["raw"]))
        row = next(row for row in raw["rows"] if row[0] == day.isoformat())
        row[FIELDS.index("high")] = str(float(row[FIELDS.index("low")]) - 1)
        raw_payload = gzip.compress(encode(raw).encode("utf-8"), compresslevel=6, mtime=0)
        typed = pl.read_parquet(io.BytesIO(parts["daily"])).with_columns(
            pl.when(pl.col("date") == day).then(pl.col("low") - 1).otherwise(pl.col("high")).alias("high")
        )
        stream = io.BytesIO()
        typed.write_parquet(stream, compression="zstd")
        typed_payload = stream.getvalue()
        manifest = entry["manifest"]
        manifest["raw_sha256"] = hashlib.sha256(raw_payload).hexdigest()
        manifest["parquet_sha256"] = hashlib.sha256(typed_payload).hexdigest()
        manifest["content_hash"] = digest(raw)
        for part, payload in (("raw", raw_payload), ("daily", typed_payload)):
            name = entry[part][0]
            self.assertEqual(index["packs"][name]["symbols"], 1)
            (capture / "packs" / name).write_bytes(payload)
            entry[part] = [name, 0, len(payload)]
            index["packs"][name]["bytes"] = len(payload)
            index["packs"][name]["sha256"] = hashlib.sha256(payload).hexdigest()
        manifests = [{"symbol": name, "parquet_sha256": value["manifest"]["parquet_sha256"],
                      "rows": value["manifest"]["rows"]} for name, value in sorted(index["symbols"].items())]
        index["manifest_digest"] = digest(manifests)
        (capture / "packs/index.json").write_text(encode({**index, "checksum": digest(index)}), encoding="utf-8")

    def test_capture_path_must_be_canonical_and_have_no_link_ancestor(self):
        value = self.write_pointer(self.capture)
        value["capture_path"] = str(self.capture.parent / ".." / "retro_daily" / self.capture.name)
        pointer_path(self.data).write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not canonical"):
            local_data_provider(self.data, "raw").load(self.request((self.symbols[0],)))
        alias = self.root / "source-link"
        alias.symlink_to(self.capture.parents[2], target_is_directory=True)
        value["capture_path"] = str(alias / "_market_data" / "retro_daily" / self.capture.name)
        pointer_path(self.data).write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "symlink"):
            local_data_provider(self.data, "raw").load(self.request((self.symbols[0],)))

    def test_historical_trunk_identity_is_unchanged_and_tail_not_read(self):
        request = self.request((self.symbols[0],), self.start, date(2026, 9, 4))
        baseline = MQCParquetProvider(self.data, "raw").load(request)
        with patch("quantlab.data.retro_tail.RetroTail.tail_bars", side_effect=AssertionError("tail read")):
            pointed = local_data_provider(self.data, "raw").load(request)
        self.assertTrue(baseline.bars.equals(pointed.bars))
        self.assertEqual(baseline.snapshot.snapshot_id, pointed.snapshot.snapshot_id)
        self.assertEqual(baseline.snapshot.files, pointed.snapshot.files)

    def test_qfq_and_minute_keep_old_boundaries_without_tail_call(self):
        write_mqc_daily(self.data / "lake/silver/qfq_kline_daily/sh_600000.parquet",
                        self.symbols[0], self.sessions[:4], base=9)
        write_mqc_min5(self.data / "lake/bronze/provider=baostock/stock_kline_min5/sh_600000.parquet",
                       self.symbols[0], self.start)
        with patch("quantlab.data.retro_tail.RetroTail.tail_bars", side_effect=AssertionError("tail read")):
            qfq = local_data_provider(self.data, "qfq").load(self.request((self.symbols[0],)))
            minute = local_data_provider(self.data, "raw").load(
                self.request((self.symbols[0],), self.start, self.start, Timeframe.MIN5)
            )
        self.assertEqual(qfq.bars["datetime"].max().date(), date(2026, 9, 4))
        self.assertEqual(minute.bars.height, 1)

    def test_different_symbol_cutoffs_extend_only_each_strict_suffix(self):
        batch = local_data_provider(self.data, "raw").load(self.request(self.symbols))
        counts = batch.bars.group_by("symbol").len().sort("symbol")
        self.assertEqual(counts["len"].to_list(), [len(self.sessions), len(self.sessions)])
        files = {item["symbol"]: item for item in batch.snapshot.files if item.get("role") == "raw_daily_tail_symbol"}
        self.assertEqual(files["sh.600000"]["window_start"], "2026-09-05")
        self.assertEqual(files["sz.000001"]["window_start"], "2026-09-09")
        first_close = batch.bars.filter(
            (pl.col("symbol") == "sh.600000") & (pl.col("datetime").dt.date() == date(2026, 9, 4))
        )["close"].item()
        self.assertEqual(first_close, 13.5)  # the MQC trunk was not replaced by retro value

    def test_empty_tail_window_is_explicitly_rejected(self):
        with self.assertRaisesRegex(ValueError, "trading sessions|No requested bars"):
            local_data_provider(self.data, "raw").load(
                self.request((self.symbols[0],), date(2026, 9, 5), date(2026, 9, 6))
            )

    def test_missing_symbol_source_is_not_silently_dropped(self):
        write_mqc_daily(self.data / "lake/bronze/provider=baostock/stock_kline_daily/sh_600001.parquet",
                        "sh.600001", self.sessions[:4], base=30)
        with self.assertRaisesRegex(ValueError, "not present|not in capture|Symbols"):
            local_data_provider(self.data, "raw").load(
                self.request(("sh.600001",), date(2026, 9, 7), self.end)
            )


if __name__ == "__main__":
    unittest.main()
