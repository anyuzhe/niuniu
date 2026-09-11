import contextlib
from copy import deepcopy
from datetime import date,timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.data.baostock_catalog import import_plan,DAILY_FIELDS
from quantlab.data.baostock_ingest import collect,import_root
from quantlab.data.baostock_dataset import read_table,dataset_manifest,responses
from quantlab.data.baostock_provider import BaostockSnapshotProvider
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.agent.market_data_tools import MarketDataResearchAPI


def plan():
    return {'symbols':['sh.600000','sh.600519','sz.000001'],'start':'2025-01-01','end':'2025-01-10',
        'datasets':['daily_raw','daily_qfq','calendar','financials'],
        'snapshot_dates':[],'quarters':['2024Q4']}


class Response:
    error_code='0';error_msg='success'
    def __init__(self,rows,fields=None):
        self.rows=rows;self.fields=fields or list(rows[0]);self.index=-1
    def next(self):self.index+=1;return self.index<len(self.rows)
    def get_row_data(self):return [self.rows[self.index][k] for k in self.fields]


class SDK:
    def __init__(self):self.calls=[];self.logged_out=False
    def login(self):return Response([{'ok':'1'}])
    def logout(self):self.logged_out=True
    def query_trade_dates(self,**kwargs):
        start=date.fromisoformat(kwargs['start_date']);end=date.fromisoformat(kwargs['end_date'])
        return Response([{'calendar_date':str(start+timedelta(days=i)),
            'is_trading_day':str(int((start+timedelta(days=i)).weekday()<5))} for i in range((end-start).days+1)])
    def query_history_k_data_plus(self,**kwargs):
        self.calls.append(kwargs);calendar=self.query_trade_dates(**kwargs);rows=[]
        for i,r in enumerate(calendar.rows):
            if r['is_trading_day']=='0':continue
            price=10+int(kwargs['code'][-1])*2+i*.1;scale=2 if kwargs['adjustflag']=='2' else 1
            row={k:'1' for k in DAILY_FIELDS.split(',')}
            row.update(date=r['calendar_date'],code=kwargs['code'],open=str(price*scale),
                high=str((price+1)*scale),low=str((price-1)*scale),close=str((price+.2)*scale),
                volume='1000',amount='10000',adjustflag=kwargs['adjustflag'],isST='0',tradestatus='1',
                turn='' if i==1 else '2.5',peTTM='999' if scale==2 else '12',pcfNcfTTM='-2')
            rows.append(row)
        return Response(rows)
    def __getattr__(self,name):
        if not name.startswith('query_'):raise AttributeError(name)
        return lambda **kw:Response([{'code':kw['code'],'pubDate':'2025-04-01','statDate':'2024-12-31','totalShare':'100'}])


class BaostockDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.identifier=str(uuid4());self.directory=import_root(self.root)/self.identifier
    def imported(self,spec=None,sdk=None):
        with contextlib.redirect_stdout(io.StringIO()):
            result=collect(spec or plan(),self.directory,sdk or SDK(),interval=0)
        return result
    def test_finite_plan_and_daily_new_endpoints(self):
        spec=plan();spec['datasets']+=['daily_market','daily_etf','daily_adjustments']
        spec['snapshot_dates']=['2025-01-10'];_,queries=import_plan(spec)
        self.assertTrue({'query_daily_history_k_AStock','query_daily_history_k_ETF','query_daily_adjust_factor'}<=set(q['method'] for q in queries))
        for change in ({'datasets':['unknown']},{'symbols':['sh.600000']*2},
                {'datasets':['daily_qfq']},{'snapshot_dates':['2026-01-01']},
                {'quarters':[]},{'extra':'invalid'}):
            with self.assertRaises((ValueError,TypeError)):import_plan({**plan(),**change})
    def test_real_reader_schema_nulls_and_raw_ratios(self):
        sdk=SDK();receipt=self.imported(sdk=sdk);self.assertEqual(receipt['status'],'completed')
        self.assertTrue(receipt['dataset_ready']);self.assertTrue(sdk.logged_out)
        dataset=self.directory/'dataset';manifest,_=dataset_manifest(dataset)
        self.assertFalse(manifest['daily_market_cap']);self.assertFalse(manifest['strict_pit'])
        req=DataRequest(tuple(plan()['symbols']),Timeframe.DAILY,date(2025,1,1),date(2025,1,10))
        qfq=BaostockSnapshotProvider(dataset,'qfq').load(req)
        original=MQCParquetProvider(dataset,'qfq').load(req)
        assert_frame_equal(qfq.bars.select(original.bars.columns),original.bars)
        self.assertEqual(qfq.bars['bs_pe_ttm'].unique().to_list(),[12.])
        self.assertEqual(qfq.bars['bs_turn_pct'].null_count(),3)
        self.assertTrue(qfq.bars['bs_pcf_ncf_ttm'].eq(-2).all())
        self.assertTrue(read_table(dataset,'profit')['_historical_available_at'].is_null().all())
        with self.assertRaises(FileExistsError):self.imported()
    def test_source_and_dataset_corruption_rejected(self):
        manifest=self.imported();source=self.directory/manifest['responses'][0]['file']
        source.write_text(source.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'校验'):list(responses(self.directory,manifest))
        dataset=self.directory/'dataset';table=dataset/'research/profit.parquet';table.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'校验'):read_table(dataset,'profit')
        with self.assertRaises(ValueError):read_table(dataset,'../../secret')
    def test_optional_failed_and_empty_are_not_reported_as_received(self):
        class Failing(SDK):
            def query_profit_data(self,**kwargs):
                response=Response([],['code']);response.error_code='x';response.error_msg='fixture'
                return response
            def query_daily_history_k_ETF(self,**kwargs):return Response([],['date','code'])
        spec=plan();spec['datasets'].append('daily_etf');spec['snapshot_dates']=['2025-01-10']
        result=self.imported(spec,Failing())
        self.assertEqual(result['status'],'completed_with_errors');self.assertTrue(result['dataset_ready'])
        statuses={r['kind']:r['status'] for r in result['responses']}
        self.assertEqual(statuses['profit'],'failed');self.assertEqual(statuses['daily_etf'],'no_data')
        self.assertNotIn('profit',result['dataset']['tables'])
    def test_incomplete_calendar_does_not_become_ready(self):
        class Missing(SDK):
            def query_trade_dates(self,**kwargs):
                response=super().query_trade_dates(**kwargs);response.rows=response.rows[:-1];return response
        result=self.imported(sdk=Missing())
        self.assertFalse(result['dataset_ready']);self.assertIn('日历',result['normalization_error'])
    def test_agent_queries_imported_evidence_without_download(self):
        self.imported();api=MarketDataResearchAPI(self.root)
        self.assertNotIn('download_baostock',[t['name'] for t in api.schemas()])
        listing=api.call('list_baostock_imports',{'offset':0,'limit':20})
        self.assertEqual(listing['data']['total'],1)
        verified=api.call('get_baostock_import',{'import_id':self.identifier})
        self.assertTrue(verified['ok'],verified)
        value=api.call('read_baostock_table',{'import_id':self.identifier,'table':'profit','symbol':'sh.600000','offset':0,'limit':20})
        self.assertTrue(value['ok'],value);self.assertEqual(value['data']['total'],1)
        self.assertFalse(value['data']['historical_available_at_verified'])
        self.assertFalse(api.call('read_baostock_table',{'import_id':self.identifier,'table':'profit','symbol':'','offset':True,'limit':20})['ok'])
        self.assertFalse(api.call('get_baostock_import',{'import_id':'../escape'})['ok'])
        self.assertFalse(list(self.root.glob('_jobs/*.json')))
    def test_original_research_engine_and_frozen_replay(self):
        from quantlab.app import build_runner
        from quantlab.workbench.jobs import prepare
        from quantlab.storage.bundle import reproduce_artifact
        self.imported();dataset=self.directory/'dataset';spec={'symbols':plan()['symbols'],
            'start':plan()['start'],'end':plan()['end'],'factor':'BASE.MOMENTUM',
            'parameters':{'lookback':2},'horizons':[1],'quantiles':3,'replay':True}
        cfg=prepare(spec).config
        result=build_runner(dataset,self.root/'runs',cfg.data.symbols,'qfq').run(cfg)
        proof=reproduce_artifact(result.artifact_path,self.root/'reproduced')
        self.assertEqual(proof['status'],'numerically_matched')

    def test_cancel_before_launch_and_invalid_timeout(self):
        from threading import Event
        from unittest.mock import patch
        from quantlab.data.baostock_ingest import run_import
        stop=Event();stop.set()
        with patch('quantlab.data.baostock_ingest.subprocess.Popen') as child:
            with self.assertRaisesRegex(ValueError,'取消'):
                run_import(self.root,plan(),stop=stop)
            for timeout in (True,0,float('nan'),601):
                with self.assertRaises(ValueError):run_import(self.root,plan(),timeout=timeout)
            child.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_logout_error_preserves_result_and_socket_timeout(self):
        import socket
        class LogoutFailure(SDK):
            def logout(self):raise OSError('fixture logout failed')
        before=socket.getdefaulttimeout();result=self.imported(sdk=LogoutFailure())
        self.assertTrue(result['dataset_ready']);self.assertEqual(result['logout_warning'],'OSError')
        self.assertEqual(socket.getdefaulttimeout(),before)

    def test_complete_batch_checks_normalized_files_too(self):
        self.imported();api=MarketDataResearchAPI(self.root)
        source=self.directory/'dataset/research/profit.parquet';source.write_bytes(b'changed')
        result=api.call('get_baostock_import',{'import_id':self.identifier})
        self.assertFalse(result['ok']);self.assertIn('校验',result['error']['message'])
