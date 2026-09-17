"""Host CLI for verifiable limit-board forecasts: catalog, record (host), baselines, resolve, scorecard; no network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from quantlab.storage.codec import encode
from quantlab.trading.limit_forecasts import ForecastError, LimitForecastJournal, question_catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description='打板可验证预测（research_only）：开盘 09:15 前记录、收盘后按情绪指标判定并计 Brier 分数')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('questions', 'record', 'list', 'baselines', 'resolve', 'scorecard'))
    parser.add_argument('--date', default='', help='目标交易日 YYYY-MM-DD')
    parser.add_argument('--forecaster', default='host:manual')
    parser.add_argument('--question', default='')
    parser.add_argument('--probability', type=float, default=None)
    parser.add_argument('--rationale', default='')
    args = parser.parse_args(argv)
    try:
        journal = LimitForecastJournal(Path(args.output))
        if args.call == 'questions':
            data = question_catalog()
        elif args.call == 'scorecard':
            data = journal.scorecard()
        else:
            if not args.date:
                raise ValueError(args.call + ' 需要 --date。')
            if args.call == 'record':
                if not args.forecaster.startswith('host:'):
                    raise ValueError('命令行只能记录 host: 预测。')
                data = journal.record(request_id=str(uuid4()), forecaster=args.forecaster, question_id=args.question, target_day=args.date,
                                      probability=args.probability, rationale=args.rationale)
            elif args.call == 'list':
                data = {'forecasts': journal.forecasts(args.date), 'resolution': journal.resolution(args.date)}
            elif args.call == 'baselines':
                data = journal.generate_baselines(args.date)
            else:
                data = journal.resolve(args.date)
        result = {'ok': True, 'data': data}
    except (ForecastError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
