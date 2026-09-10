"""Chronological fixed-parameter evaluation, not automatic model fitting."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl

from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, UniverseProvider
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.statistics.permutation import inference_family
from quantlab.storage.codec import digest
from quantlab.multitimeframe.source import with_context_source
from quantlab.processing.pipeline import PipelineConfig


@dataclass(frozen=True)
class ChronologicalSplit:
    train_end: date
    valid_end: date

    def __post_init__(self):
        if type(self.train_end) is not date or type(self.valid_end) is not date or self.train_end >= self.valid_end:
            raise ValueError("Split requires dates with train_end < valid_end")

    def periods(self, request: DataRequest):
        if not request.start <= self.train_end < self.valid_end < request.end:
            raise ValueError("Require data.start <= train_end < valid_end < data.end")
        return (
            ("train", request.start, self.train_end),
            ("valid", self.train_end + timedelta(days=1), self.valid_end),
            ("test", self.valid_end + timedelta(days=1), request.end),
        )


@dataclass(frozen=True)
class _PrefixData:
    batch: DataBatch
    request: DataRequest

    def load(self, request):
        if request.symbols != self.request.symbols or request.timeframe != self.request.timeframe or request.start != self.request.start or not request.start <= request.end <= self.request.end:
            raise ValueError("Holdout child must request a prefix of the study data")
        bars = self.batch.bars.filter(pl.col("datetime").dt.date() <= request.end)
        if bars.is_empty():
            raise ValueError("No data in requested holdout prefix")
        source = self.batch.snapshot
        snapshot = DataSnapshot(digest({"parent_snapshot": source.snapshot_id, "prefix_request": request}),
            source.source + ":prefix", source.adjustment, source.files)
        return DataBatch(bars, snapshot)


@dataclass(frozen=True)
class _PeriodUniverse:
    source: UniverseProvider
    name: str
    start: date
    end: date

    @property
    def universe_id(self):
        return f"{self.source.universe_id}:{self.name}:{self.start}:{self.end}"

    @property
    def version(self):
        return self.source.version

    @property
    def metadata(self):
        return getattr(self.source, 'metadata', {})

    def mask(self, bars):
        return self.source.mask(bars).with_columns(
            (pl.col("eligible") & pl.col("datetime").dt.date().is_between(self.start, self.end)).alias("eligible"))


@dataclass(frozen=True)
class HoldoutResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    periods: list[dict]


class HoldoutRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config: ExperimentConfig, split: ChronologicalSplit) -> HoldoutResult:
        run_id = str(uuid4())
        manifest = {"config": asdict(config), "split": asdict(split), "runtime": runtime_fingerprint()}
        record = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "kind": "holdout", "manifest": manifest, "periods": []}
        try:
            periods = split.periods(config.data)
            if isinstance(config.processor, PipelineConfig):
                config = replace(config, processor=replace(config.processor, fit_start=config.data.start, fit_end=split.train_end))
                manifest['config'] = asdict(config)
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest["data_snapshot"] = asdict(batch.snapshot)
            data = with_context_source(_PrefixData(batch, config.data), captured, config, manifest)
            for name, start, end in periods:
                child_runner = ExperimentRunner(data, self.runner.registry,
                    _PeriodUniverse(self.runner.universe, name, start, end), self.runner.store, self.runner.research)
                child = child_runner.run(replace(config, data=replace(config.data, end=end)))
                record["periods"].append({"name": name, "start": start, "end": end,
                    "experiment_id": child.experiment_id, "run_id": child.run_id, "artifact_path": str(child.artifact_path), "metrics": child.metrics})
            manifest["child_experiments"] = [{"name": p["name"], "experiment_id": p["experiment_id"]} for p in record["periods"]]
            frozen = freeze_inputs(captured, self.runner.universe, manifest) if config.replay else {}
            record.update({"experiment_id": digest(manifest), "status": "completed"})
        except Exception as error:
            record.update({"experiment_id": digest(manifest), "status": "failed", "error": f"{type(error).__name__}: {error}"})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f"Holdout failure record could not be saved: {storage_error}")
            raise
        if config.permutation is not None:
            record['inference'] = inference_family(record, config.permutation)
        path = self.runner.store.save(run_id, record, None, **({"inputs":frozen} if config.replay else {}))
        return HoldoutResult(record["experiment_id"], run_id, path, record["periods"])
