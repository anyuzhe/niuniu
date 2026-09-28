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
    COLLECTION_SCOPE,SCOPE_FORMAT,_scope_job_decision,apply_collection_scope,
    load_collection_scope,load_scheduler_policy,validate_collection_scope,writer_lease,
)
from quantlab.data.tdx_lake import TdxLake,digest,write_json
from quantlab.data.tdx_sharding import read_role
from quantlab.storage.codec import encode


PHASEA_EXCLUDED=("bars_1m","bars_5m","bars_daily","opening_match")


def proposed_phasea_scope(pid,floor):
    core={
        "format":SCOPE_FORMAT,
        "plan_id":pid,
        "excluded_families":list(PHASEA_EXCLUDED),
        "family_history_floors":{"trades":{"sh":floor,"sz":floor,"bj":floor}},
        "history_complete":False,
        "reason":"Retail Microstructure V2 Phase-A trades-only backfill; keep K-lines and standalone opening_match excluded",
    }
    return validate_collection_scope({**core,"scope_id":digest(core)},pid)


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

    proposed=proposed_phasea_scope(pid,floor)

    con=sqlite3.connect(str(lake.queue));con.row_factory=sqlite3.Row
    trade_rows=[dict(r) for r in con.execute("""
      SELECT * FROM jobs
      WHERE plan_id=? AND family='trades' AND state IN ('PENDING','SKIPPED_POLICY','ERROR')
      ORDER BY job_id
    """,(pid,))]
    affected_families=sorted(set(proposed["excluded_families"])|set(proposed.get("family_history_floors",{})))
    marks=",".join("?" for _ in affected_families)
    scope_rows=[dict(r) for r in con.execute(
        "SELECT * FROM jobs WHERE plan_id=? AND family IN ("+marks+") "
        "AND state IN ('PENDING','SKIPPED_POLICY') ORDER BY job_id",
        (pid,*affected_families))]
    inflight=con.execute(
        "SELECT count(*) FROM jobs WHERE plan_id=? AND state IN ('RUNNING','STORED')",(pid,)
    ).fetchone()[0]
    con.close()
    queue_snapshot=digest(scope_rows)

    restore=[];skip=[];untouched_errors=0
    for job in trade_rows:
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
        "current_scope_id":current.get("scope_id"),
        "proposed_scope":proposed,
        "phasea_floor":floor,
        "queue_snapshot":queue_snapshot,
        "queue_snapshot_families":affected_families,
        "queue_snapshot_rows":len(scope_rows),
        "inflight_jobs":inflight,
        "restore_scope_skipped_trade_seeds":len(restore),
        "skip_pending_below_floor":len(skip),
        "untouched_trade_errors":untouched_errors,
        "restore_sample":[{k:j[k] for k in ("job_id","symbol","day","state")} for j in restore[:12]],
        "skip_sample":[{k:j[k] for k in ("job_id","symbol","day","state","proposed_reason")} for j in skip[:12]],
        "notes":[
            "Phase-A exclusions are explicit and identical on every worker; they do not inherit a worker's prior scope.",
            "Scheduler policy and distributed assignment remain byte/identity compatible because only collection scope changes.",
            "Standalone opening_match remains excluded; exact opening-match rows may still be derived locally from fetched trade pages without an extra network request.",
            "ERROR trade jobs are not retried or relabeled by the scope migration.",
            "Actual collection still requires separately writing the reviewed scope on every worker and an explicit resume."
        ],
    }


def apply_reviewed_scope(worker_root,floor,expected_proposed_scope_id,
                         expected_current_scope_id,expected_queue_snapshot):
    lake=TdxLake(worker_root)
    with writer_lease(lake):
        preview=build_preview(worker_root,floor)
        expected_current=None if expected_current_scope_id=="NONE" else expected_current_scope_id
        if preview["proposed_scope"]["scope_id"]!=expected_proposed_scope_id:
            raise ValueError("Phase-A proposed scope changed since review")
        if preview["current_scope_id"]!=expected_current:
            raise ValueError("Phase-A current scope changed since review")
        if preview["queue_snapshot"]!=expected_queue_snapshot:
            raise ValueError("Phase-A scope queue changed since review")
        if not preview["stop_exists"]:
            raise ValueError("Phase-A scope apply requires STOP to remain present")
        if preview["inflight_jobs"]:
            raise ValueError("Phase-A scope apply refuses RUNNING/STORED jobs")

        scope_path=lake.base/COLLECTION_SCOPE
        write_json(scope_path,preview["proposed_scope"])
        changed=apply_collection_scope(lake,preview["plan_id"],preview["proposed_scope"])
        after=build_preview(worker_root,floor)
        if after["current_scope_id"]!=expected_proposed_scope_id:
            raise ValueError("Phase-A scope file did not persist reviewed identity")
        if not after["stop_exists"] or after["inflight_jobs"]:
            raise ValueError("Phase-A safety state changed during scope apply")

        receipt={
            "format":"niuniu-retail-trades-phasea-scope-apply-v1",
            "worker_root":preview["worker_root"],
            "plan_id":preview["plan_id"],
            "scheduler_policy_id":preview["scheduler_policy_id"],
            "assignment_id":preview["assignment_id"],
            "shard_id":preview["shard_id"],
            "machine_name":preview["machine_name"],
            "phasea_floor":floor,
            "before_scope_id":preview["current_scope_id"],
            "applied_scope_id":expected_proposed_scope_id,
            "before_queue_snapshot":preview["queue_snapshot"],
            "after_queue_snapshot":after["queue_snapshot"],
            "queue_rows_changed":changed,
            "stop_exists":after["stop_exists"],
            "stop_modified":False,
            "network_accessed":False,
            "resume_performed":False,
        }
        write_json(lake.base/"retail-phasea-scope-receipt.json",receipt)
        return receipt


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--worker-root",type=Path,required=True)
    p.add_argument("--floor",required=True)
    p.add_argument("--output",type=Path)
    p.add_argument("--apply-reviewed",action="store_true")
    p.add_argument("--expected-proposed-scope-id")
    p.add_argument("--expected-current-scope-id")
    p.add_argument("--expected-queue-snapshot")
    a=p.parse_args(argv)
    if a.apply_reviewed:
        required=(a.expected_proposed_scope_id,a.expected_current_scope_id,a.expected_queue_snapshot)
        if any(v is None for v in required):
            raise ValueError("Reviewed apply requires expected proposed/current scope and queue snapshot")
        value=apply_reviewed_scope(
            a.worker_root,a.floor,a.expected_proposed_scope_id,
            a.expected_current_scope_id,a.expected_queue_snapshot)
    else:
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
