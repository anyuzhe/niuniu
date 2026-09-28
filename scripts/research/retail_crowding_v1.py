#!/usr/bin/env python3
"""Create and execute the frozen Retail Crowding V1 holdout family.

This is a host research runner over existing Research Lab components. It does
not impersonate autonomous Niuniu research, download data, or place orders.
"""
import argparse
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import polars as pl

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.data.dataset_registry import resolve
from quantlab.data.universe import UniverseConfig, build_universe
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.frozen_candidate_validation import normalize_research_frame
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.trial_registry import bind_result, create_registry, report_registry
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.permutation import PermutationConfig
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import LocalExperimentStore

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs/reference/retail-crowding-v1.0.1.json"


def _board(symbol: str) -> str | None:
    if symbol.startswith("sh.688"):
        return "STAR"
    if symbol.startswith("sh.60"):
        return "SH_MAIN"
    if symbol.startswith("sz.30"):
        return "CHINEXT"
    if symbol.startswith("sz.00"):
        return "SZ_MAIN"
    return None


def load_spec(path: Path = SPEC_PATH) -> dict:
    value = json.loads(Path(path).read_text())
    if value.get("spec_id") != "retail-crowding-v1" or value.get("version") != "1.0.1":
        raise ValueError("Retail Crowding V1 current runner requires frozen spec version 1.0.1")
    return value


def inference_resolution(spec: dict) -> dict:
    evaluation = spec["evaluation"]
    planned = len(spec["factors"]) * 3 * len(evaluation["horizons"]) * 2
    config = evaluation["permutation"]
    minimum_p = 1.0 / (config["resamples"] + 1)
    first_holm = config["alpha"] / planned
    result = {
        "planned_tests": planned,
        "minimum_monte_carlo_p": minimum_p,
        "holm_first_step_alpha": first_holm,
        "sufficient": minimum_p <= first_holm,
    }
    declared = evaluation.get("inference_resolution")
    if declared is not None and (
        declared.get("planned_tests") != planned
        or abs(declared.get("minimum_monte_carlo_p", -1) - minimum_p) > 1e-15
        or abs(declared.get("holm_first_step_alpha", -1) - first_holm) > 1e-15
    ):
        raise ValueError("Frozen inference-resolution declaration differs from executable family")
    if not result["sufficient"]:
        raise ValueError("Permutation resolution cannot reach the first Holm threshold")
    return result


def select_symbols(data_root: Path, spec: dict, sample_per_board: int = 0) -> tuple[tuple[str, ...], dict]:
    root = Path(data_root).resolve()
    qfq = resolve(root, "bars.daily.qfq", legacy_default="lake/silver/qfq_kline_daily")
    coverage_path = qfq.path / "_meta/coverage.parquet"
    basic_path = root / "lake/bronze/provider=baostock/stock_basic/stock_basic.parquet"
    if not coverage_path.is_file() or not basic_path.is_file():
        raise FileNotFoundError("Retail Crowding V1 requires qfq coverage and Baostock stock_basic")
    coverage_bytes = coverage_path.read_bytes()
    basic_bytes = basic_path.read_bytes()
    coverage = pl.read_parquet(io.BytesIO(coverage_bytes))
    basic = pl.read_parquet(io.BytesIO(basic_bytes))
    if "history_truncated" not in coverage.columns:
        raise ValueError("Retail Crowding V1 requires explicit qfq history_truncated flags")
    start = date.fromisoformat(spec["scope"]["start"])
    eligible = coverage.filter(
        (~pl.col("history_truncated")) | (pl.col("valid_from").str.to_date(strict=True) <= start)
    )
    symbols = sorted(set(eligible["code"].to_list()) & set(basic["code"].to_list()))
    boards = set(spec["scope"]["boards"])
    symbols = [s for s in symbols if _board(s) in boards and (qfq.path / f"{s.replace('.', '_')}.parquet").is_file()]
    counts = {board: sum(_board(s) == board for s in symbols) for board in sorted(boards)}
    if sample_per_board:
        if sample_per_board < 3:
            raise ValueError("sample_per_board must be zero or >= 3")
        selected = []
        for board in sorted(boards):
            bucket = [s for s in symbols if _board(s) == board]
            bucket.sort(key=lambda s: hashlib.sha256(f"retail-crowding-v1|{board}|{s}".encode()).hexdigest())
            selected.extend(bucket[:sample_per_board])
        symbols = sorted(selected)
    if len(symbols) < 10:
        raise ValueError("Retail Crowding V1 needs at least ten eligible symbols")
    evidence = {
        "selection_method": "all eligible symbols" if not sample_per_board else f"deterministic sha256 stratified sample: {sample_per_board} per board",
        "selected": len(symbols),
        "selected_by_board": {board: sum(_board(s) == board for s in symbols) for board in sorted(boards)},
        "eligible_before_sampling_by_board": counts,
        "qfq_path": str(qfq.path),
        "qfq_registry_sha256": qfq.registry_sha256,
        "coverage_path": str(coverage_path),
        "coverage_sha256": hashlib.sha256(coverage_bytes).hexdigest(),
        "stock_basic_path": str(basic_path),
        "stock_basic_sha256": hashlib.sha256(basic_bytes).hexdigest(),
        "symbols_sha256": hashlib.sha256("\n".join(symbols).encode()).hexdigest(),
    }
    return tuple(symbols), evidence


class NullableQfqResearchProvider:
    """Research-only qfq reader that preserves null volume/amount rows.

    Production MQC validation intentionally rejects these rows. This adapter
    reuses the previously audited nullable research normalization: price/time
    errors still fail closed, quantities stay null, and source bytes are
    recorded in the snapshot.
    """

    def __init__(self, root: Path, allowed_symbols: tuple[str, ...]):
        self.root = Path(root).resolve()
        resolved = resolve(self.root, "bars.daily.qfq", legacy_default="lake/silver/qfq_kline_daily")
        self.directory = resolved.path
        self.registry_sha256 = resolved.registry_sha256
        self.allowed_symbols = frozenset(allowed_symbols)

    def load(self, request: DataRequest) -> DataBatch:
        if request.timeframe != Timeframe.DAILY or not set(request.symbols) <= self.allowed_symbols:
            raise ValueError("Retail Crowding nullable provider only accepts the frozen daily symbol set")
        frames, files = [], []
        for symbol in sorted(request.symbols):
            path = self.directory / f"{symbol.replace('.', '_')}.parquet"
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError("Unsafe qfq source path")
            payload = path.read_bytes()
            original = pl.read_parquet(io.BytesIO(payload)).filter(pl.col("date").is_between(request.start, request.end))
            bars = normalize_research_frame(original, symbol)
            frames.append(bars)
            files.append({
                "path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
                "null_volume": bars["volume"].null_count(), "null_turnover": bars["turnover"].null_count(),
                "research_normalization": "nullable_volume_preserve_rows_v1",
            })
        if not frames:
            raise ValueError("No Retail Crowding qfq rows")
        bars = pl.concat(frames).sort("symbol", "datetime")
        snapshot_id = digest({
            "files": files, "request": request, "adjustment": "qfq",
            "dataset_registry_sha256": self.registry_sha256,
            "research_normalization": "nullable_volume_preserve_rows_v1",
        })
        return DataBatch(bars, DataSnapshot(snapshot_id, "retail_crowding_nullable_qfq", "qfq", tuple(files)))


@dataclass(frozen=True)
class QuantityAwareResearchUniverse:
    """Keep nullable quantity rows on the timeline but exclude them as signal dates."""

    source: object

    @property
    def universe_id(self):
        return self.source.universe_id + ":quantity_aware_research"

    @property
    def version(self):
        return self.source.version

    @property
    def metadata(self):
        return {
            **getattr(self.source, "metadata", {}),
            "quantity_policy": "volume>0 and finite volume/turnover at signal time; null rows preserved, never filled",
        }

    def mask(self, bars):
        base = self.source.mask(bars)
        quantity = bars.select(
            "symbol", "datetime",
            ((pl.col("volume") > 0) & pl.col("volume").is_finite() & pl.col("turnover").is_finite())
            .fill_null(False).alias("_quantity_eligible"),
        )
        joined = base.join(quantity, on=["symbol", "datetime"], how="left", validate="1:1")
        if joined["_quantity_eligible"].null_count():
            raise ValueError("Quantity eligibility must cover every research bar")
        return joined.select(
            "symbol", "datetime",
            (pl.col("eligible") & pl.col("_quantity_eligible")).alias("eligible"),
        )


def build_family(spec: dict, symbols: tuple[str, ...]) -> tuple[dict, dict[str, ExperimentConfig], ChronologicalSplit]:
    scope, evaluation = spec["scope"], spec["evaluation"]
    request = DataRequest(
        symbols, Timeframe.DAILY, date.fromisoformat(scope["start"]), date.fromisoformat(scope["end"])
    )
    bootstrap = BootstrapConfig(**evaluation["bootstrap"])
    permutation = PermutationConfig(**evaluation["permutation"])
    configs = {}
    trials = []
    split = ChronologicalSplit(
        date.fromisoformat(evaluation["split"]["train_end"]),
        date.fromisoformat(evaluation["split"]["valid_end"]),
    )
    for item in spec["factors"]:
        config = ExperimentConfig(
            research_question=f"Retail Crowding V1 · {item['trial_id']}",
            data=request,
            factor_id=item["factor_id"],
            factor_version=item["factor_version"],
            parameters=item["parameters"],
            horizons=tuple(evaluation["horizons"]),
            quantiles=evaluation["quantiles"],
            random_seed=20260927,
            bootstrap=bootstrap,
            permutation=permutation,
            replay=False,
        )
        configs[item["trial_id"]] = config
        trials.append({
            "trial_id": item["trial_id"],
            "config": json.loads(encode(config)),
            "study": {
                "kind": "holdout",
                "design": {"split": json.loads(encode(asdict(split)))},
            },
        })
    return {"name": "Retail Crowding V1 frozen holdout family", "alpha": permutation.alpha, "trials": trials}, configs, split


def execute(data_root: Path, output: Path, sample_per_board: int = 0, spec_path: Path = SPEC_PATH) -> dict:
    spec = load_spec(spec_path)
    resolution = inference_resolution(spec)
    symbols, selection = select_symbols(data_root, spec, sample_per_board)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "spec.json").write_text(encode(spec))
    (output / "selection.json").write_text(encode({**selection, "symbols": symbols}))
    plan, configs, split = build_family(spec, symbols)
    create_registry(plan, output / "registry")
    (output / "plan.json").write_text(encode(plan))
    if spec["scope"]["adjustment"] != "qfq":
        raise ValueError("Retail Crowding V1 is frozen to qfq")
    data = NullableQfqResearchProvider(Path(data_root), symbols)
    base_universe = build_universe(
        Path(data_root), symbols,
        UniverseConfig(mode="listing", min_listed_days=spec["scope"]["min_listed_days"]),
    )
    runner = ExperimentRunner(
        data, default_registry(), QuantityAwareResearchUniverse(base_universe),
        LocalExperimentStore(output / "runs"),
    )
    results = []
    for trial_id, config in configs.items():
        result = HoldoutRunner(runner).run(config, split)
        binding = bind_result(output / "registry", trial_id, result.artifact_path)
        results.append({
            "trial_id": trial_id,
            "run_id": result.run_id,
            "artifact_path": str(result.artifact_path),
            "binding": binding,
        })
    report = report_registry(output / "registry", output / "report")
    summary = {
        "spec_id": spec["spec_id"],
        "spec_version": spec["version"],
        "output": str(output),
        "selection": selection,
        "inference_resolution": resolution,
        "results": results,
        "report": {
            "registry_id": report["registry_id"],
            "planned_tests": report["planned_tests"],
            "available_tests": report["available_tests"],
        },
        "limitations": [
            "Host-executed frozen research; not an autonomous Niuniu research milestone.",
            "Retrospective listing eligibility and current available qfq files are not a Strict PIT tradable universe.",
            "Historical ST exclusion and transaction-cost/execution simulation are not part of V1."
        ]
    }
    (output / "summary.json").write_text(encode(summary))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-per-board", type=int, default=0,
                        help="0=all eligible; positive value creates a deterministic stratified pilot")
    parser.add_argument("--spec", type=Path, default=SPEC_PATH,
                        help="Frozen Retail Crowding V1.0.1 spec; older under-resolved specs are not executed by this runner")
    args = parser.parse_args(argv)
    print(encode(execute(args.data_root, args.output, args.sample_per_board, args.spec)))


if __name__ == "__main__":
    main()
