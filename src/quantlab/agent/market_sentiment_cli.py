"""Host CLI for daily limit-board sentiment metrics; local computation only, no network."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.market_sentiment import MarketSentimentError, MarketSentimentLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description='日度打板情绪指标（research_only）：由完整回溯日线 capture 计算，不联网')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'build', 'get', 'verify', 'read'))
    parser.add_argument('--capture-ids', default='')
    parser.add_argument('--build-id', default='')
    parser.add_argument('--forward-through', default='', help='用 DailyMarket 前瞻日线把回溯数据延伸到该交易日（含）')
    parser.add_argument('--start', default='')
    parser.add_argument('--end', default='')
    args = parser.parse_args(argv)
    try:
        library = MarketSentimentLibrary(Path(args.output))
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
            if args.call == 'get':
                data = library.get(args.build_id)
            elif args.call == 'verify':
                data = library.verify(args.build_id)
            else:
                frame, manifest = library.read(args.build_id, start=args.start or None, end=args.end or None)
                if frame.height > 500:
                    raise ValueError('read 最多返回 500 个交易日，请缩小 --start/--end。')
                data = {'build_id': args.build_id, 'rows': frame.to_dicts(), 'available_policy': manifest['available_policy']}
        result = {'ok': True, 'data': data}
    except (MarketSentimentError, ValueError, OSError) as error:
        code = error.code if isinstance(error, MarketSentimentError) else 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
