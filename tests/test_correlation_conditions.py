import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from test_context_experiments import ContextProvider, context_config, runner
from quantlab.experiments.correlation import CorrelationConfig, CorrelationRunner
from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.storage.experiments import load_record


def config():
    base = context_config()
    return CorrelationConfig('条件相关分段', base.data, {
        'short':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':1}},
        'long':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':4}}}, min_periods=1,
        processor=CrossSectionConfig(), regime=RegimeConfig(2,1), regime_filter=RegimeFilter(direction='Bull'), context=base.context)


class CorrelationConditionTests(unittest.TestCase):
    def test_same_pipeline_as_factor_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = runner(provider, Path(tmp))
            cfg = config()
            result = CorrelationRunner(engine).run(cfg)
            self.assertEqual(len(provider.calls), 2)
            panel = pl.read_parquet(result.artifact_path/'observations.parquet')
            self.assertGreater(panel.height, 0)
            self.assertTrue((panel['context_value'] > 0).all())
            self.assertTrue((panel['regime_direction'] == 'Bull').all())
            for alias, spec in cfg.inputs.items():
                original = engine.run(replace(context_config(), factor_id=spec['factor_id'], parameters=spec['parameters'],
                    processor=cfg.processor, regime=cfg.regime, regime_filter=cfg.regime_filter))
                observations = pl.read_parquet(original.artifact_path/'observations.parquet')
                assert_frame_equal(panel.select('symbol','datetime',pl.col(f'factor_{alias}').alias('value'),pl.col(f'raw_factor_{alias}').alias('raw_value')),
                    observations.select('symbol','datetime','value','raw_value'), check_exact=True)
            record = load_record(result.artifact_path/'experiment.json')
            counts = record['selection_summary']
            self.assertGreaterEqual(counts['universe_rows'], counts['after_regime_rows'])
            self.assertGreaterEqual(counts['after_regime_rows'], counts['selected_rows'])

    def test_holdout_reproducible_and_future_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            split = ChronologicalSplit(date(2025,1,4), date(2025,1,8))
            provider = ContextProvider()
            engine = CorrelationHoldoutRunner(runner(provider, Path(tmp)))
            result = engine.run(config(), split)
            self.assertEqual(len(provider.calls), 2)
            repeated = engine.run(config(), split)
            self.assertEqual(result.experiment_id, repeated.experiment_id)
            self.assertEqual(result.comparisons, repeated.comparisons)
            changed = CorrelationHoldoutRunner(runner(ContextProvider(True), Path(tmp))).run(config(), split)
            for p, q in zip(result.periods[:2], changed.periods[:2]):
                self.assertEqual(p['pairs'], q['pairs'])
                self.assertEqual(p['groups'], q['groups'])
                assert_frame_equal(pl.read_parquet(Path(p['artifact_path'])/'observations.parquet'),
                    pl.read_parquet(Path(q['artifact_path'])/'observations.parquet'), check_exact=True)
            for p in result.periods:
                record = load_record(Path(p['artifact_path'])/'experiment.json')
                self.assertEqual(record['manifest']['context']['high_request']['end'], p['end'].isoformat())
                panel = pl.read_parquet(Path(p['artifact_path'])/'observations.parquet')
                self.assertFalse(panel.filter(~pl.col('datetime').dt.date().is_between(p['start'], p['end'])).height)
            self.assertIn('相对训练段', (result.artifact_path/'report.md').read_text())

    def test_unknown_stability_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = runner(provider, Path(tmp))
            cfg = config()
            empty = replace(cfg, context=replace(cfg.context, parameters={'lookback':1000}, op='ne'))
            result = CorrelationHoldoutRunner(engine).run(empty, ChronologicalSplit(date(2025,1,4),date(2025,1,8)))
            for comparison in result.comparisons:
                for p in comparison['periods'].values():
                    self.assertIsNone(p['same_group'])
                    self.assertIsNone(p['spearman_delta_from_train'])
            before = len(provider.calls)
            with self.assertRaises(ValueError):
                CorrelationHoldoutRunner(engine).run(cfg, ChronologicalSplit(date(2024,1,1),date(2024,2,1)))
            self.assertEqual(before, len(provider.calls))
            boolean = replace(cfg, inputs={**cfg.inputs, 'event':{'factor_id':'EVT.BREAKOUT_HIGH'}})
            with self.assertRaisesRegex(ValueError, 'scalar'):
                CorrelationRunner(engine).run(boolean)
            self.assertEqual(before, len(provider.calls))
            records = [load_record(p) for p in Path(tmp).glob('*/experiment.json')]
            self.assertEqual(sum(r['status']=='failed' for r in records), 2)


if __name__ == '__main__':
    unittest.main()
