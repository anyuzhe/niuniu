"""Host CLI for forward limit-event details over archived public evidence; local computation, no network."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from quantlab.data.public_evidence import TZ
from quantlab.storage.codec import encode
from quantlab.trading.event_details import EventDetailError, EventDetailLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description='涨停事件前瞻明细（东方财富归档，research_only）：封板时间、封单、炸板、龙虎榜、人气；与日线状态核对')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'build', 'get', 'read'))
    parser.add_argument('--date', default='')
    parser.add_argument('--build-id', default='')
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args(argv)
    try:
        library = EventDetailLibrary(Path(args.output))
        day = args.date or datetime.now(TZ).date().isoformat()
        if not 1 <= args.limit <= 2000:
            raise ValueError('--limit 必须为 1–2000。')
        if args.call == 'list':
            data = {'days': library.list_days()}
        elif args.call == 'build':
            data = library.build(day)
        elif args.call == 'get':
            data = library.get(day, args.build_id or None)
        else:
            frame, manifest = library.read(day, args.build_id or None)
            data = {'manifest': manifest, 'rows': frame.head(args.limit).to_dicts(), 'truncated': frame.height > args.limit}
        result = {'ok': True, 'data': data}
    except (EventDetailError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
