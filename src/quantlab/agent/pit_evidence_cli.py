"""Host CLI for archived point-in-time evidence receipts; no hidden network access."""
from __future__ import annotations

import argparse,json
from pathlib import Path

from quantlab.data.pit_evidence import KINDS,archive_pit_evidence,list_pit_evidence,verify_pit_statements
from quantlab.storage.codec import encode


def _statements(path):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>5_000_000:
        raise ValueError('statements file missing/symlink/too large')
    value=json.loads(target.read_text())
    if isinstance(value,dict):value=[value]
    if not isinstance(value,list) or not value:raise ValueError('statements must be a nonempty JSON object/list')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 Strict PIT evidence archive/verify；只归档本地官方原文，不自动联网下载')
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--call',required=True,choices=('list','verify','archive'))
    parser.add_argument('--kind',choices=KINDS)
    parser.add_argument('--statements',default='')
    parser.add_argument('--source-url',default='');parser.add_argument('--published-at',default='');parser.add_argument('--document',default='')
    parser.add_argument('--confirm-publication-time',action='store_true')
    args=parser.parse_args(argv)
    try:
        root=Path(args.data_root)
        if args.call=='list':data=list_pit_evidence(root)
        else:
            if not args.kind or not args.statements:raise ValueError('verify/archive require --kind and --statements')
            rows=_statements(args.statements)
            if args.call=='verify':data=verify_pit_statements(root,args.kind,rows)
            else:
                if not args.source_url or not args.published_at or not args.document:
                    raise ValueError('archive requires --source-url --published-at --document')
                data=archive_pit_evidence(root,args.kind,rows,args.source_url,args.published_at,args.document,
                    confirm_publication_time=args.confirm_publication_time)
        result={'ok':True,'data':data};code=0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as error:
        result={'ok':False,'error':{'code':'PIT_EVIDENCE_ERROR','message':str(error)[:500]}};code=2
    print(encode(result));return code


if __name__=='__main__':raise SystemExit(main())
