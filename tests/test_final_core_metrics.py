import math
import statistics
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import polars as pl
from quantlab.experiments.event_metrics import event_path_metrics, signal_turnover
from quantlab.execution.performance import performance_metrics


class FinalMetricsTests(unittest.TestCase):
    def test_event_recovery_and_censoring(self):
        at = datetime(2020, 1, 1, 15, tzinfo=ZoneInfo('Asia/Shanghai'))
        bars = pl.DataFrame([{'symbol': 'A', 'datetime': at+timedelta(days=i), 'close': c} for i,c in enumerate([100., 97., 99., 103., 101.])])
        m = event_path_metrics(bars, bars.head(1), 4)
        self.assertEqual(m['failure_rate'], 1)
        self.assertEqual(m['mean_time_to_target_bars'], 3)
        self.assertEqual(m['mean_recovery_bars'], 2)
        self.assertEqual(m['recovery_rate'], 1)
        empty = event_path_metrics(bars, bars.head(0), 4)
        self.assertIsNone(empty['failure_rate'])
        self.assertIsNone(empty['mean_time_to_target_bars'])

    def test_turnover_counts_exited_names_and_cash(self):
        at = datetime(2020, 1, 1)
        frame = pl.DataFrame([{'symbol': s, 'datetime': at+timedelta(days=d), 'value': v} for d, pairs in enumerate([[('A',1.),('B',2.)],[('A',2.),('C',1.)],[('A',1.),('C',1.)]]) for s,v in pairs])
        m = signal_turnover(frame,2)
        self.assertEqual(m['transitions'],2)
        self.assertEqual(m['mean_one_way'],1.)

    def test_sharpe_daily_not_per_intraday_bar(self):
        at = datetime(2020,1,1,10,tzinfo=ZoneInfo('Asia/Shanghai'))
        curve = pl.DataFrame([{'datetime':at+timedelta(days=d,hours=h),'equity':value} for d,h,value in [(0,0,120.),(0,5,101.),(1,0,110.),(1,5,99.),(2,5,103.)]])
        returns = [.01,99/101-1,103/99-1]
        m = performance_metrics(curve,100.)
        self.assertEqual(m['performance_days'],3)
        self.assertAlmostEqual(m['sharpe'],statistics.mean(returns)/statistics.stdev(returns)*math.sqrt(252))
        self.assertIsNone(performance_metrics(curve.head(1),100.)['sharpe'])
