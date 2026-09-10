import unittest
from quantlab.factors.sequences import CustomOrderedSequence,FailedLowThenBreakout
from quantlab.causal import assert_prefix_invariant
from test_reclaim_sequence import make_frame

class CustomSequenceTests(unittest.TestCase):
    def test_custom_matches_existing_rule_and_prefix_contract(self):
        factor=CustomOrderedSequence()
        for tail in [[(7.,10.,9.),(8.,12.,12.)],[(7.,10.,9.),(8.,11.,9.),(8.,12.,12.)]]:
            frame=make_frame(tail)
            for gap in (86400,172800,259200):
                params={'lookback':2,'max_gap_seconds':gap}
                values,matches,_=factor.trace(frame,params)
                original,expected,_=FailedLowThenBreakout().trace(frame,params)
                self.assertEqual(values.to_dicts(),original.to_dicts())
                self.assertEqual([(m.status,m.available_at) for m in matches],[(m.status,m.available_at) for m in expected])
                assert_prefix_invariant(factor,frame,params,frame['datetime'].to_list())
    def test_order_changes_result_and_unsupported_features_rejected(self):
        f=CustomOrderedSequence();frame=make_frame([(7.,10.,9.),(8.,12.,12.)])
        params={'lookback':2,'steps':['EVT.BREAKOUT_HIGH','EVT.FAILED_BREAKOUT_LOW']}
        self.assertEqual(f.compute(frame,params)['value'].drop_nulls().to_list(),[0.,0.])
        for params in ({'steps':['EVT.BREAKOUT_HIGH']},{'optional':True},{'steps':['MISSING','EVT.BREAKOUT_HIGH']},{'invalidators':['EVT.BREAKOUT_HIGH']}):
            with self.assertRaises(ValueError):f.parameters(params)
