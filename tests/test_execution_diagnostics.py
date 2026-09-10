import unittest
from dataclasses import replace
from datetime import timedelta
import polars as pl
from test_technical import bars
from quantlab.execution.backtest import OpenExecutionBacktester,ExecutionConfig
from quantlab.execution.rules import MarketRules


class ExecutionDiagnosticTests(unittest.TestCase):
    def scenario(self,new_target=False):
        market=bars([10.]*4,'sh.600000')
        targets=market.head(2 if new_target else 1).select('symbol','datetime','available_at').with_columns(pl.lit(1.).alias('weight'))
        rules=[{'symbol':'sh.600000','effective_at':t.replace(hour=0),'available_at':t.replace(hour=0),
            'expires_at':t.replace(hour=0)+timedelta(days=1),'suspended':i==1,'st':False,'limit_up':None,'limit_down':None,
            'commission_bps':0,'minimum_commission':0,'sell_tax_bps':0,'transfer_bps':0,'source':'synthetic diagnostic fixture'} for i,t in enumerate(market['datetime'])]
        return market,targets,MarketRules(rules)

    def test_suspension_retry_and_actual_turnover(self):
        market,targets,rules=self.scenario()
        engine=OpenExecutionBacktester(ExecutionConfig(initial_cash=10000,slippage_bps=0),rules)
        curve,fills,reject,summary=engine.run(targets,market)
        audit=engine.execution_audit
        self.assertEqual(len(fills),1);self.assertEqual(fills[0]['quantity'],1000)
        self.assertEqual(audit['attempts'][1]['retry_of'],1)
        self.assertEqual(audit['attempts'][0]['reason'],'suspended')
        self.assertEqual(summary['execution_diagnostics']['retry_attempts_with_fills'],1)
        self.assertIsNone(audit['bars'][0]['stock_weight_gap_l1'])
        self.assertEqual(audit['bars'][1]['weight_gaps'],{'sh.600000':-1.})
        self.assertEqual(audit['bars'][2]['weight_gaps'],{'sh.600000':0.})
        self.assertEqual([r['gross_turnover'] for r in audit['daily_turnover']],[0.,0.,1.,0.])
        self.assertEqual(curve['equity'].to_list(),[10000.]*4)

    def test_new_decision_supersedes_retry_even_same_weight(self):
        market,targets,rules=self.scenario(new_target=True)
        engine=OpenExecutionBacktester(ExecutionConfig(initial_cash=10000,slippage_bps=0),rules)
        engine.run(targets,market)
        self.assertIsNone(engine.execution_audit['attempts'][1]['retry_of'])

    def test_partial_fill_and_diagnostic_prefix(self):
        market,targets,rules=self.scenario()
        cfg=ExecutionConfig(initial_cash=10000,slippage_bps=0,max_actual_position=.6)
        short=OpenExecutionBacktester(cfg,rules);short.run(targets,market.head(3))
        full=OpenExecutionBacktester(cfg,rules);_,fills,_,summary=full.run(targets,market)
        self.assertEqual(full.execution_audit['bars'][:3],short.execution_audit['bars'])
        self.assertEqual(full.execution_audit['attempts'][:2],short.execution_audit['attempts'])
        self.assertEqual(full.execution_audit['attempts'][1]['unfilled'],400)
        self.assertEqual(summary['execution_diagnostics']['buy_notional'],6000.)
        self.assertAlmostEqual(full.execution_audit['bars'][-1]['stock_weight_gap_l1'],.4)

    def test_intraday_turnover_denominator_is_previous_day_close(self):
        from quantlab.execution.diagnostics import ExecutionAudit
        at=bars([10.])['datetime'][0];audit=ExecutionAudit(10000)
        audit.close(at,None,{}, {'A':0},{'A':0},{'A':10},{'A'},12000,12000,0,[])
        fill={'side':'buy','quantity':100,'price':10}
        for minute,equity in [(5,11000),(10,10000)]:
            audit.close(at+timedelta(days=1,minutes=minute),at,{'A':.1},{'A':100},{'A':0},{'A':10},{'A'},equity,equity-1000,0,[fill])
        self.assertAlmostEqual(audit.result()[1]['daily_turnover'][1]['gross_turnover'],2000/12000)

    def test_capacity_uses_previous_volume_and_retries(self):
        market,targets,_=self.scenario()
        market=market.with_columns(pl.lit(1000.).alias('volume'))
        cfg=ExecutionConfig(initial_cash=10000,commission_bps=0,minimum_commission=0,slippage_bps=0,max_volume_participation=.1,max_actual_position=.6)
        engine=OpenExecutionBacktester(cfg);_,fills,_,summary=engine.run(targets,market)
        self.assertEqual([f['quantity'] for f in fills],[100,100,100])
        self.assertEqual(summary['ending_positions'],{'sh.600000':300})
        self.assertEqual(summary['execution_diagnostics']['retry_attempts'],2)
        self.assertEqual(engine.execution_audit['attempts'][0]['capacity']['reference']['at'],market['datetime'][0])
        self.assertEqual(engine.execution_audit['attempts'][0]['reason'],'lagged_volume_capacity')
        changed=market.with_columns(pl.when(pl.col('datetime')==market['datetime'][-1]).then(0.).otherwise(pl.col('volume')).alias('volume'))
        self.assertEqual(fills,OpenExecutionBacktester(cfg).run(targets,changed)[1])
        # A decision before the first observed bar has no causal volume history.
        early=targets.with_columns(pl.col('datetime','available_at')-pl.duration(days=1))
        self.assertEqual(OpenExecutionBacktester(cfg).run(early,market)[2][0]['reason'],'capacity_history_missing')
        from quantlab.adapters.vnpy import validate_config
        with self.assertRaisesRegex(ValueError,'vnpy_rules'):validate_config(cfg)
        for value in (True,0,-.1,1.1,float('nan')):
            with self.assertRaisesRegex(ValueError,'participation'):replace(cfg,max_volume_participation=value)
        sell_market=market.with_columns(pl.Series('volume',[5000.,1000.,1000.,1000.]))
        sell_targets=sell_market.head(2).select('symbol','datetime','available_at').with_columns(pl.Series('weight',[1.,0.]))
        sell_engine=OpenExecutionBacktester(cfg);sell_engine.run(sell_targets,sell_market)
        # Settled shares exceed the volume cap: T+1 must not steal attribution.
        self.assertEqual(sell_engine.execution_audit['attempts'][1]['reason'],'lagged_volume_capacity')
