"""Explicit host-only commands for fixed-shard personal-research collection."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from quantlab.data.tdx_lake import FAMILIES, TdxLake, encode, write_json
from quantlab.agent.tdx_distributed import (
    create_bootstraps, install_bootstrap, export_results, import_results,
    worker_status, aggregate_status, BundleDeferred,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--personal-research-only', action='store_true')
    commands = parser.add_subparsers(dest='action', required=True)
    bootstrap = commands.add_parser('bootstrap')
    bootstrap.add_argument('--plan-id')
    bootstrap.add_argument('--output', required=True, type=Path)
    bootstrap.add_argument('--machines', nargs='+', default=['macbook', 'homepc', '601'])
    for name in ('install', 'import'):
        command = commands.add_parser(name)
        command.add_argument('--bundle', required=True, type=Path)
        command.add_argument('--sha256', required=True)
    export = commands.add_parser('export')
    export.add_argument('--output', required=True, type=Path)
    export.add_argument('--max-pages', type=int, default=500)
    export.add_argument('--max-mib', type=int, default=128)
    commands.add_parser('status')
    commands.add_parser('worker-status')
    commands.add_parser('stop')
    compact = commands.add_parser('compact-storage')
    compact.add_argument('--family', action='append', dest='families')
    compact.add_argument('--batch-pages', type=int, default=1000)
    compact.add_argument('--max-pages', type=int)
    sync = commands.add_parser('sync-export-history')
    sync.add_argument('--canonical-root', required=True, type=Path)
    merge = commands.add_parser('merge-local-workers')
    merge.add_argument('--worker-root', required=True, action='append', type=Path)
    merge.add_argument('--batch-pages', type=int, default=1000)
    retire = commands.add_parser('retire-local-workers')
    retire.add_argument('--worker-root', required=True, action='append', type=Path)
    retire.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.action not in ('status', 'worker-status', 'stop') and not args.personal_research_only:
        parser.error('Explicit --personal-research-only is required')
    if args.action == 'install':
        result = install_bootstrap(args.data_root, args.bundle, args.sha256)
    else:
        lake = TdxLake(args.data_root)
        if args.action == 'bootstrap':
            pid = args.plan_id or json.loads((lake.base/'active-plan.json').read_text(encoding='utf-8'))['plan_id']
            cluster = create_bootstraps(lake, pid, args.output, tuple(args.machines))
            result = {k: v for k, v in cluster.items() if k != 'assignments'}
            result['assignments'] = [{k: v for k, v in a.items() if k != 'symbols'} for a in cluster['assignments']]
        elif args.action == 'export':
            result = export_results(lake, args.output, max_pages=args.max_pages, max_bytes=args.max_mib*1024**2)
        elif args.action == 'import':
            try:
                result = import_results(lake, args.bundle, args.sha256)
            except BundleDeferred as error:
                print(encode({'state': 'DEFERRED', 'reason': str(error), 'history_complete': False}))
                return 3
        elif args.action == 'status':
            result = aggregate_status(lake)
        elif args.action == 'worker-status':
            result = worker_status(lake)
        elif args.action == 'stop':
            from quantlab.data.tdx_lake import now
            (lake.base/'STOP').write_text(now(), encoding='utf-8')
            result = {'stop_requested': True, 'history_complete': False}
        elif args.action == 'compact-storage':
            from quantlab.agent.tdx_storage import compact_storage
            result = compact_storage(lake, families=tuple(args.families) if args.families else FAMILIES,
                                     batch_pages=args.batch_pages, max_pages=args.max_pages)
        elif args.action == 'sync-export-history':
            from quantlab.agent.tdx_storage import synchronize_export_history
            result = synchronize_export_history(lake, TdxLake(args.canonical_root))
        elif args.action == 'merge-local-workers':
            from quantlab.agent.tdx_storage import merge_local_workers
            result = merge_local_workers(lake, tuple(TdxLake(root) for root in args.worker_root), batch_pages=args.batch_pages)
        elif args.action == 'retire-local-workers':
            from quantlab.agent.tdx_storage import retire_local_worker_pages
            result = retire_local_worker_pages(lake, tuple(TdxLake(root) for root in args.worker_root), dry_run=args.dry_run)
    print(encode(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
