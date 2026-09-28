#!/usr/bin/env python3
"""Run Retail Microstructure Phase A on one physical Mac using 3 logical TDX shards.

Default is dry-run only. Network access requires both --execute and
--personal-research-only. Every shard starts from STOP and STOP is restored in
finally, including failures.
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import json
import sqlite3
import sys
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from quantlab.agent.tdx_collection_cli import (
    AUTO_HALT,Runner,apply_collection_scope,load_collection_scope,
    load_scheduler_policy,recover_for_resume,writer_lease,
)
from quantlab.data.tdx_lake import TdxLake,digest,now,rows_for
from quantlab.data.tdx_sharding import load_worker_assignment,read_role,validate_worker_queue
from quantlab.storage.codec import encode
from scripts.research.retail_trades_phasea_scope import proposed_phasea_scope


ELTDX_VERSION="3.2.2"
ELTDX_WHEEL_SHA256="20f0a78dff4b2b7c701d288fe80db9b68b1d2662431b95af62084a45b7780b68"
LOCAL_RUNTIME_ERROR="PackageNotFoundError: No package metadata was found for eltdx"
MISSING_PRECEDING_BYTES_ERROR="ValueError: TDX page bytes not found"


def verified_eltdx_runtime(data_root:Path,*,activate:bool=False):
    data_root=Path(data_root).resolve()
    automation=data_root/"automation/tdx"
    manifest_path=automation/"runtime-manifest.json"
    runtime=automation/f"runtime-{ELTDX_VERSION}"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size>2_000_000:
        raise ValueError("Verified eltdx runtime manifest is unavailable")
    if runtime.is_symlink() or not runtime.is_dir():
        raise ValueError("Verified eltdx runtime directory is unavailable")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("distribution")!=f"eltdx=={ELTDX_VERSION}"
            or manifest.get("personal_research_only") is not True
            or manifest.get("default_application_dependency") is not False
            or manifest.get("wheel_sha256")!=ELTDX_WHEEL_SHA256):
        raise ValueError("Verified eltdx runtime manifest identity mismatch")
    files=manifest.get("files")
    if not isinstance(files,dict) or not files:
        raise ValueError("Verified eltdx runtime manifest file inventory missing")
    required={
        "eltdx/__init__.py","eltdx/_native.abi3.so",
        "eltdx-3.2.2.dist-info/METADATA","eltdx-3.2.2.dist-info/RECORD",
    }
    if not required <= set(files):
        raise ValueError("Verified eltdx runtime manifest omits required runtime files")
    checked=0
    for relative,expected in sorted(files.items()):
        pure=PurePosixPath(relative)
        if pure.is_absolute() or not pure.parts or any(part in ("",".","..") for part in pure.parts):
            raise ValueError("Unsafe eltdx runtime manifest path")
        path=runtime.joinpath(*pure.parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Verified eltdx runtime file missing: "+relative)
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=expected:
            raise ValueError("Verified eltdx runtime file hash mismatch: "+relative)
        checked+=1
    if activate and str(runtime) not in sys.path:
        sys.path.insert(0,str(runtime))
    if activate:
        if importlib.metadata.version("eltdx")!=ELTDX_VERSION:
            raise ValueError("Activated eltdx runtime version mismatch")
        import eltdx
        module=Path(eltdx.__file__).resolve()
        if not module.is_relative_to(runtime):
            raise ValueError("Activated eltdx module escaped verified runtime")
    return {
        "runtime":str(runtime),
        "manifest":str(manifest_path),
        "distribution":manifest["distribution"],
        "wheel_sha256":manifest["wheel_sha256"],
        "files_checked":checked,
        "activated":activate,
    }


def repair_local_runtime_errors(worker_root:Path,floor:str):
    before=preflight_worker(worker_root,floor)
    lake=TdxLake(worker_root)
    with writer_lease(lake):
        locked=preflight_worker(worker_root,floor,before["shard_id"])
        if locked["assignment_id"]!=before["assignment_id"] or locked["scope_id"]!=before["scope_id"]:
            raise ValueError("Mac serial worker identity changed before runtime-error repair")
        with lake.db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS retail_phasea_runtime_repair_audit(
                event_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,before_json TEXT NOT NULL,
                repair_reason TEXT NOT NULL,repaired_at TEXT NOT NULL)""")
            rows=[dict(r) for r in con.execute(
                "SELECT * FROM jobs WHERE plan_id=? AND family='trades' AND state='ERROR' AND error=? ORDER BY job_id",
                (before["plan_id"],LOCAL_RUNTIME_ERROR))]
            for job in rows:
                event_id=hashlib.sha256((job["job_id"]+"|"+LOCAL_RUNTIME_ERROR).encode()).hexdigest()
                con.execute("INSERT OR IGNORE INTO retail_phasea_runtime_repair_audit VALUES (?,?,?,?,?)",
                            (event_id,job["job_id"],encode(job),"verified-runtime-not-loaded",now()))
                con.execute("UPDATE jobs SET state='PENDING',error=NULL,updated_at=? WHERE job_id=? AND state='ERROR' AND error=?",
                            (now(),job["job_id"],LOCAL_RUNTIME_ERROR))
            con.commit()
        return {
            "worker_root":before["worker_root"],
            "shard_id":before["shard_id"],
            "assignment_id":before["assignment_id"],
            "repaired":len(rows),
            "error_exact":LOCAL_RUNTIME_ERROR,
            "stop_exists":(lake.base/"STOP").exists(),
        }


def repair_missing_preceding_archives(worker_root:Path,canonical_root:Path,floor:str):
    before=preflight_worker(worker_root,floor)
    worker=TdxLake(worker_root)
    canonical=TdxLake(canonical_root)
    coordinator_role=read_role(canonical)
    if not coordinator_role or coordinator_role.get("role")!="coordinator":
        raise ValueError("Canonical TDX coordinator role is required for archive repair")
    cluster=coordinator_role.get("cluster") or {}
    if (cluster.get("cluster_id")!=before["cluster_id"]
            or cluster.get("plan_id")!=before["plan_id"]
            or cluster.get("policy_id")!=before["policy_id"]):
        raise ValueError("Canonical coordinator identity differs from worker")
    registered={a.get("assignment_id") for a in cluster.get("assignments",[])}
    if before["assignment_id"] not in registered:
        raise ValueError("Worker assignment is not registered by canonical coordinator")

    repaired=[]
    with writer_lease(worker):
        locked=preflight_worker(worker_root,floor,before["shard_id"])
        if locked["assignment_id"]!=before["assignment_id"] or locked["scope_id"]!=before["scope_id"]:
            raise ValueError("Mac serial worker identity changed before archive repair")
        with worker.db(readonly=True) as con:
            failed=[dict(r) for r in con.execute(
                "SELECT * FROM jobs WHERE plan_id=? AND family='trades' AND state='ERROR' AND error=? ORDER BY job_id",
                (before["plan_id"],MISSING_PRECEDING_BYTES_ERROR))]
        worker.initialize_archive()

        for current in failed:
            if not current["offset"]:
                raise ValueError("Missing-page repair requires a paginated trade job")
            with worker.db(readonly=True) as con:
                previous=con.execute(
                    """SELECT * FROM jobs
                       WHERE plan_id=? AND family=? AND symbol=? AND day=? AND offset<?
                         AND state='SAVED' AND chunk IS NOT NULL
                       ORDER BY offset DESC LIMIT 1""",
                    (current["plan_id"],current["family"],current["symbol"],current["day"],current["offset"])).fetchone()
                publication=con.execute(
                    """SELECT * FROM publications
                       WHERE plan_id=? AND family=? AND symbol=? AND day=?
                       ORDER BY observed_at DESC""",
                    (current["plan_id"],current["family"],current["symbol"],current["day"])).fetchall()
            if previous is None:
                raise ValueError("Missing-page repair found no preceding SAVED job")
            previous=dict(previous)
            if previous["offset"]+previous["rows"]!=current["offset"] or not previous["rows"]:
                raise ValueError("Missing-page repair preceding cursor is not exact")
            sid=PurePosixPath(previous["chunk"].replace("\\","/")).name
            if len(sid)!=64 or any(c not in "0123456789abcdef" for c in sid):
                raise ValueError("Missing-page repair source identity invalid")
            matching=[dict(row) for row in publication if row["source_id"]==sid]
            if len(matching)!=1:
                raise ValueError("Missing-page repair worker publication identity missing")
            worker_pub=matching[0]
            for key in ("plan_id","family","symbol","day","rows","chunk"):
                if worker_pub[key]!=previous[key]:
                    raise ValueError("Missing-page repair worker publication/job mismatch")

            with canonical.db(readonly=True) as con:
                canonical_job=con.execute("SELECT * FROM jobs WHERE job_id=?",(previous["job_id"],)).fetchone()
                canonical_pub=con.execute("SELECT * FROM publications WHERE source_id=?",(sid,)).fetchone()
            if canonical_job is None or canonical_pub is None:
                raise ValueError("Missing-page repair canonical job/publication missing")
            canonical_job=dict(canonical_job);canonical_pub=dict(canonical_pub)
            for key in ("job_id","plan_id","family","symbol","day","offset","rows","chunk"):
                if canonical_job[key]!=previous[key]:
                    raise ValueError("Missing-page repair canonical job mismatch")
            if canonical_job["state"]!="SAVED":
                raise ValueError("Missing-page repair canonical preceding job is not SAVED")
            for key in ("source_id","plan_id","family","symbol","day","rows","chunk"):
                if canonical_pub[key]!=worker_pub[key]:
                    raise ValueError("Missing-page repair canonical publication mismatch")

            with canonical.archive_db(readonly=True) as con:
                archive=con.execute("SELECT * FROM page_archive WHERE source_id=? AND family=?",(sid,current["family"])).fetchone()
            if archive is None:
                raise ValueError("Missing-page repair canonical archive missing")
            archive=dict(archive)
            raw=bytes(archive["raw_bytes"]);parquet=bytes(archive["parquet_bytes"]);manifest_bytes=bytes(archive["manifest_bytes"])
            if (hashlib.sha256(raw).hexdigest()!=archive["raw_sha256"]
                    or hashlib.sha256(parquet).hexdigest()!=archive["parquet_sha256"]
                    or hashlib.sha256(manifest_bytes).hexdigest()!=archive["manifest_sha256"]
                    or archive["rows"]!=previous["rows"]):
                raise ValueError("Missing-page repair canonical archive hash/row mismatch")
            canonical_source=canonical.page_source(current["family"],sid,canonical_pub["chunk"])
            manifest=canonical_source.verify()
            if manifest.get("rows")!=previous["rows"] or manifest.get("source_id")!=sid:
                raise ValueError("Missing-page repair canonical manifest mismatch")
            payload=json.loads(gzip.decompress(raw))
            request=payload.get("request") or {}
            result=payload.get("result")
            parsed=rows_for(current["family"],result)
            if (request.get("job_id")!=previous["job_id"] or len(parsed)!=previous["rows"]
                    or digest({"job":previous["job_id"],"body":result})!=sid):
                raise ValueError("Missing-page repair canonical response identity mismatch")

            with worker.archive_db() as con:
                existing=con.execute(
                    "SELECT family,raw_sha256,parquet_sha256,manifest_sha256,rows FROM page_archive WHERE source_id=?",
                    (sid,)).fetchone()
                identity=(archive["family"],archive["raw_sha256"],archive["parquet_sha256"],archive["manifest_sha256"],archive["rows"])
                if existing is not None and tuple(existing)!=identity:
                    raise ValueError("Missing-page repair worker archive conflict")
                if existing is None:
                    con.execute(
                        "INSERT INTO page_archive VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (archive["source_id"],archive["family"],raw,parquet,manifest_bytes,
                         archive["raw_sha256"],archive["parquet_sha256"],archive["manifest_sha256"],
                         archive["rows"],archive["archived_at"]))
                    con.commit()
            restored=worker.page_source(current["family"],sid,previous["chunk"]).verify()
            if restored!=manifest:
                raise ValueError("Missing-page repair restored manifest differs from canonical")

            with worker.db() as con:
                con.execute("""CREATE TABLE IF NOT EXISTS retail_phasea_archive_restore_audit(
                    event_id TEXT PRIMARY KEY,failed_job_id TEXT NOT NULL,previous_job_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,before_json TEXT NOT NULL,canonical_hashes_json TEXT NOT NULL,
                    restored_at TEXT NOT NULL)""")
                event_id=hashlib.sha256((current["job_id"]+"|"+sid+"|canonical-archive-v1").encode()).hexdigest()
                hashes={k:archive[k] for k in ("raw_sha256","parquet_sha256","manifest_sha256","rows")}
                con.execute(
                    "INSERT OR IGNORE INTO retail_phasea_archive_restore_audit VALUES (?,?,?,?,?,?,?)",
                    (event_id,current["job_id"],previous["job_id"],sid,encode(current),encode(hashes),now()))
                changed=con.execute(
                    "UPDATE jobs SET state='PENDING',error=NULL,updated_at=? WHERE job_id=? AND state='ERROR' AND error=?",
                    (now(),current["job_id"],MISSING_PRECEDING_BYTES_ERROR)).rowcount
                con.commit()
            if changed!=1:
                raise ValueError("Missing-page repair failed to requeue exact failed job")
            repaired.append({"failed_job_id":current["job_id"],"previous_job_id":previous["job_id"],"source_id":sid})
    return {
        "worker_root":before["worker_root"],
        "shard_id":before["shard_id"],
        "assignment_id":before["assignment_id"],
        "canonical_root":str(Path(canonical_root).resolve()),
        "repaired":len(repaired),
        "pages":repaired,
        "error_exact":MISSING_PRECEDING_BYTES_ERROR,
        "stop_exists":(worker.base/"STOP").exists(),
        "network_accessed":False,
    }


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
    workers_base=Path(workers_base).resolve()
    runtime=verified_eltdx_runtime(workers_base.parent,activate=False)
    rows=[preflight_worker(workers_base/f"worker-{sid}",floor,sid) for sid in shards]
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
        "runtime":runtime,
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
    workers_base=Path(workers_base).resolve()
    runtime=verified_eltdx_runtime(workers_base.parent,activate=True)
    pre=preflight_serial(workers_base,floor,tuple(shards))
    pre["runtime"]=runtime
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
    p.add_argument("--repair-local-runtime-errors",action="store_true")
    p.add_argument("--repair-missing-preceding-archives",action="store_true")
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

    if a.repair_local_runtime_errors:
        if not a.personal_research_only:
            raise ValueError("--repair-local-runtime-errors requires --personal-research-only")
        verified_eltdx_runtime(Path(a.workers_base).resolve().parent,activate=False)
        result={"format":"niuniu-retail-phasea-runtime-error-repair-v1","repairs":[
            repair_local_runtime_errors(Path(a.workers_base)/f"worker-{sid}",a.floor)
            for sid in a.shards]}
        print(encode(result))
        return
    if a.repair_missing_preceding_archives:
        if not a.personal_research_only:
            raise ValueError("--repair-missing-preceding-archives requires --personal-research-only")
        canonical_root=Path(a.workers_base).resolve().parent
        result={"format":"niuniu-retail-phasea-archive-restore-v1","repairs":[
            repair_missing_preceding_archives(Path(a.workers_base)/f"worker-{sid}",canonical_root,a.floor)
            for sid in a.shards]}
        print(encode(result))
        return
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
