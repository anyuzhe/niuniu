"""Read-only MarketSnapshot provider capability/readiness CLI."""
import argparse
from quantlab.storage.codec import encode
from quantlab.trading.market_snapshot_provider import MarketSnapshotProviderReadiness


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 MarketSnapshot Provider readiness；只读，不联网抓行情')
    parser.parse_args(argv)
    data=MarketSnapshotProviderReadiness().build()
    print(encode({'ok':True,'data':data}));return 0


if __name__=='__main__':raise SystemExit(main())
