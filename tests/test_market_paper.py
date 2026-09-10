import unittest
from datetime import timedelta
from tempfile import TemporaryDirectory
from pathlib import Path
import polars as pl
from test_technical import bars
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount


def fixture():
    market=bars([10.,10.,11.,12.,12.]).with_columns(pl.lit('sh.600000').alias('symbol'))
    targets=market.select('symbol','datetime','available_at').with_columns(pl.Series('weight',[1.,1.,0.,0.,0.]))
    rules=[]
    for at in market['datetime']:
        rules.append({'symbol':'sh.600000','effective_at':at.replace(hour=0),'available_at':at.replace(hour=0),
            'expires_at':at.replace(hour=0)+timedelta(days=1),'suspended':False,'st':False,
            'limit_up':100.,'limit_down':1.,'commission_bps':3.,'minimum_commission':5.,'sell_tax_bps':5.,'transfer_bps':.1,'source':'synthetic test rules'})
    cfg=ExecutionConfig(initial_cash=10000,lot_size=100,slippage_bps=2,fee_decimals=2,max_actual_position=.6,max_actual_exposure=.7)
    return market,targets,rules,cfg

class MarketPaperTests(unittest.TestCase):
    def test_rules_availability_suspension_limits_and_costs(self):
        market,targets,records,cfg=fixture()
        records[1]['suspended']=True;records[2]['st']=True
        rules=MarketRules(records);_,fills,rejections,summary=OpenExecutionBacktester(cfg,rules).run(targets,market)
        self.assertEqual(fills,[])
        self.assertEqual([r['reason'] for r in rejections],['suspended','st_buy_blocked'])
        records[1]['suspended']=False;records[1]['limit_up']=market['open'][1]
        self.assertEqual(OpenExecutionBacktester(cfg,MarketRules(records)).run(targets,market)[2][0]['reason'],'session_price_limit')
        records[1]['available_at']=records[1]['expires_at']
        self.assertEqual(OpenExecutionBacktester(cfg,MarketRules(records)).run(targets,market)[2][0]['reason'],'missing_market_rule')
        market,targets,records,cfg=fixture();curve,fills,_,summary=OpenExecutionBacktester(cfg,MarketRules(records)).run(targets,market)
        self.assertEqual(fills[0]['quantity'],500)
        self.assertEqual(fills[0]['commission'],5.)
        self.assertGreater(summary['transfer_fee'],0)
        self.assertTrue(all(abs(f['commission']*100-round(f['commission']*100))<1e-8 for f in fills))
        changed=market.with_columns((pl.col('high')+100).alias('high'),pl.lit(.1).alias('low'),pl.lit(0.).alias('volume'))
        self.assertEqual(fills,OpenExecutionBacktester(cfg,MarketRules(records)).run(targets,changed)[1])

    def test_native_rule_aware_cash_positions(self):
        from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
        from quantlab.adapters.vnpy import compare_backends
        market,targets,records,cfg=fixture();rules=MarketRules(records)
        reference=OpenExecutionBacktester(cfg,rules).run(targets,market)
        native=VnpyRulesBacktester(cfg,rules);actual=native.run(targets,market)
        self.assertEqual(compare_backends(reference,actual)['status'],'matched')
        self.assertGreater(len(native.diagnostics['native_trades']),1)
        self.assertLess(native.diagnostics['cash_error'],1e-6)

    def test_paper_restart_idempotency_and_late_revision(self):
        market,targets,records,cfg=fixture()
        with TemporaryDirectory() as directory:
            path=Path(directory)/'paper.json'
            first=PaperAccount(path).advance(market.head(2),targets.head(2),MarketRules(records[:2]),cfg)
            self.assertEqual(PaperAccount(path).advance(market.head(2),targets.head(2),MarketRules(records[:2]),cfg),first)
            final=PaperAccount(path).advance(market,targets,MarketRules(records),cfg)
            reference=OpenExecutionBacktester(cfg,MarketRules(records)).run(targets,market)
            self.assertAlmostEqual(final['summary']['final_equity'],reference[3]['final_equity'])
            self.assertEqual(final['revision'],2)
            self.assertEqual(len({o['order_id'] for o in final['orders']}),len(final['orders']))
            changed=market.with_columns((pl.col('volume')+1).alias('volume'))
            with self.assertRaisesRegex(ValueError,'revised'):PaperAccount(path).advance(changed,targets,MarketRules(records),cfg)
            self.assertEqual(PaperAccount(path).read(),final)
