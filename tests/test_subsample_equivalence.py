import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
import polars as pl
from test_context_experiments import ContextProvider,context_config
from quantlab.app import default_registry
from quantlab.data.base import ExplicitUniverse
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.stability import run_stability
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.storage.bundle import reproduce_artifact


class SubsampleEquivalenceTest(unittest.TestCase):
    def source(self,root):
        provider=ContextProvider();symbols=[p+str(i+1).zfill(6) for p in ('sh.','sz.') for i in range(3)]
        for period,frame in provider.frames.items():
            provider.frames[period]=pl.concat([frame.with_columns(pl.col('symbol').replace_strict(dict(zip(('A','B','C'),symbols[offset:offset+3])))) for offset in (0,3)])
        cfg=replace(context_config(),context=None,replay=True);cfg=replace(cfg,data=replace(cfg.data,symbols=tuple(symbols)))
        engine=ExperimentRunner(provider,default_registry(),ExplicitUniverse(tuple(symbols)),LocalExperimentStore(root))
        result=engine.run(cfg)
        item={'name':'沪深固定样本','candidate':str(result.artifact_path),'baseline':str(result.artifact_path),
            'start':'2025-01-01','end':'2025-01-12','horizon':1,'candidate_symbols':symbols[:3],'baseline_symbols':symbols[3:],'equivalence_margin':.01}
        return {'name':'子样本验收','comparison_kind':'cross_market_equivalence','comparisons':[item],
            'permutation':{'resamples':200,'block_days':1},'bootstrap':{'resamples':200,'block_days':1}}

    def test_equivalence_and_full_source_reproduction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.source(root/'runs');result=run_stability(plan,root/'runs')
            eq=result['summary']['comparisons'][0]['equivalence']
            self.assertTrue(eq['equivalent']);self.assertEqual(eq['interval']['ci_low'],0);self.assertGreater(eq['paired_valid_dates'],2)
            self.assertEqual(reproduce_artifact(result['artifact_path'],root/'reproduced')['status'],'numerically_matched')

    def test_cohort_validation_boundary_and_tail_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.source(root/'runs');item=plan['comparisons'][0]
            item['baseline_symbols'][0]=item['candidate_symbols'][0]
            with self.assertRaisesRegex(ValueError,'overlap'):run_stability(plan,root/'runs')
            item['baseline_symbols'][0]='sz.000001';item['end']='2025-01-10'
            with self.assertRaisesRegex(ValueError,'label boundary'):run_stability(plan,root/'runs')
            item['end']='2025-01-12';plan['bootstrap']['resamples']=20
            result=run_stability(plan,root/'runs')['summary']['comparisons'][0]['equivalence']
            self.assertIsNone(result['equivalent']);self.assertEqual(result['reason'],'insufficient_resamples_in_tail')
