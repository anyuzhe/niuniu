import unittest
from datetime import datetime,date,timedelta
from dataclasses import replace
import polars as pl
import test_core
from test_technical import bars
from quantlab.data.query import query_bars
from quantlab.data.audit import audit_market
from quantlab.data.industry import IndustryHistory
from quantlab.execution.portfolio import PortfolioConfig,TargetWeightBuilder
from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester

class DataPortfolioTests(unittest.TestCase):
    def test_duckdb_date_filter_and_audit_missing_session(self):
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        request=replace(fixture.request,start=date(2025,1,3),end=date(2025,1,5))
        f,files=query_bars(fixture.root,request);self.assertEqual(f.height,15);self.assertEqual(len(files),5)
        path=fixture.root/'lake/bronze/provider=baostock/trade_calendar';path.mkdir()
        pl.DataFrame({'calendar_date':['2025-01-03','2025-01-04','2025-01-05'],'is_trading_day':['1','1','1']}).write_parquet(path/'calendar.parquet')
        source=fixture.root/'lake/bronze/provider=baostock/stock_kline_daily/sh_600000.parquet'
        pl.read_parquet(source).filter(pl.col('date')!=date(2025,1,4)).write_parquet(source)
        changed=pl.read_parquet(source)
        pl.concat([changed,changed.head(1).with_columns(pl.lit(None,dtype=pl.Date).alias('date'))]).write_parquet(source)
        result=audit_market(fixture.root,request)
        self.assertEqual(result['results'][0]['null_date_rows_in_source'],1)
        self.assertEqual(result['results'][0]['unexplained_calendar_gaps'],[date(2025,1,4)])
        self.assertEqual(result['results'][1]['status'],'checked')

    def test_inverse_volatility_and_industry_prefix(self):
        market=pl.concat([bars([10.,11.,10.,11.,10.],'A'),bars([10.,12.,10.,12.,10.],'B')]);at=market['datetime'][0]
        events=[{'symbol':s,'sector':'bank','effective_at':at.isoformat(),'available_at':at.isoformat(),'source':'test'} for s in ('A','B')]
        cfg=PortfolioConfig(weighting='inverse_volatility',volatility_lookback=2,sector_limit=.4,industry_events=events)
        obs=market.select('symbol','datetime','available_at').with_columns(pl.lit(1.).alias('value'))
        targets,audit=TargetWeightBuilder(cfg).build(obs,market,top_n=2,threshold=0,exposure=1)
        self.assertGreater(audit[-1]['weights']['A'],audit[-1]['weights']['B'])
        self.assertLessEqual(sum(audit[-1]['weights'].values()),.4+1e-12)
        before=market.filter(pl.col('datetime')<=at+timedelta(days=3))
        self.assertEqual(TargetWeightBuilder(cfg).build(obs.filter(pl.col('datetime')<=at+timedelta(days=3)),before,top_n=2,threshold=0,exposure=1)[1],audit[:4])
        future=[{**r,'available_at':(at+timedelta(days=10)).isoformat()} for r in events]
        no,_=TargetWeightBuilder(replace(cfg,industry_events=future)).build(obs,market,top_n=2,threshold=0,exposure=1)
        self.assertEqual(no['weight'].sum(),0.)

    def test_actual_sector_limit_and_unknown_industry(self):
        market=pl.concat([bars([10.]*3,'A'),bars([10.]*3,'B')]);at=market['datetime'][0]
        targets=market.select('symbol','datetime','available_at').with_columns(pl.lit(.5).alias('weight'))
        events=[{'symbol':s,'sector':'same','effective_at':at.isoformat(),'available_at':at.isoformat(),'source':'test'} for s in ('A','B')]
        cfg=ExecutionConfig(initial_cash=10000,commission_bps=0,minimum_commission=0,slippage_bps=0,max_actual_sector=.4,industry_events=events)
        curve,fills,_,_=OpenExecutionBacktester(cfg).run(targets,market)
        self.assertLessEqual(curve['position_value'].max(),4000.)
        _,empty,reject,_=OpenExecutionBacktester(replace(cfg,industry_events=[])).run(targets,market)
        self.assertEqual(empty,[]);self.assertTrue(all(r['reason']=='unknown_industry' for r in reject))
