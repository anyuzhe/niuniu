"""Host CLI for point-in-time Paper D1/D2/D3+ outcome reviews."""
import argparse
from pathlib import Path
from quantlab.storage.codec import encode
from quantlab.trading.paper_review import PaperReviewError,PaperReviewService

def main(argv=None):
    parser=argparse.ArgumentParser(description='Paper Outcome Review；只生成复盘证据，不自动 HOLD/REDUCE/EXIT')
    parser.add_argument('--output',required=True);parser.add_argument('--plan-id',default='')
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--auto',action='store_true');group.add_argument('--auto-all',action='store_true');group.add_argument('--day');group.add_argument('--list',action='store_true')
    parser.add_argument('--limit-days',type=int,default=20);args=parser.parse_args(argv)
    try:
        service=PaperReviewService(Path(args.output))
        if args.auto_all:data=service.auto_all(limit_days=args.limit_days)
        elif args.auto:
            if not args.plan_id:raise ValueError('--auto 需要 --plan-id。')
            data={'records':service.auto(args.plan_id,args.limit_days)}
        elif args.day:
            if not args.plan_id:raise ValueError('--day 需要 --plan-id。')
            data=service.build(args.plan_id,args.day)
        else:data={'records':service.list(args.plan_id,limit=5000)}
        print(encode({'ok':True,'data':data}));return 0
    except (PaperReviewError,OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','INVALID_REQUEST'),'message':str(error)[:500]}}));return 2
if __name__=='__main__':raise SystemExit(main())
