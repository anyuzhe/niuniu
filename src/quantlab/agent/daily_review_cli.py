"""Host CLI for the layered daily limit-board close review; local computation over research datasets, no network."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from quantlab.data.public_evidence import TZ
from quantlab.storage.codec import encode
from quantlab.trading.daily_review import DailyReviewError, DailyReviewLibrary, render_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(description='打板情绪收盘复盘（事实/机器状态/评论分层，research_only）；annotate 只追加评论，不改事实')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('list', 'build', 'get', 'markdown', 'annotate'))
    parser.add_argument('--date', default='')
    parser.add_argument('--review-id', default='')
    parser.add_argument('--text-file', default='')
    parser.add_argument('--author', default='')
    parser.add_argument('--kind', default='host', choices=('host', 'ai'))
    args = parser.parse_args(argv)
    try:
        library = DailyReviewLibrary(Path(args.output))
        day = args.date or datetime.now(TZ).date().isoformat()
        if args.call == 'list':
            data = {'days': library.list_days()}
        elif args.call == 'build':
            data = library.build(day)
        elif args.call == 'get':
            data = library.get(day, args.review_id or None)
        elif args.call == 'markdown':
            data = {'markdown': render_markdown(library.get(day, args.review_id or None))}
        else:
            if not args.text_file or not args.review_id:
                raise ValueError('annotate 需要 --review-id 与 --text-file。')
            path = Path(args.text_file)
            if path.stat().st_size > 64000:
                raise ValueError('评论文件过大。')
            data = library.annotate(day, args.review_id, text=path.read_text(encoding='utf-8'), author=args.author, kind=args.kind)
        result = {'ok': True, 'data': data}
    except (DailyReviewError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
