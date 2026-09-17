"""Host CLI for daily machine theme facts over archived public evidence; local computation, no network."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import polars as pl

from quantlab.data.public_evidence import TZ
from quantlab.storage.codec import encode
from quantlab.trading.theme_engine import ThemeEngineError, ThemeFactsLibrary

TOP_COLUMNS = ('family', 'rank', 'board_code', 'board_name', 'constituents', 'limit_up_count', 'twenty_cm_limit_up_count',
               'first_board_count', 'streak_2_count', 'streak_3_count', 'streak_4_count', 'streak_5plus_count', 'max_streak',
               'broken_count', 'limit_down_count', 'seal_fund_total', 'earliest_first_seal_time', 'leaders', 'board_pct_change',
               'limit_up_count_prev', 'persistence_days', 'persistence_days_3plus', 'persistence_truncated', 'membership_day')


def main(argv=None):
    parser = argparse.ArgumentParser(description='每日题材事实（东方财富公开证据归档，research_only）：build 只读本地归档；publish 写入 Theme Matrix 需 --confirm')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'build', 'get', 'top', 'industries', 'publish'))
    parser.add_argument('--date', default='')
    parser.add_argument('--build-id', default='')
    parser.add_argument('--family', default='concept', choices=('concept', 'industry'))
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--concept-limit', type=int, default=10)
    parser.add_argument('--industry-limit', type=int, default=5)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    try:
        library = ThemeFactsLibrary(Path(args.output))
        day = args.date or datetime.now(TZ).date().isoformat()
        if not 1 <= args.limit <= 200:
            raise ValueError('--limit 必须为 1–200。')
        if args.call == 'list':
            data = {'days': library.list_days()}
        elif args.call == 'build':
            data = library.build(day)
        elif args.call == 'get':
            data = library.get(day, args.build_id or None)
        elif args.call == 'top':
            themes, manifest = library.read(day, args.build_id or None)
            rows = themes.filter((pl.col('family') == args.family) & pl.col('rank').is_not_null()).sort('rank').head(args.limit)
            data = {'build_id': manifest['build_id'], 'trading_day': manifest['trading_day'], 'facts_as_of': manifest['facts_as_of'],
                    'skipped_families': manifest['skipped_families'], 'rows': rows.select(list(TOP_COLUMNS)).to_dicts(),
                    'limitations': manifest['limitations']}
        elif args.call == 'industries':
            frame, manifest = library.read(day, args.build_id or None, table='pool_industries')
            data = {'build_id': manifest['build_id'], 'trading_day': manifest['trading_day'], 'rows': frame.head(args.limit).to_dicts()}
        else:
            data = library.publish(day, confirmed=args.confirm, concept_limit=args.concept_limit, industry_limit=args.industry_limit)
        result = {'ok': True, 'data': data}
    except (ThemeEngineError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
