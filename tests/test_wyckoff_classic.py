import unittest
from dataclasses import asdict
import json
import polars as pl
from test_technical import bars
from quantlab.factors.wyckoff_classic import ClassicWyckoffFactor,COMPONENTS
from quantlab.sequence.replay import replay_page
from quantlab.storage.codec import encode


def fixture():
    rows=[(14,14.3,13.7,100),(13,13.3,12.7,100),(12,12.3,11.7,100),(11,11.3,10.7,100),
        (10.8,11.2,10.4,150),(10,11,9,400),(12,12.5,10,180),(10,10.5,9.2,100),
        (10.5,11,10,100),(9.5,10,8.5,180),(10,10.4,9.1,80),(13,13.4,10.3,400),
        (12.8,13,12.5,80),(14,14.2,13,180),(14.5,15,14,100),(12,14,11.8,100)]
    return bars([float(x[0]) for x in rows]).with_columns(*[pl.Series(k,[float(x[j]) for x in rows]) for j,k in ((1,'high'),(2,'low'),(3,'volume'))])
P={'lookback':3,'context':4,'trend_threshold':.01,'min_bars_b':2,'box_pct':.05}

def change(frame,i,**columns):
    return frame.with_columns(*[pl.when(pl.col('datetime')==frame['datetime'][i]).then(v).otherwise(pl.col(k)).alias(k) for k,v in columns.items()])

class ClassicWyckoffTests(unittest.TestCase):
    def test_accumulation_and_distribution_full_lifecycle(self):
        f=fixture();m,states,events=ClassicWyckoffFactor('position').matrix(f,P)
        names=['PS','SC','AR_UP','ST_UP','SPRING','TEST_UP','SOS','LPS','MARKUP','EXIT']
        self.assertEqual([e.factor_id for e in events],['WYCKOFF.CLASSIC_'+n for n in names])
        self.assertEqual(m['position'].to_list(),[None]*4+[0.]*9+[1.,1.,0.])
        self.assertEqual(m['phase'].to_list(),[None]*4+[1.,1.,1.,2.,2.,3.,3.,4.,4.,5.,5.,0.])
        self.assertEqual(states[-1].status,'completed');self.assertEqual(len({s.match_id for s in states}),1)
        self.assertEqual(events[-1].metadata['reason'],'trailing_stop')
        self.assertEqual(m['range_high'][7:15].unique().to_list(),[12.5])
        self.assertEqual(m['cause_columns'][11:15].n_unique(),1)
        mirror=f.with_columns((40-pl.col('open')).alias('open'),(40-pl.col('close')).alias('close'),
            (40-pl.col('low')).alias('high'),(40-pl.col('high')).alias('low'))
        mm,_,ee=ClassicWyckoffFactor('position').matrix(mirror,P)
        self.assertEqual(mm['phase'].to_list(),[None if x is None else -x for x in m['phase']])
        self.assertEqual(mm['position'].sum(),0)
        self.assertEqual([e.factor_id.rsplit('.',1)[1] for e in ee],['CLASSIC_'+n for n in ['PSY','BC','AR_DOWN','ST_DOWN','UTAD','TEST_DOWN','SOW','LPSY','MARKDOWN','EXIT']])

    def test_no_sweep_direct_climax_and_entry_target_guard(self):
        f=change(fixture(),9,open=10.,close=10.,low=9.2,volume=80.)
        _,_,e=ClassicWyckoffFactor('position').matrix(f,P)
        self.assertFalse(any(x.factor_id.endswith('SPRING') for x in e))
        self.assertTrue(any(x.metadata['reason']=='no_sweep_variant' for x in e))
        self.assertTrue(any(x.factor_id.endswith('MARKUP') for x in e))
        f=change(fixture(),4,volume=100.)
        _,_,e=ClassicWyckoffFactor('position').matrix(f,P)
        self.assertEqual(e[0].factor_id,'WYCKOFF.CLASSIC_SC')
        m,_,e=ClassicWyckoffFactor('position').matrix(fixture(),{**P,'box_pct':.001})
        self.assertTrue(any(x.metadata['reason']=='target_exhausted_before_entry' for x in e))
        self.assertEqual(m['position'].sum(),0.)

    def test_timeout_invalidation_and_hold_exit(self):
        f=fixture()
        for changed,params,reason in [
            (f,{**P,'max_bars':2},'phase_timeout'),
            (change(f,10,low=8.),P,'frozen_extreme_broken'),
            (change(f,12,open=12.,close=12.,low=11.8),P,'breakout_failed'),
            (f,{**P,'max_hold':1},'max_hold'),
            (change(f,14,open=20.,close=20.,high=21.,low=19.),P,'target')]:
            _,_,events=ClassicWyckoffFactor('position').matrix(changed,params)
            self.assertTrue(any(e.metadata['reason']==reason for e in events),reason)

    def test_all_components_prefix_and_symbol_isolation(self):
        f=fixture();factor=ClassicWyckoffFactor('position');m,states,events=factor.matrix(f,P)
        for n in range(1,f.height):
            pm,ps,pe=factor.matrix(f.head(n),P);cutoff=f['available_at'][n-1]
            self.assertTrue(pm.equals(m.head(n)),n)
            self.assertEqual(ps,[s for s in states if s.available_at<=cutoff])
            self.assertEqual(pe,[e for e in events if e.available_at<=cutoff])
        other=f.with_columns(pl.lit('B').alias('symbol'))
        mm,_,_=factor.matrix(pl.concat([f,other]).reverse(),P)
        self.assertTrue(mm.filter(pl.col('symbol')=='A').equals(m))
        for c in COMPONENTS:self.assertEqual(ClassicWyckoffFactor(c).compute(f,P)['value'].to_list(),m[c].to_list())

    def test_replay_cutoff_and_ended_ranges(self):
        f=fixture();_,_,events=ClassicWyckoffFactor('position').matrix(f,P)
        record=json.loads(encode({'replay':{'version':'wyckoff_ae_v1'},'sequence_audit':{'sequences':[{'events':[asdict(e) for e in events]}]}}))
        early=replay_page(f,record,'A',8)
        self.assertFalse(any(e['factor_id'].endswith('SPRING') for e in early['events']))
        self.assertEqual(early['zones'][0]['lower_price'],9.)
        later=pl.concat([f,f.tail(1).with_columns(pl.col('datetime')+pl.duration(days=1),pl.col('available_at')+pl.duration(days=1))])
        self.assertEqual(replay_page(later,record,'A',16)['zones'][0]['end_visible_index'],15)

    def test_parameters_and_zero_volume(self):
        factor=ClassicWyckoffFactor('position')
        for p in ({'lookback':True},{'box_pct':0},{'test_volume':float('nan')},{'context':2},{'other':1}):
            with self.assertRaises(ValueError):factor.parameters(p)
        self.assertEqual(factor.compute(fixture().with_columns(pl.lit(0.).alias('volume')),P)['value'].sum(),0.)
        with self.assertRaisesRegex(ValueError,'unique'):
            factor.compute(fixture().with_columns(pl.lit(fixture()['available_at'][-1]).alias('available_at')),P)

    def test_runner_archive_template_and_next_open_execution(self):
        import tempfile
        from pathlib import Path
        from datetime import date
        from test_context_experiments import runner
        from quantlab.data.base import DataBatch,DataSnapshot,DataRequest
        from quantlab.domain import Timeframe
        from quantlab.experiments.config import ExperimentConfig
        from quantlab.experiments.execution import ExecutionStudy
        from quantlab.execution.backtest import ExecutionConfig
        from quantlab.storage.codec import digest
        from quantlab.storage.experiments import load_record
        from quantlab.theory.templates import resolve_template
        class Provider:
            def load(self,request):
                f=fixture()
                return DataBatch(f,DataSnapshot(digest(f.write_json()),'fixture','qfq',()))
        with tempfile.TemporaryDirectory() as tmp:
            engine=runner(Provider(),Path(tmp))
            cfg=ExperimentConfig('威克夫链路',DataRequest(('A',),Timeframe.DAILY,date(2025,1,1),date(2025,1,16)),
                'WYCKOFF.CLASSIC_POSITION',parameters=P,horizons=(1,),sequence_audit=True,replay=True)
            result=ExecutionStudy(engine).run(cfg,ExecutionConfig(top_n=1,threshold=.5))
            record=load_record(result.artifact_path/'experiment.json')
            child=Path(record['children'][0]['artifact_path'])
            source=load_record(child/'experiment.json');obs=pl.read_parquet(child/'observations.parquet')
            self.assertTrue(set('wyckoff_'+c for c in COMPONENTS)<=set(obs.columns))
            self.assertEqual(source['replay']['version'],'wyckoff_ae_v1')
            self.assertEqual(record['manifest']['data_snapshot']['adjustment'],'qfq')
            self.assertTrue(record['fills'])
            self.assertTrue(all(x['filled_at']>x['decision_at'] for x in record['fills']))
            params,_=resolve_template('RESEARCH.WYCKOFF_CLASSIC_POSITION',engine.registry)
            for spec in params['inputs'].values():spec['parameters']=P
            self.assertEqual(engine.registry.get('COMB.CONDITION','1.0.0').compute(fixture(),params)['value'].to_list(),
                ClassicWyckoffFactor('position').compute(fixture(),P)['value'].to_list())
            from dataclasses import replace
            combined=engine.run(replace(cfg,factor_id='COMB.CONDITION',parameters=params))
            self.assertEqual(load_record(combined.artifact_path/'experiment.json')['replay']['version'],'wyckoff_ae_v1')
            self.assertIn('wyckoff_score',pl.read_parquet(combined.artifact_path/'observations.parquet').columns)
