"""Host CLI for sentiment-cycle machine states and similar-day lookup; local computation only."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import polars as pl

from quantlab.storage.codec import encode
from quantlab.trading.market_sentiment import MarketSentimentError, MarketSentimentLibrary
from quantlab.trading.sentiment_cycle import CYCLE_RULES_VERSION, RULE_ORIGIN, RULES, compute_cycle, similar_days


def main(argv=None):
    parser = argparse.ArgumentParser(description='情绪周期机器状态与相似日（research_only，工程阈值，不是交易信号）')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('rules', 'cycle', 'similar'))
    parser.add_argument('--build-id', default='')
    parser.add_argument('--start', default='')
    parser.add_argument('--end', default='')
    parser.add_argument('--date', default='')
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--exclude-recent', type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.call == 'rules':
            data = {'rules_version': CYCLE_RULES_VERSION, 'origin': RULE_ORIGIN, 'rules': RULES}
        else:
            if not args.build_id:
                raise ValueError(args.call + ' 需要 --build-id。')
            daily, manifest = MarketSentimentLibrary(Path(args.output)).read(args.build_id)
            if args.call == 'cycle':
                cycle = compute_cycle(daily)
                if args.start:
                    cycle = cycle.filter(pl.col('date') >= date.fromisoformat(args.start))
                if args.end:
                    cycle = cycle.filter(pl.col('date') <= date.fromisoformat(args.end))
                if cycle.height > 500:
                    raise ValueError('cycle 最多返回 500 个交易日，请缩小 --start/--end。')
                data = {'build_id': args.build_id, 'rules_version': CYCLE_RULES_VERSION, 'origin': RULE_ORIGIN,
                        'rows': cycle.to_dicts(), 'available_policy': manifest['available_policy']}
            else:
                if not args.date:
                    raise ValueError('similar 需要 --date。')
                data = {'build_id': args.build_id, 'origin': RULE_ORIGIN,
                        **similar_days(daily, args.date, k=args.k, exclude_recent=args.exclude_recent)}
        result = {'ok': True, 'data': data}
    except (MarketSentimentError, ValueError, OSError) as error:
        code = error.code if isinstance(error, MarketSentimentError) else 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
