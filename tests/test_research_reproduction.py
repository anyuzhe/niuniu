import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import polars as pl
from test_context_experiments import ContextProvider,context_config
from quantlab.app import default_registry
from quantlab.data.base import ExplicitUniverse
from quantlab.data.universe import HistoricalUniverse,UniverseConfig
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.holdout import HoldoutRunner,ChronologicalSplit
from quantlab.experiments.walkforward import WalkForwardRunner,WalkForwardConfig
from quantlab.experiments.sweep import SweepRunner,ParameterGrid
from quantlab.experiments.ablation import AblationRunner
from quantlab.experiments.theory_study import TheoryStudyRunner,TheoryStudyPlan
from quantlab.experiments.correlation import CorrelationRunner,CorrelationConfig
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.storage.bundle import reproduce_artifact,export_bundle,restore_bundle
from quantlab.storage.codec import encode
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.processing.pipeline import PipelineConfig


class ResearchReproductionTests(unittest.TestCase):
    def runner(self,path,mode='pit'):
        symbols=('A','B','C')
        if mode=='listing':
            frame=pl.DataFrame({'code':symbols,'ipoDate':['2020-01-01']*3,'outDate':['','','2025-01-08']})
        else:
            at=lambda d:datetime(2025,1,d,tzinfo=ZoneInfo('Asia/Shanghai'))
            frame=pl.DataFrame({'symbol':['A','B','C','C'],'effective_at':[at(1)]*3+[at(5)],'available_at':[at(1)]*3+[at(7)],'eligible':[True,True,True,False]})
        universe=HistoricalUniverse(symbols,frame,UniverseConfig(mode),{'source':'synthetic historical fixture; not official records'})
        return ExperimentRunner(ContextProvider(),default_registry(),universe,LocalExperimentStore(path))

    def combo(self):
        return {'inputs':{'a':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':1}},'b':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':2}}},'weights':{'a':.5,'b':.5}}

    def test_historical_metadata_and_daily_context_rebuilt_without_sources(self):
        for mode in ('listing','pit'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);runner=self.runner(root/'runs',mode)
                cfg=replace(context_config(),replay=True,processor=CrossSectionConfig())
                original=runner.run(cfg)
                with patch.object(ContextProvider,'load',side_effect=AssertionError('live source accessed')):
                    result=reproduce_artifact(original.artifact_path,root/'out')
                self.assertEqual(result['status'],'numerically_matched');self.assertEqual(result['checked_runs'],1)

    def test_parent_studies_rebuild_all_descendants_and_training_pipeline(self):
        for kind in ('holdout','walkforward','sweep','ablation','theory_study','correlation','correlation_holdout','correlation_walkforward'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);runner=self.runner(root/'runs');cfg=replace(context_config(),replay=True)
                split=ChronologicalSplit(date(2025,1,4),date(2025,1,8));schedule=WalkForwardConfig(4,3,3)
                if kind=='holdout':original=HoldoutRunner(runner).run(replace(cfg,processor=PipelineConfig([{'method':'robust_zscore'}])),split)
                elif kind=='walkforward':original=WalkForwardRunner(runner).run(cfg,schedule)
                elif kind=='sweep':original=SweepRunner(runner).run(cfg,ParameterGrid({'lookback':[1,2]}),split=split)
                elif kind=='ablation':original=AblationRunner(runner).run(replace(cfg,factor_id='COMB.SCORE',parameters=self.combo()))
                elif kind=='theory_study':original=TheoryStudyRunner(runner).run(replace(cfg,factor_id='COMB.SCORE',parameters=self.combo()),TheoryStudyPlan(split,schedule,'a',{'lookback':[1,2]},False))
                else:
                    from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
                    from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner
                    correlation=CorrelationConfig('correlation',cfg.data,self.combo()['inputs'],context=cfg.context,min_periods=1)
                    if kind=='correlation_holdout':original=CorrelationHoldoutRunner(runner).run(correlation,split)
                    elif kind=='correlation_walkforward':original=CorrelationWalkForwardRunner(runner).run(correlation,schedule)
                    else:original=CorrelationRunner(runner).run(correlation)
                with patch.object(ContextProvider,'load',side_effect=AssertionError('live source accessed')):
                    result=reproduce_artifact(original.artifact_path,root/'out')
                self.assertEqual(result['status'],'numerically_matched')
                self.assertEqual(result['checked_runs'],len(list((root/'runs').glob('*/experiment.json'))))

    def test_missing_and_changed_inputs_refuse_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.runner(root/'runs').run(replace(context_config(),replay=True))
            path=next(original.artifact_path.glob('input-*.parquet'));payload=path.read_bytes();path.unlink()
            with self.assertRaises(FileNotFoundError):reproduce_artifact(original.artifact_path,root/'out')
            path.write_bytes(payload)
            frame=pl.read_parquet(path)
            if 'eligible' in frame:frame=frame.with_columns(~pl.col('eligible'))
            else:frame=frame.with_columns((pl.col('close')+1).alias('close'))
            frame.write_parquet(path)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):reproduce_artifact(original.artifact_path,root/'out')
            self.assertFalse((root/'out').exists())

    def test_parent_difference_is_persisted_and_bundle_is_portable(self):
        import os,sys,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=HoldoutRunner(self.runner(root/'runs')).run(replace(context_config(),replay=True),ChronologicalSplit(date(2025,1,4),date(2025,1,8)))
            export_bundle(original.artifact_path,root/'bundle.zip');restore_bundle(root/'bundle.zip',root/'delivery')
            run=subprocess.run([sys.executable,str(root/'delivery/tools/reproduce.py'),str(root/'delivery/runs'/original.run_id),str(root/'portable')],env={**os.environ,'PYTHONPATH':str(root/'delivery/source')},text=True,capture_output=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout)['checked_runs'],4)
            path=original.artifact_path/'experiment.json';r=json.loads(path.read_text());r['periods'][0]['metrics']['1']['observations']+=1;path.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'Reproduction'):reproduce_artifact(original.artifact_path,root/'mismatch')
            result=list((root/'mismatch').glob('*/reproduction.json'));self.assertEqual(len(result),1)
            self.assertEqual(json.loads(result[0].read_text())['status'],'mismatch')

    def test_execution_with_pit_and_context(self):
        from quantlab.experiments.execution import ExecutionStudy
        from quantlab.execution.backtest import ExecutionConfig
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runner=self.runner(root/'runs')
            config=replace(context_config(),replay=True,processor=CrossSectionConfig())
            original=ExecutionStudy(runner).run(config,ExecutionConfig(initial_cash=100000,top_n=2))
            self.assertGreater(original.summary['fills'],0)
            self.assertEqual(reproduce_artifact(original.artifact_path,root/'out')['status'],'numerically_matched')
