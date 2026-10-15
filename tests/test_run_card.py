import json
import tempfile
import unittest
from pathlib import Path

from quantlab.experiments.run_card import build_run_card, render_markdown, verify_run_card, write_run_card

RUNTIME = {"code_hash": "c" * 64, "python": "3.13.5", "dependencies": {"polars": "1.44.1"}}


def files(count, adjustment="qfq"):
    return {"adjustment": adjustment, "files": [{"bytes": 10, "path": f"/d/{i}.parquet", "sha256": f"{i:064x}"} for i in range(count)]}


def research():
    return {"run_id": "r1", "experiment_id": "e1", "status": "completed", "created_at": "2026-10-14T00:00:00+00:00",
            "limitations": ["close-to-close label"],
            "manifest": {"config": {"factor_id": "X", "data": {"start": "2020-01-01"}}, "runtime": RUNTIME, "factor": "BASE.MOMENTUM",
                         "data_snapshot": files(50), "universe": {"id": "csi300", "mask_hash": "m" * 64}},
            "metrics": {"1": {"ic": 0.03, "icir": 0.4, "rank_ic": 0.02, "observations": 1000, "triggered": True,
                              "permutation": {"daily_mean_ic": {"p_value": 0.04, "status": "computed"}}},
                        "5": {"ic": 0.01, "observations": 900}}}


def execution(fills=12, adjustment="qfq"):
    return {"run_id": "x1", "experiment_id": "ex1", "kind": "execution", "status": "completed", "created_at": "2026-10-14T00:00:00+00:00",
            "cost_model_warnings": ["no impact cost"], "children": [{"run_id": "r1"}],
            "manifest": {"config": {"factor_id": "X"}, "runtime": RUNTIME, "backend": "open", "data_snapshot": files(60, adjustment),
                         "universe": {"id": "explicit_symbols:a", "mask_hash": "m" * 64}},
            "execution": {"net_return": 0.12, "max_drawdown": -0.2, "sharpe": 0.7, "fills": fills, "initial_cash": 1_000_000,
                          "ending_positions": {"a": 1}}}


def with_interval(low, high, status="computed"):
    record = execution()
    record["sampling_uncertainty"] = ({"status": status, "reason": "x"} if status != "computed" else
                                      {"status": "computed", "n_days": 500, "block_days": 10, "observed": {"sharpe": 0.7}, "intervals": {"sharpe": [low, high]},
                                       "p_sharpe_not_above_zero": 0.03, "iid_psr_vs_zero": 0.97})
    return record


class RunCardTests(unittest.TestCase):
    def test_sampling_interval_is_copied_verified_and_flagged_when_it_spans_zero(self):
        record = with_interval(-0.2, 1.4)
        card = build_run_card(record)
        names = {h["name"]: h["value"] for h in card["headline"]}
        self.assertEqual((names["sampling_uncertainty.intervals.sharpe.0"], names["sampling_uncertainty.intervals.sharpe.1"]), (-0.2, 1.4))
        self.assertIn("SHARPE_INTERVAL_INCLUDES_ZERO", [f["code"] for f in card["flags"]])
        self.assertEqual(verify_run_card(card, record), [])
        record["sampling_uncertainty"]["intervals"]["sharpe"][0] = 0.1
        self.assertTrue(verify_run_card(card, record))
        self.assertNotIn("SHARPE_INTERVAL_INCLUDES_ZERO", [f["code"] for f in build_run_card(with_interval(0.1, 1.4))["flags"]])

    def test_old_or_unavailable_interval_does_not_invent_numbers(self):
        old = [f["code"] for f in build_run_card(execution())["flags"]]
        self.assertIn("NO_SAMPLING_INTERVAL", old)
        short = build_run_card(with_interval(0, 0, status="unavailable"))
        self.assertFalse([h for h in short["headline"] if h["name"].startswith("sampling_uncertainty")])
        self.assertNotIn("SHARPE_INTERVAL_INCLUDES_ZERO", [f["code"] for f in short["flags"]])

    def test_headline_numbers_are_copied_with_their_paths_and_verify(self):
        record = research()
        card = build_run_card(record)
        sources = {row["source"]: row["value"] for row in card["headline"]}
        self.assertEqual(sources["metrics.1.ic"], 0.03)
        self.assertEqual(sources["metrics.1.permutation.daily_mean_ic.p_value"], 0.04)
        self.assertNotIn("metrics.1.triggered", sources)          # booleans are not numbers
        self.assertEqual(verify_run_card(card, record), [])
        self.assertEqual(card["data"]["file_count"], 50)
        self.assertEqual(card["code"]["factor"], "BASE.MOMENTUM")

    def test_verification_catches_a_changed_card_or_record(self):
        record, card = research(), build_run_card(research())
        card["headline"][0]["value"] = 999
        self.assertTrue(verify_run_card(card, record))
        record["metrics"]["1"]["ic"] = 0.5
        self.assertTrue(verify_run_card(build_run_card(research()), record))

    def test_flags_are_derived_only_from_present_fields(self):
        codes = lambda card: {f["code"] for f in card["flags"]}
        self.assertEqual(codes(build_run_card(research())), set())
        self.assertIn("NO_FILLS", codes(build_run_card(execution(fills=0))))
        self.assertIn("RAW_PRICES", codes(build_run_card(execution(adjustment="raw"))))
        self.assertIn("NON_PIT_UNIVERSE", codes(build_run_card(execution())))
        record = research()
        del record["metrics"]["1"]["permutation"]
        self.assertIn("NO_SIGNIFICANCE_TEST", codes(build_run_card(record)))
        failed = research()
        failed.update(status="failed", error="boom")
        failed["manifest"]["runtime"] = None
        self.assertTrue({"NOT_COMPLETED", "NO_RUNTIME_FINGERPRINT"} <= codes(build_run_card(failed)))
        small = research()
        small["manifest"]["data_snapshot"] = files(5)
        self.assertIn("SMALL_UNIVERSE", codes(build_run_card(small)))

    def test_minimal_and_unknown_records_do_not_crash(self):
        card = build_run_card({})
        self.assertEqual(card["headline"], [])
        self.assertIn("NOT_COMPLETED", {f["code"] for f in card["flags"]})
        self.assertIn("Run card", render_markdown(card))

    def test_card_id_ignores_generation_time_and_changes_with_content(self):
        a, b = build_run_card(research()), build_run_card(research())
        self.assertEqual(a["card_id"], b["card_id"])
        changed = research()
        changed["metrics"]["1"]["ic"] = 0.031
        self.assertNotEqual(build_run_card(changed)["card_id"], a["card_id"])

    def test_write_outside_artifact_folder_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact"
            artifact.mkdir()
            (artifact / "experiment.json").write_text(json.dumps(execution()))
            with self.assertRaises(ValueError):
                write_run_card(artifact / "experiment.json", artifact)
            card = write_run_card(artifact / "experiment.json", Path(tmp) / "cards" / "x1")
            saved = json.loads((Path(tmp) / "cards" / "x1" / "run_card.json").read_text())
            self.assertEqual(saved["card_id"], card["card_id"])
            self.assertEqual(len(saved["identity"]["source_sha256"]), 64)
            self.assertIn("NON_PIT_UNIVERSE", (Path(tmp) / "cards" / "x1" / "run_card.md").read_text())
            self.assertEqual(sorted(p.name for p in artifact.iterdir()), ["experiment.json"])


if __name__ == "__main__":
    unittest.main()
