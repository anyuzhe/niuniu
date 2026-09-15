import unittest
from datetime import date,timedelta
from unittest.mock import patch

from quantlab.agent.watch_sequential import VERSION,build_baseline,monitor,sequential_fingerprint


def rows(values,start_day=11):
    start=date(2025,1,start_day)
    return [{'signal_date':str(start+timedelta(days=i)),'rank_ic':value,
        'mature_at':str(start+timedelta(days=i))+'T15:00:00+08:00','timestamps':1}
        for i,value in enumerate(values)]


class WatchSequentialTests(unittest.TestCase):
    def baseline(self,reference=.20,min_new=10):
        return {'version':VERSION,'algorithm':sequential_fingerprint(),'family_alpha':.05,
            'min_effect':.02,'min_new_dates':min_new,'block_sessions':5,'baseline_min_dates':20,
            'baseline_as_of':'2025-01-10T15:00:00+08:00','lambda_grid':[.05,.1,.2,.3,.4],
            'method':'mixture_e_process_against_frozen_empirical_rank_ic_reference',
            'horizons':{'1':{'status':'ready','reference_mean':reference,'valid_sessions':30,
                'first_signal_date':'2024-12-01','last_signal_date':'2025-01-09',
                'last_mature_at':'2025-01-10T15:00:00+08:00','local_alpha':.05}},
            'limitations':[]}
    def test_strong_persistent_drop_crosses_anytime_e_threshold(self):
        baseline=self.baseline();series={'1':rows([-1.0]*60)}
        with patch('quantlab.agent.watch_sequential._read_daily_series',return_value=({'horizons':[1]},series)):
            value=monitor('/tmp','run','2025-01-22T15:00:00+08:00','f'*64,baseline)
        item=value['horizons']['1']
        self.assertEqual(value['status'],'DEGRADATION_EVIDENCE')
        self.assertGreaterEqual(item['max_e_value'],item['evidence_threshold'])
        self.assertIsNotNone(item['first_crossed_at'])
        self.assertGreater(item['observed_drop'],baseline['min_effect'])

    def test_repeated_looks_do_not_create_evidence_without_new_bad_data(self):
        baseline=self.baseline();series={'1':rows([.20]*20)}
        with patch('quantlab.agent.watch_sequential._read_daily_series',return_value=({'horizons':[1]},series)):
            first=monitor('/tmp','run','2025-01-30T15:00:00+08:00','f'*64,baseline)
            second=monitor('/tmp','run','2025-01-30T15:00:00+08:00','f'*64,baseline)
        self.assertEqual(first,second)
        self.assertEqual(first['horizons']['1']['status'],'NO_DECISIVE_CHANGE')
        self.assertLess(first['horizons']['1']['max_e_value'],first['horizons']['1']['evidence_threshold'])

    def test_crossing_is_sticky_even_if_later_values_recover(self):
        baseline=self.baseline();series={'1':rows([-1.0]*60+[1.0]*40)}
        with patch('quantlab.agent.watch_sequential._read_daily_series',return_value=({'horizons':[1]},series)):
            value=monitor('/tmp','run','2025-01-30T15:00:00+08:00','f'*64,baseline)
        item=value['horizons']['1']
        self.assertEqual(item['status'],'DEGRADATION_EVIDENCE')
        self.assertIsNotNone(item['first_crossed_at'])
        self.assertGreaterEqual(item['max_e_value'],item['evidence_threshold'])
    def test_family_alpha_is_split_across_horizons_at_baseline(self):
        series={'1':rows([.1]*20,1),'5':rows([.2]*20,1)}
        cfg={'horizons':[1,5]}
        with patch('quantlab.agent.watch_sequential._read_daily_series',return_value=(cfg,series)):
            baseline=build_baseline('/tmp','run','2025-01-20T15:00:00+08:00','f'*64,20,
                family_alpha=.05,min_effect=.02,min_new_dates=10)
        self.assertAlmostEqual(baseline['horizons']['1']['local_alpha'],.025)
        self.assertAlmostEqual(baseline['horizons']['5']['local_alpha'],.025)
        self.assertEqual(baseline['horizons']['1']['status'],'ready');self.assertEqual(baseline['block_sessions'],5)

    def test_insufficient_and_historical_revision_fail_closed(self):
        baseline=self.baseline();baseline['horizons']['1']['status']='insufficient_baseline'
        series={'1':rows([-1.0]*30)}
        with patch('quantlab.agent.watch_sequential._read_daily_series',return_value=({'horizons':[1]},series)):
            value=monitor('/tmp','run','2025-02-10T15:00:00+08:00','f'*64,baseline)
        self.assertEqual(value['horizons']['1']['status'],'INSUFFICIENT_BASELINE')
        blocked=monitor('/tmp','run','2025-02-10T15:00:00+08:00','f'*64,baseline,historical_revision=True)
        self.assertEqual(blocked['status'],'HISTORICAL_REVISION_BLOCKED')

    def test_algorithm_change_requires_new_watch(self):
        baseline=self.baseline();baseline['algorithm']='0'*64
        with self.assertRaisesRegex(ValueError,'算法已变化'):
            monitor('/tmp','run','2025-01-20T15:00:00+08:00','f'*64,baseline)


if __name__=='__main__':unittest.main()
