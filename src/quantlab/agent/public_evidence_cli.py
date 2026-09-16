"""Host CLI for after-close public market evidence capture; capture is explicit network I/O."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from quantlab.data.public_evidence import TZ, PublicEvidenceArchive, PublicEvidenceError
from quantlab.storage.codec import encode


def main(argv=None):
    parser = argparse.ArgumentParser(description='公开市场证据收盘后归档（东方财富网页接口，research_only）；capture 会联网')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('sources', 'capture', 'capture-all', 'list', 'get', 'read', 'accept-revision', 'overview'))
    parser.add_argument('--source', default='')
    parser.add_argument('--date', default='')
    parser.add_argument('--capture-id', default='')
    parser.add_argument('--allow-late', action='store_true')
    parser.add_argument('--confirm-revision', action='store_true')
    args = parser.parse_args(argv)
    try:
        archive = PublicEvidenceArchive(Path(args.output))
        day = args.date or datetime.now(TZ).date().isoformat()
        if args.call == 'sources':
            data = {'sources': [{'source_id': s.source_id, 'description': s.description, 'parser_version': s.parser_version}
                                for s in archive.sources.values()]}
        elif args.call == 'overview':
            data = archive.overview()
        elif args.call == 'capture-all':
            results = {}
            for source_id in archive.sources:
                try:
                    manifest = archive.capture(source_id, day, allow_late=args.allow_late)
                    results[source_id] = {'ok': True, 'rows': manifest['rows'], 'created': manifest['created'],
                                          'capture_timing': manifest['capture_timing'], 'warnings': manifest['warnings']}
                except PublicEvidenceError as error:
                    results[source_id] = {'ok': False, 'code': error.code, 'message': str(error)[:300]}
            data = {'trading_day': day, 'results': results}
            if not all(item['ok'] for item in results.values()):
                print(encode({'ok': False, 'data': data, 'error': {'code': 'PARTIAL_FAILURE', 'message': '部分来源失败'}}))
                return 2
        else:
            if not args.source:
                raise ValueError(args.call + ' 需要 --source。')
            if args.call == 'capture':
                data = archive.capture(args.source, day, allow_late=args.allow_late)
            elif args.call == 'list':
                data = {'days': archive.list_days(args.source)}
            elif args.call == 'get':
                data = archive.get(args.source, day, args.capture_id or None)
            elif args.call == 'read':
                frame, manifest = archive.read_table(args.source, day, args.capture_id or None)
                data = {'manifest': manifest, 'rows': frame.head(500).to_dicts(), 'truncated': frame.height > 500}
            else:
                data = archive.accept_revision(args.source, day, args.capture_id, confirmed=args.confirm_revision)
        result = {'ok': True, 'data': data}
    except (PublicEvidenceError, ValueError, OSError) as error:
        code = error.code if isinstance(error, PublicEvidenceError) else 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
