import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from test_context_experiments import ContextProvider, context_config, runner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.experiments.walkforward import WalkForwardConfig
from quantlab.experiments.sweep import ParameterGrid, SweepRunner
from quantlab.experiments.research import FactorResearchEngine
from quantlab.storage.experiments import load_record


class FailingResearch(FactorResearchEngine):
    def __init__(self):
        self.calls = 0

    def evaluate(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 2:
            raise ValueError('intentional second-child failure')
        return super().evaluate(*args, **kwargs)


class SweepTests(unittest.TestCase):
    def test_grid_results_snapshot_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = runner(provider, Path(tmp))
            cfg = context_config()
            grid = ParameterGrid({'lookback':[1,2,4]})
            result = SweepRunner(engine).run(cfg, grid)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual([c['parameters']['lookback'] for c in result.children], [1,2,4])
            repeated = SweepRunner(engine).run(cfg, grid)
            self.assertEqual(result.experiment_id, repeated.experiment_id)
            self.assertEqual([c['evaluations'] for c in result.children], [c['evaluations'] for c in repeated.children])
            for child in result.children:
                independent = engine.run(replace(cfg, parameters=child['parameters']))
                self.assertEqual(child['evaluations'][0]['metrics'], independent.metrics)
                self.assertEqual(child['experiment_id'], independent.experiment_id)
            self.assertIn('不按表现自动择优', (result.artifact_path/'report.md').read_text())

    def test_holdout_and_walkforward_sweeps(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in ({'split':ChronologicalSplit(date(2025,1,4), date(2025,1,8))},
                           {'schedule':WalkForwardConfig(4,2,2)}):
                provider = ContextProvider()
                result = SweepRunner(runner(provider, Path(tmp))).run(context_config(), ParameterGrid({'lookback':[1,2]}), **kwargs)
                self.assertEqual(len(provider.calls), 2)
                phases = [e['phase'] for e in result.children[0]['evaluations']]
                self.assertEqual(len(phases), 3 if 'split' in kwargs else 9)
                self.assertEqual(phases[-1], 'test' if 'split' in kwargs else 'fold_3:test')

    def test_invalid_grids_fail_before_read_and_are_recorded(self):
        for parameters in ({}, {'lookback':[]}, {'lookback':[1,1]}, {'lookback':[1,0]}, {'lookback':list(range(1,258))}):
            with tempfile.TemporaryDirectory() as tmp:
                provider = ContextProvider()
                with self.assertRaises(ValueError):
                    SweepRunner(runner(provider, Path(tmp))).run(context_config(), ParameterGrid(parameters))
                self.assertEqual(provider.calls, [])
                record = load_record(next(Path(tmp).glob('*/experiment.json')))
                self.assertEqual(record['status'], 'failed')
                self.assertEqual(record['kind'], 'sweep')

    def test_runtime_failure_retains_completed_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = runner(ContextProvider(), Path(tmp))
            engine.research = FailingResearch()
            with self.assertRaisesRegex(ValueError, 'second-child'):
                SweepRunner(engine).run(replace(context_config(), context=None), ParameterGrid({'lookback':[1,2,3]}))
            records = [load_record(p) for p in Path(tmp).glob('*/experiment.json')]
            parent = next(r for r in records if r.get('kind') == 'sweep')
            self.assertEqual(parent['status'], 'failed')
            self.assertEqual(len(parent['children']), 1)
            self.assertEqual(len(records), 3)


if __name__ == '__main__':
    unittest.main()
