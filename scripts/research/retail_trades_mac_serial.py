#!/usr/bin/env python3
"""Run Retail Microstructure Phase A on one physical Mac using 3 logical TDX shards.

Default is dry-run only. Network access requires both --execute and
--personal-research-only. Every shard starts from STOP and STOP is restored in
finally, including failures.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from quantlab.agent.tdx_collection_cli import (
    AUTO_HALT,Runner,apply_collection_scope,load_collection_scope,
    load_scheduler_policy,recover_for_resume,writer_lease,
)
from quantlab.data.tdx_lake import TdxLake,now
from quantlab.data.tdx_sharding import load_worker_assignment,read_role,validate_worker_queue
from quantlab.storage.codec import encode
from scripts.research.retail_trades_phasea_scope import proposed_phasea_scope


def preflight_worker(worker_root:Path,floor:str,expected_shard:int|None=None):
    lake=TdxLake(worker_root)
    active=json.loads((lake.base/"active-plan.json").read_text())
    pid=active["plan_id"]
    policy=load_scheduler_policy(lake,pid)
    role=read_role(lake)
    if role is None or role.get("role")!="worker":
        raise ValueError("Mac serial Phase-A requires a worker root")
    assignment=load_worker_assignment(lake,pid,policy.get("policy_id"))
    validate_worker_queue(lake,assignment)
    if expected_shard is not None and assignment["shard_id"]!=expected_shard:
        raise ValueError("Mac serial worker shard mismatch")

    scope=load_collection_scope(lake,pid)
    expected_scope=proposed_phasea_scope(pid,floor)
    if scope.get("scope_id")!=expected_scope["scope_id"]:
        raise ValueError("Mac serial worker is not on the reviewed trades-only Phase-A scope")
    if not (lake.base/"STOP").exists():
        raise ValueError("Mac serial preflight requires STOP on every worker")
    if (lake.base/AUTO_HALT).exists():
        raise ValueError("Mac serial worker has AUTO_HALT; review before collection")

    con=sqlite3.connect(str(lake.queue));con.row_factory=sqlite3.Row
    inflight=con.execute(
        "SELECT count(*) FROM jobs WHERE plan_id=? AND state IN ('RUNNING','STORED')",(pid,)
    ).fetchone()[0]
    pending=[dict(r) for r in con.execute(
        "SELECT family,count(*) AS n FROM jobs WHERE plan_id=? AND state='PENDING' "
        "GROUP BY family ORDER BY family",(pid,))]
    trade_errors=con.execute(
        "SELECT count(*) FROM jobs WHERE plan_id=? AND family='trades' AND state='ERROR'",(pid,)
    ).fetchone()[0]
    con.close()
    if inflight:
        raise ValueError("Mac serial worker has RUNNING/STORED jobs")
    if any(row["family"]!="trades" for row in pending):
        raise ValueError("Mac serial Phase-A refuses non-trades PENDING jobs")

    return {
        "worker_root":str(Path(worker_root).resolve()),
        "plan_id":pid,
        "policy_id":policy.get("policy_id"),
        "cluster_id":assignment["cluster_id"],
        "assignment_id":assignment["assignment_id"],
        "machine_name":assignment["machine_name"],
        "shard_id":assignment["shard_id"],
        "shard_count":assignment["shard_count"],
        "symbol_count":assignment["symbol_count"],
        "scope_id":scope["scope_id"],
        "pending":pending,
        "trade_errors":trade_errors,
        "stop":True,
        "inflight":0,
    }


def preflight_serial(workers_base:Path,floor:str,shards=(0,1,2)):
    rows=[preflight_worker(Path(workers_base)/f"worker-{sid}",floor,sid) for sid in shards]
    if len({r["plan_id"] for r in rows})!=1 or len({r["policy_id"] for r in rows})!=1:
        raise ValueError("Mac serial workers do not share plan/policy")
    if len({r["cluster_id"] for r in rows})!=1:
        raise ValueError("Mac serial workers do not share distributed cluster")
    if len({r["scope_id"] for r in rows})!=1:
        raise ValueError("Mac serial workers do not share Phase-A scope")
    counts={r["shard_count"] for r in rows}
    if len(counts)!=1:
        raise ValueError("Mac serial shard_count mismatch")
    count=next(iter(counts))
    if tuple(sorted(shards))!=tuple(range(count)):
        raise ValueError("Mac serial execution must cover every frozen shard")
    if len({r["assignment_id"] for r in rows})!=len(rows):
        raise ValueError("Mac serial duplicate assignment")
    return {
        "format":"niuniu-retail-phasea-mac-serial-preflight-v1",
        "physical_host":"macbook",
        "floor":floor,
        "shards":rows,
        "network_accessed":False,
        "stop_modified":False,
    }


def _pending_nontrades(lake,pid):
    with lake.db(readonly=True) as con:
        return [dict(r) for r in con.execute(
            "SELECT family,count(*) AS n FROM jobs WHERE plan_id=? AND state='PENDING' "
            "AND family!='trades' GROUP BY family ORDER BY family",(pid,))]


def run_worker_batch(worker_root:Path,floor:str,seconds:int,max_requests:int,max_new_gib:int,
                     network_workers:int=2,request_interval:float=.35,max_job_attempts:int=12):
    before=preflight_worker(worker_root,floor)
    lake=TdxLake(worker_root)
    pid=before["plan_id"]
    stop=lake.base/"STOP"
    with writer_lease(lake):
        # Recheck all mutable preconditions under the writer lease.
        locked=preflight_worker(worker_root,floor,before["shard_id"])
        if locked["assignment_id"]!=before["assignment_id"] or locked["scope_id"]!=before["scope_id"]:
            raise ValueError("Mac serial worker identity changed during preflight")
        stop.unlink()
        try:
            recover_for_resume(lake,pid,max_job_attempts)
            scope=load_collection_scope(lake,pid)
            apply_collection_scope(lake,pid,scope)
            extra=_pending_nontrades(lake,pid)
            if extra:
                raise ValueError("Mac serial scope failed to suppress non-trades PENDING jobs")
            runner=Runner(
                lake,pid,network_workers,
                request_retries=3,transient_burst=8,recovery_cycles=6,
                cooldown_seconds=60,max_job_attempts=max_job_attempts,
                request_interval_seconds=request_interval,
            )
            result=runner.run(seconds,max_requests,max_new_gib)
            return {
                "format":"niuniu-retail-phasea-mac-serial-batch-v1",
                "worker_root":before["worker_root"],
                "assignment_id":before["assignment_id"],
                "shard_id":before["shard_id"],
                "scope_id":before["scope_id"],
                "result":result,
            }
        finally:
            stop.write_text(now(),encoding="utf-8")


def run_serial(workers_base:Path,floor:str,shards,seconds,max_requests,max_new_gib,
               network_workers=2,request_interval=.35):
    pre=preflight_serial(workers_base,floor,tuple(shards))
    results=[]
    for row in pre["shards"]:
        batch=run_worker_batch(
            Path(row["worker_root"]),floor,seconds,max_requests,max_new_gib,
            network_workers=network_workers,request_interval=request_interval)
        results.append(batch)
        if batch["result"]["state"]=="HALTED":
            break
    return {
        "format":"niuniu-retail-phasea-mac-serial-run-v1",
        "preflight":pre,
        "batches":results,
        "network_accessed":bool(results),
        "all_stops_restored":all(
            (Path(r["worker_root"])/"lake/bronze/provider=tdx/STOP").exists()
            for r in pre["shards"]),
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--workers-base",type=Path,required=True)
    p.add_argument("--floor",default="2026-08-21")
    p.add_argument("--shards",type=int,nargs="+",default=[0,1,2])
    p.add_argument("--seconds-per-shard",type=int,default=120)
    p.add_argument("--max-requests-per-shard",type=int,default=200)
    p.add_argument("--max-new-gib-per-shard",type=int,default=2)
    p.add_argument("--network-workers",type=int,choices=(1,2),default=2)
    p.add_argument("--request-interval",type=float,default=.35)
    p.add_argument("--execute",action="store_true")
    p.add_argument("--personal-research-only",action="store_true")
    a=p.parse_args(argv)
    if not 10<=a.seconds_per_shard<=86400:
        raise ValueError("seconds-per-shard out of bounds")
    if not 1<=a.max_requests_per_shard<=1000000:
        raise ValueError("max-requests-per-shard out of bounds")
    if not 1<=a.max_new_gib_per_shard<=500:
        raise ValueError("max-new-gib-per-shard out of bounds")
    if not .2<=a.request_interval<=2:
        raise ValueError("request-interval out of bounds")

    if not a.execute:
        print(encode(preflight_serial(a.workers_base,a.floor,tuple(a.shards))))
        return
    if not a.personal_research_only:
        raise ValueError("--execute requires --personal-research-only")
    result=run_serial(
        a.workers_base,a.floor,tuple(a.shards),
        a.seconds_per_shard,a.max_requests_per_shard,a.max_new_gib_per_shard,
        network_workers=a.network_workers,request_interval=a.request_interval)
    print(encode(result))


if __name__=="__main__":
    main()
