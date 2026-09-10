import math
import unittest
from datetime import timedelta
import polars as pl
from test_multitimeframe import bars,at
from quantlab.factors.chan_multiscale import ClassicChanNestFactor,nested_segments
from quantlab.factors.engine import compute_factor
from quantlab.app import default_registry
from quantlab.sequence.audit import collect_sequence_audit


class ChanMultiscaleTests(unittest.TestCase):
    def test_replay_automatically_freezes_multiscale_audit(self):
        import tempfile,json
        from pathlib import Path
        from quantlab.data.base import DataBatch,DataSnapshot,DataRequest,ExplicitUniverse
        from quantlab.domain import Timeframe
        from quantlab.experiments.runner import ExperimentRunner
        from quantlab.experiments.config import ExperimentConfig
        from quantlab.storage.experiments import LocalExperimentStore
        frame=self.frame()
        class Provider:
            def load(self,request):return DataBatch(frame,DataSnapshot('fixture','test','qfq',()))
        request=DataRequest(('A',),Timeframe.MIN5,frame['datetime'][0].date(),frame['datetime'][-1].date())
        with tempfile.TemporaryDirectory() as tmp:
            runner=ExperimentRunner(Provider(),default_registry(),ExplicitUniverse(('A',)),LocalExperimentStore(Path(tmp)))
            result=runner.run(ExperimentConfig('automatic nesting replay',request,'CHAN.CLASSIC_MULTISCALE_DIRECTION',replay=True))
            record=json.loads((result.artifact_path/'experiment.json').read_text())
            self.assertEqual(record['replay']['version'],'chan_multiscale_v1')
            self.assertEqual(len(record['sequence_audit']['sequences']),1)
            self.assertTrue((result.artifact_path/'bars.parquet').is_file())

    def test_containment_direction_latest_root_and_backtracking(self):
        def node(key,start,end,d=1):return {'object_key':key,'start_at':start,'end_at':end,'direction':d}
        low=[node('l',3,4)];mid=[node('m1',2,5),node('m2',6,8)];high=[node('h',1,9)]
        self.assertEqual([n['object_key'] for n in nested_segments([low,mid,high])],['h','m1','l'])
        self.assertEqual(nested_segments([low,mid,high+[node('new',10,20)]]),[])
        self.assertEqual(nested_segments([[node('opposite',3,4,-1)],mid,high]),[])
        self.assertEqual(len(nested_segments([[node('opposite',3,4,-1)],mid,high],False)),3)
        self.assertIsNone(nested_segments([low,mid,[]]))
        self.assertEqual(nested_segments([[node('outside',0,4)],mid,high]),[])

    def frame(self):
        times=[]
        for day in range(14):
            start=at(1)+timedelta(days=day)
            times.extend(start.replace(hour=m//60,minute=m%60) for origin in (570,780) for m in range(origin+5,origin+121,5))
        prices=[100+10*math.sin(i/38)+3*math.sin(i/6)+math.sin(i/1.7) for i in range(len(times))]
        return bars(times,'5m',prices)

    def test_actual_aggregation_prefix_missing_bars_and_audit_wiring(self):
        frame=self.frame();factor=ClassicChanNestFactor();full,_,events=factor.trace(frame,{})
        for count in (1,47,144,387):
            prefix,_,earlier=ClassicChanNestFactor().trace(frame.head(count),{})
            self.assertTrue(full.head(count).equals(prefix))
            self.assertEqual(earlier,[e for e in events if e.available_at<=frame['available_at'][count-1]])
        registry=default_registry();registered=registry.get(factor.definition.factor_id,'1.0.0')
        computed=compute_factor(registered,frame,{})
        audit=collect_sequence_audit(registered,frame,{},registry,computed)
        self.assertEqual(len(audit['sequences']),1)
        for e in events:
            for node in e.metadata['segments']:self.assertLessEqual(node['available_at'],e.available_at)
            self.assertEqual([s['timeframe'] for s in e.metadata['segments']],['60m','15m','5m'] if e.metadata['segments'] else [])
        # Removing a constituent cannot create a partial high-period bar.
        incomplete=frame.filter(pl.col('datetime')!=frame['datetime'][0])
        missing=compute_factor(ClassicChanNestFactor(),incomplete,{})
        self.assertEqual(missing.height,incomplete.height)
        with self.assertRaises(ValueError):factor.compute(frame,{'middle_timeframe':'1m'})
        for params in ({'same_direction':1},{'middle_timeframe':'60m','higher_timeframe':'15m'},{'higher_timeframe':'2d'}):
            with self.assertRaises(ValueError):factor.parameters(params)

    def test_long_warmup_then_first_nested_value_has_numeric_schema(self):
        from unittest.mock import patch
        from quantlab.domain import Event,Timeframe
        frame=self.frame()
        def structural_fixture(instance,source):
            start=next(i for i,t in enumerate(source['datetime']) if t>=at(1,11).replace(minute=30))
            end=source.height-1;tf=source['timeframe'][0]
            event=Event(tf,'CHAN.CLASSIC_SEGMENT_UP','A',Timeframe(tf),source['datetime'][end],source['available_at'][end],direction=1,
                metadata={'kind':'segment_up','object_key':'segment:1','start_index':start,'end_index':end,'lower':90.,'upper':110.,'direction':1,'status':'added'})
            return source.select('symbol','datetime','available_at'),[event]
        with patch('quantlab.factors.chan_multiscale.ClassicChanFactor.matrix',structural_fixture):
            values,_,events=ClassicChanNestFactor().trace(frame,{})
        self.assertEqual(values['value'].null_count(),frame.height-1)
        self.assertEqual(values['value'][-1],1.);self.assertEqual(len(events),1)
        self.assertEqual([n['timeframe'] for n in events[0].metadata['segments']],['60m','15m','5m'])
        import json
        from quantlab.storage.codec import encode
        from quantlab.sequence.replay import replay_page
        record=json.loads(encode({'replay':{'version':'chan_multiscale_v1'},'sequence_audit':{'sequences':[{'events':events}]}}))
        self.assertEqual(replay_page(frame,record,'A',frame.height-2)['structures'],[])
        shown=replay_page(frame,record,'A',frame.height-1)['structures']
        self.assertEqual([n['timeframe'] for n in shown],['60m','15m','5m'])
        self.assertTrue(all(n['end_visible_index']<=99 for n in shown))
