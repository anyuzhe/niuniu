import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from datetime import date
from test_context_experiments import ContextProvider,context_config,runner
from quantlab.experiments.residual import run_residual
from quantlab.experiments.stability import run_stability
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.experiments.return_increment import compare_returns
from quantlab.experiments.return_family import run_return_family
from quantlab.storage.bundle import reproduce_artifact,export_bundle,restore_bundle
from quantlab.storage.experiments import load_record_fields


class DerivedReproductionTests(unittest.TestCase):
    def sources(self,root,execution=False):
        engine=runner(ContextProvider(),root);cfg=replace(context_config(),context=None,replay=True)
        results=[]
        for lookback in (1,2):
            c=replace(cfg,parameters={'lookback':lookback})
            results.append(ExecutionStudy(engine).run(c,ExecutionConfig(initial_cash=100000,top_n=1)) if execution else engine.run(c))
        return [r.artifact_path for r in results]

    def test_stability_preserves_original_plan_seed_after_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a,b=self.sources(root/'runs')
            plan={'name':'paired','comparisons':[{'name':'lookback','candidate':str(a),'baseline':str(b),'start':'2025-01-01','end':'2025-01-12','horizon':1}],'permutation':{'resamples':20,'block_days':1},'bootstrap':{'resamples':20,'block_days':1}}
            original=run_stability(plan,root/'runs');export_bundle(original['artifact_path'],root/'bundle.zip');restore_bundle(root/'bundle.zip',root/'restored')
            (root/'runs').rename(root/'unavailable-original')
            result=reproduce_artifact(root/'restored/runs'/original['run_id'],root/'out')
            self.assertEqual(result['status'],'numerically_matched')
            actual=load_record_fields(Path(result['artifact_path'])/'experiment.json',{'manifest'})
            self.assertEqual(actual['manifest']['plan'],plan)

    def test_residual_recomputes_training_projection_and_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a,b=self.sources(root/'runs')
            original=run_residual(a,[b],date(2025,1,6),root/'runs')
            result=reproduce_artifact(original['artifact_path'],root/'out')
            self.assertEqual(result['status'],'numerically_matched')
            self.assertEqual(len(result['run_mapping']),3)

    def test_return_comparison_and_family_keep_failed_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a,b=self.sources(root/'runs',True)
            original=compare_returns(a,b,date(2025,1,3),root/'runs')
            self.assertEqual(reproduce_artifact(original['artifact_path'],root/'out')['status'],'numerically_matched')
            plan={'name':'fixed family','alpha':.05,'comparisons':[{'id':'known','candidate':str(a),'baseline':str(b),'start':'2025-01-03'}, {'id':'unavailable','candidate':str(root/'missing'),'baseline':str(b),'start':'2025-01-03'}]}
            family=run_return_family(plan,root/'runs')
            export_bundle(family['archive_path'],root/'family.zip');restore_bundle(root/'family.zip',root/'restored')
            result=reproduce_artifact(root/'restored/runs'/family['run_id'],root/'family-out')
            self.assertEqual(result['status'],'available_results_matched')
            self.assertEqual(result['planned_tests'],2);self.assertEqual(result['preserved_failed_slots'],1)
            self.assertEqual(result['recomputed_tests'],1)
            actual=load_record_fields(Path(result['artifact_path'])/'experiment.json',{'summary','manifest'})
            self.assertEqual(actual['summary']['tests'][0]['p_holm'],family['report']['tests'][0]['p_holm'])
            original_registry=json.loads((Path(family['artifact_path'])/'plan.json').read_text())
            self.assertEqual(actual['manifest']['registry'],original_registry)
