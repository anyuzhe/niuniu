"""Synthetic-only regression tests for the finite archived daily dataset package."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import gzip
import hashlib
import io
import json

import polars as pl

from test_retro_daily import FakeSDK, bar
from quantlab.data.archived_daily_dataset import (
    FORMAT,
    MARKER,
    ArchivedDailyDatasetProvider,
    export_archived_daily_dataset,
    inspect_archived_daily_dataset,
    preview_archived_daily_dataset,
)
from quantlab.data.base import DataRequest
from quantlab.data.retro_daily import FIELDS, SCHEMA, RetroDailyStore, normalize_symbol_rows
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest, encode


class ArchivedDailyDatasetTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.days = [date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9),
                     date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 13)]
        self.sessions = self.days[:5]
        calendar = [(day.isoformat(), "1" if day in self.sessions else "0") for day in self.days]
        basic = [("sh.600001", "甲", "2000-01-01", "", "1", "1"),
                 ("sz.000002", "乙", "2000-01-01", "", "1", "1")]
        bars = {}
        for symbol, base in (("sh.600001", 10.0), ("sz.000002", 20.0)):
            bars[symbol] = [bar(day.isoformat(), symbol, base + index, base + index - 0.2,
                                st="1" if symbol == "sh.600001" and index == 2 else "0")
                            for index, day in enumerate(self.sessions)]
        self.sdk = FakeSDK(basic=basic, calendar=calendar, bars=bars)
        self.store = RetroDailyStore(self.source, today_fn=lambda: date(2026, 9, 21),
                                     now_fn=lambda: datetime(2026, 9, 21, 8, tzinfo=timezone.utc))
        self.capture_id = self.store.create_plan("2026-09-07", "2026-09-13", sdk=self.sdk)["capture_id"]
        fetched = self.store.fetch(self.capture_id, sdk=self.sdk)
        self.assertEqual(fetched["completed"], 2)
        self.symbols = "sh.600001 sz.000002"
        self.start, self.end = "2026-09-07", "2026-09-11"

    @staticmethod
    def _tree_bytes(root: Path):
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()}

    def _preview(self):
        return preview_archived_daily_dataset(
            self.source, self.capture_id, self.symbols, self.start, self.end
        )

    def _export(self, name="dataset"):
        preview = self._preview()
        destination = self.root / name
        result = export_archived_daily_dataset(
            self.source, self.capture_id, self.symbols, self.start, self.end, destination,
            expected_preview_hash=preview["preview_hash"], confirmed=True,
        )
        return destination, preview, result

    def _rewrite_symbol(self, symbol, mutate):
        """Create another internally valid synthetic source revision for drift tests."""
        directory = self.store._symbol_dir(self.capture_id, symbol)
        raw = json.loads(gzip.decompress((directory / "rows.json.gz").read_bytes()))
        mutate(raw["rows"])
        plan = self.store.plan(self.capture_id, with_symbols=True)
        calendar = set(self.store.trading_days(self.capture_id))
        records = normalize_symbol_rows(raw["rows"], symbol, date.fromisoformat(plan["start"]),
                                       date.fromisoformat(plan["end"]), calendar)
        frame = pl.DataFrame(records, schema=SCHEMA)
        self._replace_symbol_bytes(symbol, raw, frame)

    def _replace_symbol_bytes(self, symbol, raw, frame):
        """Rewrite a synthetic capture consistently, including intentionally invalid semantics."""
        directory = self.store._symbol_dir(self.capture_id, symbol)
        raw_payload = gzip.compress(encode(raw).encode(), compresslevel=6, mtime=0)
        stream = io.BytesIO()
        frame.write_parquet(stream, compression="zstd")
        typed_payload = stream.getvalue()
        old = json.loads((directory / "manifest.json").read_text())
        core = {key: value for key, value in old.items() if key != "checksum"}
        core.update(status="OK" if frame.height else "EMPTY", rows=frame.height,
                    first_date=frame["date"][0].isoformat() if frame.height else None,
                    last_date=frame["date"][-1].isoformat() if frame.height else None,
                    tradable_rows=frame.filter(pl.col("tradestatus") == 1).height,
                    st_rows=frame.filter(pl.col("isST") == 1).height,
                    raw_sha256=hashlib.sha256(raw_payload).hexdigest(),
                    parquet_sha256=hashlib.sha256(typed_payload).hexdigest(), content_hash=digest(raw))
        (directory / "rows.json.gz").write_bytes(raw_payload)
        (directory / "daily.parquet").write_bytes(typed_payload)
        (directory / "manifest.json").write_text(encode({**core, "checksum": digest(core)}))

    def test_preview_is_write_free_and_has_explicit_stable_contract(self):
        before = self._tree_bytes(self.source)
        first = self._preview()
        second = self._preview()
        self.assertEqual(before, self._tree_bytes(self.source))
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"preview_hash", "capture_id", "symbols", "start", "end", "rows",
                                      "actual_sessions", "fields", "adjustment", "qualification", "time_policy",
                                      "source_evidence", "limitations"})
        self.assertEqual((first["rows"], first["actual_sessions"]), (10, 5))
        self.assertEqual((first["adjustment"], first["qualification"]), ("raw", "research_only"))
        self.assertFalse(first["time_policy"]["historical_available_at_verified"])
        self.assertTrue(first["source_evidence"]["raw_and_typed_bytes_verified"])
        self.assertEqual(len(first["preview_hash"]), 64)

    def test_packed_and_unpacked_sources_have_identical_preview_and_export_bytes(self):
        unpacked = self._preview()
        originals = {symbol: {
            "raw": (self.store._symbol_dir(self.capture_id, symbol) / "rows.json.gz").read_bytes(),
            "daily": (self.store._symbol_dir(self.capture_id, symbol) / "daily.parquet").read_bytes(),
        } for symbol in self.symbols.split()}
        result = self.store.consolidate(self.capture_id, confirmed=True, remove_originals=True)
        self.assertEqual(result["state"], "COMPLETE")
        packed = self._preview()
        self.assertEqual(unpacked, packed)
        destination, _, _ = self._export("packed")
        for symbol in self.symbols.split():
            prefix = destination / "source/symbols" / symbol.replace(".", "_")
            self.assertEqual((prefix / "rows.json.gz").read_bytes(), originals[symbol]["raw"])
            self.assertEqual((prefix / "daily.parquet").read_bytes(), originals[symbol]["daily"])

    def test_missing_session_suspension_and_empty_required_value_fail_closed(self):
        # Missing one requested trading day.
        self._rewrite_symbol("sh.600001", lambda rows: rows.pop(2))
        with self.assertRaisesRegex(ValueError, "missing, duplicate, or unexpected"):
            self._preview()

        # Each subcase gets a fresh fixture because the source is immutable from the API's perspective.
        for kind in ("suspension", "empty"):
            with self.subTest(kind=kind), TemporaryDirectory() as name:
                root = Path(name).resolve(); source = root / "source"; source.mkdir()
                calendar = [(day.isoformat(), "1" if day in self.sessions else "0") for day in self.days]
                basic = [("sh.600001", "甲", "2000-01-01", "", "1", "1")]
                rows = [bar(day.isoformat(), "sh.600001", 10 + index, 9.8 + index)
                        for index, day in enumerate(self.sessions)]
                if kind == "suspension":
                    rows[2] = bar(self.sessions[2].isoformat(), "sh.600001", 0, 11.8, tradestatus="0")
                else:
                    changed = list(rows[2]); changed[FIELDS.index("amount")] = ""; rows[2] = tuple(changed)
                sdk = FakeSDK(basic=basic, calendar=calendar, bars={"sh.600001": rows})
                store = RetroDailyStore(source, today_fn=lambda: date(2026, 9, 21),
                                        now_fn=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
                capture = store.create_plan(self.start, "2026-09-13", sdk=sdk)["capture_id"]
                self.assertEqual(store.fetch(capture, sdk=sdk)["completed"], 1)
                pattern = "tradestatus!=1" if kind == "suspension" else "empty or non-finite"
                with self.assertRaisesRegex(ValueError, pattern):
                    preview_archived_daily_dataset(source, capture, "sh.600001", self.start, self.end)

    def test_duplicate_raw_is_rejected_by_existing_bridge_contract(self):
        directory = self.store._symbol_dir(self.capture_id, "sh.600001")
        raw = json.loads(gzip.decompress((directory / "rows.json.gz").read_bytes()))
        raw["rows"].insert(1, list(raw["rows"][0]))
        payload = gzip.compress(encode(raw).encode(), compresslevel=6, mtime=0)
        old = json.loads((directory / "manifest.json").read_text())
        core = {key: value for key, value in old.items() if key != "checksum"}
        core.update(raw_sha256=hashlib.sha256(payload).hexdigest(), content_hash=digest(raw))
        (directory / "rows.json.gz").write_bytes(payload)
        (directory / "manifest.json").write_text(encode({**core, "checksum": digest(core)}))
        with self.assertRaises(ValueError):
            self._preview()

    def test_invalid_ohlc_is_rejected_even_when_raw_and_typed_bytes_are_resigned(self):
        symbol = "sh.600001"
        directory = self.store._symbol_dir(self.capture_id, symbol)
        raw = json.loads(gzip.decompress((directory / "rows.json.gz").read_bytes()))
        raw["rows"][0][FIELDS.index("high")] = "1"
        frame = pl.read_parquet(directory / "daily.parquet").with_row_index("_row").with_columns(
            pl.when(pl.col("_row") == 0).then(1.0).otherwise(pl.col("high")).alias("high")
        ).drop("_row")
        self._replace_symbol_bytes(symbol, raw, frame)
        with self.assertRaises(ValueError):
            self._preview()

    def test_nonfinite_value_is_rejected_even_when_raw_and_typed_bytes_are_resigned(self):
        symbol = "sh.600001"
        directory = self.store._symbol_dir(self.capture_id, symbol)
        raw = json.loads(gzip.decompress((directory / "rows.json.gz").read_bytes()))
        raw["rows"][0][FIELDS.index("open")] = "NaN"
        frame = pl.read_parquet(directory / "daily.parquet").with_row_index("_row").with_columns(
            pl.when(pl.col("_row") == 0).then(float("nan")).otherwise(pl.col("open")).alias("open")
        ).drop("_row")
        self._replace_symbol_bytes(symbol, raw, frame)
        with self.assertRaises(ValueError):
            self._preview()

    def test_raw_only_strict_range_and_symbol_rules(self):
        with self.assertRaises(ValueError):
            preview_archived_daily_dataset(self.source, self.capture_id, "sh.600001 sh.600001", self.start, self.end)
        with self.assertRaises(ValueError):
            preview_archived_daily_dataset(self.source, self.capture_id, "bj.920001", self.start, self.end)
        with self.assertRaises(ValueError):
            preview_archived_daily_dataset(self.source, self.capture_id, "sh.600001", "2026-09-06", self.end)
        with self.assertRaises(ValueError):
            preview_archived_daily_dataset(self.source, self.capture_id, "sh.600001", self.end, self.start)
        with self.assertRaisesRegex(ValueError, "No observed calendar"):
            preview_archived_daily_dataset(self.source, self.capture_id, "sh.600001", "2026-09-12", "2026-09-13")
        with self.assertRaisesRegex(ValueError, "371"):
            preview_archived_daily_dataset(self.source, self.capture_id, "sh.600001", "2025-01-01", "2026-09-13")
        destination, _, _ = self._export()
        with self.assertRaisesRegex(ValueError, "adjustment='raw'"):
            ArchivedDailyDatasetProvider(destination, "qfq")
        provider = ArchivedDailyDatasetProvider(destination)
        with self.assertRaisesRegex(ValueError, "timeframe=1d"):
            provider.load(DataRequest(("sh.600001",), Timeframe.MIN1, self.sessions[0], self.sessions[-1]))

    def test_export_shape_exact_source_hashes_and_st_retention(self):
        destination, preview, result = self._export()
        self.assertEqual(set(result), {"dataset_id", "path", "preview_hash", "rows"})
        self.assertEqual(result["preview_hash"], preview["preview_hash"])
        inspected = inspect_archived_daily_dataset(destination)
        self.assertEqual(inspected["dataset_id"], result["dataset_id"])
        self.assertEqual(inspected["rows"], 10)
        self.assertEqual(json.loads((destination / MARKER).read_text())["format"], FORMAT)
        for symbol in self.symbols.split():
            original = self.store._symbol_dir(self.capture_id, symbol)
            packaged = destination / "source/symbols" / symbol.replace(".", "_")
            self.assertEqual(hashlib.sha256((packaged / "rows.json.gz").read_bytes()).hexdigest(),
                             hashlib.sha256((original / "rows.json.gz").read_bytes()).hexdigest())
            self.assertEqual(hashlib.sha256((packaged / "daily.parquet").read_bytes()).hexdigest(),
                             hashlib.sha256((original / "daily.parquet").read_bytes()).hexdigest())
        batch = ArchivedDailyDatasetProvider(destination).load(
            DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[1], self.sessions[3]))
        self.assertEqual(batch.bars.height, 3)
        self.assertEqual(batch.bars["bs_is_st"].to_list(), [0, 1, 0])
        self.assertTrue((batch.bars["bs_trade_status"] == 1).all())
        self.assertTrue((batch.bars["adj_factor"] == 1.0).all())
        self.assertEqual(batch.snapshot.source, "archived_retro_daily_dataset")
        self.assertTrue(all(item["dataset_id"] == result["dataset_id"] for item in batch.snapshot.files))
        self.assertTrue(all(item["historical_available_at_verified"] is False for item in batch.snapshot.files))

    def test_preview_drift_confirmation_and_existing_destination_are_rejected(self):
        preview = self._preview()
        with self.assertRaisesRegex(ValueError, "confirmed=True"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          self.root / "not-confirmed", expected_preview_hash=preview["preview_hash"])
        with self.assertRaisesRegex(ValueError, "complete expected_preview_hash"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          self.root / "short", expected_preview_hash="abc", confirmed=True)
        existing = self.root / "existing"; existing.mkdir()
        with self.assertRaisesRegex(ValueError, "wholly new"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          existing, expected_preview_hash=preview["preview_hash"], confirmed=True)

        def change(rows):
            row = rows[0]
            row[FIELDS.index("close")] = str(float(row[FIELDS.index("close")]) + 0.1)
            row[FIELDS.index("high")] = row[FIELDS.index("close")]
        self._rewrite_symbol("sh.600001", change)
        with self.assertRaisesRegex(ValueError, "Preview hash changed"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          self.root / "drift", expected_preview_hash=preview["preview_hash"], confirmed=True)
        self.assertFalse((self.root / "drift").exists())

    def test_destination_escape_source_tree_and_symlink_parent_are_rejected(self):
        preview = self._preview()
        inside = self.source / "_market_data" / "forbidden"
        with self.assertRaisesRegex(ValueError, "_market_data"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          inside, expected_preview_hash=preview["preview_hash"], confirmed=True)
        real = self.root / "real"; real.mkdir()
        redirect = self.root / "redirect"; redirect.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink/redirect"):
            export_archived_daily_dataset(self.source, self.capture_id, self.symbols, self.start, self.end,
                                          redirect / "dataset", expected_preview_hash=preview["preview_hash"], confirmed=True)
        self.assertEqual(list(real.iterdir()), [])

    def test_source_can_go_offline_and_provider_supports_bounded_subsets(self):
        destination, _, _ = self._export()
        self.source.rename(self.root / "offline-source")
        provider = ArchivedDailyDatasetProvider(destination)
        request = DataRequest(("sz.000002",), Timeframe.DAILY, self.sessions[1], self.sessions[3])
        first = provider.load(request)
        second = provider.load(request)
        self.assertTrue(first.bars.equals(second.bars))
        self.assertEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        with self.assertRaisesRegex(ValueError, "exceed"):
            provider.load(DataRequest(("sh.699999",), Timeframe.DAILY, self.sessions[1], self.sessions[3]))
        with self.assertRaisesRegex(ValueError, "exceed"):
            provider.load(DataRequest(("sz.000002",), Timeframe.DAILY, date(2026, 9, 6), self.sessions[3]))
        with self.assertRaisesRegex(ValueError, "exceed"):
            provider.load(DataRequest(("sz.000002",), Timeframe.DAILY, date(2026, 9, 12), date(2026, 9, 13)))

    def test_corruption_extra_state_and_repeated_read_tampering_are_detected(self):
        destination, _, _ = self._export()
        provider = ArchivedDailyDatasetProvider(destination)
        request = DataRequest(("sh.600001",), Timeframe.DAILY, self.sessions[0], self.sessions[-1])
        provider.load(request)
        raw = destination / "source/symbols/sh_600001/rows.json.gz"
        raw.write_bytes(raw.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            provider.load(request)

        second, _, _ = self._export("extra-state")
        (second / "unexpected.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "extra package state"):
            inspect_archived_daily_dataset(second)

    def test_modified_bars_with_fully_resigned_self_manifest_still_fails_semantic_rebuild(self):
        destination, _, _ = self._export()
        bars_path = destination / "normalized/bars.parquet"
        bars = pl.read_parquet(bars_path).with_columns(
            pl.when((pl.col("symbol") == "sh.600001") & (pl.col("datetime").dt.date() == self.sessions[0]))
              .then(pl.col("close") + 0.25).otherwise(pl.col("close")).alias("close"),
            pl.when((pl.col("symbol") == "sh.600001") & (pl.col("datetime").dt.date() == self.sessions[0]))
              .then(pl.col("high") + 0.25).otherwise(pl.col("high")).alias("high"),
        )
        bars.write_parquet(bars_path, compression="zstd")
        payload = bars_path.read_bytes()
        marker = json.loads((destination / MARKER).read_text())
        for entry in marker["files"]:
            if entry["path"] == "normalized/bars.parquet":
                entry.update(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
        marker["normalized"]["semantics_sha256"] = digest(bars.to_dicts())
        core = {key: value for key, value in marker.items() if key not in ("dataset_id", "checksum")}
        marker["dataset_id"] = digest(core)
        marker["checksum"] = digest({key: value for key, value in marker.items() if key != "checksum"})
        (destination / MARKER).write_text(encode(marker))
        with self.assertRaisesRegex(ValueError, "normalized"):
            inspect_archived_daily_dataset(destination)

    def test_manifest_path_escape_and_symlink_payload_are_rejected_without_external_read(self):
        destination, _, _ = self._export()
        marker_path = destination / MARKER
        marker = json.loads(marker_path.read_text())
        marker["files"][0]["path"] = "../outside"
        core = {key: value for key, value in marker.items() if key not in ("dataset_id", "checksum")}
        marker["dataset_id"] = digest(core)
        marker["checksum"] = digest({key: value for key, value in marker.items() if key != "checksum"})
        marker_path.write_text(encode(marker))
        with self.assertRaises(ValueError):
            inspect_archived_daily_dataset(destination)

        second, _, _ = self._export("symlink-payload")
        target = second / "source/plan.json"
        saved = second / "saved-plan"
        target.rename(saved)
        target.symlink_to(saved)
        with self.assertRaisesRegex(ValueError, "symlink|extra package state"):
            inspect_archived_daily_dataset(second)

    def test_concurrent_exports_publish_at_most_once_without_stage_residue(self):
        preview = self._preview()
        destination = self.root / "race"

        def run():
            try:
                return export_archived_daily_dataset(
                    self.source, self.capture_id, self.symbols, self.start, self.end, destination,
                    expected_preview_hash=preview["preview_hash"], confirmed=True,
                )
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: run(), range(2)))
        successes = [item for item in outcomes if isinstance(item, dict)]
        failures = [item for item in outcomes if isinstance(item, ValueError)]
        self.assertEqual((len(successes), len(failures)), (1, 1))
        self.assertEqual(inspect_archived_daily_dataset(destination)["dataset_id"], successes[0]["dataset_id"])
        self.assertEqual(list(self.root.glob(".race.stage-*")), [])
        self.assertFalse((self.root / ".race.archived-dataset-export.lock").exists())
