import unittest
from dataclasses import asdict
import polars as pl
from test_technical import bars
from quantlab.adapters.chan_inclusion import finalized_inclusion_bars,center_lifecycle
from quantlab.factors.chan_inclusion import ChanInclusionComponent
from quantlab.factors.order_block import OrderBlockComponent
from quantlab.causal import assert_prefix_invariant


def ob_bars():
    return bars([10.,11.5,10.5,9.5,14.,10.,8.,8.5]).with_columns(
        pl.Series('open',[9.8,11.,10.8,10.,10.,11.,10.,8.]),
        pl.Series('high',[10.5,12.,11.,10.5,14.5,11.,10.,9.]),
        pl.Series('low',[9.5,10.5,10.,9.,9.8,9.6,7.5,7.8]))


class TheoryExtensionTests(unittest.TestCase):
    def test_center_frozen_extension_and_fresh_restart(self):
        times=bars([10.]*8)['available_at'].to_list()
        bounds=[(1,4),(2,5),(1,5),(1,3),(4,6),(3,6),(2,5),(3,7)]
        strokes=[{'kind':'chan_bi','symbol':'A','timeframe':'1d','occurred_at':at,'available_at':at,'lower':lo,'upper':hi,'structure_id':str(i)} for i,(at,(lo,hi)) in enumerate(zip(times,bounds))]
        events=center_lifecycle(strokes)
        self.assertEqual([e['kind'] for e in events],['chan_active_center','chan_center_extended','chan_center_exit_up','chan_active_center'])
        self.assertEqual([(e['lower'],e['upper']) for e in events],[(2,4),(2,4),(2,4),(3,5)])
        self.assertEqual(events[-1]['components'],['5','6','7'])
        for n in range(1,len(strokes)):
            self.assertEqual(center_lifecycle(strokes[:n]),[e for e in events if e['available_at']<=times[n-1]])
        mirrored=[{**s,'lower':10-s['upper'],'upper':10-s['lower']} for s in strokes]
        self.assertEqual(center_lifecycle(mirrored)[2]['kind'],'chan_center_exit_down')
    def test_inclusion_direction_confirmation_and_unfinished_tail(self):
        high=[10.,12.,11.5,13.,11.,10.5,9.];low=[8.,10.,10.5,11.,9.,9.5,7.]
        frame=bars([(h+l)/2 for h,l in zip(high,low)]).with_columns(pl.Series('high',high),pl.Series('low',low))
        merged,records=finalized_inclusion_bars(frame)
        self.assertEqual(merged['high'].to_list(),[10.,12.,13.,10.5])
        self.assertEqual(merged['low'].to_list(),[8.,10.5,11.,9.])
        self.assertEqual([len(r['components']) for r in records],[1,2,1,2])
        self.assertEqual(merged['available_at'].to_list(),[frame['available_at'][i] for i in [1,3,4,6]])
        for n in range(1,frame.height):
            prefix,earlier=finalized_inclusion_bars(frame.head(n))
            self.assertEqual(earlier,[r for r in records if r['available_at']<=frame['available_at'][n-1]])
        mirrored=frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        reflected,_=finalized_inclusion_bars(mirrored)
        self.assertEqual(reflected['high'].to_list(),[30-v for v in merged['low']])

    def test_inclusion_structure_prefix_and_center(self):
        frame=bars([10.,12.,9.,13.,10.,12.,9.,13.,10.,12.,10.,11.]);p={'left':1,'right':1,'min_separation':1}
        factor=ChanInclusionComponent('center');_,_,events=factor.trace(frame,p)
        self.assertTrue(any(e.factor_id=='CHAN.INCLUSION_CENTER' for e in events))
        for n in range(1,frame.height):
            self.assertEqual(factor.trace(frame.head(n),p)[2],[e for e in events if e.available_at<=frame['available_at'][n-1]])
        assert_prefix_invariant(factor,frame,p,frame['available_at'].to_list()[1:-1])

    def test_ob_creation_first_touch_invalidation_mirror_and_prefix(self):
        frame=ob_bars();p={'lookback':2,'left':1,'right':1,'atr_multiple':1.0}
        factor=OrderBlockComponent('created',1);_,_,events=factor.trace(frame,p)
        self.assertEqual([e.factor_id for e in events],['ICT.OB_CREATED_UP','ICT.OB_TOUCHED_UP','ICT.OB_INVALIDATED_UP'])
        self.assertEqual([e.available_at for e in events],[frame['available_at'][i] for i in (4,5,6)])
        self.assertEqual(events[0].metadata['anchor_at'],frame['datetime'][3])
        self.assertEqual((events[0].metadata['lower'],events[0].metadata['upper']),(9.,10.5))
        self.assertTrue(events[1].metadata['touched'])
        for n in range(1,frame.height):
            self.assertEqual(factor.trace(frame.head(n),p)[2],[e for e in events if e.available_at<=frame['available_at'][n-1]])
        for component in ('created','touched','invalidated','expired'):
            assert_prefix_invariant(OrderBlockComponent(component,1),frame,p,frame['available_at'].to_list()[1:-1])
        mirror=frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        reflected=OrderBlockComponent('created',-1).trace(mirror,p)[2]
        self.assertEqual([e.factor_id.replace('DOWN','UP') for e in reflected],[e.factor_id for e in events])
        self.assertEqual([e.available_at for e in reflected],[e.available_at for e in events])

    def test_ob_expiry_precedes_same_bar_invalidation(self):
        frame=ob_bars();p={'lookback':2,'left':1,'right':1,'atr_multiple':1.,'max_age_bars':1}
        events=OrderBlockComponent('expired',1).trace(frame,p)[2]
        self.assertEqual(events[-1].factor_id,'ICT.OB_EXPIRED_UP')
        self.assertFalse(any(e.factor_id=='ICT.OB_INVALIDATED_UP' for e in events))
        for value in (0,True,1.5):
            with self.assertRaises(ValueError):OrderBlockComponent('created',1).parameters({'search_bars':value})
