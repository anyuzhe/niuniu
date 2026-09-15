"""Host CLI for verified security-status materialization; no network access."""
from __future__ import annotations

import argparse,json
from pathlib import Path

from quantlab.data.security_status import load_security_status,materialize_security_status
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 Strict PIT security_status；仅从已验证 receipt 物化，不联网下载')
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--call',choices=('status','materialize'),default='status')
    args=parser.parse_args(argv)
    try:
        root=Path(args.data_root)
        if args.call=='materialize':
            data=materialize_security_status(root)
        else:
            try:
                frame,manifest=load_security_status(root)
                data={'configured':True,'rows':frame.height,'manifest':manifest,
                    'symbols':frame['symbol'].n_unique() if frame.height else 0}
            except ValueError as error:
                if 'missing' not in str(error):raise
                data={'configured':False,'rows':0,'reason':str(error)}
        result={'ok':True,'data':data};code=0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as error:
        result={'ok':False,'error':{'code':'SECURITY_STATUS_ERROR','message':str(error)[:500]}};code=2
    print(encode(result));return code


if __name__=='__main__':raise SystemExit(main())