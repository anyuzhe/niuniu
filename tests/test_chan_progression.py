import unittest
from datetime import timedelta
import polars as pl
from test_technical import bars
from quantlab.adapters.chan_progression import progression_events
from quantlab.factors.chan_progression import ChanProgressionComponent,COMPONENTS
from quantlab.causal import assert_prefix_invariant


def fixture(mirror=False):
    prices=[20.,10.,15.,8.,16.,12.,18.,11.,16.,7.,17.,10.,18.]
    if mirror:prices=[40-p for p in prices]
    times=bars(prices)['datetime'].to_list();indices=[0,1,2,3,4,5,6,9,12,15,18,21,24]
    positions={('A',t):i for t,i in zip(times,indices)}
    strokes=[{'kind':'chan_bi','symbol':'A','timeframe':'1d','occurred_at':times[i],'end_at':times[i+1],
        'available_at':times[i+1]+timedelta(hours=1),'direction':1 if prices[i+1]>prices[i] else -1,
        'lower':min(prices[i:i+2]),'upper':max(prices[i:i+2]),'structure_id':str(i)} for i in range(len(prices)-1)]
    center={'kind':'chan_center_exit_down' if mirror else 'chan_center_exit_up','components':['center','3'],
        'structure_id':'center-exit','lower':34. if mirror else 4.,'upper':36. if mirror else 6.}
    return strokes,[center],positions


class ChanProgressionTests(unittest.TestCase):
    def test_confirmed_segments_divergence_and_points(self):
        strokes,centers,positions=fixture();events=progression_events(strokes,centers,positions)
        segments=[e for e in events if e['kind'].startswith('segment_')]
        self.assertEqual([e['kind'] for e in segments],['segment_down','segment_up','segment_down'])
        self.assertEqual(segments[0]['components'],['0','1','2'])
        self.assertEqual(segments[0]['available_at'],strokes[3]['available_at'])
        self.assertEqual(segments[0]['end_at'],strokes[2]['end_at'])
        self.assertEqual([e['kind'] for e in events if e['kind'] in ('buy1','buy2','buy3')],['buy3','buy1','buy2'])
        divergence=next(e for e in events if e['kind']=='divergence_down')
        self.assertLess(divergence['segment']['price_speed'],.8*divergence['previous_segment']['price_speed'])
        self.assertLess(divergence['segment']['end_price'],divergence['previous_segment']['end_price'])
        mirrored=progression_events(*fixture(True))
        self.assertEqual([e['kind'] for e in mirrored if e['kind'] in ('sell1','sell2','sell3')],['sell3','sell1','sell2'])
        for n in range(1,len(strokes)):
            self.assertEqual(progression_events(strokes[:n],centers,positions),[e for e in events if e['available_at']<=strokes[n-1]['available_at']])

    def test_expiry_and_failed_pullback_cancel(self):
        strokes,centers,positions=fixture()
        events=progression_events(strokes,centers,positions,max_follow_strokes=1)
        self.assertFalse(any(e['kind']=='buy2' for e in events))
        self.assertTrue(any(e['kind']=='setup_expired' for e in events))
        changed=[dict(s) for s in strokes];changed[10]['lower']=7.
        events=progression_events(changed,centers,positions)
        self.assertFalse(any(e['kind']=='buy2' for e in events))
        self.assertTrue(any(e['kind']=='setup_invalidated' for e in events))

    def test_composed_factor_prefix_is_causal(self):
        frame=bars([20.,10.,15.,8.,16.,12.,18.,11.,16.,7.,17.,10.,18.,9.,19.,8.,20.,9.,21.,10.,19.,11.,18.,10.,19.])
        p={'left':1,'right':1,'min_separation':1}
        factor=ChanProgressionComponent('segment_up');_,_,events=factor.trace(frame,p)
        self.assertTrue(any(e.factor_id=='CHAN.RULE_SEGMENT_UP' for e in events))
        for component in COMPONENTS:
            assert_prefix_invariant(ChanProgressionComponent(component),frame,p,frame['available_at'].to_list()[3:-1:4])
        for cutoff in frame['available_at'].to_list()[3:-1:4]:
            self.assertEqual(factor.trace(frame.filter(pl.col('available_at')<=cutoff),p)[2],[e for e in events if e.available_at<=cutoff])

    def test_parameter_validation(self):
        factor=ChanProgressionComponent('buy1')
        for params in ({'divergence_ratio':True},{'divergence_ratio':0},{'divergence_ratio':float('nan')},{'max_follow_strokes':0},{'extra':1}):
            with self.assertRaises(ValueError):factor.parameters(params)
