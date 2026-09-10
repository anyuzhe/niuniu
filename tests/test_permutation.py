import math
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import test_core
from quantlab.app import build_runner
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.sweep import ParameterGrid, SweepRunner
from quantlab.experiments.holdout import ChronologicalSplit
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.experiments.ablation import AblationRunner
from quantlab.statistics.permutation import PermutationConfig, block_sign_test, permutation_statistics, holm
from quantlab.storage.experiments import load_record
from quantlab.workbench.jobs import prepare


class PermutationTests(unittest.TestCase):
    def test_exact_sign_counts_missing_slots_and_monte_carlo(self):
        cfg=PermutationConfig(64,1)
        exact=block_sign_test([1.]*6,cfg,7)
        self.assertEqual(exact['sampling'],'exact')
        self.assertEqual(exact['p_value'],2/64)
        self.assertEqual(block_sign_test([0.]*6,cfg,7)['p_value'],1)
        missing=block_sign_test([1.,None]*6,PermutationConfig(64,2),7)
        self.assertEqual(missing['p_value'],exact['p_value'])
        self.assertEqual((missing['observed_days'],missing['valid_days'],missing['nonempty_blocks']),(12,6,6))
        short=block_sign_test([1.]*5+[None],cfg,7)
        self.assertIsNone(short['p_value'])
        monte=block_sign_test([1.]*10,PermutationConfig(20,1),7)
        self.assertEqual(monte['sampling'],'monte_carlo')
        self.assertGreaterEqual(monte['p_value'],1/21)
        self.assertEqual(monte,block_sign_test([1.]*10,PermutationConfig(20,1),7))
        for kwargs in [{'resamples':19},{'resamples':True},{'block_days':0},{'alpha':math.nan}]:
            with self.assertRaises(ValueError):PermutationConfig(**kwargs)
        with self.assertRaises(ValueError):block_sign_test([math.inf],cfg,7)

    def test_holm_known_family_and_missing_reservation(self):
        self.assertEqual(holm([.01,.04,.03,None]),[.04,.09,.09,None])
        self.assertEqual(holm([.01,.01,1]),[.03,.03,1])
        self.assertEqual(holm([None,None]),[None,None])
        with self.assertRaises(ValueError):holm([-.1])

    def test_date_weighting_constant_sections_and_order_invariance(self):
        rows=[]
        for day in range(8):
            for hour in ([10,11] if day==0 else [10]):
                for i,symbol in enumerate(['A','B','C']):
                    rows.append({'symbol':symbol,'datetime':datetime(2025,1,1)+timedelta(days=day,hours=hour),
                        'value':float(i) if day<7 else 1.,'forward_1':float(i)*(-1 if day==0 and hour==11 else 1)})
        frame=pl.DataFrame(rows)
        cfg=PermutationConfig(128,1)
        result=permutation_statistics(frame,(1,),cfg,0)
        for test in result['1'].values():
            self.assertAlmostEqual(test['estimate'],6/7)
            self.assertEqual((test['valid_days'],test['observed_days']),(7,8))
        self.assertEqual(result,permutation_statistics(frame.reverse(),(1,),cfg,0))
        empty=permutation_statistics(frame.head(0),(1,),cfg,0)
        self.assertEqual(empty['1']['daily_mean_ic']['status'],'unavailable')

    def test_runners_parent_family_reports_and_reproducibility(self):
        fixture=test_core.CoreTests();fixture.setUp()
        try:
            engine=build_runner(fixture.root,fixture.root/'out',fixture.symbols)
            config=ExperimentConfig('检验集成',fixture.request,'BASE.MOMENTUM',parameters={'lookback':2},horizons=(1,2),permutation=PermutationConfig(64,1))
            run=engine.run(config);repeated=engine.run(config)
            self.assertEqual(run.metrics,repeated.metrics)
            self.assertEqual(run.experiment_id,repeated.experiment_id)
            record=load_record(run.artifact_path/'experiment.json')
            self.assertEqual(record['inference']['planned_tests'],4)
            self.assertIn('Holm', (run.artifact_path/'report.md').read_text())
            baseline=engine.run(replace(config,permutation=None))
            self.assertNotIn('inference',load_record(baseline.artifact_path/'experiment.json'))
            for h in config.horizons:
                self.assertEqual({k:v for k,v in run.metrics[str(h)].items() if k!='permutation'},baseline.metrics[str(h)])
            plain=SweepRunner(engine).run(config,ParameterGrid({'lookback':[2,3]}))
            parent=load_record(plain.artifact_path/'experiment.json')['inference']
            self.assertEqual(parent['planned_tests'],8)
            self.assertGreater(parent['available_tests'],0)
            self.assertEqual([t['p_holm'] for t in parent['tests']],holm([t['p_value'] for t in parent['tests']]))
            for t in parent['tests']:
                if t['p_value'] is not None:self.assertGreaterEqual(t['p_holm'],t['p_value'])
            split=ChronologicalSplit(fixture.start+timedelta(days=3),fixture.start+timedelta(days=6))
            scan=SweepRunner(engine).run(config,ParameterGrid({'lookback':[2,3]}),split=split)
            family=load_record(scan.artifact_path/'experiment.json')['inference']
            self.assertEqual(family['planned_tests'],24)
            self.assertEqual([t['p_holm'] for t in family['tests']],holm([t['p_value'] for t in family['tests']]))
            rolling=WalkForwardRunner(engine).run(config,WalkForwardConfig(4,2,2))
            self.assertEqual(load_record(rolling.artifact_path/'experiment.json')['inference']['planned_tests'],24)
            combo=replace(config,factor_id='COMB.SCORE',parameters={})
            ablation=AblationRunner(engine).run(combo)
            self.assertEqual(load_record(ablation.artifact_path/'experiment.json')['inference']['planned_tests'],12)
            prepared=prepare({'start':'2025-01-01','end':'2025-01-10','symbols':['sh.600000'],
                'permutation':{'resamples':64,'block_days':1}})
            self.assertEqual(prepared.config.permutation.resamples,64)
        finally:fixture.tearDown()
