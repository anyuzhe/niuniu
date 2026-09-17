from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import unittest

import polars as pl

from quantlab.adapters.vnpy import validate_config
from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.execution.fees import effective_fee_bps, statutory_fee_bps
from quantlab.trading.qimo_paper import CONFIG, POLICY, VERSION

TZ = ZoneInfo('Asia/Shanghai')


def market(start):
    times = [datetime(*start, 15, tzinfo=TZ) + timedelta(days=i) for i in range(4)]
    return pl.DataFrame({'symbol': ['sh.600000'] * 4, 'datetime': times, 'available_at': times, 'timeframe': ['1d'] * 4, 'open': [10.0] * 4,
                         'high': [10.0] * 4, 'low': [10.0] * 4, 'close': [10.0] * 4, 'volume': [1e6] * 4, 'turnover': [1e7] * 4})


class StatutoryFeeTests(unittest.TestCase):
    def test_schedule_boundaries_and_statutory_floor(self):
        self.assertEqual(statutory_fee_bps(date(2019, 1, 2)), {'sell_tax_bps': 10.0, 'transfer_bps': 0.2})
        self.assertEqual(statutory_fee_bps(date(2022, 4, 28))['transfer_bps'], 0.2)
        self.assertEqual(statutory_fee_bps(date(2022, 4, 29))['transfer_bps'], 0.1)
        self.assertEqual(statutory_fee_bps(date(2023, 8, 27))['sell_tax_bps'], 10.0)
        self.assertEqual(statutory_fee_bps(datetime(2023, 8, 28, 9, 30, tzinfo=TZ)), {'sell_tax_bps': 5.0, 'transfer_bps': 0.1})
        for bad in (date(2015, 7, 31), '2024-01-02', None):
            with self.assertRaises(ValueError):
                statutory_fee_bps(bad)
        self.assertEqual(effective_fee_bps({'sell_tax_bps': 0, 'transfer_bps': 0}, date(2026, 9, 17), True), (5.0, 0.1))
        self.assertEqual(effective_fee_bps({'sell_tax_bps': 12, 'transfer_bps': 0.5}, date(2026, 9, 17), True), (12, 0.5))  # never double counted
        self.assertEqual(effective_fee_bps({'sell_tax_bps': 0, 'transfer_bps': 0}, date(2026, 9, 17), False), (0, 0))

    def test_backtest_charges_statutory_fees_by_trade_date(self):
        results = {}
        for start in ((2023, 8, 21), (2023, 8, 28)):
            prices = market(start)
            targets = prices.head(2).select('symbol', 'datetime', 'available_at').with_columns(pl.Series('weight', [1.0, 0.0]))
            for statutory in (False, True):
                cfg = ExecutionConfig(initial_cash=100000, slippage_bps=0, commission_bps=0, minimum_commission=0, statutory_fees=statutory)
                curve, fills, _, _ = OpenExecutionBacktester(cfg).run(targets, prices)
                results[start, statutory] = ([(f['side'], f['quantity'], f['tax'], f['transfer_fee']) for f in fills], curve['equity'].to_list()[-1])
        self.assertEqual(results[(2023, 8, 21), False], ([('buy', 10000, 0.0, 0.0), ('sell', 10000, 0.0, 0.0)], 100000.0))
        # Before 2023-08-28 the seller pays 10 bps stamp duty; buying power already reserves the transfer fee.
        self.assertEqual(results[(2023, 8, 21), True][0], [('buy', 9900, 0.0, 0.99), ('sell', 9900, 99.0, 0.99)])
        self.assertEqual(results[(2023, 8, 28), True][0], [('buy', 9900, 0.0, 0.99), ('sell', 9900, 49.5, 0.99)])
        self.assertAlmostEqual(results[(2023, 8, 28), True][1], 100000 - 49.5 - 1.98, places=6)

    def test_config_validation_vnpy_and_qimo_policy(self):
        with self.assertRaises(ValueError):
            ExecutionConfig(statutory_fees=1)
        plain = ExecutionConfig(minimum_commission=0, slippage_bps=0, limit_pct=.1)
        validate_config(plain)
        with self.assertRaisesRegex(ValueError, 'vnpy_rules'):
            validate_config(ExecutionConfig(minimum_commission=0, slippage_bps=0, limit_pct=.1, statutory_fees=True))
        self.assertEqual((VERSION, CONFIG.statutory_fees, POLICY['config']['statutory_fees']), ('qimo-auto-paper-v3', True, True))


if __name__ == '__main__':
    unittest.main()
