import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from test_context_experiments import ContextProvider, runner
from test_correlation_conditions import config
from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner, summarize_tests
from quantlab.experiments.walkforward import WalkForwardConfig
from quantlab.storage.experiments import load_record


class CorrelationRollingTests(unittest.TestCase):
    def test_missing_folds_are_not_zero_and_means_are_equal_weighted(self):
        folds = [{'comparisons':[{'left':'a','right':'b','periods':{'test':{'spearman':v,'same_group':g}}}]} for v,g in [(.8,True),(None,None),(-.4,False)]]
        row = summarize_tests(folds)[0]
        self.assertAlmostEqual(row['mean_test_spearman'], .2)
        self.assertEqual((row['valid_folds'],row['total_folds']), (2,3))
        self.assertEqual(row['same_group_fraction'], .5)
        self.assertEqual((row['positive_folds'],row['negative_folds'],row['zero_folds']), (1,1,0))
        empty = summarize_tests([folds[1]])[0]
        self.assertIsNone(empty['mean_test_spearman'])
        self.assertIsNone(empty['same_group_fraction'])

    def test_rolling_prefixes_reproducibility_and_future_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = CorrelationWalkForwardRunner(runner(provider, Path(tmp)))
            cfg = config()
            schedule = WalkForwardConfig(4,2,2)
            result = engine.run(cfg, schedule)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(len(result.folds), 3)
            repeated = engine.run(cfg, schedule)
            self.assertEqual(result.experiment_id, repeated.experiment_id)
            self.assertEqual(result.summary, repeated.summary)
            changed = CorrelationWalkForwardRunner(runner(ContextProvider(True), Path(tmp))).run(cfg, schedule)
            self.assertEqual(result.folds[0]['comparisons'], changed.folds[0]['comparisons'])
            for a,b in zip(result.folds[0]['periods'],changed.folds[0]['periods']):
                assert_frame_equal(pl.read_parquet(Path(a['artifact_path'])/'observations.parquet'),
                    pl.read_parquet(Path(b['artifact_path'])/'observations.parquet'), check_exact=True)
            previous = None
            for fold in result.folds:
                test = next(p for p in fold['periods'] if p['name']=='test')
                if previous is not None:
                    self.assertGreater(test['start'], previous)
                previous = test['end']
                for p in fold['periods']:
                    record = load_record(Path(p['artifact_path'])/'experiment.json')
                    self.assertEqual(record['manifest']['context']['high_request']['end'],p['end'].isoformat())
                    self.assertEqual(record['manifest']['context']['high_request']['start'],'2024-12-30')
                    frame = pl.read_parquet(Path(p['artifact_path'])/'observations.parquet')
                    self.assertFalse(frame.filter(~pl.col('datetime').dt.date().is_between(p['start'],p['end'])).height)
            self.assertIn('缺失轮次不填零', (result.artifact_path/'report.md').read_text())

    def test_tail_and_invalid_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = CorrelationWalkForwardRunner(runner(provider,Path(tmp)))
            cfg = replace(config(),data=replace(config().data,end=date(2025,1,11)))
            result = engine.run(cfg,WalkForwardConfig(4,2,2))
            self.assertEqual(len(result.folds),2)
            self.assertEqual(load_record(result.artifact_path/'experiment.json')['manifest']['unused_tail'],
                {'start':'2025-01-11','end':'2025-01-11'})
            before = len(provider.calls)
            with self.assertRaises(ValueError):
                engine.run(cfg,WalkForwardConfig(20,2,2))
            self.assertEqual(len(provider.calls),before)
            failures = [load_record(p) for p in Path(tmp).glob('*/experiment.json')]
            self.assertTrue(any(r['kind']=='correlation_walkforward' and r['status']=='failed' for r in failures))


if __name__ == '__main__':
    unittest.main()
