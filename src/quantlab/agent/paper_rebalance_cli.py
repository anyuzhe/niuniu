"""Host CLI for confirmed Dynamic Paper ADD/REDUCE/EXIT rebalance plans."""
import argparse,json
from pathlib import Path
import polars as pl
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode
from quantlab.trading.paper_rebalance import PaperRebalanceError,PaperRebalancePlanService

def _json(path,maximum=2_000_000):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>maximum:raise ValueError('JSON 输入不存在、为符号链接或超过大小限制。')
    return json.loads(target.read_text())

def main(argv=None):
    parser=argparse.ArgumentParser(description='长期动态 Paper 再平衡；只允许已有证券 ADD/REDUCE/EXIT')
    parser.add_argument('--output',required=True);group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--create',action='store_true');group.add_argument('--execute',action='store_true');group.add_argument('--status',action='store_true');group.add_argument('--list',action='store_true')
    parser.add_argument('--account-name');parser.add_argument('--decision-id',action='append',default=[]);parser.add_argument('--target-weights-json');parser.add_argument('--plan-id')
    parser.add_argument('--bars-parquet');parser.add_argument('--rules-json');parser.add_argument('--config-json');parser.add_argument('--backend',choices=('open','vnpy_rules'),default='open');parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args(argv)
    try:
        service=PaperRebalancePlanService(Path(args.output))
        if args.create:
            if not all((args.account_name,args.decision_id,args.target_weights_json)):raise ValueError('--create 需要 account-name / decision-id / target-weights-json。')
            data=service.create(args.account_name,args.decision_id,_json(args.target_weights_json,256000),confirmed=args.confirm)
        elif args.execute:
            if not all((args.plan_id,args.bars_parquet,args.rules_json)):raise ValueError('--execute 需要 plan-id / bars-parquet / rules-json。')
            raw=_json(args.rules_json);config=ExecutionConfig(**_json(args.config_json,256000)) if args.config_json else None
            data=service.execute(args.plan_id,pl.read_parquet(args.bars_parquet),MarketRules(raw),config,args.backend,confirmed=args.confirm)
        elif args.status:
            if not args.plan_id:raise ValueError('--status 需要 --plan-id。')
            data=service.get(args.plan_id)
        else:data={'records':service.list()}
        print(encode({'ok':True,'data':data}));return 0
    except (PaperRebalanceError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:
        print(encode({'ok':False,'error':{'code':getattr(error,'code','INVALID_REQUEST'),'message':str(error)[:500]}}));return 2
if __name__=='__main__':raise SystemExit(main())
