import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from quantlab.agent.tdx_collection_cli import POLICY_FORMAT,SCHEDULER_POLICY
from quantlab.data.tdx_lake import TdxLake,digest,write_json
from scripts.research.retail_trades_backfill_plan import (
    _current_feature_coverage,_eligible,build_plan,
)
from scripts.research.retail_trades_phasea_scope import (
    PHASEA_EXCLUDED, proposed_phasea_scope,
)


class RetailTradesBackfillPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.canonical=base/"canonical"
        self.worker=base/"worker"
        self.canonical.mkdir()
        self.worker.mkdir()
        (self.canonical/"catalog").mkdir()
        con=duckdb.connect(str(self.canonical/"catalog/mqc.duckdb"))
        con.execute("""CREATE TABLE tdx_trades_compacted(
            date DATE,code VARCHAR,price DOUBLE,volume DOUBLE,record_json VARCHAR
        )""")
        con.executemany(
            "INSERT INTO tdx_trades_compacted VALUES (?,?,?,?,?)",
            [
                ("2026-01-24","sh.600000",10,1,json.dumps({"side":"buy"})),
                ("2026-01-24","sz.000001",11,1,json.dumps({"side":"sell"})),
                ("2026-01-25","sh.600000",10,0,json.dumps({"side":"buy"})),
            ],
        )
        con.close()

        lake=TdxLake(self.worker,create=True)
        days=[f"2026-01-{i:02d}" for i in range(1,26)]
        symbols=("sh.600000","sz.000001","sh.600001","sz.000002","sh.600002","sz.000003")
        body={
            "format":"tdx-personal-collection-v1",
            "history_end":days[-1],
            "history_start":days[0],
            "trading_days":days,
            "symbols":list(symbols),
            "max_offset":1000000,
        }
        self.pid=lake.add_plan(body)
        write_json(lake.base/"active-plan.json",{"plan_id":self.pid})
        core={
            "format":POLICY_FORMAT,
            "plan_id":self.pid,
            "created_at":"2026-01-26T00:00:00+00:00",
            "qualification":"scheduler_optimization_only_not_pit",
            "lifecycle_bounds":{
                "sh.600000":{"listed":"2020-01-01","delisted":None},
                "sz.000001":{"listed":"2020-01-01","delisted":None},
                "sh.600001":{"listed":"2026-01-10","delisted":None},
                "sz.000002":{"listed":"2020-01-01","delisted":"2026-01-20"},
                "sh.600002":{"listed":"2020-01-01","delisted":None},
                "sz.000003":{"listed":"2020-01-01","delisted":None},
            },
            "lifecycle_known":6,
            "lifecycle_unknown":[],
            "lifecycle_sources":{},
            "family_market_history_floors":{},
            "auction_retention_evidence":None,
            "rate_benchmark_evidence":None,
            "request_interval_seconds":0.35,
            "request_estimate":{},
            "limitations":[],
        }
        policy={**core,"policy_id":digest(core)}
        write_json(lake.base/SCHEDULER_POLICY,policy)

    def test_batch_coverage_and_lifecycle(self):
        coverage=_current_feature_coverage(self.canonical,("2026-01-23","2026-01-24","2026-01-25"))
        self.assertEqual(coverage,{"2026-01-23":0,"2026-01-24":2,"2026-01-25":0})
        policy=json.loads((self.worker/"lake/bronze/provider=tdx"/SCHEDULER_POLICY).read_text())
        self.assertFalse(_eligible(policy,"sh.600001","2026-01-09"))
        self.assertTrue(_eligible(policy,"sh.600001","2026-01-10"))
        self.assertTrue(_eligible(policy,"sz.000002","2026-01-20"))
        self.assertFalse(_eligible(policy,"sz.000002","2026-01-21"))

    def test_phasea_scope_is_explicit_and_does_not_inherit_worker_scope(self):
        scope=proposed_phasea_scope(self.pid,"2026-01-10")
        self.assertEqual(tuple(scope["excluded_families"]),PHASEA_EXCLUDED)
        self.assertNotIn("trades",scope["excluded_families"])
        self.assertEqual(scope["family_history_floors"],{
            "trades":{"sh":"2026-01-10","sz":"2026-01-10","bj":"2026-01-10"}})

    def test_build_plan_is_dry_run_and_lifecycle_bounded(self):
        queue=self.worker/"catalog/tdx_ingestion.sqlite3"
        before=queue.read_bytes()
        result=build_plan(self.canonical,self.worker,20,3)
        after=queue.read_bytes()
        self.assertEqual(before,after)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["network_accessed"])
        self.assertFalse(result["queue_modified"])
        self.assertFalse(result["scope_modified"])
        self.assertFalse(result["stop_modified"])
        self.assertEqual(result["history_start"],"2026-01-06")
        self.assertEqual(result["history_end"],"2026-01-25")
        self.assertEqual(sum(result["eligible_symbol_days_by_shard"].values()),result["eligible_symbol_days_total"])
        # 6 symbols * 20 days = 120, minus 4 pre-listing days for sh.600001
        # and 5 post-delisting days for sz.000002.
        self.assertEqual(result["eligible_symbol_days_total"],111)
        self.assertEqual(result["current_feature_symbols_by_target_day"]["2026-01-24"],2)
        self.assertEqual(result["current_days_at_least_3000_feature_symbols"],0)


if __name__=="__main__":
    unittest.main()
