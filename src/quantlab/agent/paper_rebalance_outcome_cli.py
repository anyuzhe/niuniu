"""Host CLI for Dynamic Paper rebalance fill outcomes."""
import argparse
from pathlib import Path
from quantlab.storage.codec import encode
from quantlab.trading.paper_rebalance_outcome import PaperRebalanceOutcomeBridge,PaperRebalanceOutcomeError

def main(argv=None):
    parser=argparse.ArgumentParser(description='Rebalance 模拟成交 → Strategy Intent outcome；宿主确认')
    parser.add_argument('--output',required=True);parser.add_argument('--plan-id',required=True)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--apply',action='store_true');group.add_argument('--status',action='store_true')
    parser.add_argument('--confirm',action='store_true');args=parser.parse_args(argv)
    try:
        service=PaperRebalanceOutcomeBridge(Path(args.output));data=service.apply(args.plan_id,confirmed=args.confirm) if args.apply else service.get(args.plan_id)
        print(encode({'ok':True,'data':data}));return 0
    except (PaperRebalanceOutcomeError,OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','INVALID_REQUEST'),'message':str(error)[:500]}}));return 2
if __name__=='__main__':raise SystemExit(main())
