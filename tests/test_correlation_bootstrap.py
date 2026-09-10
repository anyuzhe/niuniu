import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, date
from pathlib import Path

import polars as pl

from test_context_experiments import ContextProvider, runner
from test_correlation_conditions import config
from quantlab.experiments.correlation import CorrelationRunner
from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.experiments.walkforward import WalkForwardConfig
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.correlation import cross_section_correlations
from quantlab.storage.experiments import load_record


class CorrelationBootstrapTests(unittest.TestCase):
    def test_daily_estimand_missing_and_gates(self):
        rows = []
        for day,hour,sign in [(1,10,1),(1,11,-1),(2,10,1),(3,10,0)]:
            for i in range(3):
                rows.append({'symbol':str(i),'datetime':datetime(2025,1,day,hour),'factor_x':float(i),'factor_y':float(i*sign)})
        panel = pl.DataFrame(rows)
        bs = BootstrapConfig(100,1)
        pairs = cross_section_correlations(panel,['x','y'],min_periods=3,bootstrap=bs,random_seed=7)
        self.assertEqual(pairs,cross_section_correlations(panel.reverse(),['y','x'],min_periods=3,bootstrap=bs,random_seed=7))
        xy = next(p for p in pairs if (p['left'],p['right'])==('x','y'))
        self.assertAlmostEqual(xy['spearman'],1/3)
        for method in ('pearson','spearman'):
            interval = xy['bootstrap'][method]
            self.assertAlmostEqual(interval['estimate'],.5)
            self.assertEqual((interval['observed_days'],interval['valid_days']), (3,2))
            self.assertEqual(interval['status'],'computed')
        for minimum,block,reason in [(4,1,'insufficient_valid_periods'),(3,2,'insufficient_valid_days_for_two_blocks')]:
            pair = cross_section_correlations(panel,['x','y'],min_periods=minimum,bootstrap=BootstrapConfig(100,block))[1]
            self.assertEqual(pair['bootstrap']['spearman']['reason'],reason)
            self.assertIsNone(pair['bootstrap']['spearman']['ci_low'])
            self.assertEqual(pair['bootstrap']['spearman']['resamples_used'],0)
        empty = cross_section_correlations(panel.head(0),['x','y'],bootstrap=bs)
        self.assertTrue(all(p['bootstrap']['spearman']['status']=='unavailable' for p in empty))

    def test_runner_preserves_matrix_and_groups_and_persists_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = runner(ContextProvider(),Path(tmp))
            cfg = replace(config(),regime=None,regime_filter=None,bootstrap=BootstrapConfig(50,1),random_seed=7)
            a = CorrelationRunner(engine).run(cfg)
            b = CorrelationRunner(engine).run(cfg)
            raw = CorrelationRunner(engine).run(replace(cfg,bootstrap=None))
            self.assertEqual(a.experiment_id,b.experiment_id)
            self.assertEqual(a.pairs,b.pairs)
            self.assertEqual(a.groups,raw.groups)
            self.assertEqual([{k:v for k,v in p.items() if k!='bootstrap'} for p in a.pairs],raw.pairs)
            self.assertTrue(any(p['bootstrap']['spearman']['status']=='computed' for p in a.pairs))
            self.assertIn('日期分块相关置信区间',(a.artifact_path/'report.md').read_text())
            self.assertEqual(load_record(a.artifact_path/'experiment.json')['manifest']['config']['random_seed'],7)

    def test_holdout_and_rolling_propagate_and_isolate_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = replace(config(),regime=None,regime_filter=None,bootstrap=BootstrapConfig(20,1),random_seed=7)
            split = ChronologicalSplit(date(2025,1,4),date(2025,1,8))
            original = CorrelationHoldoutRunner(runner(ContextProvider(),Path(tmp))).run(cfg,split)
            changed = CorrelationHoldoutRunner(runner(ContextProvider(True),Path(tmp))).run(cfg,split)
            for p,q in zip(original.periods[:2],changed.periods[:2]):
                self.assertEqual(p['pairs'],q['pairs'])
            rolling = CorrelationWalkForwardRunner(runner(ContextProvider(),Path(tmp))).run(cfg,WalkForwardConfig(4,2,2))
            for fold in rolling.folds:
                for period in fold['periods']:
                    self.assertIn('bootstrap',period['pairs'][0])


if __name__ == '__main__':
    unittest.main()
