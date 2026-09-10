import json
import unittest
from datetime import timedelta
import polars as pl
from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.data.universe import HistoricalUniverse, UniverseConfig
from quantlab.factors.smc import SwingBreakUp, SwingBreakDown
from quantlab.factors.engine import compute_factor
from quantlab.structure.breaks import ConfirmedSwingBreakEngine
from quantlab.sequence.replay import replay_evidence, replay_page
from quantlab.storage.codec import encode
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester, factor_targets


class UniverseTests(unittest.TestCase):
    def test_listing_boundaries_and_current_status_ignored(self):
        frame=bars([10.]*5)
        metadata=pl.DataFrame({'code':['A'],'ipoDate':['2025-01-02'],'outDate':['2025-01-05'],'status':['0']})
        universe=HistoricalUniverse(('A',),metadata,UniverseConfig('listing',1))
        self.assertEqual(universe.mask(frame)['eligible'].to_list(),[False,False,True,True,False])
        self.assertEqual(universe.mask(frame)['eligible'].to_list(),HistoricalUniverse(('A',),metadata.with_columns(pl.lit('1').alias('status')),UniverseConfig('listing',1)).mask(frame)['eligible'].to_list())
        with self.assertRaisesRegex(ValueError,'missing'):
            HistoricalUniverse(('A','B'),metadata,UniverseConfig('listing'))

    def test_pit_late_revision_and_future_effective_record(self):
        frame=bars([10.]*5);t=frame['datetime'].to_list()
        events=pl.DataFrame({'symbol':['A']*3,'effective_at':[t[0],t[0],t[4]],
            'available_at':[t[1],t[3],t[2]],'eligible':[True,False,True]})
        universe=HistoricalUniverse(('A',),events,UniverseConfig('pit'))
        self.assertEqual(universe.mask(frame)['eligible'].to_list(),[False,True,True,False,True])
        self.assertEqual(universe.mask(frame.head(3))['eligible'].to_list(),[False,True,True])
        self.assertNotEqual(universe.version,HistoricalUniverse(('A',),events.head(2),UniverseConfig('pit')).version)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            HistoricalUniverse(('A',),pl.concat([events,events.head(1)]),UniverseConfig('pit'))


class SwingReplayTests(unittest.TestCase):
    def test_confirmed_breaks_and_prefix_invariance(self):
        frame=bars([1.,3.,2.,4.,5.,1.,.5])
        output,events=ConfirmedSwingBreakEngine(1,1).analyze(frame)
        self.assertEqual(output['up'].to_list(),[None,None,0.,1.,0.,0.,0.])
        self.assertEqual(output['down'].to_list(),[None,None,None,0.,0.,1.,0.])
        self.assertEqual(len(events),2)
        self.assertLess(events[0].metadata['swing_available_at'],events[0].available_at)
        for factor in (SwingBreakUp(),SwingBreakDown()):
            assert_prefix_invariant(factor,frame,{'left':1,'right':1},frame['datetime'].to_list()[1:-1])
            mixed=pl.concat([frame,bars([10.]*7,'B')])
            self.assertTrue(compute_factor(factor,mixed,{'left':1,'right':1}).filter(pl.col('symbol')=='B')['value'].is_null().all())

    def test_replay_filters_future_confirmation_zone_updates_and_fills(self):
        frame=bars([1.,3.,2.,4.,5.,1.])
        record=json.loads(encode({'replay':replay_evidence(frame,{'left':1,'right':1}),
            'fills':[{'symbol':'A','filled_at':frame['datetime'][4],'side':'buy'}]}))
        early=replay_page(frame,record,'A',1)
        self.assertEqual(len(early['bars']),2)
        self.assertEqual(early['structures'],[])
        self.assertEqual(early['fills'],[])
        confirmed=replay_page(frame,record,'A',2)
        self.assertEqual(len(confirmed['structures']),1)
        for at in range(frame.height):
            page=replay_page(frame,record,'A',at,2)
            self.assertLessEqual(len(page['bars']),2)
            for key in ('events','structures','zones'):
                self.assertTrue(all(v['available_at']<=page['as_of'].isoformat() for v in page[key]))
            self.assertTrue(all(v['available_at']<=page['as_of'].isoformat() for v in page['zone_states'].values()))
        self.assertEqual(len(replay_page(frame,record,'A',5)['fills']),1)


class ExecutionTests(unittest.TestCase):
    def config(self,**kw):
        return ExecutionConfig(**{'initial_cash':1000.,'lot_size':10,'commission_bps':0.,'minimum_commission':0.,'slippage_bps':0.,**kw})

    def targets(self,frame,weights):
        return frame.head(len(weights)).select('symbol','datetime','available_at').with_columns(pl.Series('weight',weights,dtype=pl.Float64))

    def test_next_open_fees_cash_and_no_terminal_liquidation(self):
        frame=bars([10.,10.,12.])
        curve,fills,rejections,summary=OpenExecutionBacktester(self.config(minimum_commission=5.)).run(self.targets(frame,[1.,1.,0.]),frame)
        self.assertEqual(fills[0]['filled_at'],frame['datetime'][1].replace(hour=9,minute=30))
        self.assertEqual(fills[0]['quantity'],90)
        self.assertEqual(curve['cash'][1],95.)
        self.assertEqual(summary['ending_positions'],{'A':90})
        self.assertEqual(summary['final_equity'],1175.)
        self.assertEqual(summary['unprocessed_target_snapshots'],1)
        self.assertTrue(all(f['filled_at']>f['decision_at'] for f in fills))

    def test_intraday_t_plus_one_and_next_day_release(self):
        frame=bars([10.]*4)
        day=frame['datetime'][0].replace(hour=9,minute=35)
        times=[day,day+timedelta(minutes=5),day+timedelta(minutes=10),day+timedelta(days=1)]
        frame=frame.with_columns(pl.Series('datetime',times),pl.Series('available_at',times),pl.lit('5m').alias('timeframe'))
        targets=self.targets(frame,[1.,0.,0.])
        _,fills,rejections,summary=OpenExecutionBacktester(self.config()).run(targets,frame)
        self.assertEqual([f['side'] for f in fills],['buy','sell'])
        self.assertEqual(fills[1]['filled_at'].date(),times[3].date())
        self.assertEqual(rejections[0]['reason'],'t_plus_one')
        self.assertEqual(summary['ending_positions'],{})
        _,free_fills,_,_=OpenExecutionBacktester(self.config(t_plus_one=False)).run(targets,frame)
        self.assertEqual(free_fills[1]['filled_at'].date(),times[0].date())

    def test_no_current_final_bar_fill_inputs_and_price_limit(self):
        frame=bars([10.,11.,11.]);targets=self.targets(frame,[1.])
        engine=OpenExecutionBacktester(self.config())
        original=engine.run(targets,frame)[1]
        changed=frame.with_columns((pl.col('high')+100).alias('high'),pl.lit(.1).alias('low'),pl.lit(0.).alias('volume'))
        self.assertEqual(original,engine.run(targets,changed)[1])
        _,fills,rejections,_=OpenExecutionBacktester(self.config(limit_pct=.1)).run(targets,frame.head(2))
        self.assertEqual(fills,[])
        self.assertEqual(rejections[0]['reason'],'configured_price_limit')
        with self.assertRaises(ValueError):engine.run(self.targets(frame,[1.1]),frame)
        with self.assertRaises(ValueError):engine.run(self.targets(frame,[-.1]),frame)

    def test_targets_ignore_future_labels_and_respect_eligibility(self):
        frame=bars([10.]*3)
        obs=frame.select('symbol','datetime','available_at').with_columns(pl.Series('value',[1.,2.,3.]),pl.Series('eligible',[True,False,True]),pl.lit(999.).alias('forward_return_1'))
        targets=factor_targets(obs,frame,self.config())
        self.assertEqual(targets['weight'].to_list(),[1.,0.,1.])
        self.assertTrue(targets.equals(factor_targets(obs.with_columns(pl.lit(-999.).alias('forward_return_1')),frame,self.config())))


class ExtensionIntegrationTests(unittest.TestCase):
    def test_adjusted_execution_rejects_mismatched_sessions(self):
        import test_core
        from quantlab.workbench.jobs import prepare, execute
        fixture=test_core.CoreTests();fixture.setUp()
        try:
            raw=fixture.root/'lake/bronze/provider=baostock/stock_kline_daily/sh_600000.parquet'
            pl.read_parquet(raw).slice(1).write_parquet(raw)
            spec={'question':'复权时间对齐','symbols':list(fixture.symbols),
                'start':'2025-01-01','end':'2025-01-10','factor':'BASE.MOMENTUM',
                'parameters':{'lookback':2},'horizons':[1],'mode':'execution'}
            with self.assertRaisesRegex(ValueError,'可用时间不一致'):
                execute(prepare(spec),fixture.root,fixture.root/'artifacts')
        finally:fixture.tearDown()

    def test_execution_listing_frozen_replay_http_and_pit_adapter(self):
        import threading
        from urllib.request import urlopen
        import test_core
        from quantlab.workbench.jobs import prepare, execute
        from quantlab.workbench.server import make_server
        from quantlab.data.universe import build_universe
        fixture=test_core.CoreTests();fixture.setUp()
        server=None
        try:
            basic=fixture.root/'lake/bronze/provider=baostock/stock_basic'
            basic.mkdir()
            pl.DataFrame({'code':fixture.symbols,'ipoDate':['2025-01-03']*5,'outDate':['']*5}).write_parquet(basic/'stock_basic.parquet')
            spec={'question':'成交全链路','symbols':list(fixture.symbols),'start':'2025-01-01','end':'2025-01-10',
                'factor':'BASE.MOMENTUM','parameters':{'lookback':2},'horizons':[1],
                'mode':'execution','universe':{'mode':'listing'},'execution':{'initial_cash':100000.,'lot_size':100}}
            result=execute(prepare(spec),fixture.root,fixture.root/'artifacts')
            record=json.loads((result.artifact_path/'experiment.json').read_text())
            self.assertEqual(record['status'],'completed')
            self.assertGreater(record['execution']['fills'],0)
            self.assertEqual(record['manifest']['signal_data_snapshot']['adjustment'],'qfq')
            self.assertEqual(record['manifest']['data_snapshot']['adjustment'],'raw')
            raw_bars=pl.read_parquet(result.artifact_path/'bars.parquet')
            child=fixture.root/'artifacts'/record['children'][0]['run_id']
            signal_bars=pl.read_parquet(child/'bars.parquet')
            self.assertEqual(raw_bars['close'][0],2*signal_bars['close'][0])
            fill=record['fills'][0]
            from datetime import datetime
            raw_open=raw_bars.filter((pl.col('symbol')==fill['symbol']) & (pl.col('datetime')==pl.lit(datetime.fromisoformat(fill['bar_end'])).dt.convert_time_zone('Asia/Shanghai')))['open'][0]
            self.assertAlmostEqual(fill['price'],raw_open*(1+prepare(spec).execution.slippage_bps/10000))
            self.assertIn('retrospective',record['manifest']['universe']['metadata']['knowledge_policy'])
            self.assertTrue((result.artifact_path/'bars.parquet').exists())
            self.assertIn('独立', (result.artifact_path/'report.md').read_text())
            server=make_server(fixture.root/'artifacts',0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}/api/runs/{result.run_id}'
            with urlopen(url+'/replay?at=0') as response: page=json.load(response)
            self.assertEqual(len(page['bars']),1)
            self.assertEqual(page['bars'][0]['close'],5.0)
            self.assertEqual(page['fills'],[])
            with urlopen(url+'/observations') as response:self.assertEqual(json.load(response)['total'],10)
            raw_result=execute(prepare({**spec,'adjustment':'raw'}),fixture.root,fixture.root/'artifacts')
            raw_record=json.loads((raw_result.artifact_path/'experiment.json').read_text())
            self.assertEqual(raw_record['manifest']['signal_data_snapshot']['adjustment'],'raw')
            self.assertEqual(raw_record['execution'],record['execution'])
            # Replay must remain independent of any later source-data changes.
            source=fixture.root/'lake/bronze/provider=baostock/stock_kline_daily/sh_600000.parquet'
            source.unlink()
            with urlopen(url+'/replay?at=9') as response:self.assertEqual(len(json.load(response)['bars']),10)
            pit=fixture.root/'research';pit.mkdir()
            stamp=bars([10.])['datetime'][0]
            pl.DataFrame({'symbol':[fixture.symbols[0]],'effective_at':[stamp],'available_at':[stamp],'eligible':[True]}).write_parquet(pit/'universe_events.parquet')
            universe=build_universe(fixture.root,fixture.symbols,UniverseConfig('pit'))
            self.assertTrue(universe.metadata['sha256'])
            self.assertEqual(universe.mask(bars([10.],fixture.symbols[1]))['eligible'].to_list(),[False])
        finally:
            if server:server.shutdown();server.server_close();thread.join()
            fixture.tearDown()


class ExecutionAccountingTests(unittest.TestCase):
    config = ExecutionTests.config
    targets = ExecutionTests.targets
    def test_sell_tax_cash_conservation(self):
        frame=bars([10.,10.,12.])
        curve,fills,_,summary=OpenExecutionBacktester(self.config(minimum_commission=5.,sell_tax_bps=100.)).run(self.targets(frame,[1.,0.]),frame)
        self.assertEqual([f['side'] for f in fills],['buy','sell'])
        self.assertAlmostEqual(fills[1]['tax'],10.8)
        self.assertAlmostEqual(curve['cash'][-1],1159.2)
        self.assertEqual(summary['ending_positions'],{})

    def test_sell_before_buy_and_delayed_bar_rejected(self):
        frame=pl.concat([bars([10.]*3,'A'),bars([10.]*3,'B')])
        targets=pl.concat([self.targets(bars([10.]*3,'A'),[0.,1.]),self.targets(bars([10.]*3,'B'),[1.,0.])])
        engine=OpenExecutionBacktester(self.config())
        _,fills,_,summary=engine.run(targets,frame)
        self.assertEqual([(f['symbol'],f['side']) for f in fills],[('B','buy'),('B','sell'),('A','buy')])
        self.assertEqual(summary['ending_positions'],{'A':100})
        with self.assertRaisesRegex(ValueError,'available at their close'):
            engine.run(targets,frame.with_columns((pl.col('available_at')+pl.duration(minutes=1)).alias('available_at')))

if __name__=='__main__':unittest.main()
