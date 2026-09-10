import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import polars as pl
from test_technical import bars
from test_theory_extensions import ob_bars
from quantlab.factors.ict_context import Breaker,DealingRange,KillZone
from quantlab.causal import assert_prefix_invariant

class ICTContextTests(unittest.TestCase):
    def test_breaker_after_invalidation_and_direction_mirror(self):
        frame=ob_bars().with_columns(pl.Series('high',[10.5,12.,11.,10.5,14.5,11.,10.,9.5]))
        parameters={'lookback':2,'left':1,'right':1,'atr_multiple':1.0}
        for direction,source in [(-1,frame),(1,frame.with_columns((30-pl.col('open')).alias('open'),(30-pl.col('close')).alias('close'),(30-pl.col('low')).alias('high'),(30-pl.col('high')).alias('low')))]:
            factor=Breaker(direction);values,_,events=factor.trace(source,parameters)
            self.assertEqual(values['value'].to_list(),[0.]*7+[1.])
            point=next(e for e in events if e.factor_id==factor.definition.factor_id)
            self.assertLess(point.metadata['invalidation_available_at'],point.available_at)
            assert_prefix_invariant(factor,source,parameters,source['available_at'].to_list()[2:])
    def test_lagged_range_and_timezone_dst(self):
        frame=bars([10.,12.,11.,11.5,20.])
        for component in ('range_position','premium','discount'):
            assert_prefix_invariant(DealingRange(component),frame,{'lookback':2},frame['available_at'].to_list()[2:])
        self.assertEqual(DealingRange('premium').compute(frame,{'lookback':2})['value'][-1],0.)
        stamps=[datetime(2025,1,10,12,tzinfo=ZoneInfo('UTC')),datetime(2025,7,10,12,tzinfo=ZoneInfo('UTC'))]
        frame=frame.head(2).with_columns(pl.Series('datetime',stamps),pl.Series('available_at',stamps),pl.lit('5m').alias('timeframe'))
        # Winter 07:00 is the excluded opening boundary; summer 08:00 is inside.
        self.assertEqual(KillZone().compute(frame,{})['value'].to_list(),[0.,1.])

if __name__=='__main__':unittest.main()
