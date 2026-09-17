"""Host CLI for the limit-up event library; local computation only, no network."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.limit_events import LimitEventError, LimitEventLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description='涨停事件库（research_only）：由完整回溯日线 capture（可加 DailyMarket 前瞻日线）构建，不联网')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'build', 'get', 'verify', 'summary'))
    parser.add_argument('--capture-ids', default='')
    parser.add_argument('--build-id', default='')
    parser.add_argument('--forward-through', default='', help='用 DailyMarket 前瞻日线把回溯数据延伸到该交易日（含）')
    args = parser.parse_args(argv)
    try:
        library = LimitEventLibrary(Path(args.output))
        if args.call == 'list':
            data = {'builds': library.list()}
        elif args.call == 'build':
            captures = [value.strip() for value in args.capture_ids.split(',') if value.strip()]
            if not captures:
                raise ValueError('build 需要 --capture-ids。')
            data = library.build(captures, args.forward_through or None)
        else:
            if not args.build_id:
                raise ValueError(args.call + ' 需要 --build-id。')
            data = {'get': library.get, 'verify': library.verify, 'summary': library.summary}[args.call](args.build_id)
        result = {'ok': True, 'data': data}
    except (LimitEventError, ValueError, OSError) as error:
        code = error.code if isinstance(error, LimitEventError) else 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
