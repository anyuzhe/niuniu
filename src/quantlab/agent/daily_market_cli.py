"""Host CLI for immutable full-market daily captures; capture is explicit network I/O."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.data.daily_market_archive import DailyMarketArchive,DailyMarketArchiveError
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='全A股每日增量归档；只有 capture 会联网，修订切换需显式确认')
    parser.add_argument('--output',required=True)
    parser.add_argument('--call',required=True,choices=('overview','list','get','capture','accept-revision'))
    parser.add_argument('--date',default='')
    parser.add_argument('--snapshot-id',default='')
    parser.add_argument('--confirm-revision',action='store_true')
    args=parser.parse_args(argv)
    try:
        store=DailyMarketArchive(Path(args.output))
        if args.call=='overview':data=store.overview()
        elif args.call=='list':data={'days':store.list_days(limit=5000)}
        elif args.call=='get':
            if not args.date:raise ValueError('get 需要 --date。')
            data=store.get(args.date,args.snapshot_id)
        elif args.call=='capture':
            if not args.date:raise ValueError('capture 需要 --date。')
            data=store.capture(args.date)
        else:
            if not args.date or not args.snapshot_id:
                raise ValueError('accept-revision 需要 --date 与 --snapshot-id。')
            data=store.accept_revision(args.date,args.snapshot_id,confirmed=args.confirm_revision)
        result={'ok':True,'data':data}
    except (DailyMarketArchiveError,ValueError,OSError) as error:
        code=error.code if isinstance(error,DailyMarketArchiveError) else 'INVALID_REQUEST'
        result={'ok':False,'error':{'code':code,'message':str(error)[:500]}}
    print(encode(result));return 0 if result.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())
