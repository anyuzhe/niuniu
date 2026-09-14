"""CLI for time-gated forward Expert Playbook snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.playbook_forward import forward_frame_status,freeze_forward_snapshot
from quantlab.trading.playbook_store import PlaybookError


def _load_payload(path):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise ValueError('payload 文件不存在或为符号链接。')
    if target.stat().st_size>256000:
        raise ValueError('payload 文件超过256KB。')
    value=json.loads(target.read_text())
    if not isinstance(value,dict):raise ValueError('payload 必须是 JSON 对象。')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='期末50分/Expert Playbook 前瞻冻结；不联网下载行情')
    parser.add_argument('--output',required=True)
    parser.add_argument('--trading-day',required=True)
    parser.add_argument('--frame',required=True,choices=('PREP','AUCTION','R1'))
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--status',action='store_true')
    group.add_argument('--payload')
    args=parser.parse_args(argv)
    try:
        if args.status:
            from datetime import datetime
            result={'ok':True,'status':forward_frame_status(Path(args.output),
                args.trading_day,args.frame,lambda:datetime.now().astimezone())}
        else:
            value=_load_payload(args.payload)
            if value.get('trading_day')!=args.trading_day or value.get('frame')!=args.frame:
                raise ValueError('payload 的 trading_day/frame 必须与 CLI 参数一致。')
            result=freeze_forward_snapshot(Path(args.output),value)
    except (PlaybookError,ValueError,OSError,json.JSONDecodeError) as error:
        code=error.code if isinstance(error,PlaybookError) else 'INVALID_REQUEST'
        result={'ok':False,'error':{'code':code,'message':str(error)[:400]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())
