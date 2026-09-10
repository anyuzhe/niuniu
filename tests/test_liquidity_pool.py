import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict,replace
import polars as pl
from test_technical import bars
from quantlab.factors.liquidity_pool import LiquidityPoolFactor,COMPONENTS
from quantlab.factors.cache import FactorCache
from quantlab.storage.codec import encode

P={'left':1,'right':1,'tolerance_bps':0.,'absolute_tolerance':.1}


def fixture():
    high=[9.,10.,9.,10.,9.,9.5,10.,9.,10.4,9.,9.,9.]
    return bars([8.5]*len(high)).with_columns(pl.Series('high',high),pl.lit(8.).alias('low'))


class LiquidityPoolTests(unittest.TestCase):
    def test_complete_lifecycle_and_frozen_band(self):
        frame=fixture();matrix,transitions,events=LiquidityPoolFactor('reclaimed',1).matrix(frame,P)
        self.assertEqual([e.factor_id for e in events],['ICT.EQH_'+n for n in
            ['CREATED','TOUCHED','STRENGTHENED','SWEPT','RECLAIMED']])
        self.assertEqual([e.available_at for e in events],[frame['datetime'][i] for i in (4,6,7,8,9)])
        self.assertEqual(transitions[-1].status,'completed')
        self.assertEqual(len({e.metadata['pool']['id'] for e in events}),1)
        self.assertEqual(matrix['active_count'].to_list(),[0.]*4+[1.]*5+[0.]*3)
        self.assertEqual(matrix['lower_price'][4:9].unique().to_list(),[9.9])
        self.assertEqual(len(events[0].metadata['pool']['anchors']),2)
        self.assertEqual(len(events[2].metadata['pool']['anchors']),3)
        self.assertLess(events[0].metadata['pool']['anchors'][0]['occurred_at'],events[0].available_at)

    def test_mirrored_equal_lows_prefix_and_symbol_isolation(self):
        frame=fixture();factor=LiquidityPoolFactor('reclaimed',1)
        matrix,transitions,events=factor.matrix(frame,P)
        for size in range(1,frame.height):
            m,ts,es=LiquidityPoolFactor('reclaimed',1).matrix(frame.head(size),P)
            cutoff=frame['datetime'][size-1]
            self.assertTrue(m.equals(matrix.head(size)),size)
            self.assertEqual(ts,[t for t in transitions if t.available_at<=cutoff])
            self.assertEqual(es,[e for e in events if e.available_at<=cutoff])
        mirrored=frame.with_columns((40-pl.col('open')).alias('open'),(40-pl.col('close')).alias('close'),
            (40-pl.col('low')).alias('high'),(40-pl.col('high')).alias('low'))
        m,_,es=LiquidityPoolFactor('reclaimed',-1).matrix(mirrored,P)
        self.assertEqual(m['reclaimed'].to_list(),matrix['reclaimed'].to_list())
        self.assertTrue(all(e.factor_id.startswith('ICT.EQL_') for e in es))
        self.assertAlmostEqual(m['lower_price'][4],29.9)
        mixed=pl.concat([frame,frame.with_columns(pl.lit('B').alias('symbol'))])
        self.assertTrue(factor.matrix(mixed,P)[0].filter(pl.col('symbol')=='A').equals(matrix))
        for name in COMPONENTS:
            self.assertEqual(LiquidityPoolFactor(name,1).compute(frame,P)['value'].to_list(),matrix[name].to_list())

    def test_terminal_priority_and_no_preconfirmation_sweep_backfill(self):
        frame=fixture();at=frame['datetime'][8]
        changed=frame.with_columns(pl.when(pl.col('datetime')==at).then(10.3).otherwise(pl.col('close')).alias('close'))
        _,_,events=LiquidityPoolFactor('invalidated',1).matrix(changed,P)
        self.assertTrue(any(e.factor_id=='ICT.EQH_INVALIDATED' for e in events))
        self.assertFalse(any(e.factor_id=='ICT.EQH_RECLAIMED' for e in events))
        _,_,events=LiquidityPoolFactor('expired',1).matrix(frame,{**P,'max_age_bars':3})
        self.assertTrue(any(e.factor_id=='ICT.EQH_EXPIRED' and e.available_at==at for e in events))
        self.assertFalse(any(e.factor_id=='ICT.EQH_SWEPT' for e in events))
        changed=frame.with_columns(pl.when(pl.col('datetime')==frame['datetime'][2]).then(10.3).otherwise(pl.col('high')).alias('high'))
        _,_,events=LiquidityPoolFactor('created',1).matrix(changed.head(6),P)
        self.assertFalse(events)
        for bad in ({'right':0},{'min_touches':1},{'tolerance_bps':float('nan')},{'unknown':1}):
            with self.assertRaises(ValueError):LiquidityPoolFactor('created',1).parameters(bad)

    def test_resume_at_sweep_matches_complete_state(self):
        frame=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            first=LiquidityPoolFactor('reclaimed',1);first._persistent_cache=FactorCache(Path(tmp),'fixture')
            first.matrix(frame.head(9),P)
            second=LiquidityPoolFactor('reclaimed',1);second._persistent_cache=FactorCache(Path(tmp),'fixture')
            actual=second.matrix(frame,P);expected=LiquidityPoolFactor('reclaimed',1).matrix(frame,P)
            self.assertEqual(second._persistent_cache.recursive_resumed_bars,9)
            self.assertTrue(actual[0].equals(expected[0]))
            self.assertEqual(actual[1:],expected[1:])

    def test_registered_archive_replay_and_isolated_reproduction(self):
        from test_context_experiments import runner,context_config
        from quantlab.data.base import DataBatch,DataSnapshot
        from quantlab.storage.codec import digest
        from quantlab.storage.experiments import load_record
        from quantlab.sequence.replay import replay_page
        from quantlab.storage.bundle import reproduce_artifact
        class Provider:
            def load(self,request):
                frame=fixture()
                return DataBatch(frame,DataSnapshot(digest(frame.write_json()),'fixture','raw',()))
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);cfg=replace(context_config(),factor_id='ICT.EQH_RECLAIMED',parameters=P,
                context=None,replay=True,horizons=(1,),data=replace(context_config().data,timeframe=__import__('quantlab.domain',fromlist=['Timeframe']).Timeframe.DAILY))
            result=runner(Provider(),output).run(cfg);record=load_record(result.artifact_path/'experiment.json')
            self.assertEqual(record['replay']['version'],'equal_extreme_pool_v1')
            self.assertEqual(len(record['sequence_audit']['sequences']),1)
            self.assertFalse(replay_page(fixture(),record,'A',3)['zones'])
            self.assertEqual(replay_page(fixture(),record,'A',4)['zones'][0]['status'],'active')
            self.assertEqual(replay_page(fixture(),record,'A',8)['zones'][0]['status'],'swept')
            page=replay_page(fixture(),record,'A',11)
            self.assertEqual(page['zones'][0]['status'],'reclaimed')
            self.assertEqual(page['zones'][0]['end_visible_index'],9)
            self.assertEqual(reproduce_artifact(result.artifact_path,output/'reproduced')['status'],'numerically_matched')
