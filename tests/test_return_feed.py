import unittest,json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
import polars as pl
import test_core
from quantlab.experiments.return_increment import compare_returns
from quantlab.execution.feed import MQCPaperFeed
from quantlab.execution.backtest import ExecutionConfig
from quantlab.domain import Timeframe
from quantlab.storage.codec import encode

class ReturnFeedTests(unittest.TestCase):
    def test_paired_returns_and_reject_different_costs(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);paths=[root/'a',root/'b'];times=[datetime(2025,1,1,15,tzinfo=ZoneInfo('Asia/Shanghai'))+timedelta(days=i) for i in range(40)]
            for i,path in enumerate(paths):
                path.mkdir();record={'run_id':str(i),'experiment_id':str(i),'kind':'execution','status':'completed','manifest':{'config':{'data':{}},'execution':{'initial_cash':100},'data_snapshot':{'id':'same'},'universe':{},'portfolio':{},'backend':'open','market_rules':None}}
                (path/'experiment.json').write_text(encode(record));pl.DataFrame({'datetime':times,'equity':[100*(1.02 if i==0 else 1.01)**(n+1) for n in range(40)]}).write_parquet(path/'observations.parquet')
            result=compare_returns(*paths,date(2025,1,5),root/'out')
            self.assertAlmostEqual(result['summary']['mean_daily_difference'],.01)
            self.assertEqual(result['summary']['permutation']['status'],'computed')
            record['manifest']['execution']['initial_cash']=101;(paths[1]/'experiment.json').write_text(encode(record))
            with self.assertRaisesRegex(ValueError,'Incomparable'):compare_returns(*paths,date(2025,1,5),root/'out')

    def test_mqc_feed_incremental_recovery_and_source_failure(self):
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        rules=[]
        for s in fixture.symbols:
            rules.append({'symbol':s,'effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00','expires_at':'2025-02-01T00:00:00+08:00','suspended':False,'st':False,'limit_up':None,'limit_down':None,'commission_bps':0,'minimum_commission':0,'sell_tax_bps':0,'transfer_bps':0,'source':'synthetic test'})
        path=fixture.root/'rules.json';path.write_text(encode(rules));account=fixture.root/'paper.json'
        feed=MQCPaperFeed(fixture.root,account,fixture.symbols,Timeframe.DAILY,fixture.start,'BASE.MOMENTUM',{'lookback':2},ExecutionConfig(),adjustment='raw')
        now=datetime(2025,1,5,16,tzinfo=ZoneInfo('Asia/Shanghai'))
        with self.assertRaisesRegex(ValueError,'Stale source'):feed.poll(path,now,require_fresh=True)
        self.assertFalse(account.exists())
        self.assertFalse(account.with_suffix('.feed.json').exists())
        one=feed.poll(path,now)
        self.assertEqual(feed.poll(path,now)['revision'],one['revision'])
        before=account.read_bytes();path.write_text('{broken')
        with self.assertRaises(ValueError):feed.poll(path,now+timedelta(days=1))
        self.assertEqual(account.read_bytes(),before)
        path.write_text(encode(rules));two=feed.poll(path,now+timedelta(days=3));self.assertEqual(two['revision'],2)
        self.assertGreater(two['summary']['fills'],0)
        from quantlab.execution.reconcile import reconcile_account
        self.assertEqual(reconcile_account(account)['status'],'matched')
        damaged=json.loads(account.read_text());damaged['nav'][-1]['cash']+=10;account.write_text(encode(damaged))
        self.assertEqual(reconcile_account(account)['status'],'different')

    def test_research_feed_works_with_only_saved_qfq_prices(self):
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        raw=fixture.root/'lake/bronze/provider=baostock/stock_kline_daily'
        silver=fixture.root/'lake/silver/qfq_kline_daily';silver.mkdir(parents=True,exist_ok=True)
        for p in raw.glob('*.parquet'):
            pl.read_parquet(p).with_columns(pl.col('open','high','low','close')*.5,pl.lit(.5).alias('factor')).write_parquet(silver/p.name)
        raw.rename(fixture.root/'unavailable-raw')
        rules=[{'symbol':s,'effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00','expires_at':'2025-02-01T00:00:00+08:00','suspended':False,'st':False,'limit_up':None,'limit_down':None,'commission_bps':3,'minimum_commission':1,'sell_tax_bps':0,'transfer_bps':0,'source':'synthetic test'} for s in fixture.symbols]
        path=fixture.root/'rules.json';path.write_text(encode(rules));account=fixture.root/'qfq-paper.json'
        feed=MQCPaperFeed(fixture.root,account,fixture.symbols,Timeframe.DAILY,fixture.start,'BASE.MOMENTUM',{'lookback':2},ExecutionConfig())
        result=feed.poll(path,datetime(2025,1,9,16,tzinfo=ZoneInfo('Asia/Shanghai')))
        self.assertEqual(result['signal_adjustment'],'qfq');self.assertGreater(result['summary']['commission'],0)
        from quantlab.execution.reconcile import reconcile_account
        self.assertEqual(reconcile_account(account)['status'],'matched')
