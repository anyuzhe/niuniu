import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import polars as pl
from quantlab.data.dividends import import_cash_dividends


class StockImportTests(unittest.TestCase):
    def test_decimal_components_and_invalid_record_remain_unresolved(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'lake/bronze/provider=baostock/corporate_actions_dividend';folder.mkdir(parents=True)
            row={'code':'sh.600000','dividStocksPs':'0.1','dividReserveToStockPs':'0.2','fetch_ts':'2025-02-01T12:00:00',
                'dividRegistDate':'2025-01-02','dividOperateDate':'2025-01-03','dividPayDate':'2025-01-03',
                'dividStockMarketDate':'2025-01-06','dividCashPsBeforeTax':'0'}
            pl.DataFrame([row,{**row,'dividStocksPs':'unknown'}]).write_parquet(folder/'sh_600000.parquet')
            result=import_cash_dividends(root,['sh.600000'],0,include_stock=True)
            self.assertEqual(result['corporate_actions'][0]['stock_per_share'],.3)
            self.assertEqual(result['corporate_actions'][0]['fractional_policy'],'reject')
            self.assertEqual(len(result['unresolved']),1)
            self.assertFalse(result['strict_pit_ready'])
