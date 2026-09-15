"""Read-only P12 mobile/bot brief CLI over the shared workspace state."""
import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.mobile import MobileBriefService


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 P12 Mobile Brief；只读复用同一 Decision/Dossier/Paper/System Health 状态')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root')
    parser.add_argument('--trading-day',default='');parser.add_argument('--symbol',default='')
    args=parser.parse_args(argv)
    try:
        data=MobileBriefService(Path(args.output),Path(args.data_root) if args.data_root else None).build(args.trading_day,args.symbol)
        print(encode({'ok':True,'data':data}));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(encode({'ok':False,'error':{'code':'MOBILE_BRIEF_FAILED','message':str(exc)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())
