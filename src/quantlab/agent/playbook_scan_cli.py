"""CLI for deterministic daily Playbook scanning over frozen MarketSnapshots."""
from __future__ import annotations

import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.playbook_forward import freeze_forward_snapshot
from quantlab.trading.playbook_scanner import DailyPlaybookScanner,PlaybookScanError
from quantlab.trading.playbook_store import PlaybookError


def main(argv=None):
    parser=argparse.ArgumentParser(description='Daily Playbook Scanner；默认只读，--freeze 才写 SYSTEM_PREDICTION')
    parser.add_argument('--output',required=True)
    parser.add_argument('--candidate-set-id',required=True)
    parser.add_argument('--market-snapshot-id',required=True)
    parser.add_argument('--auction-snapshot-id',default='')
    parser.add_argument('--previous-snapshot-id',default='')
    parser.add_argument('--reference-prediction-id',default='')
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args(argv)
    try:
        result=DailyPlaybookScanner(Path(args.output)).scan(args.candidate_set_id,
            args.market_snapshot_id,args.auction_snapshot_id,args.previous_snapshot_id,args.reference_prediction_id)
        if args.freeze:result['freeze_result']=freeze_forward_snapshot(Path(args.output),result['forward_payload'])
        reply={'ok':True,'data':result}
    except (PlaybookScanError,PlaybookError,ValueError,OSError) as error:
        code=getattr(error,'code','INVALID_REQUEST');reply={'ok':False,'error':{'code':code,'message':str(error)[:400]}}
    print(encode(reply));return 0 if reply.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())
