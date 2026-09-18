"""Bounded worker cycles, durable outbox and canonical acknowledgements.

The OS supervisor may restart this program; it never clears STOP/AUTO_HALT.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

from quantlab.data.tdx_lake import TdxLake, encode, now, safe, write_json
from quantlab.agent.tdx_collection_cli import main as collection_main, writer_lease
from quantlab.agent.tdx_distributed import (
    worker_status, export_results, import_results, BundleConflict, BundleDeferred,
)
from quantlab.agent.tdx_transfer import send_result, validate_ack, endpoint


def pending_bundles(lake):
    with lake.db(readonly=True) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='distributed_result_bundles'").fetchone()
        rows=[dict(r) for r in con.execute('SELECT * FROM distributed_result_bundles WHERE acked=0 ORDER BY sequence_no')] if exists else []
    return rows


def acknowledge(lake,receipt,ack):
    validate_ack(ack,receipt)
    with writer_lease(lake):
        with lake.db() as con:
            row=con.execute('SELECT * FROM distributed_result_bundles WHERE bundle_id=?',(receipt['bundle_id'],)).fetchone()
            if not row or row['sha256']!=receipt['sha256'] or row['sequence_no']!=receipt['sequence_no']:
                raise BundleConflict('Acknowledgement does not identify the durable outbox')
            con.execute('UPDATE distributed_result_bundles SET acked=1 WHERE bundle_id=?',(receipt['bundle_id'],));con.commit()
        directory=lake.base/'distributed-acks';directory.mkdir(exist_ok=True)
        write_json(directory/(receipt['bundle_id']+'.json'),ack)
    # Remove the transfer copy, not source pages or source errors, after the receipt is durable.
    path=safe(lake.root,Path(receipt['path']))
    path.unlink(missing_ok=True)
    safe(lake.root,path.with_suffix('.receipt.json')).unlink(missing_ok=True)


def deliver_pending(lake,*,server_url=None,canonical_root=None):
    delivered=0
    for row in pending_bundles(lake):
        path=safe(lake.root,Path(row['path']).with_suffix('.receipt.json'))
        receipt=json.loads(path.read_text(encoding='utf-8'))
        if receipt['bundle_id']!=row['bundle_id'] or receipt['sha256']!=row['sha256']:
            raise BundleConflict('Outbox receipt differs from durable export')
        if canonical_root:
            try:ack=import_results(TdxLake(canonical_root),Path(row['path']),row['sha256'])
            except ValueError as error:
                if str(error).startswith('Another collector owns the TDX writer lease;'):
                    raise BundleDeferred('Canonical writer is busy; retain this exact outbox bundle') from error
                raise
            validate_ack(ack,receipt)
        else:
            ack=send_result(server_url,receipt)
        if ack is None:break
        acknowledge(lake,receipt,ack);delivered+=1
    return delivered


def collect_cycle(lake,*,seconds=120,max_requests=400,max_new_gib=10,request_interval_seconds=None):
    worker_status(lake)  # Refuse a canonical or misbound root before any side effects.
    if (lake.base/'STOP').exists():return {'state':'USER_STOP','processed_this_run':0}
    if (lake.base/'AUTO_HALT.json').exists():return {'state':'AUTO_HALTED','processed_this_run':0}
    args=['--data-root',str(lake.root),'autoresume','--personal-research-only',
        '--seconds',str(seconds),'--max-requests',str(max_requests),'--max-new-gib',str(max_new_gib),'--workers','2']
    if request_interval_seconds is not None:args.extend(['--runtime-request-interval',str(request_interval_seconds)])
    collection_main(args)
    return json.loads((lake.base/'progress.json').read_text(encoding='utf-8'))


def run_service(lake,*,server_url=None,canonical_root=None,seconds=86400,max_requests=200000,max_new_gib=100,cycle_seconds=120,request_interval_seconds=None):
    if bool(server_url)==bool(canonical_root):raise ValueError('Exactly one canonical delivery route is required')
    if server_url:endpoint(server_url)
    if not 1<=seconds<=86400 or not 1<=max_requests<=1000000 or not 1<=max_new_gib<=200 or not 1<=cycle_seconds<=600:
        raise ValueError('Service budget outside supported bounds')
    if request_interval_seconds is not None and (type(request_interval_seconds) not in (int,float) or not .2<=request_interval_seconds<=2):
        raise ValueError('Service request interval outside supported bounds')
    status=worker_status(lake)
    if canonical_root and Path(canonical_root).resolve()==lake.root:raise ValueError('Worker must not share canonical root')
    directory=safe(lake.root,lake.base/'_service');directory.mkdir(exist_ok=True)
    lock_scope=SimpleNamespace(root=lake.root,base=directory)
    started=time.monotonic();initial_free=shutil.disk_usage(lake.root).free;processed=0;cycles=0
    with writer_lease(lock_scope):
        while time.monotonic()-started<seconds and processed<max_requests:
            stopped=(lake.base/'STOP').exists();halted=(lake.base/'AUTO_HALT.json').exists()
            if stopped or halted:
                result={'state':'USER_STOP' if stopped else 'AUTO_HALTED','pid':os.getpid(),'observed_at':now(),'processed_this_service':processed,'cycles':cycles}
                write_json(directory/'state.json',result);return result
            state={'state':'RUNNING','pid':os.getpid(),'observed_at':now(),'processed_this_service':processed,'cycles':cycles,'shard_id':status['shard_id'],'history_complete':False}
            write_json(directory/'state.json',state)
            try:
                deliver_pending(lake,server_url=server_url,canonical_root=canonical_root)
                pending=pending_bundles(lake)
                if sum(row['bytes'] for row in pending)>=512*1024**2:
                    write_json(directory/'state.json',{**state,'state':'SYNC_BACKPRESSURE'})
                    time.sleep(15);continue
                free=shutil.disk_usage(lake.root).free
                if free<30*1024**3 or initial_free-free>=max_new_gib*1024**3:
                    write_json(lake.base/'AUTO_HALT.json',{'reason':'SERVICE_DISK_BUDGET','halted_at':now()})
                    continue
                remaining=max(1,int(seconds-(time.monotonic()-started)))
                cycle=collect_cycle(lake,seconds=min(cycle_seconds,remaining),max_requests=min(2000,max_requests-processed),max_new_gib=min(10,max_new_gib),request_interval_seconds=request_interval_seconds)
                processed+=cycle.get('processed_this_run',0);cycles+=1
                if cycle.get('state') in ('USER_STOP','AUTO_HALTED'):continue
                receipt=export_results(lake,lake.base/'_outbox',max_pages=500,max_bytes=128*1024**2)
                print(encode({'phase':'export',**receipt}),flush=True)
                deliver_pending(lake,server_url=server_url,canonical_root=canonical_root)
                write_json(directory/'state.json',{**state,'state':'CYCLE_COMPLETE','observed_at':now(),'cycles':cycles,'processed_this_service':processed,'last_cycle':cycle,'pending_transfer_bundles':len(pending_bundles(lake))})
                if cycle.get('stop_reason')=='QUEUE_DRAINED':time.sleep(15)
            except BundleConflict as exc:
                write_json(lake.base/'AUTO_HALT.json',{'reason':'TRANSFER_CONFLICT','error':str(exc),'halted_at':now()})
                raise
            except (OSError,ConnectionError,TimeoutError,BundleDeferred) as exc:
                write_json(directory/'state.json',{**state,'state':'TRANSFER_WAIT','observed_at':now(),'error':type(exc).__name__+': '+str(exc)[:500]})
                time.sleep(15)
        result={'state':'SERVICE_BUDGET','pid':os.getpid(),'observed_at':now(),'processed_this_service':processed,'cycles':cycles,'history_complete':False}
        write_json(directory/'state.json',result);return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    route=parser.add_mutually_exclusive_group(required=True)
    route.add_argument('--server-url')
    route.add_argument('--canonical-root',type=Path)
    parser.add_argument('--seconds',type=int,default=86400)
    parser.add_argument('--max-requests',type=int,default=200000)
    parser.add_argument('--max-new-gib',type=int,default=100)
    parser.add_argument('--cycle-seconds',type=int,default=120)
    parser.add_argument('--request-interval',type=float)
    parser.add_argument('--personal-research-only',action='store_true')
    args=parser.parse_args(argv)
    if not args.personal_research_only:parser.error('Explicit --personal-research-only required')
    result=run_service(TdxLake(args.data_root),server_url=args.server_url,canonical_root=args.canonical_root,
        seconds=args.seconds,max_requests=args.max_requests,max_new_gib=args.max_new_gib,cycle_seconds=args.cycle_seconds,
        request_interval_seconds=args.request_interval)
    print(encode(result));return 0


if __name__=='__main__':raise SystemExit(main())
