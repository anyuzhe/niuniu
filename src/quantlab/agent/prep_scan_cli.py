import argparse,json
from pathlib import Path
from uuid import uuid4

from quantlab.storage.codec import encode
from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore
from quantlab.trading.playbook_forward import freeze_forward_snapshot
from quantlab.trading.playbook_store import PlaybookError,PlaybookStore
from quantlab.trading.prep_scanner import (
    PrepScanError,build_prep_forward_payload,prep_market_snapshot_content,scan_prep_universe,
)


def _read_json(path):
    if not path:return None
    source=Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size>10_000_000:
        raise ValueError('JSON输入路径无效或超过10MB。')
    return json.loads(source.read_text())


def _symbols(path):
    value=_read_json(path)
    if value is None:return None
    if not isinstance(value,list):raise ValueError('universe JSON 必须是证券字符串数组。')
    return value
def main():
    parser=argparse.ArgumentParser(description='全市场PREP扫描；默认只读，证据不足时fail-closed为PARTIAL/UNKNOWN')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root',required=True)
    parser.add_argument('--as-of-session',required=True,help='用于连板/市场状态计算的最近收盘交易日')
    parser.add_argument('--trading-day',required=True,help='本次PREP对应的目标交易日')
    parser.add_argument('--target-streak',type=int,help='宿主显式覆盖目标身位；不等于专家规则')
    parser.add_argument('--market-rules-json');parser.add_argument('--universe-json')
    parser.add_argument('--snapshot-as-of',help='带时区ISO时间；默认使用当前Asia/Shanghai时钟')
    parser.add_argument('--save-snapshot',action='store_true')
    parser.add_argument('--freeze',action='store_true',help='保存快照并尝试冻结PREP SYSTEM_PREDICTION')
    parser.add_argument('--definition-id',help='--freeze时必须显式指定PlaybookDefinition UUID')
    args=parser.parse_args()
    try:
        if args.freeze and not args.definition_id:raise ValueError('--freeze 必须提供 --definition-id。')
        rules=_read_json(args.market_rules_json);universe=_symbols(args.universe_json)
        scan=scan_prep_universe(args.data_root,args.as_of_session,target_streak=args.target_streak,
            market_rules=rules,universe_symbols=universe,universe_pit_verified=False)
        result={'ok':True,'scan':scan,'snapshot':None,'freeze':None}
        if args.save_snapshot or args.freeze:
            if args.snapshot_as_of:as_of=args.snapshot_as_of
            else:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                as_of=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
            content=prep_market_snapshot_content(scan,args.trading_day,as_of,args.data_root)
            snapshot=MarketSnapshotStore(args.output).create(str(uuid4()),content);result['snapshot']=snapshot
            if args.freeze:
                definition=PlaybookStore(args.output).get_definition(args.definition_id)
                payload=build_prep_forward_payload(scan,snapshot,definition)
                result['freeze']=freeze_forward_snapshot(args.output,payload)
        print(encode(result));raise SystemExit(0)
    except (PrepScanError,MarketSnapshotError,PlaybookError,ValueError,OSError,json.JSONDecodeError) as exc:
        code=getattr(exc,'code','PREP_SCAN_FAILED')
        print(encode({'ok':False,'error':{'code':code,'message':str(exc)[:500]}}));raise SystemExit(2)


if __name__=='__main__':main()
