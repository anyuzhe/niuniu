import json
import tempfile
import unittest
from pathlib import Path
from datetime import date,datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from unittest.mock import patch
import polars as pl
from quantlab.storage.codec import encode
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.storage.bundle import export_bundle,restore_bundle
from quantlab.workbench.server import ArtifactCatalog
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe


class DeliveryTests(unittest.TestCase):
    def test_identity_projection_preserves_full_manifest_without_audits(self):
        from quantlab.storage.experiments import load_record_fields,load_identity
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'experiment.json'
            record={'run_id':'test','manifest':{'symbols':list(range(500)), 'escaped':'\\n  "manifest": false'},'execution_audit':[{'manifest':'nested'}]*1000}
            for text in (encode(record),json.dumps(record)):
                path.write_text(text)
                self.assertEqual(load_record_fields(path,{'manifest'}),{'manifest':record['manifest']})
                self.assertEqual(load_identity(path)['manifest'],record['manifest'])

    def test_bundle_restore_preserves_evidence_and_lightweight_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=str(uuid4())
            record={'run_id':run,'experiment_id':'fixture','created_at':'2026-01-01T00:00:00+00:00','status':'failed','manifest':{'config':{'research_question':'fixture'}},'error':'fixture','fills':[{'id':i} for i in range(201)],'replay':{'large':'data'}}
            path=LocalExperimentStore(root/'runs').save(run,record,None)
            export_bundle(path,root/'bundle.zip');restored=restore_bundle(root/'bundle.zip',root/'restored')
            self.assertEqual(json.loads((Path(restored['artifact_root'])/run/'experiment.json').read_text()),record)
            catalog=ArtifactCatalog(restored['artifact_root'])
            with patch.object(catalog,'record',side_effect=AssertionError('Detail should not parse full evidence')):
                view=catalog.detail(run,lightweight=True)['record']
            self.assertEqual(view['_display_summary']['counts']['/fills'],201)
            self.assertNotIn('replay',view)
            with self.assertRaises(FileExistsError):restore_bundle(root/'bundle.zip',root/'restored')

    def test_eastmoney_minute_units_and_no_qfq_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'lake/bronze/provider=eastmoney/stock_kline_min1';directory.mkdir(parents=True)
            pl.DataFrame({'code':['sh.600000'],'date':[date(2026,9,8)],'time':['2026090809310000'],'open':[10.],'high':[10.],'low':[10.],'close':[10.],'volume':[20],'amount':[20000.]}).write_parquet(directory/'sh_600000.parquet')
            request=DataRequest(('sh.600000',),Timeframe.MIN1,date(2026,9,8),date(2026,9,8))
            batch=MQCParquetProvider(root,'raw').load(request)
            self.assertEqual(batch.bars['volume'][0],2000)
            self.assertEqual(batch.bars['datetime'][0].minute,31)
            with self.assertRaisesRegex(ValueError,'前复权 1m'):MQCParquetProvider(root,'qfq').load(request)

    def test_paper_default_qfq_signals_raw_accounting(self):
        import test_core
        from quantlab.execution.feed import MQCPaperFeed
        from quantlab.execution.backtest import ExecutionConfig
        from quantlab.factors.engine import compute_factor
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        directory=fixture.root/'lake/silver/qfq_kline_daily';directory.mkdir(parents=True,exist_ok=True)
        for source in (fixture.root/'lake/bronze/provider=baostock/stock_kline_daily').glob('*.parquet'):
            f=pl.read_parquet(source).with_columns(*[(pl.col(c).cast(pl.Float64)/2).alias(c) for c in ('open','high','low','close')],pl.lit(.5).alias('factor'))
            f.write_parquet(directory/source.name)
        rules=[{'symbol':s,'effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00','expires_at':'2025-02-01T00:00:00+08:00','suspended':False,'st':False,'limit_up':None,'limit_down':None,'commission_bps':0,'minimum_commission':0,'sell_tax_bps':0,'transfer_bps':0,'source':'synthetic fixture'} for s in fixture.symbols]
        rules_path=fixture.root/'rules.json';rules_path.write_text(encode(rules));account=fixture.root/'paper.json'
        feed=MQCPaperFeed(fixture.root,account,fixture.symbols,Timeframe.DAILY,fixture.start,'BASE.MOMENTUM',{'lookback':2},ExecutionConfig(price_mode='account'))
        with patch('quantlab.execution.feed.compute_factor',wraps=compute_factor) as calculation:
            result=feed.poll(rules_path,datetime(2025,1,8,16,tzinfo=ZoneInfo('Asia/Shanghai')))
            signal=calculation.call_args.args[1]
        self.assertEqual(result['signal_adjustment'],'qfq')
        state=json.loads(account.read_text())
        self.assertAlmostEqual(state['bars'][0]['close'],signal['close'][0]*2)
        self.assertNotEqual(result['source_snapshot'],result['signal_snapshot'])
