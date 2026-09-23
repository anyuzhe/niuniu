import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import polars as pl
from test_technical import bars
from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataSnapshot, ExplicitUniverse
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.execution import ExecutionStudy
from quantlab.execution.backtest import ExecutionConfig
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.storage.bundle import reproduce_artifact, export_bundle, restore_bundle
from quantlab.workbench.jobs import prepare
from _optional import requires_vnpy


class ExecutionReproductionTests(unittest.TestCase):
    def original(self,root,backend='open',price_mode='account'):
        raw=bars([10.+i*.1+(i%7)*.2 for i in range(45)],'sh.600000')
        signal=raw.with_columns(pl.col('open','high','low','close')*.5)
        class Source:
            def __init__(self,frame,adjustment):self.frame=frame;self.adjustment=adjustment
            def load(self,request):
                if price_mode=='research' and self.adjustment=='raw':raise AssertionError('Research mode fetched raw prices')
                return DataBatch(self.frame,DataSnapshot(digest(self.frame.write_json()),'synthetic reproduction fixture',self.adjustment,()))
        config=prepare({'question':'归档执行复算测试','factor':'BASE.MOMENTUM','parameters':{'lookback':2},
            'symbols':['sh.600000'],'timeframe':'1d','start':'2025-01-01','end':'2025-02-14','horizons':[1], 'adjustment':'qfq','replay':True}).config
        runner=ExperimentRunner(Source(signal,'qfq'),default_registry(),ExplicitUniverse(config.data.symbols),LocalExperimentStore(root))
        return ExecutionStudy(runner,Source(raw,'raw')).run(config,ExecutionConfig(initial_cash=10000,top_n=1,price_mode=price_mode),backend=backend)

    def test_qfq_signal_raw_execution_and_portable_helper(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.original(root/'runs')
            record=json.loads((original.artifact_path/'experiment.json').read_text())
            self.assertTrue(record['fills'])
            with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('External lake accessed')):
                result=reproduce_artifact(original.artifact_path,root/'reproduced')
            self.assertEqual(result['status'],'numerically_matched')
            self.assertEqual(json.loads((Path(result['artifact_path'])/'reproduction.json').read_text())['status'],'numerically_matched')
            export_bundle(original.artifact_path,root/'bundle.zip')
            restored=restore_bundle(root/'bundle.zip',root/'delivery')
            env={**os.environ,'PYTHONPATH':str(root/'delivery/source')}
            run=subprocess.run([sys.executable,str(root/'delivery/tools/reproduce.py'),str(Path(restored['artifact_root'])/original.run_id),str(root/'portable-output')],env=env,text=True,capture_output=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout)['status'],'numerically_matched')

    def test_changed_fills_are_reported_as_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.original(root/'runs');path=original.artifact_path/'experiment.json'
            record=json.loads(path.read_text());record['fills'][0]['price']+=1;path.write_text(encode(record))
            with self.assertRaisesRegex(ValueError,'fills'):
                reproduce_artifact(original.artifact_path,root/'reproduced')
            results=list((root/'reproduced').glob('*/reproduction.json'))
            self.assertEqual(len(results),1)
            self.assertEqual(json.loads(results[0].read_text())['status'],'mismatch')

    def test_missing_child_bad_runtime_and_targets_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.original(root/'runs');path=original.artifact_path/'experiment.json'
            record=json.loads(path.read_text());changed=json.loads(path.read_text())
            changed['manifest']['runtime']['code_hash']='different';path.write_text(encode(changed))
            with self.assertRaisesRegex(ValueError,'fingerprint'):reproduce_artifact(original.artifact_path,root/'out')
            path.write_text(encode(record));child=root/'runs'/record['children'][0]['run_id']
            child.rename(root/'missing')
            with self.assertRaises(FileNotFoundError):reproduce_artifact(original.artifact_path,root/'out')
            (root/'missing').rename(child)
            targets=original.artifact_path/'targets.parquet'
            pl.read_parquet(targets).with_columns(pl.lit(0.).alias('weight')).write_parquet(targets)
            with self.assertRaisesRegex(ValueError,'targets hash'):reproduce_artifact(original.artifact_path,root/'out')
            self.assertFalse((root/'out').exists())

    @requires_vnpy
    def test_native_vnpy_rules_reproduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.original(root/'runs','vnpy_rules')
            self.assertEqual(reproduce_artifact(original.artifact_path,root/'out')['status'],'numerically_matched')

    def test_research_prices_need_no_raw_source_and_reproduce(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=self.original(root/'runs',price_mode='research')
            record=json.loads((original.artifact_path/'experiment.json').read_text())
            self.assertEqual(record['manifest']['data_snapshot']['adjustment'],'qfq')
            self.assertEqual(record['manifest']['data_snapshot'],record['manifest']['signal_data_snapshot'])
            self.assertGreater(record['execution']['commission'],0)
            self.assertEqual(record['execution'].get('corporate_action_ledger',[]),[])
            self.assertEqual(reproduce_artifact(original.artifact_path,root/'out')['status'],'numerically_matched')
            child=root/'runs'/record['children'][0]['run_id']
            self.assertTrue(pl.read_parquet(child/'bars.parquet').equals(pl.read_parquet(original.artifact_path/'bars.parquet')))

    def test_research_configuration_rejects_double_adjustment(self):
        import test_stock_splits
        _,_,_,cfg=test_stock_splits.StockSplitTests().fixture()
        with self.assertRaisesRegex(ValueError,'不重复处理公司行动'):cfg.validate_price_inputs()
        from dataclasses import replace
        replace(cfg,price_mode='account').validate_price_inputs()
