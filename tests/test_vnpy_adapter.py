import importlib.util
import unittest
import polars as pl
from test_technical import bars
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.adapters.vnpy import VnpyOpenBacktester, compare_backends, validate_config, vt_symbol

class VnpyConfigTests(unittest.TestCase):
    def test_mapping_and_explicit_model_boundary(self):
        self.assertEqual(vt_symbol('sh.600519'),'600519.SSE')
        self.assertEqual(vt_symbol('sz.000001'),'000001.SZSE')
        with self.assertRaises(ValueError):vt_symbol('A')
        with self.assertRaisesRegex(ValueError,'minimum_commission'):validate_config(ExecutionConfig())

@unittest.skipUnless(importlib.util.find_spec('vnpy'), 'optional vnpy dependency not installed')
class VnpyNativeTests(unittest.TestCase):
    def config(self,**kwargs):
        return ExecutionConfig(**{'initial_cash':10000.,'lot_size':10,'commission_bps':3.,'minimum_commission':0.,'slippage_bps':0.,'sell_tax_bps':5.,'limit_pct':.1,**kwargs})
    def test_real_native_orders_cash_and_holdings_match(self):
        frame=pl.concat([bars([10.,10.,10.5,10.5],'sh.600000'),bars([20.,20.,19.,19.],'sz.000001')])
        targets=frame.filter(pl.col('datetime')<frame['datetime'][3]).select('symbol','datetime','available_at').with_columns(pl.Series('weight',[1.,0.,1.,0.,1.,0.]))
        cfg=self.config();adapter=VnpyOpenBacktester(cfg)
        result=adapter.run(targets,frame)
        report=compare_backends(OpenExecutionBacktester(cfg).run(targets,frame),result)
        self.assertEqual(report['status'],'matched',report)
        self.assertTrue(adapter.diagnostics['native_orders'])
        self.assertTrue(adapter.diagnostics['native_daily_result'])
        self.assertAlmostEqual(adapter.diagnostics['daily_net_pnl_error'],0.,places=6)
        self.assertTrue(all('vnpy_trade_id' in f for f in result[1]))
        self.assertGreater(len(result[1]),2)
        changed=frame.with_columns((pl.col('high')+100).alias('high'),pl.lit(.1).alias('low'))
        self.assertEqual(result[1],VnpyOpenBacktester(cfg).run(targets,changed)[1])
    def test_t_plus_one_and_fixed_limit(self):
        from datetime import timedelta
        frame=bars([10.,10.,10.,10.],'sh.600000');day=frame['datetime'][0].replace(hour=9,minute=35)
        stamps=[day,day+timedelta(minutes=5),day+timedelta(minutes=10),day+timedelta(days=1)]
        frame=frame.with_columns(pl.Series('datetime',stamps),pl.Series('available_at',stamps),pl.lit('5m').alias('timeframe'))
        targets=frame.head(3).select('symbol','datetime','available_at').with_columns(pl.Series('weight',[1.,0.,0.]))
        cfg=self.config();actual=VnpyOpenBacktester(cfg).run(targets,frame)
        self.assertEqual(compare_backends(OpenExecutionBacktester(cfg).run(targets,frame),actual)['status'],'matched')
        self.assertEqual(actual[1][-1]['filled_at'].date(),stamps[-1].date())
        frame=bars([10.,11.],'sh.600000');targets=frame.head(1).select('symbol','datetime','available_at').with_columns(pl.lit(1.).alias('weight'))
        actual=VnpyOpenBacktester(cfg).run(targets,frame)
        self.assertEqual(actual[1],[])
        self.assertEqual(compare_backends(OpenExecutionBacktester(cfg).run(targets,frame),actual)['status'],'matched')

    def test_missing_bar_carries_valuation_not_fills(self):
        a=bars([10.,10.,10.5,10.5],'sh.600000')
        b=bars([20.,20.,19.,19.],'sz.000001')
        frame=pl.concat([a.filter(pl.col('datetime')!=a['datetime'][2]),b])
        targets=pl.concat([a.head(3),b.head(3)]).select('symbol','datetime','available_at').with_columns(pl.Series('weight',[1.,0.,0.,0.,0.,0.]))
        cfg=self.config();adapter=VnpyOpenBacktester(cfg);actual=adapter.run(targets,frame)
        self.assertEqual(compare_backends(OpenExecutionBacktester(cfg).run(targets,frame),actual)['status'],'matched')
        self.assertTrue(all(f['bar_end']!=a['datetime'][2] for f in actual[1] if f['symbol']=='sh.600000'))
        self.assertAlmostEqual(adapter.diagnostics['daily_net_pnl_error'],0.,places=6)
