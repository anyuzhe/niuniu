"""Host CLI for explicit Playbook PaperPlan creation and simulated execution."""
from __future__ import annotations

import argparse,json
from pathlib import Path

import polars as pl

from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode
from quantlab.trading.playbook_paper_plan import PlaybookPaperPlanError,PlaybookPaperPlanService


def _json(path,maximum=2_000_000):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>maximum:
        raise ValueError('JSON 输入不存在、为符号链接或超过大小限制。')
    return json.loads(target.read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(description='Playbook PaperPlan；PLAN_OPEN + 显式确认后才允许模拟执行，不连接券商')
    parser.add_argument('--output',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create',action='store_true');group.add_argument('--execute',action='store_true')
    group.add_argument('--status',action='store_true');group.add_argument('--list',action='store_true')
    parser.add_argument('--selection-id');parser.add_argument('--decision-id',action='append',default=[])
    parser.add_argument('--account-name');parser.add_argument('--target-weights-json');parser.add_argument('--plan-id')
    parser.add_argument('--bars-parquet');parser.add_argument('--rules-json');parser.add_argument('--config-json')
    parser.add_argument('--backend',choices=('open','vnpy_rules'),default='open');parser.add_argument('--dynamic',action='store_true',help='使用长期动态-universe PaperAccount');parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args(argv)
    try:
        service=PlaybookPaperPlanService(Path(args.output))
        if args.create:
            if not all((args.selection_id,args.decision_id,args.account_name,args.target_weights_json)):
                raise ValueError('--create 需要 selection-id / decision-id / account-name / target-weights-json。')
            weights=_json(args.target_weights_json,256000)
            data=service.create(args.selection_id,args.decision_id,args.account_name,weights,confirmed=args.confirm)
        elif args.execute:
            if not all((args.plan_id,args.bars_parquet,args.rules_json)):
                raise ValueError('--execute 需要 plan-id / bars-parquet / rules-json。')
            rules_value=_json(args.rules_json)
            if not isinstance(rules_value,list):raise ValueError('rules-json 必须是 MarketRules 记录数组。')
            config=ExecutionConfig(**_json(args.config_json,256000)) if args.config_json else ExecutionConfig(price_mode='account')
            data=(service.execute_dynamic(args.plan_id,pl.read_parquet(args.bars_parquet),MarketRules(rules_value),config,args.backend,confirmed=args.confirm) if args.dynamic else service.execute(args.plan_id,pl.read_parquet(args.bars_parquet),MarketRules(rules_value),config,args.backend,confirmed=args.confirm))
        elif args.status:
            if not args.plan_id:raise ValueError('--status 需要 --plan-id。')
            data=service.get(args.plan_id)
        else:data={'records':service.list(),'paper_execution_model':'explicit_host_confirmed_simulation_only'}
        print(encode({'ok':True,'data':data}));return 0
    except (PlaybookPaperPlanError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','INVALID_REQUEST'),'message':str(error)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())
