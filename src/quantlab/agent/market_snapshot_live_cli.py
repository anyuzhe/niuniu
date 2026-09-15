"""Host-only live MarketSnapshot capture using Tencent/Eastmoney/Sina consensus."""
import argparse
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5

from quantlab.storage.codec import digest,encode
from quantlab.trading.market_snapshot import MarketSnapshotStore
from quantlab.trading.public_web_market_snapshot import PublicWebConsensusProvider


def _symbols(value):
    rows=[item.strip().lower() for item in value.split(',') if item.strip()]
    if not rows:raise ValueError('--symbols 不能为空')
    return rows


def main(argv=None):
    parser=argparse.ArgumentParser(description='宿主三源实时行情抓取；腾讯主源、东财第二源、新浪备用校验')
    parser.add_argument('--output',required=True);parser.add_argument('--trading-day',required=True)
    parser.add_argument('--frame',required=True,choices=('AUCTION','R1','R2','R3'))
    parser.add_argument('--symbols',required=True,help='逗号分隔 sh.600000,sz.000001')
    parser.add_argument('--confirm-network',action='store_true',help='明确允许访问三家公开网页行情接口')
    parser.add_argument('--store',action='store_true',help='通过MarketSnapshotStore冻结本次结果')
    args=parser.parse_args(argv)
    try:
        if args.confirm_network is not True:raise ValueError('抓取实时行情需要 --confirm-network 明确授权联网')
        content=PublicWebConsensusProvider().capture(args.trading_day,args.frame,_symbols(args.symbols))
        data=content
        if args.store:
            request_id=str(uuid5(NAMESPACE_URL,'niuniu-public-web-market-snapshot:'+digest(content)))
            data=MarketSnapshotStore(Path(args.output)).create(request_id,content)
        result={'ok':True,'data':data,'warnings':['公开网页行情不是官方交易所feed，不认证Strict PIT；未来券商/QMT可替代为正式主源。']}
    except (OSError,ValueError,KeyError,TypeError) as error:
        result={'ok':False,'error':{'code':'LIVE_MARKET_CAPTURE_FAILED','message':str(error)[:500]}}
    print(encode(result));return 0 if result.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())
