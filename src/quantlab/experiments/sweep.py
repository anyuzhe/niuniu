"""Explicit parameter-grid studies; no automatic selection or fitting."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from itertools import product
from math import prod
from pathlib import Path
from uuid import uuid4

from quantlab.experiments.ablation import _LoadedData
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.multitimeframe.source import with_context_source
from quantlab.statistics.permutation import inference_family
from quantlab.storage.codec import digest


@dataclass(frozen=True)
class ParameterGrid:
    parameters: dict

    def variants(self, factor, base):
        if not isinstance(self.parameters, dict) or not self.parameters:
            raise ValueError("Parameter grid must be a nonempty object")
        if any(not isinstance(k, str) or not k or not isinstance(v, list) or not v for k, v in self.parameters.items()):
            raise ValueError("Grid requires parameter names and nonempty value lists")
        if prod(len(v) for v in self.parameters.values()) > 256:
            raise ValueError("Parameter grid is limited to 256 configurations per study")
        keys = sorted(self.parameters)
        variants, seen = [], set()
        for values in product(*(self.parameters[key] for key in keys)):
            params = factor.parameters({**base, **dict(zip(keys, values))})
            fingerprint = digest(params)
            if fingerprint in seen:
                raise ValueError("Parameter grid contains duplicate resolved configurations")
            seen.add(fingerprint)
            variants.append(params)
        return variants


@dataclass(frozen=True)
class SweepResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    children: list[dict]


class SweepRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config, grid: ParameterGrid, *, split: ChronologicalSplit | None = None,
            schedule: WalkForwardConfig | None = None) -> SweepResult:
        run_id = str(uuid4())
        manifest = {"config": asdict(config), "grid": asdict(grid), "runtime": runtime_fingerprint(),
            "split": asdict(split) if split is not None else None,
            "schedule": asdict(schedule) if schedule is not None else None}
        record = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "sweep", "manifest": manifest, "children": []}
        try:
            if split is not None and schedule is not None:
                raise ValueError("Choose holdout or walk-forward for a sweep")
            if split is not None:
                split.periods(config.data)
            if schedule is not None:
                schedule.windows(config.data)
            factor = self.runner.registry.get(config.factor_id, config.factor_version)
            variants = grid.variants(factor, config.parameters)
            manifest["variants"] = variants
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest["data_snapshot"] = asdict(batch.snapshot)
            data = with_context_source(_LoadedData(batch, config.data), captured, config, manifest)
            runner = ExperimentRunner(data, self.runner.registry, self.runner.universe, self.runner.store, self.runner.research)
            for parameters in variants:
                child_config = replace(config, parameters=parameters)
                if split is not None:
                    child = HoldoutRunner(runner).run(child_config, split)
                    evaluations = [{"phase": p["name"], "metrics": p["metrics"]} for p in child.periods]
                elif schedule is not None:
                    child = WalkForwardRunner(runner).run(child_config, schedule)
                    evaluations = [{"phase": f"fold_{f['fold']}:{p['name']}", "metrics": p["metrics"]}
                        for f in child.folds for p in f["periods"]]
                else:
                    child = runner.run(child_config)
                    evaluations = [{"phase": "all", "metrics": child.metrics}]
                record["children"].append({"parameters": parameters, "experiment_id": child.experiment_id,
                    "run_id": child.run_id, "artifact_path": str(child.artifact_path), "evaluations": evaluations})
            manifest["child_experiments"] = [c["experiment_id"] for c in record["children"]]
            frozen = freeze_inputs(captured, self.runner.universe, manifest) if config.replay else {}
            record.update({"experiment_id": digest(manifest), "status": "completed"})
        except Exception as error:
            record.update({"experiment_id": digest(manifest), "status": "failed", "error": f"{type(error).__name__}: {error}"})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f"Sweep failure record could not be saved: {storage_error}")
            raise
        if config.permutation is not None:
            record['inference'] = inference_family(record, config.permutation)
        path = self.runner.store.save(run_id, record, None, **({"inputs":frozen} if config.replay else {}))
        return SweepResult(record["experiment_id"], run_id, path, record["children"])
