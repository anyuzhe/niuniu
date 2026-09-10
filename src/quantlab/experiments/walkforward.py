"""Rolling, fixed-parameter holdouts with disjoint test periods."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl

from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.statistics.permutation import inference_family
from quantlab.storage.codec import digest
from quantlab.multitimeframe.source import with_context_source


@dataclass(frozen=True)
class WalkForwardConfig:
    train_days: int
    valid_days: int
    test_days: int
    expanding: bool = False

    def __post_init__(self):
        if type(self.expanding) is not bool:raise ValueError("expanding must be boolean")
        if any(type(n) is not int or n < 1 for n in (self.train_days, self.valid_days, self.test_days)):
            raise ValueError("Walk-forward lengths must be positive integer calendar days")

    def windows(self, request: DataRequest):
        total = self.train_days + self.valid_days + self.test_days
        days = (request.end - request.start).days + 1
        if total > days:
            raise ValueError("Date range cannot fit a complete walk-forward window")
        windows = []
        for offset in range(0, days - total + 1, self.test_days):
            start = request.start.toordinal() + offset
            windows.append({"fold": len(windows) + 1, "start": request.start if self.expanding else date.fromordinal(start),
                "train_end": date.fromordinal(start + self.train_days - 1),
                "valid_end": date.fromordinal(start + self.train_days + self.valid_days - 1),
                "end": date.fromordinal(start + total - 1)})
        return windows


@dataclass(frozen=True)
class _WindowData:
    batch: DataBatch
    request: DataRequest

    def load(self, request):
        if request.symbols != self.request.symbols or request.timeframe != self.request.timeframe or not self.request.start <= request.start <= request.end <= self.request.end:
            raise ValueError("Walk-forward child requested data outside the study")
        bars = self.batch.bars.filter(pl.col("datetime").dt.date().is_between(request.start, request.end))
        if bars.is_empty():
            raise ValueError("No data in walk-forward window")
        source = self.batch.snapshot
        snapshot = DataSnapshot(digest({"parent_snapshot": source.snapshot_id, "window_request": request}),
            source.source + ":window", source.adjustment, source.files)
        return DataBatch(bars, snapshot)


@dataclass(frozen=True)
class WalkForwardResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    folds: list[dict]


class WalkForwardRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config: ExperimentConfig, schedule: WalkForwardConfig) -> WalkForwardResult:
        run_id = str(uuid4())
        manifest = {"config": asdict(config), "schedule": asdict(schedule), "runtime": runtime_fingerprint()}
        record = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "walkforward", "manifest": manifest, "folds": []}
        try:
            windows = schedule.windows(config.data)
            manifest["windows"] = windows
            final = windows[-1]["end"]
            manifest["unused_tail"] = {"start": date.fromordinal(final.toordinal() + 1), "end": config.data.end} if final < config.data.end else None
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest["data_snapshot"] = asdict(batch.snapshot)
            data = with_context_source(_WindowData(batch, config.data), captured, config, manifest)
            holdout = HoldoutRunner(ExperimentRunner(data, self.runner.registry,
                self.runner.universe, self.runner.store, self.runner.research))
            for window in windows:
                child_config = replace(config, data=replace(config.data, start=window["start"], end=window["end"]))
                child = holdout.run(child_config, ChronologicalSplit(window["train_end"], window["valid_end"]))
                record["folds"].append({**window, "experiment_id": child.experiment_id, "run_id": child.run_id,
                    "artifact_path": str(child.artifact_path), "periods": child.periods})
            manifest["child_experiments"] = [{"fold": f["fold"], "experiment_id": f["experiment_id"]} for f in record["folds"]]
            frozen = freeze_inputs(captured, self.runner.universe, manifest) if config.replay else {}
            record.update({"experiment_id": digest(manifest), "status": "completed"})
        except Exception as error:
            record.update({"experiment_id": digest(manifest), "status": "failed", "error": f"{type(error).__name__}: {error}"})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f"Walk-forward failure record could not be saved: {storage_error}")
            raise
        if config.permutation is not None:
            record['inference'] = inference_family(record, config.permutation)
        path = self.runner.store.save(run_id, record, None, **({"inputs":frozen} if config.replay else {}))
        return WalkForwardResult(record["experiment_id"], run_id, path, record["folds"])
