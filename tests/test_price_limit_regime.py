from datetime import date, datetime
import unittest

from quantlab.trading.price_limit_regime import (
    BSE, CHINEXT, MAIN, NO_LIMIT, NORMAL, STAR, UNKNOWN, UNMODELED, REGIME_VERSION,
    board_of, limit_prices, limit_rule,
)


class BoardTests(unittest.TestCase):
    def test_all_current_stock_prefixes_are_classified(self):
        for symbol in ('sh.600000','sh.601318','sh.603288','sh.605499','sz.000001','sz.001979','sz.002594','sz.003816'):
            self.assertEqual(board_of(symbol),MAIN,symbol)
        for symbol in ('sz.300750','sz.301236','sz.302132'):
            self.assertEqual(board_of(symbol),CHINEXT,symbol)
        for symbol in ('sh.688981','sh.689009'):
            self.assertEqual(board_of(symbol),STAR,symbol)
        self.assertEqual(board_of('bj.920118'),BSE)
        self.assertEqual(board_of('sh.900901'),UNKNOWN)

    def test_invalid_arguments_fail_closed(self):
        for bad in ('600000','SH.600000','sh.60000',None):
            with self.assertRaises(ValueError):board_of(bad)
        with self.assertRaises(ValueError):limit_rule('sh.600000','2026-09-16')
        with self.assertRaises(ValueError):limit_rule('sh.600000',date(2026,9,16),is_st=1)
        with self.assertRaises(ValueError):limit_rule('sh.600000',date(2026,9,16),sessions_since_listing=0)
        with self.assertRaises(ValueError):limit_rule('sh.600000',date(2026,9,16),sessions_to_delisting=-1)


class RegimeTests(unittest.TestCase):
    def rate(self,symbol,day,**kwargs):
        result=limit_rule(symbol,day,**kwargs);self.assertEqual(result['status'],NORMAL,result);return result['rate']

    def test_main_board_risk_warning_changes_on_2026_07_06(self):
        self.assertEqual(self.rate('sh.600000',date(2019,1,2)),0.10)
        self.assertEqual(self.rate('sz.002594',date(2026,7,3),is_st=True),0.05)
        self.assertEqual(self.rate('sz.002594',date(2026,7,6),is_st=True),0.10)
        self.assertEqual(self.rate('sh.600000',date(2026,9,16),is_st=False),0.10)
        self.assertEqual(limit_rule('sh.600000',date(2026,7,6),is_st=True)['reason'],'MAIN_RISK_WARNING_10PCT')

    def test_chinext_reform_boundary(self):
        self.assertEqual(self.rate('sz.300750',date(2020,8,21)),0.10)
        self.assertEqual(self.rate('sz.300750',date(2020,8,21),is_st=True),0.05)
        self.assertEqual(self.rate('sz.300750',date(2020,8,24)),0.20)
        self.assertEqual(self.rate('sz.300750',date(2020,8,24),is_st=True),0.20)

    def test_star_and_bse_boards(self):
        self.assertEqual(self.rate('sh.688981',date(2019,7,22)),0.20)
        self.assertEqual(self.rate('sh.689009',date(2026,9,16),is_st=True),0.20)
        self.assertEqual(limit_rule('sh.688981',date(2019,7,19))['reason'],'BEFORE_BOARD_OPEN')
        self.assertEqual(self.rate('bj.920118',date(2026,9,16)),0.30)
        self.assertEqual(limit_rule('bj.920118',date(2021,11,12))['status'],UNMODELED)

    def test_registration_ipo_windows(self):
        listed=date(2023,4,10)
        for session in range(1,6):
            result=limit_rule('sh.601065',date(2023,4,10),listing_date=listed,sessions_since_listing=session)
            self.assertEqual((result['status'],result['reason']),(NO_LIMIT,'IPO_NO_LIMIT_WINDOW'))
        sixth=limit_rule('sh.601065',date(2023,4,17),listing_date=listed,sessions_since_listing=6)
        self.assertEqual((sixth['status'],sixth['rate'],sixth['listing_window_checked']),(NORMAL,0.10,True))
        self.assertEqual(limit_rule('sh.688981',date(2020,7,16),listing_date=date(2020,7,16),sessions_since_listing=1)['status'],NO_LIMIT)
        self.assertEqual(limit_rule('sz.301001',date(2020,8,24),listing_date=date(2020,8,24),sessions_since_listing=1)['status'],NO_LIMIT)
        self.assertEqual(limit_rule('bj.920118',date(2026,9,16),listing_date=date(2026,9,16),sessions_since_listing=1)['status'],NO_LIMIT)
        self.assertEqual(limit_rule('bj.920118',date(2026,9,17),listing_date=date(2026,9,16),sessions_since_listing=2)['status'],NORMAL)

    def test_pre_registration_first_day_is_unmodeled_and_old_listings_get_no_window(self):
        first=limit_rule('sh.603999',date(2023,3,31),listing_date=date(2023,3,31),sessions_since_listing=1)
        self.assertEqual((first['status'],first['reason']),(UNMODELED,'IPO_FIRST_DAY_SPECIAL_RULE_UNMODELED'))
        self.assertEqual(self.rate('sh.603999',date(2023,4,3),listing_date=date(2023,3,31),sessions_since_listing=2),0.10)
        # Listed under the old ChiNext regime: no five-session no-limit window after the reform day.
        self.assertEqual(self.rate('sz.300999',date(2020,8,24),listing_date=date(2020,8,20),sessions_since_listing=3),0.20)

    def test_listing_date_without_session_count_is_resolved_conservatively(self):
        self.assertEqual(limit_rule('sh.601065',date(2023,4,20),listing_date=date(2023,4,10))['reason'],'LISTING_WINDOW_UNRESOLVED')
        far=limit_rule('sh.601065',date(2023,5,31),listing_date=date(2023,4,10))
        self.assertEqual((far['status'],far['listing_window_checked']),(NORMAL,True))
        self.assertEqual(limit_rule('sh.601065',date(2023,4,7),listing_date=date(2023,4,10))['reason'],'BEFORE_LISTING')
        self.assertFalse(limit_rule('sh.601065',date(2023,5,31))['listing_window_checked'])

    def test_listing_date_resolves_when_no_multi_session_window_exists(self):
        old_main=limit_rule('sh.603999',date(2023,1,5),listing_date=date(2023,1,3))
        self.assertEqual((old_main['status'],old_main['rate'],old_main['listing_window_checked']),(NORMAL,0.10,True))
        self.assertEqual(limit_rule('sh.603999',date(2023,1,3),listing_date=date(2023,1,3))['reason'],'LISTING_WINDOW_UNRESOLVED')
        self.assertEqual(limit_rule('bj.920118',date(2026,9,17),listing_date=date(2026,9,16))['status'],NORMAL)
        self.assertEqual(limit_rule('sz.300999',date(2020,8,24),listing_date=date(2020,8,20))['status'],NORMAL)
        self.assertEqual(limit_rule('sh.688001',date(2026,9,17),listing_date=date(2026,9,16))['reason'],'LISTING_WINDOW_UNRESOLVED')

    def test_near_delisting_and_unknown_board_are_excluded(self):
        self.assertEqual(limit_rule('sz.000001',date(2026,9,16),sessions_to_delisting=30)['reason'],'NEAR_DELISTING_UNMODELED')
        self.assertEqual(limit_rule('sz.000001',date(2026,9,16),sessions_to_delisting=31)['status'],NORMAL)
        unknown=limit_rule('sh.900901',date(2026,9,16))
        self.assertEqual((unknown['status'],unknown['rate'],unknown['regime_version']),(UNMODELED,None,REGIME_VERSION))

    def test_datetime_sessions_are_normalized(self):
        self.assertEqual(self.rate('sz.300750',datetime(2020,8,24,9,30)),0.20)


class PriceTests(unittest.TestCase):
    def test_exchange_rounding_half_up_to_cents(self):
        self.assertEqual(limit_prices(13.96,0.10),(15.36,12.56))
        self.assertEqual(limit_prices(9.95,0.10),(10.95,8.96))
        self.assertEqual(limit_prices(10.05,0.05),(10.55,9.55))
        self.assertEqual(limit_prices(12.5,0.20),(15.0,10.0))

    def test_invalid_prices_fail_closed(self):
        for reference,rate in ((0,0.1),(float('nan'),0.1),(10,0),(10,1.0),(10,float('inf')),('10',0.1)):
            with self.assertRaises(ValueError):limit_prices(reference,rate)


if __name__=='__main__':unittest.main()
