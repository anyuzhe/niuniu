import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal
from quantlab.experiments.frozen_candidate_validation import (
    board_of, select_symbols, load_candidates, validate_protocol, normalize_research_frame,
    period_daily, descriptive, infer_daily, finalize_family)
from quantlab.storage.codec import digest, encode


def protocol():
    return {"format": "niuniu-frozen-candidate-validation-v1", "qualification": "research_only",
        "adjustment": "qfq", "candidate_change_allowed": False, "trade_execution": False,
        "data_start": "2020-01-01", "data_end": "2026-09-04", "source_generation_period": ["2024-01-01", "2024-12-31"],
        "horizons": [1, 5], "periods": [{"name": "in_sample", "start": "2020-01-01", "end": "2023-12-31"},
            {"name": "seen_year_diagnostic", "start": "2024-01-01", "end": "2024-12-31"},
            {"name": "historical_holdout", "start": "2025-01-01", "end": "2026-09-04"}],
        "statistics": {"holm_family_size": 18, "min_cross_section": 20, "min_board_cross_section": 10,
            "block_days": 20, "bootstrap_resamples": 40, "sign_resamples": 40, "confidence": .95,
            "alpha": .05, "seed": 4, "minimum_signed_rank_ic": .01}, "limitations": []}


class FrozenCandidateValidationTests(unittest.TestCase):
    def test_protocol_file_checksum_binds_body_and_rejects_tampering(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("frozen_validation_script", Path(__file__).resolve().parents[1]/"scripts/validate_frozen_candidates.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); body = protocol()
            (root/"protocol.json").write_text(encode({"protocol": body, "checksum": digest(body)}))
            self.assertEqual(module.load_protocol(root), body)
            changed = {**body, "adjustment": "raw"}
            (root/"protocol.json").write_text(encode({"protocol": changed, "checksum": digest(body)}))
            with self.assertRaisesRegex(ValueError, "checksum"): module.load_protocol(root)
            module.save_new(root/"receipt.json", {"original": True})
            with self.assertRaises(FileExistsError): module.save_new(root/"receipt.json", {"changed": True})
            receipt = {"status": "numerically_matched", "result_checksum": "abc", "runtime": {}, "verified_at": "first"}
            module.save_verification(root/"verified.json", receipt)
            before = (root/"verified.json").read_bytes()
            module.save_verification(root/"verified.json", {**receipt, "verified_at": "second"})
            self.assertEqual((root/"verified.json").read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "conflicts"):
                module.save_verification(root/"verified.json", {**receipt, "result_checksum": "changed"})

    def test_deterministic_selection_ignores_outcomes_and_current_status(self):
        records = [{"code": f"sh.60000{i}", "ipoDate": "2000-01-01", "type": "1", "status": "1"} for i in range(8)]
        available = {r["code"] for r in records}
        selection = {"boards": ["SH_MAIN"], "count_per_board": 3, "ipo_cutoff": "2019-12-31",
                     "seed": "frozen", "excluded_symbols": []}
        first = select_symbols(records, available, selection)
        changed = [{**r, "status": "0", "outDate": "2022-01-01", "future_return": -9999.0} for r in reversed(records)]
        self.assertEqual(first, select_symbols(changed, available, selection))
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            select_symbols(records[:2], available, selection)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            select_symbols(records + [records[0]], available, selection)
        self.assertEqual(board_of("sh.688001"), "STAR")
        self.assertEqual(board_of("sz.300001"), "CHINEXT")
        self.assertIsNone(board_of("bj.830001"))

    def test_protocol_rejects_seen_holdout_overlap_and_smaller_family(self):
        validate_protocol(protocol())
        for change in ("seen", "overlap", "family", "cross_section", "horizon"):
            value = protocol()
            if change == "seen": value["source_generation_period"][1] = "2025-01-02"
            elif change == "overlap": value["periods"][1]["start"] = "2023-01-01"
            elif change == "family": value["statistics"]["holm_family_size"] = 6
            elif change == "cross_section": value["statistics"]["min_cross_section"] = 2
            else: value["horizons"] = [1, 10]
            with self.subTest(change=change), self.assertRaises(ValueError): validate_protocol(value)

    def test_frozen_candidates_hash_and_spec_binding(self):
        rows = []
        for name in ("A", "B", "C"):
            expression = {"op": "field", "name": "close"}
            spec = {"parameters": {"ast": expression}}
            rows.append({"candidate": {"name": name, "ast": expression, "expected_rank_ic_sign": "negative"},
                         "spec": spec, "spec_digest": digest(spec)})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"frozen.json"
            body = {"candidates": rows}
            path.write_text(encode({**body, "checksum": digest(body)}))
            self.assertEqual(len(load_candidates(path, sha256(path.read_bytes()).hexdigest())), 3)
            with self.assertRaisesRegex(ValueError, "bytes changed"): load_candidates(path, "0"*64)
            body["candidates"][0]["spec_digest"] = "tampered"
            path.write_text(encode({**body, "checksum": digest(body)}))
            with self.assertRaisesRegex(ValueError, "binding"): load_candidates(path, sha256(path.read_bytes()).hexdigest())

    def test_missing_quantity_is_preserved_but_price_corruption_fails(self):
        frame = pl.DataFrame({"date": [date(2024, 1, 1), date(2024, 1, 2)], "code": ["sh.600001"]*2,
            "open": [10., 10.], "high": [11., 11.], "low": [9., 9.], "close": [10., 10.],
            "volume": [100., None], "amount": [1000., None], "factor": [1., 1.]})
        result = normalize_research_frame(frame, "sh.600001")
        self.assertEqual(result.height, 2)
        self.assertIsNone(result["volume"][1])
        self.assertIsNone(result["turnover"][1])
        for changed in (frame.with_columns(pl.lit(None).cast(pl.Float64).alias("close")),
                        frame.with_columns(pl.lit(8.).alias("high")),
                        frame.with_columns(pl.lit(-1.).alias("volume")), pl.concat([frame, frame.head(1)])):
            with self.assertRaises(ValueError): normalize_research_frame(changed, "sh.600001")

    def fixture(self):
        rows = []
        for day in range(3):
            for number in range(5):
                at = datetime(2025, 1, 1+day, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
                rows.append({"symbol": f"s{number}", "datetime": at, "available_at": at,
                    "value": float(number), "forward_1": float(number)/100,
                    "label_end_1": at+timedelta(days=1), "eligible": True})
        obs = pl.DataFrame(rows)
        bars = obs.select("symbol", "datetime").with_columns(pl.lit(100.).alias("volume"))
        return obs, bars

    def test_split_purges_cross_boundary_labels_and_keeps_missing_day(self):
        obs, bars = self.fixture()
        daily, detail = period_daily(obs, bars, 1, "2025-01-01", "2025-01-02", 3)
        self.assertEqual(detail["boundary_labels_excluded"], 5)
        self.assertEqual(detail["valid_label_rows"], 5)
        self.assertEqual(daily.height, 2)
        self.assertAlmostEqual(daily["rank_ic"][0], 1.)
        self.assertIsNone(daily["rank_ic"][1])
        revised = obs.with_columns(pl.when(pl.col("label_end_1").dt.date() > date(2025, 1, 2))
                                   .then(pl.lit(-999.)).otherwise(pl.col("forward_1")).alias("forward_1"))
        result, _ = period_daily(revised, bars, 1, "2025-01-01", "2025-01-02", 3)
        assert_frame_equal(daily, result, check_exact=True)

    def test_null_volume_constant_cross_sections_and_shuffled_rows(self):
        obs, bars = self.fixture()
        first, _ = period_daily(obs, bars, 1, "2025-01-01", "2025-01-03", 3)
        reverse, _ = period_daily(obs.reverse(), bars.reverse(), 1, "2025-01-01", "2025-01-03", 3)
        assert_frame_equal(first, reverse, check_exact=True)
        constant, _ = period_daily(obs.with_columns(pl.lit(1.).alias("value")), bars, 1, "2025-01-01", "2025-01-03", 3)
        self.assertEqual(constant["rank_ic"].null_count(), 3)
        missing, detail = period_daily(obs, bars.with_columns(pl.lit(None).cast(pl.Float64).alias("volume")), 1,
                                      "2025-01-01", "2025-01-03", 3)
        self.assertEqual(detail["signal_rows"], 0)
        self.assertEqual(missing["rank_ic"].null_count(), 3)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            period_daily(pl.concat([obs, obs.head(1)]), bars, 1, "2025-01-01", "2025-01-03", 3)
        with self.assertRaisesRegex(ValueError, "Delayed"):
            period_daily(obs.with_columns(pl.col("available_at")+pl.duration(hours=1)), bars, 1, "2025-01-01", "2025-01-03", 3)

    def family(self):
        return [{"candidate": name, "period": phase["name"], "horizon": h, "expected_sign": "negative",
                 "rank_ic": -.03, "test": {"p_value": .001}}
                for name in ("A", "B", "C") for phase in protocol()["periods"] for h in (1, 5)]

    def test_family_preserves_all_slots_and_opposite_sign_is_not_support(self):
        rows = self.family(); rows[0]["test"]["p_value"] = None
        rows[-1]["rank_ic"] = .08
        result = finalize_family(rows, protocol())
        self.assertAlmostEqual(result["tests"][1]["p_holm"], .018)
        self.assertFalse(result["tests"][-1]["significant_expected_direction"])
        self.assertFalse(result["conclusions"][-1]["next_stage_eligible"])
        self.assertFalse(result["alpha_verified"])
        with self.assertRaisesRegex(ValueError, "slots"): finalize_family(rows[:-1], protocol())
        duplicate = self.family(); duplicate[0] = copy.deepcopy(duplicate[1])
        with self.assertRaisesRegex(ValueError, "identities"): finalize_family(duplicate, protocol())

    def test_small_effect_or_bad_in_sample_blocks_promotion(self):
        rows = self.family(); rows[0]["rank_ic"] = .02
        rows[10]["rank_ic"] = -.001
        result = finalize_family(rows, protocol())
        self.assertFalse(result["conclusions"][0]["next_stage_eligible"])
        self.assertFalse(result["conclusions"][1]["next_stage_eligible"])
        self.assertTrue(result["conclusions"][2]["next_stage_eligible"])
        self.assertFalse(result["conclusions"][2]["alpha_verified"])

    def test_inference_keeps_null_slots_and_seed_is_reproducible(self):
        stats = protocol()["statistics"]
        daily = pl.DataFrame({"rank_ic": [.1, None]*80, "n": [30]*160, "gross_high_minus_low": [.001]*160})
        first = infer_daily(daily, stats, {"candidate": "A", "horizon": 1})
        self.assertEqual(first, infer_daily(daily, stats, {"candidate": "A", "horizon": 1}))
        self.assertEqual(first["test"]["observed_days"], 160)
        self.assertEqual(first["test"]["valid_days"], 80)
        self.assertIsNone(infer_daily(daily.head(20), stats, {})["test"]["p_value"])

if __name__ == "__main__": unittest.main()
