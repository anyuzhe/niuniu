"""Host CLI for durable daily PREP/AUCTION/R1 Playbook orchestration."""
from __future__ import annotations

import argparse,time
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.daily_orchestrator import DailyOrchestratorError,DailyPlaybookOrchestrator,TERMINAL


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛每日Playbook编排器；只运行已创建的宿主计划，不隐式授权数据下载')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root',required=True);parser.add_argument('--trading-day',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--init',action='store_true');group.add_argument('--tick',action='store_true')
    group.add_argument('--status',action='store_true');group.add_argument('--run',action='store_true')
    parser.add_argument('--as-of-session');parser.add_argument('--definition-id');parser.add_argument('--target-streak',type=int)
    parser.add_argument('--allow-daily-market-capture',action='store_true');parser.add_argument('--poll-seconds',type=int,default=60)
    args=parser.parse_args(argv)
    try:
        service=DailyPlaybookOrchestrator(Path(args.output),Path(args.data_root))
        if args.init:
            if not args.as_of_session or not args.definition_id:parser.error('--init 需要 --as-of-session 与 --definition-id')
            result=service.create_plan(args.trading_day,args.as_of_session,args.definition_id,
                target_streak=args.target_streak,allow_daily_market_capture=args.allow_daily_market_capture)
        elif args.status:result=service.get(args.trading_day)
        elif args.tick:result=service.tick(args.trading_day)
        else:
            if not 30<=args.poll_seconds<=3600:raise ValueError('poll-seconds 必须为30–3600。')
            while True:
                result=service.tick(args.trading_day);print(encode({'ok':True,'data':result}),flush=True)
                if result['status'] in TERMINAL:return 0
                time.sleep(args.poll_seconds)
        print(encode({'ok':True,'data':result}));return 0
    except (DailyOrchestratorError,OSError,ValueError,KeyError,TypeError) as error:
        code=getattr(error,'code','INVALID_REQUEST')
        print(encode({'ok':False,'error':{'code':code,'message':str(error)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())
