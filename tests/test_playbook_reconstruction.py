import unittest
from datetime import date

import polars as pl

from quantlab.trading.playbook_reconstruction import (
    exact_limit_streak_candidates, mark_limit_closes, rounded_limit_price,
)


class PlaybookReconstructionTests(unittest.TestCase):
    def frame(self):
        return pl.DataFrame([
            {'date':date(2026,6,26),'code':'sh.600707','close':13.96},
            {'date':date(2026,6,29),'code':'sh.600707','close':15.35},
            {'date':date(2026,6,30),'code':'sh.600707','close':16.89},
            {'date':date(2026,6,26),'code':'sh.600113','close':24.93},
            {'date':date(2026,6,29),'code':'sh.600113','close':27.42},
            {'date':date(2026,6,30),'code':'sh.600113','close':30.16},
        ])

    def test_exact_limit_price_does_not_treat_near_limit_as_board(self):
        self.assertEqual(rounded_limit_price(13.96,0.10),15.36)
        marked=mark_limit_closes(self.frame())
        rainbow=marked.filter(pl.col('code')=='sh.600707').sort('date')
        self.assertFalse(rainbow.row(1,named=True)['is_limit_close'])
        candidates=exact_limit_streak_candidates(marked,date(2026,6,30),streak=2)
        self.assertEqual([row['symbol'] for row in candidates],['sh.600113'])

    def test_special_s_share_rate_can_be_explicitly_frozen(self):
        bars=pl.DataFrame([
            {'date':date(2026,6,30),'code':'sh.600182','close':12.84},
            {'date':date(2026,7,1),'code':'sh.600182','close':13.48},
            {'date':date(2026,7,2),'code':'sh.600182','close':14.15},
        ])
        default=exact_limit_streak_candidates(mark_limit_closes(bars),date(2026,7,2),streak=2)
        self.assertEqual(default,[])
        marked=mark_limit_closes(bars,special_rates={'sh.600182':0.05})
        candidates=exact_limit_streak_candidates(marked,date(2026,7,2),streak=2)
        self.assertEqual(candidates[0]['symbol'],'sh.600182')
        self.assertEqual(candidates[0]['limit_rate'],0.05)

    def test_exact_streak_rejects_higher_board(self):
        bars=pl.DataFrame([
            {'date':date(2026,6,26),'code':'sh.600001','close':10.00},
            {'date':date(2026,6,29),'code':'sh.600001','close':11.00},
            {'date':date(2026,6,30),'code':'sh.600001','close':12.10},
            {'date':date(2026,7,1),'code':'sh.600001','close':13.31},
        ])
        marked=mark_limit_closes(bars)
        self.assertEqual(len(exact_limit_streak_candidates(marked,date(2026,6,30),streak=2)),1)
        self.assertEqual(exact_limit_streak_candidates(marked,date(2026,7,1),streak=2),[])

    def test_default_rates_follow_board_reform_dates(self):
        bars=pl.DataFrame([
            {'date':date(2020,8,20),'code':'sz.300001','close':10.0},
            {'date':date(2020,8,21),'code':'sz.300001','close':11.0},
            {'date':date(2020,8,24),'code':'sz.300001','close':13.2},
            {'date':date(2026,9,15),'code':'sz.302001','close':10.0},
            {'date':date(2026,9,16),'code':'sz.302001','close':12.0},
        ])
        rows={(r['code'],r['date']):r for r in mark_limit_closes(bars).iter_rows(named=True)}
        self.assertEqual(rows[('sz.300001',date(2020,8,21))]['limit_rate'],0.10)
        self.assertTrue(rows[('sz.300001',date(2020,8,21))]['is_limit_close'])
        self.assertEqual(rows[('sz.300001',date(2020,8,24))]['limit_rate'],0.20)
        self.assertTrue(rows[('sz.300001',date(2020,8,24))]['is_limit_close'])
        self.assertTrue(rows[('sz.302001',date(2026,9,16))]['is_limit_close'])
        unknown=mark_limit_closes(pl.DataFrame([{'date':date(2026,9,15),'code':'sh.900901','close':1.0},
            {'date':date(2026,9,16),'code':'sh.900901','close':1.1}])).sort('date')
        self.assertIsNone(unknown.row(1,named=True)['limit_up_price'])
        self.assertFalse(unknown.row(1,named=True)['is_limit_close'])

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            rounded_limit_price(float('nan'),0.10)
        duplicate=pl.DataFrame([
            {'date':date(2026,7,1),'code':'sh.600000','close':10.0},
            {'date':date(2026,7,1),'code':'sh.600000','close':10.0},
        ])
        with self.assertRaises(ValueError):
            mark_limit_closes(duplicate)


if __name__=='__main__':
    unittest.main()

# Regression: suspension placeholder rows must not reset a real trading-day streak.
def _suspension_regression_case():
    return pl.DataFrame([
        {'date':date(2026,6,12),'code':'sh.603137','close':11.76,'tradable':True,'limit_rate':0.10},
        {'date':date(2026,6,15),'code':'sh.603137','close':12.94,'tradable':True,'limit_rate':0.10},
        {'date':date(2026,6,30),'code':'sh.603137','close':12.94,'tradable':False,'limit_rate':0.10},
        {'date':date(2026,7,1),'code':'sh.603137','close':14.23,'tradable':True,'limit_rate':0.10},
        {'date':date(2026,7,2),'code':'sh.603137','close':15.65,'tradable':True,'limit_rate':0.10},
        {'date':date(2026,6,29),'code':'sh.603559','close':7.80,'tradable':True,'limit_rate':0.05},
        {'date':date(2026,6,30),'code':'sh.603559','close':8.19,'tradable':True,'limit_rate':0.05},
        {'date':date(2026,7,1),'code':'sh.603559','close':8.19,'tradable':False,'limit_rate':0.05},
        {'date':date(2026,7,2),'code':'sh.603559','close':9.01,'tradable':True,'limit_rate':0.10},
    ])

class PlaybookSuspensionRegressionTests(unittest.TestCase):
    def test_suspension_is_skipped_and_session_specific_rate_is_used(self):
        marked=mark_limit_closes(_suspension_regression_case())
        candidates=exact_limit_streak_candidates(marked,date(2026,7,2),streak=2)
        symbols=[row['symbol'] for row in candidates]
        self.assertIn('sh.603559',symbols)
        self.assertNotIn('sh.603137',symbols)
        tongmai=marked.filter((pl.col('code')=='sh.603559') & pl.col('tradable')).sort('date')
        self.assertTrue(tongmai.row(1,named=True)['is_limit_close'])
        self.assertEqual(tongmai.row(1,named=True)['limit_rate'],0.05)
        self.assertTrue(tongmai.row(2,named=True)['is_limit_close'])
        self.assertEqual(tongmai.row(2,named=True)['limit_rate'],0.10)
