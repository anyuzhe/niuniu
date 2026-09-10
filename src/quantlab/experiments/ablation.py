"""Leave-one-input-out comparisons on a common eligible sample."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl

from quantlab.data.base import DataBatch, DataRequest
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.factors.combinations import CombinationFactor
from quantlab.factors.engine import compute_factor
from quantlab.statistics.permutation import inference_family
from quantlab.statistics.incremental import paired_ic_statistics
from quantlab.storage.codec import digest
from quantlab.multitimeframe.source import with_context_source


def remove_condition(rule: dict, alias: str) -> dict | None:
    """Structural deletion: drop empty groups, collapse single-child groups."""
    if "input" in rule:
        return None if rule["input"] == alias else deepcopy(rule)
    if "not" in rule:
        child = remove_condition(rule["not"], alias)
        return {"not": child} if child is not None else None
    key = "all" if "all" in rule else "any"
    children = [child for item in rule[key] if (child := remove_condition(item, alias)) is not None]
    if not children:
        return None
    return children[0] if len(children) == 1 else {key: children}


def variants(factor: CombinationFactor, parameters: dict) -> dict[str, dict]:
    parameters = factor.parameters(parameters)
    if len(parameters["inputs"]) < 2:
        raise ValueError("Ablation needs at least two inputs")
    result = {}
    for alias in parameters["inputs"]:
        variant = deepcopy(parameters)
        del variant["inputs"][alias]
        if factor.mode == "weights":
            del variant["weights"][alias]
        else:
            variant["rule"] = remove_condition(variant["rule"], alias)
        result[alias] = factor.parameters(variant)
    return result


@dataclass(frozen=True)
class _LoadedData:
    batch: DataBatch
    request: DataRequest

    def load(self, request):
        if request != self.request:
            raise ValueError("Ablation data request changed")
        return self.batch


@dataclass(frozen=True)
class _CommonUniverse:
    values: pl.DataFrame
    universe_id: str
    version: str

    def mask(self, bars):
        return self.values.clone()


@dataclass(frozen=True)
class AblationResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    comparisons: list[dict]


def compare_metrics(full: dict, reduced: dict) -> dict:
    result = {}
    for horizon, reference in full.items():
        other = reduced[horizon]
        keys = ["observations", "mean_forward_return", "ic", "rank_ic", "long_short_spread"]
        pairs = {key: (reference[key], other[key]) for key in keys}
        if "triggered" in reference:
            pairs.update({f"triggered_{key}": (reference["triggered"][key], other["triggered"][key])
                for key in ("event_count", "labelled_count", "mean_forward_return", "positive_return_rate")})
        result[horizon] = {key: {"full": a, "without": b, "delta_full_minus_without": a - b if a is not None and b is not None else None}
            for key, (a, b) in pairs.items()}
    return result


class AblationRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config: ExperimentConfig) -> AblationResult:
        run_id = str(uuid4())
        manifest = {"config": asdict(config), "runtime": runtime_fingerprint()}
        record = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "ablation", "manifest": manifest, "children": []}
        comparisons = []
        try:
            factor = self.runner.registry.get(config.factor_id, config.factor_version)
            if not isinstance(factor, CombinationFactor):
                raise ValueError("Ablation requires COMB.CONDITION or COMB.SCORE")
            parameters = factor.parameters(config.parameters)
            reduced = variants(factor, parameters)
            manifest["parameters"] = parameters
            manifest["variants"] = reduced
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            values = compute_factor(factor, batch.bars, parameters)
            if values.filter(pl.col("available_at") != pl.col("datetime")).height:
                raise ValueError("Ablation requires factors available at bar close")
            original = self.runner.universe.mask(batch.bars)
            common = values.select("symbol", "datetime", pl.col("value").is_not_null().alias("ready")).join(
                original, on=["symbol", "datetime"], how="left", validate="1:1")
            if common["eligible"].null_count():
                raise ValueError("Universe mask must cover every ablation row")
            common = common.select("symbol", "datetime", (pl.col("ready") & pl.col("eligible")).alias("eligible")).sort("symbol", "datetime")
            manifest.update({"data_snapshot": asdict(batch.snapshot), "common_mask_hash": digest(common.write_json()),
                "original_universe": {"id": self.runner.universe.universe_id, "version": self.runner.universe.version},
                "common_eligible_before_regime": common.filter(pl.col("eligible")).height})
            # One exact data read for the study. Children keep independent
            # experiment artifacts and the existing regime/label semantics.
            data = with_context_source(_LoadedData(batch, config.data), captured, config, manifest)
            child_runner = ExperimentRunner(data, self.runner.registry,
                _CommonUniverse(common, self.runner.universe.universe_id + ":ablation_common", self.runner.universe.version),
                self.runner.store, self.runner.research)
            full = child_runner.run(replace(config, parameters=parameters, incremental_test=False))
            record["children"].append({"removed": None, "experiment_id": full.experiment_id, "run_id": full.run_id, "artifact_path": str(full.artifact_path)})
            if config.permutation is not None:
                record['children'][-1]['metrics'] = full.metrics
            if config.incremental_test:
                full_observations = pl.read_parquet(full.artifact_path / 'observations.parquet')
                record['contrasts'] = []
            for alias, variant in reduced.items():
                child = child_runner.run(replace(config, parameters=variant, incremental_test=False))
                record["children"].append({"removed": alias, "experiment_id": child.experiment_id, "run_id": child.run_id, "artifact_path": str(child.artifact_path)})
                if config.permutation is not None:
                    record['children'][-1]['metrics'] = child.metrics
                if config.incremental_test:
                    reduced_observations = pl.read_parquet(child.artifact_path / 'observations.parquet')
                    contrast = paired_ic_statistics(full_observations, reduced_observations, config.horizons,
                        config.permutation, config.random_seed, alias)
                    record['contrasts'].append({'name':alias, 'metrics':contrast,
                        'full_run_id':full.run_id, 'without_run_id':child.run_id})
                comparisons.append({"removed": alias, "metrics": compare_metrics(full.metrics, child.metrics)})
            manifest["child_experiments"] = [{"removed": c["removed"], "experiment_id": c["experiment_id"]} for c in record["children"]]
            frozen = freeze_inputs(captured, self.runner.universe, manifest) if config.replay else {}
            record.update({"experiment_id": digest(manifest), "status": "completed", "comparisons": comparisons})
        except Exception as error:
            record.update({"experiment_id": digest(manifest), "status": "failed", "error": f"{type(error).__name__}: {error}"})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f"Ablation failure record could not be saved: {storage_error}")
            raise
        if config.permutation is not None:
            record['inference'] = inference_family(record, config.permutation)
        path = self.runner.store.save(run_id, record, None, **({"inputs":frozen} if config.replay else {}))
        return AblationResult(record["experiment_id"], run_id, path, comparisons)
