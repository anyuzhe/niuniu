"""Suspension-aware generic replay: no filled prices, compressed clocks or false crosses."""
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo
import json
import polars as pl
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.data.validation import SUSPENSION_INPUT_CONTRACT
from quantlab.domain import Timeframe
from quantlab.structure.breaks import ConfirmedSwingBreakEngine
from quantlab.zones.fvg import FVGZoneEngine
from quantlab.sequence.replay import replay_evidence, replay_page
from quantlab.storage.codec import encode


def bars(prices, symbol='sh.600001', start=None):
    start=start or datetime(2023,1,2,15,tzinfo=ZoneInfo('Asia/Shanghai'))
    rows=[];last=10.0
    for i,price in enumerate(prices):
        price=None if price is None else float(price)
        row={'symbol':symbol,'exchange':symbol[:2], 'datetime':start+timedelta(days=i),
             'available_at':start+timedelta(days=i),'timeframe':'1d','input_contract':SUSPENSION_INPUT_CONTRACT,
             'bs_trade_status':0 if price is None else 1,'vendor_previous_close':last,
             'adj_factor':1.0,'volume':None if price is None else 1000.0,
             'turnover':None if price is None else price*1000}
        row.update({k:price for k in ('open','high','low','close')});rows.append(row)
        if price is not None:last=price
    return pl.DataFrame(rows,schema_overrides={k:pl.Float64 for k in ('open','high','low','close','volume','turnover')})


class ReplaySuspensionTests(TestCase):
    def test_active_fvg_does_not_touch_or_fill_a_suspended_row(self):
        frame=bars([10,12,14,None,16,18,20,9]);before=frame.clone()
        result=FVGZoneEngine().analyze(frame);times=frame['datetime'].to_list()
        self.assertEqual(result.counts.height,frame.height)
        self.assertIsNone(result.counts['active_count'][3])
        self.assertTrue(any(z.created_at==times[2] for z in result.zones))
        self.assertFalse(any(z.created_at in times[3:6] for z in result.zones))
        self.assertFalse(any(u.available_at==times[3] for u in result.updates))
        self.assertTrue(any(u.available_at==times[7] and u.status=='invalidated' for u in result.updates))
        self.assertTrue(frame.equals(before))
    def test_middle_suspension_never_becomes_a_three_bar_gap(self):
        frame=bars([10,None,20]);engine=FVGZoneEngine()
        self.assertEqual(engine.detect(frame),[])
        flags=engine.flags(frame)
        self.assertIsNone(flags['bull_created'][2]);self.assertIsNone(flags['bear_created'][2])
    def test_swing_requires_two_consecutive_observed_closes(self):
        frame=bars([10,15,11,None,16,14,16]);times=frame['datetime'].to_list()
        values,events=ConfirmedSwingBreakEngine(1,1).analyze(frame)
        self.assertEqual(values.height,frame.height)
        self.assertIsNone(values['up'][3]);self.assertIsNone(values['up'][4])
        self.assertFalse(any(e.occurred_at in times[3:5] for e in events))
        self.assertTrue(any(e.occurred_at==times[6] and e.direction==1 for e in events))
    def test_all_suspended_and_consecutive_suspensions_remain_missing(self):
        for prices in ([None,None,None],[10,12,14,None,None,16,18,20]):
            frame=bars(prices);ev=replay_evidence(frame)
            values,events=ConfirmedSwingBreakEngine().analyze(frame)
            missing=[i for i,v in enumerate(prices) if v is None]
            for i in missing:
                self.assertIsNone(values['up'][i]);self.assertIsNone(values['down'][i])
                self.assertFalse(any(z['created_at']==frame['datetime'][i] for z in ev['zones']))
    def test_legacy_null_and_invalid_tradable_rows_still_fail(self):
        frame=bars([10,None,12])
        for bad in (frame.drop('input_contract'),frame.with_columns(pl.lit(1).alias('bs_trade_status'))):
            for engine in (FVGZoneEngine(),ConfirmedSwingBreakEngine()):
                with self.assertRaises(ValueError):engine.analyze(bad)
    def test_finite_data_legacy_and_state_aware_outputs_match(self):
        frame=bars([10,13,11,15,18,16,20,11,9,15,13]);legacy=frame.drop('input_contract','bs_trade_status','vendor_previous_close')
        self.assertEqual(replay_evidence(frame),replay_evidence(legacy))
        self.assertTrue(FVGZoneEngine().flags(frame).select('bull_created','bear_created').equals(
            FVGZoneEngine().flags(legacy).select('bull_created','bear_created')))
    def test_replay_prefix_is_invariant_and_preserves_visible_null_candle(self):
        frame=bars([10,12,14,None,16,18,20,9,11,13]);complete=replay_evidence(frame)
        for n in range(1,frame.height+1):
            cutoff=frame['available_at'][n-1];prefix=replay_evidence(frame.head(n))
            for key in ('structures','events','zones','zone_updates'):
                known=[item for item in complete[key] if item['available_at']<=cutoff]
                self.assertEqual(prefix[key],known,(n,key))
        record=json.loads(encode({'replay':complete}))
        page=replay_page(frame,record,'sh.600001',at=3)
        self.assertEqual(len(page['bars']),4);self.assertIsNone(page['bars'][-1]['close'])
    def test_symbol_boundaries_do_not_carry_state(self):
        first=bars([10,12,14,None,16]);second=bars([5,5,5,None,5],'sz.000001')
        combined=replay_evidence(pl.concat([first,second]))
        for key in ('structures','events','zones','zone_updates'):
            self.assertEqual([v for v in combined[key] if v['symbol']=='sz.000001'],replay_evidence(second)[key])


class HoldoutReplaySuspensionTests(TestCase):
    def test_fixed_three_year_holdout_saves_replay_and_keeps_null_label_endpoints(self):
        from quantlab.app import default_registry
        from quantlab.workbench.jobs import prepare
        from quantlab.experiments.runner import ExperimentRunner
        from quantlab.experiments.holdout import HoldoutRunner
        from quantlab.storage.experiments import LocalExperimentStore
        from quantlab.storage.bundle import reproduce_artifact
        frames=[]
        for k,symbol in enumerate(('sh.600001','sh.600002','sz.000001')):
            for year in (2023,2024,2025):
                prices=[10+k+0.4*i+0.15*((i+k)%3) for i in range(35)]
                if k==0:prices[27]=None
                frames.append(bars(prices,symbol,datetime(year,1,2,15,tzinfo=ZoneInfo('Asia/Shanghai'))))
        frame=pl.concat(frames).sort('symbol','datetime');before=frame.clone()
        class Provider:
            def load(self,request):
                selected=frame.filter(pl.col('symbol').is_in(request.symbols)&pl.col('datetime').dt.date().is_between(request.start,request.end))
                return DataBatch(selected,DataSnapshot('synthetic-only-fixed-suspension','synthetic','raw',()))
        spec={'question':'synthetic replay suspension regression','symbols':['sh.600001','sh.600002','sz.000001'],
            'start':'2023-01-01','end':'2025-12-31','mode':'holdout',
            'split':{'train_end':'2023-12-31','valid_end':'2024-12-31'},'timeframe':'1d','adjustment':'raw',
            'factor':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20},'horizons':[5],
            'quantiles':2,'replay':True,'qualification':'research_only'}
        plan=prepare(spec)
        with TemporaryDirectory() as directory:
            root=Path(directory);store=LocalExperimentStore(root)
            result=HoldoutRunner(ExperimentRunner(Provider(),default_registry(),ExplicitUniverse(tuple(spec['symbols'])),store)).run(plan.config,plan.split)
            parent=json.loads((result.artifact_path/'experiment.json').read_text())
            self.assertEqual(parent['status'],'completed');self.assertEqual([p['name'] for p in parent['periods']],['train','valid','test'])
            for i,p in enumerate(parent['periods']):
                child=root/p['run_id'];record=json.loads((child/'experiment.json').read_text())
                self.assertEqual(record['status'],'completed');self.assertIn('replay',record)
                self.assertEqual(record['manifest']['trade_state_policy']['suspended_rows'],i+1)
                obs=pl.read_parquet(child/'observations.parquet')
                susp=datetime(2023+i,1,29,15,tzinfo=ZoneInfo('Asia/Shanghai'))
                self.assertEqual(obs.filter((pl.col('symbol')=='sh.600001')&(pl.col('datetime')==susp)).height,0)
                prior=obs.filter((pl.col('symbol')=='sh.600001')&(pl.col('datetime')==susp-timedelta(days=5)))
                self.assertEqual(prior.height,1);self.assertIsNone(prior['forward_5'][0])
            reproduced=reproduce_artifact(result.artifact_path,root/'reproduced')
            self.assertEqual(reproduced['status'],'numerically_matched',reproduced)
        self.assertTrue(frame.equals(before))
