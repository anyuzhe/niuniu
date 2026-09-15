"""P13-A host CLI for credential-free broker snapshots and shadow reconciliation."""
import argparse
from pathlib import Path
from quantlab.broker import BrokerShadowReconciler,BrokerSnapshotError,BrokerSnapshotStore,JsonBrokerExportAdapter
from quantlab.storage.codec import encode

def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 P13-A Broker Shadow；只读账户快照/对账，不连接券商、不下单')
    parser.add_argument('--output',required=True)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--import-json');action.add_argument('--list',action='store_true');action.add_argument('--reconcile',action='store_true')
    parser.add_argument('--confirm',action='store_true');parser.add_argument('--snapshot-id',default='')
    parser.add_argument('--account-alias',default='');parser.add_argument('--paper-account',default='')
    parser.add_argument('--cash-tolerance',type=float,default=0.01)
    args=parser.parse_args(argv);output=Path(args.output)
    try:
        if args.import_json:
            raw=JsonBrokerExportAdapter(args.import_json).snapshot()
            data=BrokerSnapshotStore(output).import_snapshot(raw,confirmed=args.confirm)
        elif args.list:
            data=BrokerSnapshotStore(output).list(args.account_alias)
        else:
            data=BrokerShadowReconciler(output).reconcile(snapshot_id=args.snapshot_id,
                account_alias=args.account_alias,paper_account=args.paper_account,cash_tolerance=args.cash_tolerance)
        print(encode({'ok':True,'data':data}));return 0
    except (BrokerSnapshotError,OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','BROKER_SHADOW_FAILED'),'message':str(error)[:500]}}));return 2

if __name__=='__main__':raise SystemExit(main())
