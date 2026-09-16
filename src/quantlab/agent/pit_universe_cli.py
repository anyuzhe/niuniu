"""Host CLI for prospective PIT Universe receipts; never performs network I/O."""
from __future__ import annotations

import argparse,json
from pathlib import Path

from quantlab.data.pit_universe import (
    PITUniverseError,archive_pit_universe,audit_pit_universe,load_pit_universe_snapshot,
)
from quantlab.storage.codec import encode


def _plan(path):
    target=Path(path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>10_000_000:
        raise PITUniverseError('INVALID_PLAN','plan file is missing, symlinked, or exceeds 10MB')
    value=json.loads(target.read_text())
    if not isinstance(value,dict):raise PITUniverseError('INVALID_PLAN','plan must be a JSON object')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 PIT Universe Receipt v1；只归档本地官方原文，不自动联网或历史回填')
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--call',required=True,choices=('archive','audit','get'))
    parser.add_argument('--plan');parser.add_argument('--snapshot');parser.add_argument('--effective-session')
    parser.add_argument('--confirm-publication-times',action='store_true')
    parser.add_argument('--confirm-semantic-mapping',action='store_true')
    parser.add_argument('--confirm-complete-official-universe',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.call=='archive':
            if not args.plan:raise PITUniverseError('INVALID_PLAN','archive requires --plan')
            data=archive_pit_universe(args.data_root,_plan(args.plan),
                confirm_publication_times=args.confirm_publication_times,
                confirm_semantic_mapping=args.confirm_semantic_mapping,
                confirm_complete_official_universe=args.confirm_complete_official_universe)
        elif args.call=='get':
            if not args.snapshot:raise PITUniverseError('INVALID_SNAPSHOT','get requires --snapshot')
            data=load_pit_universe_snapshot(args.data_root,args.snapshot,effective_session=args.effective_session)
        else:data=audit_pit_universe(args.data_root)
        result={'ok':True,'data':data};code=0
    except (PITUniverseError,OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as error:
        result={'ok':False,'error':{'code':getattr(error,'code','PIT_UNIVERSE_ERROR'),'message':str(error)[:500]}};code=2
    print(encode(result));return code


if __name__=='__main__':raise SystemExit(main())
