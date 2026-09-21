"""Host CLI for Playbook selection outcome reviews (selected vs unselected within the frozen CandidateSet)."""
import argparse
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.trading.selection_outcomes import SelectionOutcomeError, SelectionOutcomeService


def _windows(text):
    if text is None:
        return None
    try:
        return [int(part) for part in text.split(',') if part.strip()]
    except ValueError:
        raise ValueError('--windows 必须是逗号分隔的整数，例如 0,1,2,3,5,10。') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Playbook 选择结果复盘：同一冻结候选集内“选中 vs 未选中”的信号收益对照；'
                                                 '只生成研究证据，不自动调权，不写 Decision/Intent/Paper')
    parser.add_argument('--output', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--selection-id')
    group.add_argument('--auto-all', action='store_true')
    group.add_argument('--get')
    group.add_argument('--list', action='store_true')
    group.add_argument('--summary', action='store_true')
    parser.add_argument('--windows', help='逗号分隔的交易日窗口；默认 0,1,2,3,5,10（D0 仅盘前 PREP）')
    parser.add_argument('--kind', default='')
    parser.add_argument('--definition-id', default='')
    parser.add_argument('--frame', default='')
    parser.add_argument('--limit', type=int, default=2000)
    parser.add_argument('--full', action='store_true', help='--list/--get 输出包含逐证券结果')
    args = parser.parse_args(argv)
    try:
        service = SelectionOutcomeService(Path(args.output))
        windows = _windows(args.windows)
        if args.selection_id:
            data = service.build(args.selection_id, windows)
            if not args.full:
                data = {**data, 'records': [service.compact(row) for row in data['records']]}
        elif args.auto_all:
            data = service.auto_all(windows, kind=args.kind, limit=args.limit)
        elif args.get:
            data = service.get(args.get)
            if not args.full:
                data = {**data, 'records': [service.compact(row) for row in data['records']]}
        elif args.list:
            data = service.list(args.definition_id, args.kind, args.frame, limit=min(args.limit, 1000))
        else:
            data = service.summary(args.definition_id, args.kind, args.frame)
        print(encode({'ok': True, 'data': data}))
        return 0
    except (SelectionOutcomeError, OSError, ValueError, KeyError, TypeError) as error:
        print(encode({'ok': False, 'error': {'code': getattr(error, 'code', 'INVALID_REQUEST'), 'message': str(error)[:500]}}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
