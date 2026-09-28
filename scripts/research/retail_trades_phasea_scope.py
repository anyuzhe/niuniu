#!/usr/bin/env python3
"""Dry-run Retail Microstructure V2 Phase-A collection-scope migration."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from quantlab.agent.tdx_collection_cli import (
    SCOPE_FORMAT,_scope_job_decision,load_collection_scope,load_scheduler_policy,
    validate_collection_scope,
)
from quantlab.data.tdx_lake import TdxLake,digest
from quantlab.data.tdx_sharding import read_role
from quantlab.storage.codec import encode


def build_preview(worker_root,floor):
    lake=TdxLake(worker_root)
    active=json.loads((lake.base/"active-plan.json").read_text())
    pid=active["plan_id"]
    plan=lake.plan(pid)
    if floor not in plan["trading_days"]:
        raise ValueError("Phase-A floor must be an exact trading day from the frozen TDX plan")
    current=load_collection_scope(lake,pid)
    policy=load_scheduler_policy(lake,pid)
    role=read_role(lake)
    if role is None or role.get("role")!="worker":
        raise ValueError("Phase-A preview requires a distributed worker root")
    assignment=role["assignment"]
    if assignment["policy_id"]!=policy.get("policy_id"):
        raise ValueError("Worker assignment/policy mismatch before Phase-A preview")

    excluded=sorted(f for f in current.get("excluded_families",[]) if f!="trades")
    floors=dict(current.get("family_history_floors",{}) or {})
    floors["trades"]={"sh":floor,"sz":floor,"bj":floor}
    core={
        "format":SCOPE_FORMAT,
        "plan_id":pid,
        "excluded_families":excluded,
        "family_history_floors":floors,
        "history_complete":False,
        "reason":"Retail Microstructure V2 Phase-A trades-only backfill; keep K-lines and standalone opening_match excluded",
    }
    proposed=validate_collection_scope({**core,"scope_id":digest(core)},pid)

    con=sqlite3.connect(str(lake.queue));con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute("""
      SELECT * FROM jobs
      WHERE plan_id=? AND family='trades' AND state IN ('PENDING','SKIPPED_POLICY','ERROR')
      ORDER BY job_id
    """,(pid,))]
    con.close()

    restore=[];skip=[];untouched_errors=0
    for job in rows:
        if job["state"]=="ERROR":
            untouched_errors+=1
            continue
        allowed,reason=_scope_job_decision(proposed,job)
        if job["state"]=="SKIPPED_POLICY" and (
            str(job.get("error") or "").startswith("Excluded by collection scope ")
            or str(job.get("error") or "").startswith("Outside collection history floor ")
        ) and allowed:
            restore.append(job)
        elif job["state"]=="PENDING" and not allowed:
            skip.append({**job,"proposed_reason":reason})

    return {
        "format":"niuniu-retail-trades-phasea-scope-preview-v1",
        "dry_run":True,
        "network_accessed":False,
        "scope_written":False,
        "queue_modified":False,
        "stop_modified":False,
        "worker_root":str(Path(worker_root).resolve()),
        "plan_id":pid,
        "scheduler_policy_id":policy.get("policy_id"),
        "assignment_id":assignment["assignment_id"],
        "shard_id":assignment["shard_id"],
        "machine_name":assignment["machine_name"],
        "stop_exists":(lake.base/"STOP").exists(),
        "current_scope":current,
        "proposed_scope":proposed,
        "phasea_floor":floor,
        "restore_scope_skipped_trade_seeds":len(restore),
        "skip_pending_below_floor":len(skip),
        "untouched_trade_errors":untouched_errors,
        "restore_sample":[{k:j[k] for k in ("job_id","symbol","day","state")} for j in restore[:12]],
        "skip_sample":[{k:j[k] for k in ("job_id","symbol","day","state","proposed_reason")} for j in skip[:12]],
        "notes":[
            "Scheduler policy and distributed assignment remain byte/identity compatible because only collection scope changes.",
            "Standalone opening_match remains excluded; exact opening-match rows may still be derived locally from fetched trade pages without an extra network request.",
            "ERROR trade jobs are not retried or relabeled by the scope migration.",
            "Actual collection still requires separately writing the reviewed scope on every worker and an explicit resume."
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--worker-root",type=Path,required=True)
    p.add_argument("--floor",required=True)
    p.add_argument("--output",type=Path)
    a=p.parse_args(argv)
    value=build_preview(a.worker_root,a.floor)
    if a.output:
        target=a.output.resolve()
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise ValueError("output already exists")
        target.write_text(encode(value))
    print(encode(value))


if __name__=="__main__":
    main()
