"""Host-only preparation of bounded archived daily research inputs; never runs research."""
from __future__ import annotations

import argparse

from quantlab.storage.codec import encode


def main(argv=None):
    parser = argparse.ArgumentParser(description='已存回溯日线 → 明确版本研究输入；不下载、不批准、不执行')
    actions = parser.add_subparsers(dest='action', required=True)
    for action in ('preview', 'export'):
        command = actions.add_parser(action)
        command.add_argument('--source-workspace', required=True)
        command.add_argument('--capture-id', required=True)
        command.add_argument('--symbols', nargs='+', required=True)
        command.add_argument('--start', required=True)
        command.add_argument('--end', required=True)
        command.add_argument('--contract', choices=('tradable_only_v1','preserve_suspension_state_v2'), default='tradable_only_v1')
        if action == 'export':
            command.add_argument('--destination', required=True)
            command.add_argument('--expected-preview-hash', required=True)
            command.add_argument('--confirm-create', action='store_true', help='仅确认创建全新输入包，不批准研究')
    inspect = actions.add_parser('inspect')
    inspect.add_argument('--data-root', required=True)
    args = parser.parse_args(argv)
    try:
        from quantlab.data.archived_daily_dataset import (
            preview_archived_daily_dataset, export_archived_daily_dataset, inspect_archived_daily_dataset,
        )
        if args.action == 'inspect':
            data = inspect_archived_daily_dataset(args.data_root)
        else:
            selected = (args.source_workspace, args.capture_id, ' '.join(args.symbols), args.start, args.end)
            if args.action == 'preview':
                data = preview_archived_daily_dataset(*selected, contract=args.contract)
            else:
                if not args.confirm_create:
                    raise ValueError('export requires --confirm-create; no files were created')
                data = export_archived_daily_dataset(*selected, args.destination,
                    expected_preview_hash=args.expected_preview_hash, confirmed=True, contract=args.contract)
        print(encode({'ok': True, 'data': data, 'error': None, 'research_executed': False,
                      'research_approved': False}))
        return 0
    except Exception as error:
        # CLI boundary: report nonzero failure, not an empty success or implicit retry.
        print(encode({'ok': False, 'data': None,
                      'error': {'code': 'ARCHIVED_DAILY_DATASET_FAILED',
                                'message': type(error).__name__ + ': ' + str(error)[:600]},
                      'research_executed': False, 'research_approved': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
