import unittest
import polars as pl
from test_technical import bars
from quantlab.causal import assert_prefix_invariant
from quantlab.factors.brooks_wedge import BrooksWedgeComponent,COMPONENTS


class BrooksWedgeTests(unittest.TestCase):
    p={'left':1,'right':1}

    def frame(self):
        return bars([11.,10.,12.,8.,11.,7.,9.,12.])

    def test_confirmed_three_extremes_and_mirror(self):
        frame=self.frame()
        mirror=frame.with_columns(*[(30-pl.col(c)).alias(c) for c in ('open','close','high','low')])
        for d,f in ((1,frame),(-1,mirror)):
            values,states,events=BrooksWedgeComponent('confirmed',d).trace(f,self.p)
            self.assertEqual(values['value'].to_list(),[None,None,0.,0.,0.,0.,0.,1.])
            self.assertEqual([e.metadata['stage'] for e in events],['setup','confirmed'])
            self.assertEqual(states[-1].status,'completed')
            self.assertEqual(events[0].available_at,f['available_at'][6])
            self.assertEqual(events[0].metadata['sources'][-1]['occurred_at'],f['datetime'][5])
            self.assertEqual(events[0].metadata['first_increment'],2.)
            self.assertEqual(events[0].metadata['second_increment'],1.)
            self.assertEqual(events[0].metadata['stage'],'setup')
            self.assertEqual(len(events[-1].metadata['sources']),5)

    def test_invalidation_timeout_equality_and_distinct_confirmation(self):
        factor=BrooksWedgeComponent('confirmed',1)
        for closes,params,last,status in (
            ([11.,10.,12.,8.,11.,7.,9.,6.],self.p,'invalidated','invalidated'),
            ([11.,10.,12.,8.,11.,7.,9.,10.,12.],{**self.p,'max_bars':1},'expired','timeout')):
            _,states,events=factor.trace(bars(closes),params)
            self.assertEqual(events[-1].metadata['stage'],last)
            self.assertEqual(states[-1].status,status)
            self.assertEqual(len(events),2)
        # Setup confirmation already above neckline must not complete on the same bar.
        f=bars([11.,10.,12.,8.,11.,7.,12.])
        _,states,events=factor.trace(f,self.p)
        self.assertEqual([e.metadata['stage'] for e in events],['setup'])
        self.assertEqual(states[-1].status,'active')
        # Both neckline and extreme equality leave the setup active.
        f=bars([11.,10.,12.,8.,11.,7.,9.,11.]).with_columns(
            pl.when(pl.int_range(pl.len())==7).then(7.).otherwise(pl.col('low')).alias('low'))
        _,states,events=factor.trace(f,self.p)
        self.assertEqual(len(events),1)
        # A bar crossing both sides invalidates before reversal; intrabar order is unknown.
        f=f.with_columns(pl.when(pl.int_range(pl.len())==7).then(6.).otherwise(pl.col('low')).alias('low'),
            *[pl.when(pl.int_range(pl.len())==7).then(12.).otherwise(pl.col(c)).alias(c) for c in ('high','close')])
        _,states,events=factor.trace(f,self.p)
        self.assertEqual(events[-1].metadata['stage'],'invalidated')

    def test_contraction_threshold_and_ambiguous_pivots(self):
        factor=BrooksWedgeComponent('setup',1)
        self.assertEqual(factor.compute(self.frame(),{**self.p,'contraction_ratio':0.5})['value'][6],1.)
        self.assertEqual(factor.compute(self.frame(),{**self.p,'contraction_ratio':0.49})['value'][6],0.)
        # An outside bar is simultaneously high and low: clear the unpublished candidate.
        f=self.frame().with_columns(pl.when(pl.int_range(pl.len())==3).then(14.).otherwise(pl.col('high')).alias('high'))
        _,_,events=factor.trace(f,self.p)
        self.assertEqual(events,[])

    def test_prefix_and_validation(self):
        f=pl.concat([self.frame(),bars([10.]*8,'B')])
        for d in (1,-1):
            for c in COMPONENTS:
                factor=BrooksWedgeComponent(c,d)
                assert_prefix_invariant(factor,f,self.p,sorted(set(f['available_at']))[:-1])
            _,states,events=factor.trace(f,self.p)
            for cutoff in sorted(set(f['available_at'])):
                _,s,e=factor.trace(f.filter(pl.col('available_at')<=cutoff),self.p)
                self.assertEqual(s,[v for v in states if v.available_at<=cutoff])
                self.assertEqual(e,[v for v in events if v.available_at<=cutoff])
        for p in ({'left':True},{'right':0},{'max_bars':1.5},{'contraction_ratio':1},
                  {'contraction_ratio':float('nan')},{'contraction_ratio':True},{'unknown':2}):
            with self.assertRaises(ValueError):factor.parameters(p)
        with self.assertRaises(ValueError):factor.trace(pl.concat([self.frame(),self.frame().tail(1)]),{})
