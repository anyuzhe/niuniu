"""Fixed-parameter rolling comparisons of factor relationships."""

import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.experiments.walkforward import WalkForwardConfig, _WindowData
from quantlab.multitimeframe.source import with_context_source
from quantlab.storage.codec import digest


def summarize_tests(folds):
    pairs = {}
    for fold in folds:
        for comparison in fold['comparisons']:
            key = (comparison['left'], comparison['right'])
            pairs.setdefault(key, []).append(comparison['periods']['test'])
    result = []
    for (left, right), tests in sorted(pairs.items()):
        values = [t['spearman'] for t in tests if t['spearman'] is not None]
        known_groups = [t['same_group'] for t in tests if t['same_group'] is not None]
        result.append({'left':left, 'right':right, 'total_folds':len(tests), 'valid_folds':len(values),
            'mean_test_spearman': math.fsum(values)/len(values) if values else None,
            'min_test_spearman':min(values) if values else None, 'max_test_spearman':max(values) if values else None,
            'positive_folds':sum(v > 0 for v in values), 'negative_folds':sum(v < 0 for v in values),
            'zero_folds':sum(v == 0 for v in values), 'known_group_folds':len(known_groups),
            'same_group_folds':sum(known_groups),
            'same_group_fraction':sum(known_groups)/len(known_groups) if known_groups else None})
    return result


@dataclass(frozen=True)
class CorrelationWalkForwardResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    folds: list[dict]
    summary: list[dict]


class CorrelationWalkForwardRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config, schedule: WalkForwardConfig) -> CorrelationWalkForwardResult:
        run_id = str(uuid4())
        manifest = {'config':asdict(config), 'schedule':asdict(schedule), 'runtime':runtime_fingerprint()}
        record = {'kind':'correlation_walkforward', 'run_id':run_id, 'created_at':datetime.now(timezone.utc).isoformat(),
            'manifest':manifest, 'folds':[]}
        try:
            windows = schedule.windows(config.data)
            manifest['windows'] = windows
            final = windows[-1]['end']
            manifest['unused_tail'] = {'start':date.fromordinal(final.toordinal()+1), 'end':config.data.end} if final < config.data.end else None
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest['data_snapshot'] = asdict(batch.snapshot)
            data = with_context_source(_WindowData(batch, config.data), captured, config, manifest)
            holdout = CorrelationHoldoutRunner(ExperimentRunner(data, self.runner.registry, self.runner.universe, self.runner.store))
            for window in windows:
                child = holdout.run(replace(config, data=replace(config.data, start=window['start'], end=window['end'])),
                    ChronologicalSplit(window['train_end'], window['valid_end']))
                record['folds'].append({**window, 'experiment_id':child.experiment_id, 'run_id':child.run_id,
                    'artifact_path':str(child.artifact_path), 'periods':child.periods, 'comparisons':child.comparisons})
            manifest['child_experiments'] = [f['experiment_id'] for f in record['folds']]
            frozen = freeze_inputs(captured,self.runner.universe,manifest)
            record.update({'experiment_id':digest(manifest), 'status':'completed', 'summary':summarize_tests(record['folds'])})
        except Exception as error:
            record.update({'experiment_id':digest(manifest), 'status':'failed', 'error':f'{type(error).__name__}: {error}'})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f'Correlation walk-forward failure record could not be saved: {storage_error}')
            raise
        path = self.runner.store.save(run_id, record, None, inputs=frozen)
        return CorrelationWalkForwardResult(record['experiment_id'], run_id, path, record['folds'], record['summary'])
