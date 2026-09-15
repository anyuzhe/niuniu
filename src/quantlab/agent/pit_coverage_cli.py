"""Read-only Strict PIT coverage diagnostics; never archives or downloads data."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.data.pit_coverage import strict_pit_coverage
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 Strict PIT coverage：严格回执 presence + 回顾性候选数据 inventory；只读')
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--symbols',nargs='*',default=[])
    parser.add_argument('--start',default='')
    parser.add_argument('--end',default='')
    parser.add_argument('--detail-limit',type=int,default=100)
    args=parser.parse_args(argv)
    try:
        data=strict_pit_coverage(Path(args.data_root),symbols=args.symbols,
            start=args.start or None,end=args.end or None,detail_limit=args.detail_limit)
        result={'ok':True,'data':data};code=0
    except (OSError,ValueError,TypeError,KeyError) as error:
        result={'ok':False,'error':{'code':'PIT_COVERAGE_ERROR','message':str(error)[:500]}};code=2
    print(encode(result));return code


if __name__=='__main__':raise SystemExit(main())
