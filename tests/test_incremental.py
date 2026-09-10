import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import test_core
from quantlab.app import build_runner
from quantlab.experiments.ablation import AblationRunner
from quantlab.experiments.config import ExperimentConfig
from quantlab.statistics.incremental import paired_ic_statistics
from quantlab.statistics.permutation import PermutationConfig, holm
from quantlab.storage.experiments import load_record
from quantlab.workbench.jobs import prepare


class IncrementalTests(unittest.TestCase):
    def frames(self):
        rows=[{'symbol':s,'datetime':datetime(2025,1,1)+timedelta(days=d),'value':float(i),
            'forward_1':float(i)} for d in range(8) for i,s in enumerate(['A','B','C'])]
        full=pl.DataFrame(rows)
        return full, full.with_columns((-pl.col('value')).alias('value'))

    def test_paired_known_difference_null_and_order(self):
        full,reduced=self.frames();config=PermutationConfig(256,1)
        result=paired_ic_statistics(full,reduced,(1,),config,7,'a')
        for test in result['1']['permutation'].values():
            self.assertEqual(test['estimate'],2)
            self.assertEqual(test['p_value'],2/256)
            self.assertEqual(test['paired_periods'],8)
            self.assertEqual(test['paired_observations'],24)
            self.assertEqual((test['paired_full_mean'],test['paired_without_mean']),(1,-1))
        self.assertEqual(result,paired_ic_statistics(full.reverse(),reduced.reverse(),(1,),config,7,'a'))
        same=paired_ic_statistics(full,full,(1,),config,7,'same')
        for test in same['1']['permutation'].values():
            self.assertEqual((test['estimate'],test['p_value']),(0,1))
        constant=reduced.with_columns(pl.lit(1.).alias('value'))
        missing=paired_ic_statistics(full,constant,(1,),config,7,'constant')
        self.assertIsNone(missing['1']['permutation']['daily_mean_ic_difference']['p_value'])
        wrong=reduced.with_columns((pl.col('forward_1')+1).alias('forward_1'))
        with self.assertRaises(ValueError):paired_ic_statistics(full,wrong,(1,),config,7,'wrong')

    def test_common_times_only_and_insufficient_symbols(self):
        full,reduced=self.frames();reduced=reduced.filter(pl.col('datetime')>datetime(2025,1,2))
        result=paired_ic_statistics(full,reduced,(1,),PermutationConfig(64,1),0,'a')
        test=result['1']['permutation']['daily_mean_ic_difference']
        self.assertEqual((test['observed_days'],test['valid_days'],test['paired_periods']),(8,6,6))
        reduced=reduced.filter(pl.col('symbol')!='C')
        result=paired_ic_statistics(full,reduced,(1,),PermutationConfig(64,1),0,'a')
        self.assertEqual(result['1']['permutation']['daily_mean_ic_difference']['status'],'unavailable')

    def test_ablation_joint_family_and_disabled_compatibility(self):
        fixture=test_core.CoreTests();fixture.setUp()
        try:
            engine=build_runner(fixture.root,fixture.root/'out',fixture.symbols)
            config=ExperimentConfig('配对消融检验',fixture.request,'COMB.SCORE',parameters={
                'inputs':{'a':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':1}},
                'b':{'factor_id':'BASE.CLOSE_LOCATION'}},'weights':{'a':1,'b':1}},
                horizons=(1,),permutation=PermutationConfig(64,1),incremental_test=True)
            result=AblationRunner(engine).run(config)
            record=load_record(result.artifact_path/'experiment.json')
            self.assertEqual(len(record['contrasts']),2)
            self.assertEqual(record['inference']['planned_tests'],10)
            tests=record['inference']['tests']
            self.assertEqual([t['p_holm'] for t in tests],holm([t['p_value'] for t in tests]))
            self.assertIn('配对差异', (result.artifact_path/'report.md').read_text())
            for c in record['children']:
                self.assertFalse(load_record(Path(c['artifact_path'])/'experiment.json')['manifest']['config']['incremental_test'])
            repeated=AblationRunner(engine).run(config)
            again=load_record(repeated.artifact_path/'experiment.json')
            self.assertEqual(record['inference'],again['inference'])
            self.assertEqual(result.experiment_id,repeated.experiment_id)
            baseline=AblationRunner(engine).run(replace(config,incremental_test=False))
            self.assertEqual(result.comparisons,baseline.comparisons)
            self.assertNotIn('contrasts',load_record(baseline.artifact_path/'experiment.json'))
            with self.assertRaises(ValueError):engine.run(config)
            with self.assertRaises(ValueError):replace(config,permutation=None)
            with self.assertRaises(ValueError):prepare({'symbols':['sh.600000'],'start':'2025-01-01','end':'2025-01-10',
                'incremental_test':True,'permutation':{'resamples':64}})
        finally:fixture.tearDown()
