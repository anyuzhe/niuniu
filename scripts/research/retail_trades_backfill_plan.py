#!/usr/bin/env python3
"""Dry-run planner for Retail Microstructure V2 TDX trade backfill.

Reads the existing TDX personal-research plan, scheduler lifecycle policy,
current canonical trade coverage and the frozen 3-shard algorithm. It never
edits queues/scopes/STOP files and never accesses the network.
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from quantlab.agent.tdx_collection_cli import load_scheduler_policy
from quantlab.data.tdx_lake import TdxLake
from quantlab.data.tdx_sharding import shard_for
from quantlab.storage.codec import digest,encode


def _active_plan_id(lake):
    path=lake.base/"active-plan.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Active TDX plan is unavailable")
    value=json.loads(path.read_text())
    pid=value.get("plan_id")
    if not isinstance(pid,str):
        raise ValueError("Invalid active TDX plan")
    return pid


def _eligible(policy,symbol,day):
    row=(policy.get("lifecycle_bounds") or {}).get(symbol,{})
    listed=row.get("listed")
    delisted=row.get("delisted")
    return (not listed or day>=listed) and (not delisted or day<=delisted)


def _current_feature_coverage(canonical_root,days):
    days=tuple(days)
    if not days:
        return {}
    db=Path(canonical_root)/"catalog/mqc.duckdb"
    import duckdb
    marks=",".join("?" for _ in days)
    with duckdb.connect(str(db),read_only=True) as con:
        rows=con.execute(f"""
          SELECT date,count(DISTINCT code)
          FROM tdx_trades_compacted
          WHERE date IN ({marks})
            AND json_extract_string(record_json,'$.side') IN ('buy','sell')
            AND price>0 AND volume>0
          GROUP BY date
        """,[date.fromisoformat(d) for d in days]).fetchall()
    found={row[0].isoformat():row[1] for row in rows}
    return {d:found.get(d,0) for d in days}


def _trade_jobs(root):
    db=Path(root)/"catalog/tdx_ingestion.sqlite3"
    if not db.is_file():
        return {}
    con=sqlite3.connect(str(db));con.row_factory=sqlite3.Row
    rows=con.execute("""
      SELECT day,state,count(*) n,count(DISTINCT symbol) symbols
      FROM jobs WHERE family='trades' GROUP BY day,state
    """).fetchall()
    con.close()
    out={}
    for row in rows:
        out.setdefault(row["day"],{})[row["state"]]={"jobs":row["n"],"symbols":row["symbols"]}
    return out


def build_plan(canonical_root,worker0_root,days_required=120,shard_count=3):
    if type(days_required) is not int or not 20<=days_required<=500:
        raise ValueError("days_required must be 20..500")
    if type(shard_count) is not int or not 1<=shard_count<=32:
        raise ValueError("invalid shard_count")
    worker=TdxLake(worker0_root)
    pid=_active_plan_id(worker)
    plan=worker.plan(pid)
    policy=load_scheduler_policy(worker,pid)
    days=list(plan["trading_days"])
    end=plan["history_end"]
    days=[d for d in days if d<=end]
    if len(days)<days_required:
        raise ValueError("TDX plan calendar is shorter than requested backfill")
    target_days=days[-days_required:]
    symbols=tuple(plan["symbols"])

    per_shard={i:Counter() for i in range(shard_count)}
    per_day={}
    total=0
    for d in target_days:
        row=Counter()
        for symbol in symbols:
            if not _eligible(policy,symbol,d):
                continue
            sid=shard_for(symbol,shard_count)
            row[sid]+=1
            per_shard[sid]["symbol_days"]+=1
            total+=1
        per_day[d]={str(k):v for k,v in sorted(row.items())}

    feature_coverage=_current_feature_coverage(canonical_root,target_days)
    current_full_days=sum(v>=3000 for v in feature_coverage.values())
    jobs_by_root={
        "canonical":_trade_jobs(canonical_root),
        "worker0":_trade_jobs(worker0_root),
    }

    # Optional page multiplier estimate from the latest near-full canonical day.
    latest=target_days[-1]
    page_multiplier=None
    qdb=Path(canonical_root)/"catalog/tdx_ingestion.sqlite3"
    if qdb.is_file():
        con=sqlite3.connect(str(qdb));con.row_factory=sqlite3.Row
        try:
            sample=con.execute("""
              SELECT count(*) jobs,count(DISTINCT symbol) symbols
              FROM jobs WHERE family='trades' AND day=? AND state IN ('SAVED','EMPTY','ERROR')
            """,(latest,)).fetchone()
        except sqlite3.OperationalError:
            sample=None
        finally:
            con.close()
        if sample and sample["symbols"]:
            page_multiplier=sample["jobs"]/sample["symbols"]

    result={
        "format":"niuniu-retail-trades-backfill-plan-v1",
        "dry_run":True,
        "network_accessed":False,
        "queue_modified":False,
        "scope_modified":False,
        "stop_modified":False,
        "plan_id":pid,
        "scheduler_policy_id":policy.get("policy_id"),
        "history_start":target_days[0],
        "history_end":target_days[-1],
        "target_days":target_days,
        "days_required":days_required,
        "symbols_in_plan":len(symbols),
        "shard_count":shard_count,
        "eligible_symbol_days_total":total,
        "eligible_symbol_days_by_shard":{str(i):per_shard[i]["symbol_days"] for i in range(shard_count)},
        "eligible_symbols_latest_day_by_shard":per_day[target_days[-1]],
        "current_feature_symbols_by_target_day":feature_coverage,
        "current_days_at_least_3000_feature_symbols":current_full_days,
        "remaining_days_to_120_floor":max(0,days_required-current_full_days),
        "observed_latest_day_job_page_multiplier":page_multiplier,
        "estimated_top_level_symbol_day_requests":total,
        "estimated_page_requests_using_latest_multiplier":round(total*page_multiplier) if page_multiplier else None,
        "existing_trade_job_summary":jobs_by_root,
        "execution_note":"This plan is audit-only. Enabling trade backfill requires a separate reviewed collection-scope change and explicit resume; this planner performs neither.",
        "limitations":[
            "Existing canonical coverage uses only currently merged data; offline worker data not yet imported may reduce future gaps.",
            "Page multiplier is a rough estimate from the latest day and can vary substantially by stock liquidity.",
            "Lifecycle dates are retrospective acquisition bounds and are not PIT universe evidence.",
            "A 120-day collection window is a research minimum chosen by Retail Microstructure V2, not proof of statistical sufficiency."
        ],
    }
    result["plan_digest"]=digest(result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--canonical-root",type=Path,required=True)
    p.add_argument("--worker0-root",type=Path,required=True)
    p.add_argument("--days",type=int,default=120)
    p.add_argument("--output",type=Path)
    a=p.parse_args(argv)
    result=build_plan(a.canonical_root,a.worker0_root,a.days)
    if a.output:
        out=a.output.resolve()
        out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists():
            raise ValueError("output already exists")
        out.write_text(encode(result))
    print(encode(result))


if __name__=="__main__":
    main()
