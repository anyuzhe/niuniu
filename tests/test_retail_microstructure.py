import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from quantlab.agent.tdx_collection_cli import POLICY_FORMAT,SCHEDULER_POLICY
from quantlab.data.retail_microstructure import RetailMicrostructureConfig,TdxRetailMicrostructure
from quantlab.data.tdx_lake import QUALIFICATION,TdxLake,digest,write_json
from quantlab.data.tdx_sharding import ROLE_FILE,make_assignment,sealed,shard_for


class RetailMicrostructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.lake=TdxLake(self.root,create=True)
        db=self.root/"catalog/mqc.duckdb"
        con=duckdb.connect(str(db))
        def row(index,day,code,price,volume,side,orders):
            return (f"{index:064x}",0,day,code,price,volume,"lots_provider",QUALIFICATION,
                    json.dumps({"side":side,"order_count":orders}))
        rows=[
            row(1,"2026-01-01","sh.600000",10,2,"buy",2),
            row(2,"2026-01-01","sh.600000",10,4,"sell",2),
            row(3,"2026-01-01","sh.600000",10,10,"buy",1),
            row(4,"2026-01-01","sh.600000",10,3,"neutral",1),
            row(5,"2026-01-01","sh.600000",10,0,"buy",1),
            row(6,"2026-01-01","sz.000001",5,2,"buy",1),
            row(7,"2026-01-01","sz.000002",5,2,"sell",1),
            row(8,"2026-01-02","sh.600000",10,1,"buy",1),
            row(9,"2026-01-02","sz.000001",5,1,"buy",1),
            row(10,"2026-01-02","sz.000002",5,1,"sell",1),
        ]
        con.executemany(
            """INSERT INTO tdx_trades_compacted
               (source_id,record_index,date,code,price,volume,volume_unit,qualification,record_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",rows)
        con.close()
        self.install_contract(
            ("sh.600000","sz.000001","sz.000002"),1,
            ("2026-01-01","2026-01-02","2026-01-03"))

    def install_contract(self,symbols,shard_count,trading_days):
        body={
            "format":"tdx-personal-collection-v1",
            "symbols":list(symbols),
            "trading_days":list(trading_days),
            "history_start":trading_days[0],
            "history_end":trading_days[-1],
            "max_offset":1000000,
        }
        pid=self.lake.add_plan(body)
        write_json(self.lake.base/"active-plan.json",{"plan_id":pid})
        core={
            "format":POLICY_FORMAT,"plan_id":pid,
            "lifecycle_bounds":{s:{"listed":"2020-01-01","delisted":None} for s in symbols},
            "family_market_history_floors":{},"request_interval_seconds":.35,
        }
        policy={**core,"policy_id":digest(core)}
        write_json(self.lake.base/SCHEDULER_POLICY,policy)
        cluster_id="c"*64
        assignments=[make_assignment(body,pid,policy["policy_id"],cluster_id,shard_count,i,f"worker{i}")
                     for i in range(shard_count)]
        cluster=sealed({
            "format":"tdx-distributed-cluster-v1","cluster_id":cluster_id,"plan_id":pid,
            "policy_id":policy["policy_id"],"shard_algorithm":"sha256-utf8-symbol-mod-v1",
            "shard_count":shard_count,"assignments":assignments,"history_complete":False,
        })
        role=sealed({"role":"coordinator","cluster":cluster,"created_at":"2026-01-04T00:00:00+00:00"})
        write_json(self.lake.base/ROLE_FILE,role)
        return pid

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
        spec=json.loads((Path(__file__).parents[1]/"docs/reference/retail-microstructure-v2.0.2.json").read_text())
        cfg=RetailMicrostructureConfig()
        gate=spec["coverage_gate"]
        self.assertEqual(spec["source"]["qualification"],QUALIFICATION)
        self.assertEqual(gate["small_order_quantile"],cfg.small_order_quantile)
        self.assertEqual(gate["min_qualified_days"],cfg.min_qualified_days)
        self.assertEqual(gate["min_symbols_per_day"],cfg.min_symbols_per_day)
        self.assertEqual(gate["relative_full_market_ratio"],cfg.relative_full_market_ratio)
        self.assertTrue(gate["require_every_distributed_shard"])

    def test_coverage_rejects_missing_distributed_shard_even_when_total_floor_is_met(self):
        buckets={0:[],1:[]}
        for i in range(100):
            symbol=f"sh.60{i:04d}"
            buckets[shard_for(symbol,2)].append(symbol)
            if all(len(v)>=3 for v in buckets.values()):
                break
        symbols=tuple(buckets[0][:3]+buckets[1][:3])
        self.install_contract(symbols,2,("2026-01-03",))
        con=duckdb.connect(str(self.root/"catalog/mqc.duckdb"))
        rows=[
            (f"{100+i:064x}",0,"2026-01-03",symbol,10.0,1.0,"lots_provider",QUALIFICATION,
             json.dumps({"side":"buy","order_count":1}))
            for i,symbol in enumerate(buckets[0][:3])
        ]
        con.executemany(
            """INSERT INTO tdx_trades_compacted
               (source_id,record_index,date,code,price,volume,volume_unit,qualification,record_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",rows)
        con.close()
        svc=TdxRetailMicrostructure(
            self.root,
            RetailMicrostructureConfig(min_qualified_days=20,min_symbols_per_day=3,relative_full_market_ratio=.9),
        )
        c=svc.coverage(date(2026,1,3),date(2026,1,3))
        self.assertEqual(c["by_day"][0]["feature_symbols"],3)
        self.assertEqual(c["by_day"][0]["feature_symbols_by_shard"],{"0":3,"1":0})
        self.assertEqual(c["by_day"][0]["required_symbols_by_shard"],{"0":3,"1":3})
        self.assertFalse(c["by_day"][0]["qualified"])
        self.assertEqual(c["qualified_days"],0)

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
