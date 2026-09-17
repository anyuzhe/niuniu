"""Host CLI for the retrospective Baostock daily backfill; plan/fetch are explicit network I/O."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.data.forward_daily import ForwardReferenceArchive
from quantlab.data.retro_daily import RetroDailyError, RetroDailyStore
from quantlab.storage.codec import encode


def _shard(value):
    try:
        left, right = value.split('/')
        shard, shards = int(left), int(right)
    except (AttributeError, ValueError):
        raise ValueError('--shard 必须形如 0/4。') from None
    return shard, shards


def main(argv=None):
    parser = argparse.ArgumentParser(description='沪深A股回溯日线（research_only）；plan/fetch/forward-reference 会联网，其余只读')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'plan', 'fetch', 'status', 'verify', 'quarantine',
                                                                   'forward-reference', 'forward-references', 'consolidate'))
    parser.add_argument('--remove-originals', action='store_true', help='consolidate：合并并复核后删除原证券目录（可续跑）')
    parser.add_argument('--start', default='')
    parser.add_argument('--end', default='')
    parser.add_argument('--capture-id', default='')
    parser.add_argument('--max-seconds', type=float, default=140.0)
    parser.add_argument('--shard', default='0/1')
    parser.add_argument('--max-symbols', type=int, default=0)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = RetroDailyStore(Path(args.output))
        if args.call == 'list':
            data = {'captures': store.list()}
        elif args.call == 'forward-reference':
            data = ForwardReferenceArchive(Path(args.output)).capture()
        elif args.call == 'forward-references':
            data = {'snapshots': ForwardReferenceArchive(Path(args.output)).list()}
        elif args.call == 'plan':
            if not args.start or not args.end:
                raise ValueError('plan 需要 --start 与 --end。')
            data = store.create_plan(args.start, args.end)
        else:
            if not args.capture_id:
                raise ValueError(args.call + ' 需要 --capture-id。')
            if args.call == 'fetch':
                shard, shards = _shard(args.shard)
                data = store.fetch(args.capture_id, max_seconds=args.max_seconds, shard=shard, shards=shards,
                                   max_symbols=args.max_symbols or None)
            elif args.call == 'status':
                data = store.status(args.capture_id)
            elif args.call == 'verify':
                data = store.status(args.capture_id, deep=True)
            elif args.call == 'consolidate':
                data = store.consolidate(args.capture_id, confirmed=args.confirm, remove_originals=args.remove_originals,
                                         max_seconds=args.max_seconds)
            else:
                data = store.quarantine_corrupt(args.capture_id, confirmed=args.confirm)
        result = {'ok': True, 'data': data}
    except (RetroDailyError, ValueError, OSError) as error:
        code = getattr(error, 'code', None) or 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
