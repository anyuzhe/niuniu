"""Host CLI for immutable MarketSnapshot import/query; no market-data download."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5

from quantlab.storage.codec import digest,encode
from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore


def _load(path):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():raise ValueError('payload 文件不存在或为符号链接。')
    if target.stat().st_size>2_000_000:raise ValueError('payload 文件超过2MB。')
    value=json.loads(target.read_text())
    if not isinstance(value,dict):raise ValueError('payload 必须是 JSON 对象。')
    return value


def _request_id(value):return str(uuid5(NAMESPACE_URL,'quantlab-market-snapshot-v1:'+digest(value)))


def main(argv=None):
    parser=argparse.ArgumentParser(description='MarketSnapshot 导入/查询；不联网下载行情')
    parser.add_argument('--output',required=True)
    parser.add_argument('--call',required=True,choices=('import','overview','get','list'))
    parser.add_argument('--payload','--payload-path',dest='payload',default='')
    parser.add_argument('--snapshot-id',default='')
    parser.add_argument('--trading-day',default='');parser.add_argument('--frame',default='')
    parser.add_argument('--symbol',default='');parser.add_argument('--provider',default='')
    args=parser.parse_args(argv)
    try:
        store=MarketSnapshotStore(Path(args.output))
        if args.call=='import':
            if not args.payload:raise ValueError('import 需要 --payload。')
            payload=_load(args.payload);result={'ok':True,'data':store.create(_request_id(payload),payload)}
        elif args.call=='overview':result={'ok':True,'data':store.overview()}
        elif args.call=='get':
            if not args.snapshot_id:raise ValueError('get 需要 --snapshot-id。')
            result={'ok':True,'data':store.get(args.snapshot_id)}
        else:
            result={'ok':True,'data':store.list(trading_day=args.trading_day,frame=args.frame,
                symbol=args.symbol,provider=args.provider,limit=500)}
    except (MarketSnapshotError,ValueError,OSError,json.JSONDecodeError) as error:
        code=error.code if isinstance(error,MarketSnapshotError) else 'INVALID_REQUEST'
        result={'ok':False,'error':{'code':code,'message':str(error)[:400]}}
    print(encode(result));return 0 if result.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())
