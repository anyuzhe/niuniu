import unittest
from datetime import timedelta
from test_market_paper import fixture
from quantlab.execution.rules import MarketRules


class RuleExpirationTest(unittest.TestCase):
    def test_expired_replacement_does_not_restore_old_limits(self):
        _,_,records,_=fixture();older=dict(records[0]);newer=dict(records[1])
        older['expires_at']=records[-1]['expires_at']
        rules=MarketRules([older,newer]);at=newer['effective_at']+timedelta(hours=10)
        self.assertEqual(rules.at(older['symbol'],at),newer)
        self.assertIsNone(rules.at(older['symbol'],newer['expires_at']))
        newer['available_at']=newer['expires_at']+timedelta(days=1)
        self.assertEqual(MarketRules([older,newer]).at(older['symbol'],at),older)
