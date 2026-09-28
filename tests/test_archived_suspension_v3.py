"""Synthetic-only tests for opt-in vendor-placeholder normalization v3.

The old archive contracts, model bridge limits and production MQC gate stay strict.
"""
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
import io,json,hashlib
import polars as pl
import test_archived_daily_dataset as fixtures
from test_retro_daily import FakeSDK,bar
from quantlab.data.archived_daily_dataset import (
    CONTRACT_V1,CONTRACT_V2,CONTRACT_V3,FORMAT_V3,MARKER,
    preview_archived_daily_dataset,export_archived_daily_dataset,
    inspect_archived_daily_dataset,ArchivedDailyDatasetProvider)
from quantlab.data.retro_daily import FIELDS,RetroDailyStore
from quantlab.data.base import DataRequest,ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge
from quantlab.agent.archived_daily_dataset_cli import main as cli
from quantlab.agent.proposals import ProposalService
from quantlab.storage.approval_inputs import ApprovalInputFreezeStore,ApprovalFrozenDataProvider
from quantlab.storage.codec import digest
from quantlab.workbench.jobs import prepare


class ArchivedSuspensionV3Tests(TestCase):
    def setUp(self):
        self.fx=fixtures.ArchivedDailyDatasetTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.symbol='sh.600001';self.day=self.fx.sessions[2]
        self.rewrite()
    def rewrite(self,**changes):
        values={'open':'11','high':'11','low':'11','close':'11','preclose':'11',
                'volume':'','amount':'','turn':'','pctChg':'','tradestatus':'0'}
        values.update(changes)
        def mutate(rows):
            row=rows[2]
            for key,value in values.items():row[FIELDS.index(key)]=value
        self.fx._rewrite_symbol(self.symbol,mutate)
    def preview(self,contract=CONTRACT_V3):
        return preview_archived_daily_dataset(self.fx.source,self.fx.capture_id,self.fx.symbols,
            self.fx.start,self.fx.end,contract=contract)
    def export(self,name='v3'):
        p=self.preview();destination=self.fx.root/name
        result=export_archived_daily_dataset(self.fx.source,self.fx.capture_id,self.fx.symbols,
            self.fx.start,self.fx.end,destination,expected_preview_hash=p['preview_hash'],
            confirmed=True,contract=CONTRACT_V3)
        return destination,p,result
    def request(self):return DataRequest(tuple(self.fx.symbols.split()),Timeframe.DAILY,self.fx.sessions[0],self.fx.sessions[-1])
    def test_flat_source_marks_are_masked_only_in_derived_ohlc(self):
        before=self.fx._tree_bytes(self.fx.source);dst,p,result=self.export()
        self.assertEqual(before,self.fx._tree_bytes(self.fx.source))
        self.assertEqual(p['normalization_contract'],CONTRACT_V3)
        self.assertEqual(p['input_contract'],CONTRACT_V2)
        self.assertEqual((p['rows'],p['suspended_rows'],p['masked_vendor_ohlc_rows']),(10,1,1))
        self.assertEqual(json.loads((dst/MARKER).read_text())['format'],FORMAT_V3)
        view=inspect_archived_daily_dataset(dst);self.assertEqual(view['dataset_id'],result['dataset_id'])
        original=self.fx.store._symbol_dir(self.fx.capture_id,self.symbol)
        for name in ('rows.json.gz','daily.parquet'):
            self.assertEqual((dst/'source/symbols/sh_600001'/name).read_bytes(),(original/name).read_bytes())
        bars=ArchivedDailyDatasetProvider(dst).load(self.request()).bars
        self.assertEqual(bars.height,10)
        row=bars.filter((pl.col('symbol')==self.symbol)&(pl.col('datetime').dt.date()==self.day)).row(0,named=True)
        self.assertTrue(all(row[c] is None for c in ('open','high','low','close','volume','turnover')))
        self.assertEqual(row['vendor_previous_close'],11)
        self.assertEqual(row['bs_trade_status'],0)
        self.assertFalse(view['time_policy']['historical_available_at_verified'])
        self.assertFalse(list(self.fx.root.glob('_jobs/*')))
    def test_v1_v2_do_not_silently_accept_flat_suspended_source(self):
        with self.assertRaisesRegex(ValueError,'tradestatus!=1'):self.preview(CONTRACT_V1)
        with self.assertRaisesRegex(ValueError,'suspended rows must preserve null OHLC'):self.preview(CONTRACT_V2)
        self.assertEqual(self.preview()['masked_vendor_ohlc_rows'],1)
    def test_original_null_ohlc_and_explicit_zero_flow_are_preserved(self):
        self.rewrite(open='',high='',low='',close='',volume='0',amount='0',turn='0',pctChg='0')
        dst,p,_=self.export();self.assertEqual(p['masked_vendor_ohlc_rows'],0)
        bars=ArchivedDailyDatasetProvider(dst).load(self.request()).bars
        row=bars.filter((pl.col('symbol')==self.symbol)&(pl.col('datetime').dt.date()==self.day)).row(0,named=True)
        self.assertIsNone(row['close']);self.assertEqual(row['volume'],0);self.assertEqual(row['turnover'],0)
    def test_conflicting_and_partial_quotes_are_not_masked(self):
        for values in ({'open':'10'},{'close':''},{'preclose':'12'},{'open':'0','high':'0','low':'0','close':'0'}):
            with self.subTest(values=values):
                self.rewrite(**values)
                with self.assertRaisesRegex(ValueError,'contradicts source preclose'):self.preview()
    def test_nonzero_activity_is_not_explained_away_as_suspension(self):
        for key in ('volume','amount','turn','pctChg'):
            with self.subTest(key=key):
                self.rewrite(**{key:'1'})
                with self.assertRaisesRegex(ValueError,'nonzero source activity'):self.preview()
    def test_preclose_cannot_be_inferred_from_previous_row(self):
        for value in ('','0','-1'):
            with self.subTest(value=value):
                self.rewrite(preclose=value)
                with self.assertRaisesRegex(ValueError,'requires source preclose'):self.preview()
    def test_tradable_missing_amount_is_still_a_data_error(self):
        self.rewrite(tradestatus='1',volume='1000',turn='1.5',pctChg='0')
        with self.assertRaisesRegex(ValueError,'tradable archive row has empty'):self.preview()
    def test_hash_drift_and_no_overwrite_or_unconfirmed_export(self):
        preview=self.preview();dst=self.fx.root/'never'
        with self.assertRaisesRegex(ValueError,'confirmed=True'):
            export_archived_daily_dataset(self.fx.source,self.fx.capture_id,self.fx.symbols,self.fx.start,
                self.fx.end,dst,expected_preview_hash=preview['preview_hash'],contract=CONTRACT_V3)
        self.assertFalse(dst.exists())
        self.rewrite(preclose='12',open='12',high='12',low='12',close='12')
        with self.assertRaisesRegex(ValueError,'Preview hash changed'):
            export_archived_daily_dataset(self.fx.source,self.fx.capture_id,self.fx.symbols,self.fx.start,
                self.fx.end,dst,expected_preview_hash=preview['preview_hash'],confirmed=True,contract=CONTRACT_V3)
        self.assertFalse(dst.exists())
        dst,p,_=self.export();before=self.fx._tree_bytes(dst)
        with self.assertRaises(ValueError):
            export_archived_daily_dataset(self.fx.source,self.fx.capture_id,self.fx.symbols,self.fx.start,
                self.fx.end,dst,expected_preview_hash=p['preview_hash'],confirmed=True,contract=CONTRACT_V3)
        self.assertEqual(before,self.fx._tree_bytes(dst))
    def test_derived_or_source_tampering_rejected(self):
        dst,_,_=self.export();path=dst/'normalized/bars.parquet';old=path.read_bytes()
        frame=pl.read_parquet(path).with_columns(pl.col('close').fill_null(11));frame.write_parquet(path)
        with self.assertRaisesRegex(ValueError,'hash or size mismatch'):inspect_archived_daily_dataset(dst)
        path.write_bytes(old);raw=dst/'source/symbols/sh_600001/rows.json.gz';raw.write_bytes(raw.read_bytes()+b'x')
        with self.assertRaisesRegex(ValueError,'bounded regular file'):inspect_archived_daily_dataset(dst)
    def test_resigned_normalized_placeholder_still_fails_semantic_validation(self):
        dst,_,_=self.export();p=dst/'normalized/bars.parquet'
        frame=pl.read_parquet(p).with_columns(pl.col('close').fill_null(11));frame.write_parquet(p)
        manifest=json.loads((dst/MARKER).read_text());entry=next(r for r in manifest['files'] if r['path']=='normalized/bars.parquet')
        entry.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
        core={k:v for k,v in manifest.items() if k not in ('checksum','dataset_id')}
        signed={**core,'dataset_id':digest(core)};(dst/MARKER).write_text(json.dumps({**signed,'checksum':digest(signed)}))
        with self.assertRaisesRegex(ValueError,'Suspended rows must not synthesize'):inspect_archived_daily_dataset(dst)
    def test_execution_does_not_fill_a_masked_vendor_placeholder(self):
        from zoneinfo import ZoneInfo
        from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester
        dst,_,_=self.export();bars=ArchivedDailyDatasetProvider(dst).load(DataRequest((self.symbol,),Timeframe.DAILY,self.fx.sessions[0],self.fx.sessions[3])).bars
        tz=ZoneInfo('Asia/Shanghai');clock=lambda d:datetime(d.year,d.month,d.day,15,tzinfo=tz)
        times=[clock(self.fx.sessions[0]-timedelta(days=1)),clock(self.fx.sessions[1])]
        targets=pl.DataFrame({'symbol':[self.symbol,self.symbol],'datetime':times,'available_at':times,'weight':[1.,0.]})
        cfg=ExecutionConfig(initial_cash=100000,lot_size=100,commission_bps=0,minimum_commission=0,sell_tax_bps=0,slippage_bps=0)
        curve,fills,rejections,summary=OpenExecutionBacktester(cfg).run(targets,bars)
        self.assertEqual([f['side'] for f in fills],['buy','sell'])
        self.assertTrue(any(r['reason']=='vendor_suspended' and r['filled']==0 for r in rejections))
        self.assertEqual(summary['ending_positions'],{})
    def test_host_resource_profile_is_explicit_not_a_model_bridge_expansion(self):
        from quantlab.data.archived_daily_dataset import _parse_range,_parse_symbols
        symbols=' '.join('sh.'+str(600001+i) for i in range(20))
        self.assertEqual(len(_parse_symbols(symbols,CONTRACT_V3)),20)
        self.assertEqual(_parse_range('2023-01-01','2025-12-31',CONTRACT_V3)[1],date(2025,12,31))
        for contract in (CONTRACT_V1,CONTRACT_V2):
            with self.assertRaisesRegex(ValueError,'1–10'):_parse_symbols(symbols,contract)
            with self.assertRaisesRegex(ValueError,'371'):_parse_range('2023-01-01','2025-12-31',contract)
        with self.assertRaisesRegex(ValueError,'1–20'):_parse_symbols(symbols+' sz.000001',CONTRACT_V3)
        with self.assertRaisesRegex(ValueError,'1100'):_parse_range('2023-01-01','2026-01-05',CONTRACT_V3)
        bridge=ArchivedDailyBridge(self.fx.source)
        with self.assertRaisesRegex(ValueError,'1–10'):bridge.load(self.fx.capture_id,symbols,self.fx.start,self.fx.end)
        with self.assertRaisesRegex(ValueError,'371'):bridge.load(self.fx.capture_id,self.fx.symbols,'2023-01-01','2025-12-31')
    def test_cli_defaults_strict_and_requires_explicit_v3(self):
        common=['--source-workspace',str(self.fx.source),'--capture-id',self.fx.capture_id,
            '--symbols',*self.fx.symbols.split(),'--start',self.fx.start,'--end',self.fx.end]
        out=io.StringIO()
        with redirect_stdout(out):code=cli(['preview',*common])
        self.assertEqual(code,2);self.assertFalse(json.loads(out.getvalue())['ok'])
        out=io.StringIO()
        with redirect_stdout(out):code=cli(['preview',*common,'--contract',CONTRACT_V3])
        self.assertEqual(code,0);self.assertEqual(json.loads(out.getvalue())['data']['masked_vendor_ohlc_rows'],1)
    def test_frozen_input_and_research_keep_suspension_grid(self):
        dst,_,_=self.export();output=self.fx.root/'output';output.mkdir()
        spec={'question':'synthetic v3 contract only','symbols':self.fx.symbols.split(),'start':self.fx.start,
            'end':self.fx.end,'timeframe':'1d','adjustment':'raw','mode':'single','qualification':'research_only',
            'factor':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':1},'horizons':[1],'quantiles':2,'replay':True}
        service=ProposalService(output,dst);proposal=service.propose(str(uuid4()),spec)
        full=SimpleNamespace(root=output,data_root=dst,list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(Exception):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'],'approved')
        frozen=ApprovalInputFreezeStore(output,dst).path(proposal['proposal_id'])
        dst.rename(self.fx.root/'offline')
        provider=ApprovalFrozenDataProvider(frozen,'raw');batch=provider.load(self.request())
        self.assertEqual(batch.bars.height,10);self.assertEqual(batch.snapshot.files[0]['input_contract'],CONTRACT_V2)
        from quantlab.experiments.runner import ExperimentRunner
        from quantlab.storage.experiments import LocalExperimentStore
        from quantlab.app import default_registry
        result=ExperimentRunner(provider,default_registry(),ExplicitUniverse(tuple(spec['symbols'])),LocalExperimentStore(output)).run(prepare(spec).config)
        observations=pl.read_parquet(result.artifact_path/'observations.parquet')
        self.assertEqual(observations.filter((pl.col('symbol')==self.symbol)&(pl.col('datetime').dt.date()==self.day)).height,0)
        prior=observations.filter((pl.col('symbol')==self.symbol)&(pl.col('datetime').dt.date()==self.fx.sessions[1])).row(0,named=True)
        self.assertIsNone(prior['forward_1'])
        record=json.loads((result.artifact_path/'experiment.json').read_text())
        self.assertEqual(record['manifest']['trade_state_policy']['suspended_rows'],1)


class MultiYearV3Tests(TestCase):
    def test_twenty_symbols_three_years_and_late_missing_session(self):
        from tempfile import TemporaryDirectory
        from datetime import timezone
        with TemporaryDirectory() as name:
            root=Path(name).resolve();source=root/'source';source.mkdir()
            lo,hi=date(2023,1,1),date(2025,12,31)
            days=[lo+timedelta(days=i) for i in range((hi-lo).days+1)];sessions=[d for d in days if d.weekday()<5]
            calendar=[(d.isoformat(),'1' if d.weekday()<5 else '0') for d in days]
            symbols=['sh.'+str(600001+i) for i in range(20)]
            basic=[(s,'synthetic','2000-01-01','','1','1') for s in symbols]
            rows={s:[bar(d.isoformat(),s,10+i/1000,9.99+i/1000) for i,d in enumerate(sessions)] for s in symbols}
            sdk=FakeSDK(basic=basic,calendar=calendar,bars=rows)
            store=RetroDailyStore(source,today_fn=lambda:date(2026,9,28),now_fn=lambda:datetime(2026,9,28,tzinfo=timezone.utc))
            cid=store.create_plan(lo.isoformat(),hi.isoformat(),sdk=sdk)['capture_id']
            self.assertEqual(store.fetch(cid,sdk=sdk)['completed'],20)
            bridge_load=ArchivedDailyBridge.load;calls=[]
            def bounded(bridge,capture,sym,start,end):
                calls.append((len(sym.split()),(date.fromisoformat(end)-date.fromisoformat(start)).days+1))
                return bridge_load(bridge,capture,sym,start,end)
            with patch.object(ArchivedDailyBridge,'load',bounded):
                preview=preview_archived_daily_dataset(source,cid,' '.join(symbols),lo.isoformat(),hi.isoformat(),contract=CONTRACT_V3)
            self.assertEqual(calls,[(10,371),(10,371)])
            self.assertEqual(preview['rows'],20*len(sessions));self.assertEqual(preview['actual_sessions'],len(sessions))
            dst=root/'dataset';export_archived_daily_dataset(source,cid,' '.join(symbols),lo.isoformat(),hi.isoformat(),dst,
                expected_preview_hash=preview['preview_hash'],confirmed=True,contract=CONTRACT_V3)
            batch=ArchivedDailyDatasetProvider(dst).load(DataRequest(tuple(symbols),Timeframe.DAILY,lo,hi))
            self.assertEqual(batch.bars.height,20*len(sessions));self.assertEqual(batch.bars['datetime'].max().date(),hi)
            # A missing session beyond the bridge's bounded request still invalidates
            # a new capture's full three-year package; it is never quietly omitted.
            source2=root/'gapped';source2.mkdir();rows[symbols[-1]].pop(-5)
            sdk2=FakeSDK(basic=basic,calendar=calendar,bars=rows)
            store2=RetroDailyStore(source2,today_fn=lambda:date(2026,9,28),now_fn=lambda:datetime(2026,9,28,tzinfo=timezone.utc))
            cid2=store2.create_plan(lo.isoformat(),hi.isoformat(),sdk=sdk2)['capture_id'];store2.fetch(cid2,sdk=sdk2)
            with self.assertRaisesRegex(ValueError,'missing, duplicate, or unexpected'):
                preview_archived_daily_dataset(source2,cid2,' '.join(symbols),lo.isoformat(),hi.isoformat(),contract=CONTRACT_V3)
