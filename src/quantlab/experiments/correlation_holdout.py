"""Fixed chronological comparisons of factor relationships; no fitting."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from uuid import uuid4

from quantlab.experiments.correlation import CorrelationRunner
from quantlab.experiments.holdout import ChronologicalSplit, _PrefixData, _PeriodUniverse
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.multitimeframe.source import with_context_source
from quantlab.storage.codec import digest


def compare_periods(periods):
    by_name = {p['name']: p for p in periods}
    aliases = sorted({p['left'] for p in periods[0]['pairs']})
    lookup = {name: {(p['left'],p['right']):p for p in period['pairs']} for name, period in by_name.items()}
    comparisons = []
    for left, right in combinations(aliases, 2):
        row = {'left':left, 'right':right, 'periods':{}}
        train = lookup['train'][(left,right)]
        for name, period in by_name.items():
            pair = lookup[name][(left,right)]
            row['periods'][name] = {**pair,
                'pearson_delta_from_train': pair['pearson']-train['pearson'] if pair['pearson'] is not None and train['pearson'] is not None else None,
                'spearman_delta_from_train': pair['spearman']-train['spearman'] if pair['spearman'] is not None and train['spearman'] is not None else None,
                'same_group': any(left in group and right in group for group in period['groups']) if pair['spearman'] is not None else None}
        comparisons.append(row)
    return comparisons


@dataclass(frozen=True)
class CorrelationHoldoutResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    periods: list[dict]
    comparisons: list[dict]


class CorrelationHoldoutRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config, split: ChronologicalSplit) -> CorrelationHoldoutResult:
        run_id = str(uuid4())
        manifest = {'config':asdict(config), 'split':asdict(split), 'runtime':runtime_fingerprint()}
        record = {'kind':'correlation_holdout', 'run_id':run_id, 'created_at':datetime.now(timezone.utc).isoformat(),
            'manifest':manifest, 'periods':[]}
        try:
            periods = split.periods(config.data)
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest['data_snapshot'] = asdict(batch.snapshot)
            data = with_context_source(_PrefixData(batch, config.data), captured, config, manifest)
            for name, start, end in periods:
                runner = ExperimentRunner(data, self.runner.registry,
                    _PeriodUniverse(self.runner.universe, name, start, end), self.runner.store)
                child = CorrelationRunner(runner).run(replace(config, data=replace(config.data, end=end)))
                record['periods'].append({'name':name,'start':start,'end':end,'experiment_id':child.experiment_id,
                    'run_id':child.run_id,'artifact_path':str(child.artifact_path),'pairs':child.pairs,'groups':child.groups})
            manifest['child_experiments'] = [p['experiment_id'] for p in record['periods']]
            frozen = freeze_inputs(captured,self.runner.universe,manifest)
            record.update({'experiment_id':digest(manifest), 'status':'completed', 'comparisons':compare_periods(record['periods'])})
        except Exception as error:
            record.update({'experiment_id':digest(manifest), 'status':'failed', 'error':f'{type(error).__name__}: {error}'})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f'Correlation holdout failure record could not be saved: {storage_error}')
            raise
        path = self.runner.store.save(run_id, record, None, inputs=frozen)
        return CorrelationHoldoutResult(record['experiment_id'], run_id, path, record['periods'], record['comparisons'])
