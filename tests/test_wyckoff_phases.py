import unittest
import polars as pl
from test_technical import bars
from quantlab.factors.wyckoff_phases import WyckoffPhaseComponent,COMPONENTS
from quantlab.causal import assert_prefix_invariant


def phase_bars():
    return bars([10.,10.,10.,10.,9.5,10.,12.,11.3,13.]).with_columns(
        pl.Series('high',[11.,11.,11.,11.,10.,10.5,12.5,11.8,13.5]),
        pl.Series('low',[9.,9.,9.,9.,8.,9.,10.,10.8,11.5]),
        pl.Series('volume',[100.,100.,100.,100.,200.,100.,300.,100.,200.]))


class WyckoffPhaseTests(unittest.TestCase):
    def test_phase_chain_state_and_mirror(self):
        frame=phase_bars();p={'lookback':3,'max_width':.5}
        values,states,events=WyckoffPhaseComponent('code').trace(frame,p)
        self.assertEqual(values['value'].to_list(),[None,None,None,1.,2.,2.,3.,3.,4.])
        self.assertEqual([e.factor_id for e in events],['WYCKOFF.PHASE_'+x for x in ('B','C_UP','TEST_UP','D_UP','RETEST_UP','E_UP')])
        self.assertEqual(states[-1].status,'completed')
        self.assertEqual(len({s.match_id for s in states}),1)
        self.assertEqual(events[-1].metadata['episode']['upper'],11.)
        self.assertEqual(events[-1].metadata['episode']['retest']['volume'],100.)
        mirror=frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),
            (30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low'))
        reflected=WyckoffPhaseComponent('code').trace(mirror,p)
        self.assertEqual(reflected[0]['value'].to_list(),[None,None,None,1.,-2.,-2.,-3.,-3.,-4.])
        self.assertEqual([e.factor_id.replace('DOWN','UP') for e in reflected[2]],[e.factor_id for e in events])

    def test_expiry_invalidation_and_no_same_bar_retest_completion(self):
        frame=phase_bars();p={'lookback':3,'max_width':.5}
        timed=WyckoffPhaseComponent('code').trace(frame,{**p,'follow_bars':1})
        self.assertEqual(timed[2][-1].factor_id,'WYCKOFF.PHASE_EXPIRED_UP')
        self.assertEqual(timed[1][-1].status,'timeout')
        self.assertEqual(timed[0]['value'][-1],0.)
        changed=frame.with_columns(pl.when(pl.col('datetime')==frame['datetime'][7]).then(10.5).otherwise(pl.col('close')).alias('close'),
            pl.when(pl.col('datetime')==frame['datetime'][7]).then(10.4).otherwise(pl.col('low')).alias('low'))
        invalid=WyckoffPhaseComponent('e_up').trace(changed,p)
        self.assertEqual(invalid[0]['value'].sum(),0.)
        self.assertTrue(any(e.metadata['reason']=='breakout_failed' for e in invalid[2]))
        # A retest close already above the breakout high still cannot also complete E.
        changed=frame.with_columns(pl.when(pl.col('datetime')==frame['datetime'][7]).then(13.).otherwise(pl.col('close')).alias('close'),
            pl.when(pl.col('datetime')==frame['datetime'][7]).then(13.5).otherwise(pl.col('high')).alias('high'))
        self.assertEqual(WyckoffPhaseComponent('e_up').compute(changed,p)['value'][7],0.)

    def test_prefix_values_events_and_transitions(self):
        frame=phase_bars();p={'lookback':3,'max_width':.5};factor=WyckoffPhaseComponent('code')
        _,states,events=factor.trace(frame,p)
        for component in COMPONENTS:assert_prefix_invariant(WyckoffPhaseComponent(component),frame,p,frame['available_at'].to_list()[2:-1])
        for n in range(1,frame.height):
            _,prefix_states,prefix_events=factor.trace(frame.head(n),p);cutoff=frame['available_at'][n-1]
            self.assertEqual(prefix_states,[s for s in states if s.available_at<=cutoff])
            self.assertEqual(prefix_events,[e for e in events if e.available_at<=cutoff])

    def test_invalid_parameters_and_duplicate_availability(self):
        factor=WyckoffPhaseComponent('code')
        for params in ({'follow_bars':True},{'retest_fraction':0},{'retest_volume_ratio':float('nan')},{'bogus':1}):
            with self.assertRaises(ValueError):factor.parameters(params)
        frame=phase_bars().with_columns(pl.lit(phase_bars()['available_at'][-1]).alias('available_at'))
        with self.assertRaisesRegex(ValueError,'unique'):factor.trace(frame,{})
