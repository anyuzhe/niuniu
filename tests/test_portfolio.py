import unittest
import polars as pl
from test_technical import bars
from quantlab.execution.portfolio import PortfolioConfig, TargetWeightBuilder

class PortfolioTests(unittest.TestCase):
    def test_caps_turnover_and_forced_exit(self):
        frame=pl.concat([bars([10.]*3,'A'),bars([10.]*3,'B')])
        obs=frame.select('symbol','datetime','available_at').with_columns(pl.Series('value',[3.,3.,3.,1.,1.,1.]),
            pl.Series('eligible',[True,True,False,True,True,True]))
        cfg=PortfolioConfig('score',.4,.6,.2)
        target,audit=TargetWeightBuilder(cfg).build(obs,frame,top_n=2,threshold=0,exposure=1.)
        self.assertAlmostEqual(sum(audit[0]['weights'].values()),.2)
        self.assertLessEqual(max(target['weight']),.4)
        self.assertLessEqual(max(sum(a['weights'].values()) for a in audit),.6)
        self.assertEqual(audit[-1]['weights']['A'],0.)
        self.assertIn('eligibility_exit_priority',audit[-1]['reasons'])
        self.assertEqual(audit[0]['selected'],['A','B'])
        self.assertEqual(len(audit[0]['signals']),2)
        prefix=frame.filter(pl.col('datetime')<=frame['datetime'][1])
        t2,a2=TargetWeightBuilder(cfg).build(obs.filter(pl.col('datetime')<=frame['datetime'][1]),prefix,top_n=2,threshold=0,exposure=1.)
        self.assertEqual(audit[:2],a2)
    def test_negative_score_weight_rejected(self):
        frame=bars([10.]);obs=frame.select('symbol','datetime','available_at').with_columns(pl.lit(-.5).alias('value'))
        with self.assertRaises(ValueError):TargetWeightBuilder(PortfolioConfig('score')).build(obs,frame,top_n=1,threshold=-1,exposure=1.)
