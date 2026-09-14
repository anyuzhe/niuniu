"""Host CLI for copying frozen SYSTEM_PREDICTION into conservative Strategy Intent evidence."""
import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.playbook_decision_bridge import PlaybookDecisionBridge,PlaybookDecisionBridgeError


def main(argv=None):
    parser=argparse.ArgumentParser(description='Playbook SYSTEM_PREDICTION → Trading Desk bridge；最多写 WATCH/READY，不下单')
    parser.add_argument('--output',required=True);parser.add_argument('--selection-id',required=True)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--apply',action='store_true');group.add_argument('--status',action='store_true')
    args=parser.parse_args(argv)
    try:
        service=PlaybookDecisionBridge(Path(args.output));data=service.apply(args.selection_id) if args.apply else service.get(args.selection_id)
        print(encode({'ok':True,'data':data}));return 0
    except (PlaybookDecisionBridgeError,OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','INVALID_REQUEST'),'message':str(error)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())
