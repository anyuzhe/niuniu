import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import duckdb

from quantlab.agent.tdx_collection_cli import (
    COLLECTION_SCOPE,POLICY_FORMAT,SCHEDULER_POLICY,SCOPE_FORMAT,apply_collection_scope,
)
from quantlab.agent.tdx_storage import compact_storage
from quantlab.data.tdx_lake import FAMILIES,TdxLake,digest,write_json
from quantlab.data.tdx_sharding import ROLE_FILE,make_assignment,sealed
from scripts.research.retail_trades_backfill_plan import (
    _current_feature_coverage,_eligible,build_plan,
)
from scripts.research.retail_trades_phasea_scope import (
    PHASEA_EXCLUDED,apply_reviewed_scope,build_preview,proposed_phasea_scope,
)
from scripts.research.retail_trades_mac_serial import (
    ELTDX_WHEEL_SHA256,LOCAL_RUNTIME_ERROR,MISSING_PRECEDING_BYTES_ERROR,
    repair_local_runtime_errors,repair_missing_preceding_archives,
    run_worker_batch,verified_eltdx_runtime,
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

    def prepare_phasea_worker(self):
        lake=TdxLake(self.worker)
        plan=lake.plan(self.pid)
        policy=json.loads((lake.base/SCHEDULER_POLICY).read_text())
        assignment=make_assignment(plan,self.pid,policy["policy_id"],"a"*64,1,0,"testworker")
        role=sealed({"role":"worker","assignment":assignment,"created_at":"2026-01-26T00:00:00+00:00"})
        write_json(lake.base/ROLE_FILE,role)
        (lake.base/"STOP").write_text("test stop\n")
        job_id=lake.enqueue(self.pid,"trades","sh.600000","2026-01-25",0,priority=100)
        old_core={"format":SCOPE_FORMAT,"plan_id":self.pid,"excluded_families":["trades"],
                  "family_history_floors":{},"history_complete":False}
        old={**old_core,"scope_id":digest(old_core)}
        write_json(lake.base/COLLECTION_SCOPE,old)
        apply_collection_scope(lake,self.pid,old)
        return lake,job_id,old

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
        self.assertEqual(set(scope["excluded_families"]),set(FAMILIES)-{"trades"})
        self.assertEqual(scope["family_history_floors"],{
            "trades":{"sh":"2026-01-10","sz":"2026-01-10","bj":"2026-01-10"}})

    def test_reviewed_apply_writes_scope_restores_queue_and_keeps_stop(self):
        lake,job_id,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        self.assertEqual(preview["current_scope_id"],old["scope_id"])
        self.assertEqual(preview["restore_scope_skipped_trade_seeds"],1)
        self.assertEqual(preview["inflight_jobs"],0)
        receipt=apply_reviewed_scope(
            self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
            old["scope_id"],preview["queue_snapshot"])
        self.assertEqual(receipt["queue_rows_changed"],1)
        self.assertTrue(receipt["stop_exists"])
        self.assertFalse(receipt["network_accessed"])
        self.assertFalse(receipt["resume_performed"])
        current=json.loads((lake.base/COLLECTION_SCOPE).read_text())
        self.assertEqual(current["scope_id"],preview["proposed_scope"]["scope_id"])
        with lake.db(readonly=True) as con:
            state=con.execute("SELECT state FROM jobs WHERE job_id=?",(job_id,)).fetchone()[0]
        self.assertEqual(state,"PENDING")
        self.assertTrue((lake.base/"STOP").exists())
        self.assertTrue((lake.base/"retail-phasea-scope-receipt.json").is_file())

    def test_reviewed_apply_rejects_stale_queue_snapshot_without_scope_change(self):
        lake,_,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        lake.enqueue(self.pid,"trades","sz.000001","2026-01-24",0,priority=100)
        with self.assertRaisesRegex(ValueError,"queue changed"):
            apply_reviewed_scope(
                self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
                old["scope_id"],preview["queue_snapshot"])
        current=json.loads((lake.base/COLLECTION_SCOPE).read_text())
        self.assertEqual(current["scope_id"],old["scope_id"])
        self.assertTrue((lake.base/"STOP").exists())

    def test_reviewed_apply_rejects_stale_excluded_family_queue_change(self):
        lake,_,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        lake.enqueue(self.pid,"bars_daily","sh.600000","2026-01-24",0,priority=100)
        with self.assertRaisesRegex(ValueError,"queue changed"):
            apply_reviewed_scope(
                self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
                old["scope_id"],preview["queue_snapshot"])
        current=json.loads((lake.base/COLLECTION_SCOPE).read_text())
        self.assertEqual(current["scope_id"],old["scope_id"])
        self.assertTrue((lake.base/"STOP").exists())

    def test_mac_serial_batch_restores_stop_after_success(self):
        lake,_,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        apply_reviewed_scope(
            self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
            old["scope_id"],preview["queue_snapshot"])

        class FakeRunner:
            def __init__(self,lake,pid,*args,**kwargs):
                self.lake=lake;self.pid=pid
            def run(self,seconds,max_requests,max_new_gib):
                self.assert_stop_absent = not (self.lake.base/"STOP").exists()
                if not self.assert_stop_absent:
                    raise AssertionError("STOP must be removed only during bounded batch")
                return {"state":"STOPPED","stop_reason":"REQUEST_BUDGET","processed_this_run":1,
                        "shard_id":0,"full_history_complete":False}

        with patch("scripts.research.retail_trades_mac_serial.Runner",FakeRunner):
            result=run_worker_batch(self.worker,"2026-01-10",10,1,1,network_workers=1)
        self.assertEqual(result["result"]["processed_this_run"],1)
        self.assertTrue((lake.base/"STOP").exists())

    def test_mac_serial_batch_restores_stop_after_failure(self):
        lake,_,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        apply_reviewed_scope(
            self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
            old["scope_id"],preview["queue_snapshot"])

        class BrokenRunner:
            def __init__(self,*args,**kwargs): pass
            def run(self,*args,**kwargs): raise RuntimeError("synthetic runner failure")

        with patch("scripts.research.retail_trades_mac_serial.Runner",BrokenRunner):
            with self.assertRaisesRegex(RuntimeError,"synthetic runner failure"):
                run_worker_batch(self.worker,"2026-01-10",10,1,1,network_workers=1)
        self.assertTrue((lake.base/"STOP").exists())

    def test_verified_runtime_manifest_and_activation(self):
        data=Path(self.tmp.name)/"runtime-data"
        runtime=data/"automation/tdx/runtime-3.2.2"
        runtime.mkdir(parents=True)
        files={
            "eltdx/__init__.py":b"",
            "eltdx/_native.abi3.so":b"synthetic-native",
            "eltdx-3.2.2.dist-info/METADATA":(
                b"Metadata-Version: 2.1\nName: eltdx\nVersion: 3.2.2\n"),
            "eltdx-3.2.2.dist-info/RECORD":b"",
        }
        inventory={}
        for relative,payload in files.items():
            path=runtime/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(payload)
            inventory[relative]=hashlib.sha256(payload).hexdigest()
        manifest={
            "distribution":"eltdx==3.2.2",
            "personal_research_only":True,
            "default_application_dependency":False,
            "wheel_sha256":ELTDX_WHEEL_SHA256,
            "files":inventory,
        }
        manifest_path=data/"automation/tdx/runtime-manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        result=verified_eltdx_runtime(data,activate=True)
        self.assertEqual(result["distribution"],"eltdx==3.2.2")
        self.assertEqual(result["files_checked"],4)
        self.assertTrue(result["activated"])
        runtime_text=str(runtime.resolve())
        self.addCleanup(lambda: sys.path.remove(runtime_text) if runtime_text in sys.path else None)
        self.addCleanup(lambda: sys.modules.pop("eltdx",None))

    def test_runtime_error_repair_is_exact_and_preserves_protocol_error(self):
        lake,job_id,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        apply_reviewed_scope(
            self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
            old["scope_id"],preview["queue_snapshot"])
        protocol_id=lake.enqueue(
            self.pid,"trades","sz.000001","2026-01-24",0,priority=100)
        with lake.db() as con:
            con.execute(
                "UPDATE jobs SET state='ERROR',error=? WHERE job_id=?",
                (LOCAL_RUNTIME_ERROR,job_id))
            con.execute(
                "UPDATE jobs SET state='ERROR',error=? WHERE job_id=?",
                ("ProtocolError: invalid historical ticks payload",protocol_id))
            con.commit()
        result=repair_local_runtime_errors(self.worker,"2026-01-10")
        self.assertEqual(result["repaired"],1)
        self.assertTrue(result["stop_exists"])
        with lake.db(readonly=True) as con:
            rows={r["job_id"]:dict(r) for r in con.execute(
                "SELECT * FROM jobs WHERE job_id IN (?,?)",(job_id,protocol_id))}
            audit=con.execute(
                "SELECT count(*) FROM retail_phasea_runtime_repair_audit").fetchone()[0]
        self.assertEqual(rows[job_id]["state"],"PENDING")
        self.assertIsNone(rows[job_id]["error"])
        self.assertEqual(rows[protocol_id]["state"],"ERROR")
        self.assertEqual(rows[protocol_id]["error"],"ProtocolError: invalid historical ticks payload")
        self.assertEqual(audit,1)

    def test_missing_preceding_archive_repair_restores_exact_canonical_page(self):
        worker,job_id,old=self.prepare_phasea_worker()
        preview=build_preview(self.worker,"2026-01-10")
        apply_reviewed_scope(
            self.worker,"2026-01-10",preview["proposed_scope"]["scope_id"],
            old["scope_id"],preview["queue_snapshot"])
        with worker.db(readonly=True) as con:
            previous=dict(con.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone())
        packet={
            "exchange":"sh","code":"600000","trading_date":"2026-01-25",
            "ticks":[{"trade_datetime":"2026-01-25T09:30:00","event_kind":"trade",
                      "side":"buy","price":10.0,"volume":2,"order_count":1}],
        }
        roomy=SimpleNamespace(free=100*1024**3)
        with patch("quantlab.data.tdx_lake.shutil.disk_usage",return_value=roomy):
            manifest,_=worker.save_page(previous,packet,observed_at="2026-01-26T00:00:00+00:00")
        sid=manifest["source_id"]

        canonical_root=Path(self.tmp.name)/"archive-canonical"
        canonical_root.mkdir()
        canonical=TdxLake(canonical_root,create=True)
        plan=worker.plan(self.pid)
        self.assertEqual(canonical.add_plan(plan),self.pid)
        write_json(canonical.base/"active-plan.json",{"plan_id":self.pid})
        policy=json.loads((worker.base/SCHEDULER_POLICY).read_text())
        write_json(canonical.base/SCHEDULER_POLICY,policy)
        role=json.loads((worker.base/ROLE_FILE).read_text())
        assignment=role["assignment"]
        cluster=sealed({
            "format":"tdx-distributed-cluster-v1","cluster_id":assignment["cluster_id"],
            "plan_id":self.pid,"policy_id":policy["policy_id"],
            "shard_algorithm":"sha256-utf8-symbol-mod-v1","shard_count":1,
            "assignments":[assignment],"history_complete":False,
        })
        write_json(canonical.base/ROLE_FILE,sealed({
            "role":"coordinator","cluster":cluster,"created_at":"2026-01-26T00:00:00+00:00"}))
        canonical.enqueue(self.pid,"trades","sh.600000","2026-01-25",0,priority=100)
        with canonical.db(readonly=True) as con:
            cjob=dict(con.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone())
        with patch("quantlab.data.tdx_lake.shutil.disk_usage",return_value=roomy):
            cmanifest,_=canonical.save_page(cjob,packet,observed_at="2026-01-26T00:00:00+00:00")
        self.assertEqual(cmanifest["source_id"],sid)
        (canonical.base/"STOP").write_text("test stop\n")
        with patch("quantlab.agent.tdx_storage.shutil.disk_usage",return_value=roomy):
            self.assertEqual(compact_storage(canonical,families=("trades",),batch_pages=10)["compacted_pages"],1)
        self.assertIsNone(canonical.page_source("trades",sid).folder)

        worker_folder=worker.page_source("trades",sid).folder
        self.assertIsNotNone(worker_folder)
        shutil.rmtree(worker_folder)
        with self.assertRaisesRegex(ValueError,"page bytes not found"):
            worker.page_source("trades",sid,previous["chunk"])

        failed_id=worker.enqueue(self.pid,"trades","sh.600000","2026-01-25",1,priority=100)
        with worker.db() as con:
            con.execute("UPDATE jobs SET state='ERROR',error=? WHERE job_id=?",
                        (MISSING_PRECEDING_BYTES_ERROR,failed_id))
            con.commit()
        result=repair_missing_preceding_archives(self.worker,canonical_root,"2026-01-10")
        self.assertEqual(result["repaired"],1)
        self.assertEqual(result["pages"][0]["source_id"],sid)
        restored=worker.page_source("trades",sid,previous["chunk"])
        self.assertIsNone(restored.folder)
        self.assertEqual(restored.verify(),canonical.page_source("trades",sid).verify())
        with worker.db(readonly=True) as con:
            failed=dict(con.execute("SELECT * FROM jobs WHERE job_id=?",(failed_id,)).fetchone())
            audit=con.execute("SELECT count(*) FROM retail_phasea_archive_restore_audit").fetchone()[0]
        self.assertEqual(failed["state"],"PENDING")
        self.assertIsNone(failed["error"])
        self.assertEqual(audit,1)
        self.assertTrue((worker.base/"STOP").exists())

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
