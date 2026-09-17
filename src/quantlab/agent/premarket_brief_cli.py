"""Host CLI for the pre-market limit-board brief: build, get, markdown (research_only, no network)."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.premarket_brief import PremarketBriefError, PremarketBriefLibrary, render_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(description='打板盘前简报（research_only）：依据前一个收盘后的数据汇总情绪、仍有效的规律、题材、预测与风险提示')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('build', 'get', 'markdown'))
    parser.add_argument('--date', required=True, help='目标交易日 YYYY-MM-DD')
    args = parser.parse_args(argv)
    try:
        library = PremarketBriefLibrary(Path(args.output))
        if args.call == 'build':
            data = library.build(args.date)
        elif args.call == 'get':
            data = library.get(args.date)
        else:
            print(render_markdown(library.get(args.date)))
            return 0
        result = {'ok': True, 'data': data}
    except (PremarketBriefError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
