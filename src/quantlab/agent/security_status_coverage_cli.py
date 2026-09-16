"""Host CLI for complete daily SecurityStatus v2 receipts; never performs network I/O."""
from __future__ import annotations

import argparse,json
from pathlib import Path

from quantlab.data.security_status_coverage import (SecurityStatusCoverageError,
    archive_security_status_coverage,audit_security_status_coverage,
    load_security_status_coverage_snapshot,security_status_chain)
from quantlab.storage.codec import encode


def _plan(path):
    target=Path(path).expanduser()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>20_000_000:
        raise SecurityStatusCoverageError('INVALID_PLAN','plan file is missing, symlinked, or exceeds 20MB')
    value=json.loads(target.read_text())
    if not isinstance(value,dict):raise SecurityStatusCoverageError('INVALID_PLAN','plan must be a JSON object')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 SecurityStatus v2；离线归档全Universe逐日状态与显式连续链')
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--call',required=True,choices=('archive','audit','get','chain'))
    parser.add_argument('--plan');parser.add_argument('--snapshot');parser.add_argument('--effective-session');parser.add_argument('--symbol')
    parser.add_argument('--confirm-publication-times',action='store_true')
    parser.add_argument('--confirm-semantic-mapping',action='store_true')
    parser.add_argument('--confirm-complete-daily-status',action='store_true')
    parser.add_argument('--confirm-previous-session-continuity',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.call=='archive':
            if not args.plan:raise SecurityStatusCoverageError('INVALID_PLAN','archive requires --plan')
            data=archive_security_status_coverage(args.data_root,_plan(args.plan),
                confirm_publication_times=args.confirm_publication_times,
                confirm_semantic_mapping=args.confirm_semantic_mapping,
                confirm_complete_daily_status=args.confirm_complete_daily_status,
                confirm_previous_session_continuity=args.confirm_previous_session_continuity)
        elif args.call=='get':
            if not args.snapshot:raise SecurityStatusCoverageError('INVALID_SNAPSHOT','get requires --snapshot')
            data=load_security_status_coverage_snapshot(args.data_root,args.snapshot,effective_session=args.effective_session)
        elif args.call=='chain':
            if not args.symbol:raise SecurityStatusCoverageError('INVALID_SYMBOL','chain requires --symbol')
            data=security_status_chain(args.data_root,args.symbol)
        else:data=audit_security_status_coverage(args.data_root)
        result={'ok':True,'data':data};code=0
    except (SecurityStatusCoverageError,OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as error:
        result={'ok':False,'error':{'code':getattr(error,'code','SECURITY_STATUS_COVERAGE_ERROR'),
            'message':str(error)[:500]}};code=2
    print(encode(result));return code


if __name__=='__main__':raise SystemExit(main())
