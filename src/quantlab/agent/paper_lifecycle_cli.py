"""Read-only host CLI for long-horizon Paper lifecycle statistics."""
import argparse
from pathlib import Path
from quantlab.storage.codec import encode
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics

def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛长期 Paper 生命周期统计；纯只读')
    parser.add_argument('--output',required=True);args=parser.parse_args(argv)
    try:data=PaperLifecycleAnalytics(Path(args.output)).build();print(encode({'ok':True,'data':data}));return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':'READ_FAILED','message':str(error)[:500]}}));return 2
if __name__=='__main__':raise SystemExit(main())
