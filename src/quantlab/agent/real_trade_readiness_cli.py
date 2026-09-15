"""Read-only P13-B0 real-trade readiness CLI. It cannot connect or submit orders."""
import argparse
from pathlib import Path

from quantlab.broker import BrokerSnapshotError,RealTradeReadinessService
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 P13-B0 RealTrade Readiness；只读安全门，不连接券商、不下单')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root');parser.add_argument('--policy')
    args=parser.parse_args(argv)
    try:
        data=RealTradeReadinessService(Path(args.output),Path(args.data_root) if args.data_root else None,
            Path(args.policy) if args.policy else None).build()
        print(encode({'ok':True,'data':data}));return 0
    except (BrokerSnapshotError,OSError,ValueError,KeyError,TypeError) as exc:
        print(encode({'ok':False,'error':{'code':getattr(exc,'code','READINESS_FAILED'),'message':str(exc)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())
