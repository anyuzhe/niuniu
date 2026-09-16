"""Host CLI for pre-registered limit-board event studies; local computation only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.event_study import EventStudyError, EventStudyRegistry


def main(argv=None):
    parser = argparse.ArgumentParser(description='涨停事件研究：先登记冻结规格，再计算；同 family Holm 校正（research_only）')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('register', 'run', 'get', 'report'))
    parser.add_argument('--spec', default='', help='研究规格 JSON 文件路径')
    parser.add_argument('--family', default='')
    parser.add_argument('--study-id', default='')
    args = parser.parse_args(argv)
    try:
        registry = EventStudyRegistry(Path(args.output))
        if args.call == 'register':
            if not args.spec:
                raise ValueError('register 需要 --spec。')
            spec_path = Path(args.spec)
            if spec_path.stat().st_size > 20000:
                raise ValueError('规格文件过大。')
            data = registry.register(json.loads(spec_path.read_text(encoding='utf-8')))
        elif args.call == 'report':
            if not args.family:
                raise ValueError('report 需要 --family。')
            data = registry.family_report(args.family)
        else:
            if not args.family or not args.study_id:
                raise ValueError(args.call + ' 需要 --family 与 --study-id。')
            data = registry.run(args.family, args.study_id) if args.call == 'run' else registry.get(args.family, args.study_id)
        result = {'ok': True, 'data': data}
    except (EventStudyError, ValueError, OSError) as error:
        code = error.code if isinstance(error, EventStudyError) else 'INVALID_REQUEST'
        result = {'ok': False, 'error': {'code': code, 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
