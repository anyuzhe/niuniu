"""Host CLI: build the daily market overview (今日市场/主线方向) from DATA-READY files.

Reads only paths listed as READY in the DATA -> CODE catalog; writes one JSON into
<output>/_home/market/<trading_day>.json. No network access, no data-root writes.
Suitable for a scheduled after-close run.
"""
import argparse
import json
import sys

from quantlab.trading.market_overview import (MarketOverviewError, build_market_overview, latest_overview,
                                              save_overview)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='niuniu-market-overview', description=__doc__)
    parser.add_argument('--output', required=True, help='牛牛工作空间（artifacts）目录')
    parser.add_argument('--date', help='交易日 YYYY-MM-DD；默认取数据侧最新交易日')
    parser.add_argument('--data-catalog', help='DATA→CODE 数据清单路径；默认仓库内 docs/reference/data-catalog.md')
    parser.add_argument('--show', action='store_true', help='只打印已生成的最新结果，不重新计算')
    args = parser.parse_args(argv)
    if args.show:
        overview = latest_overview(args.output)
        if overview is None:
            print('还没有生成过市场总览', file=sys.stderr)
            return 2
    else:
        try:
            overview = build_market_overview(args.data_catalog, args.date)
        except MarketOverviewError as exc:
            print('生成失败：' + str(exc), file=sys.stderr)
            return 2
        path = save_overview(args.output, overview)
        print('已保存：' + str(path), file=sys.stderr)
    print('\n'.join([f"{overview['trading_day']} 收盘", *overview['summary']]))
    if not args.show:
        return 0
    print(json.dumps({k: overview[k] for k in ('trading_day', 'market', 'percentile')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
