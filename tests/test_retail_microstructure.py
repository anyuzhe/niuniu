import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from quantlab.data.retail_microstructure import RetailMicrostructureConfig,TdxRetailMicrostructure
from quantlab.data.tdx_lake import QUALIFICATION


class RetailMicrostructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/"catalog").mkdir()
        (self.root/"lake/bronze/provider=tdx").mkdir(parents=True)
        db=self.root/"catalog/mqc.duckdb"
        con=duckdb.connect(str(db))
        con.execute("""CREATE TABLE tdx_trades_compacted(
            date DATE,code VARCHAR,price DOUBLE,volume DOUBLE,
            volume_unit VARCHAR,qualification VARCHAR,record_json VARCHAR
        )""")
        def row(day,code,price,volume,side,orders):
            return (day,code,price,volume,"lots_provider",QUALIFICATION,
                    json.dumps({"side":side,"order_count":orders}))
        rows=[
            row("2026-01-01","sh.600000",10,2,"buy",2),
            row("2026-01-01","sh.600000",10,4,"sell",2),
            row("2026-01-01","sh.600000",10,10,"buy",1),
            row("2026-01-01","sh.600000",10,3,"neutral",1),
            row("2026-01-01","sh.600000",10,0,"buy",1),
            row("2026-01-01","sz.000001",5,2,"buy",1),
            row("2026-01-01","sz.000002",5,2,"sell",1),
            row("2026-01-02","sh.600000",10,1,"buy",1),
            row("2026-01-02","sz.000001",5,1,"buy",1),
            row("2026-01-02","sz.000002",5,1,"sell",1),
        ]
        con.executemany("INSERT INTO tdx_trades_compacted VALUES (?,?,?,?,?,?,?)",rows)
        con.close()

    def test_features_are_scale_free_and_preserve_quality_counts(self):
        svc=TdxRetailMicrostructure(
            self.root,
            RetailMicrostructureConfig(min_qualified_days=20,min_symbols_per_day=3,relative_full_market_ratio=.5),
        )
        f=svc.daily_features(date(2026,1,1),date(2026,1,1),("sh.600000",))
        self.assertEqual(f.height,1)
        r=f.row(0,named=True)
        self.assertEqual((r["rows_total"],r["rows_non_directional"],r["rows_nonpositive_volume"]),(5,1,1))
        self.assertAlmostEqual(r["buy_imbalance_proxy"],.5)
        self.assertAlmostEqual(r["volume_imbalance"],.5)
        self.assertAlmostEqual(r["small_order_notional_share"],.125)
        self.assertAlmostEqual(r["small_order_buy_imbalance"],1.0)
        self.assertEqual(r["notional_proxy_unit"],"provider_lot_price_units_not_RMB")

    def test_reference_contract_matches_default_config(self):
        spec=json.loads((Path(__file__).parents[1]/"docs/reference/retail-microstructure-v2.json").read_text())
        cfg=RetailMicrostructureConfig()
        gate=spec["coverage_gate"]
        self.assertEqual(spec["source"]["qualification"],QUALIFICATION)
        self.assertEqual(gate["small_order_quantile"],cfg.small_order_quantile)
        self.assertEqual(gate["min_qualified_days"],cfg.min_qualified_days)
        self.assertEqual(gate["min_symbols_per_day"],cfg.min_symbols_per_day)
        self.assertEqual(gate["relative_full_market_ratio"],cfg.relative_full_market_ratio)

    def test_coverage_gate_never_promotes_two_days_to_inference(self):
        cfg=RetailMicrostructureConfig(min_qualified_days=20,min_symbols_per_day=3,relative_full_market_ratio=.9)
        svc=TdxRetailMicrostructure(self.root,cfg)
        c=svc.coverage()
        self.assertEqual(c["qualified_days"],2)
        self.assertFalse(c["inference_ready"])
        self.assertEqual(c["status"],"INSUFFICIENT_COVERAGE")
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_COVERAGE"):
            svc.require_inference_ready()


if __name__=="__main__":
    unittest.main()
