"""Host-side read-only data review; no download, repair, export or execution commands."""
from __future__ import annotations

import argparse
from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI
from quantlab.storage.codec import encode
from quantlab.data.rights_candidates import add_rights_binding_arguments, rights_binding_from_arguments


class _NoOtherTools:
    def schemas(self):
        return []

    def call(self, name, args):
        raise ValueError('This command supports only explicit read-only review tools')


def main(argv=None):
    parser = argparse.ArgumentParser(description='牛牛只读覆盖和公司行动候选复核；不改库、不重算因子')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('contract', help='只读取复权候选复核合同，不需要数据根')
    coverage = commands.add_parser('tdx-coverage', help='查询一个TDX族的实际聚合覆盖')
    coverage.add_argument('--data-root', required=True)
    coverage.add_argument('--family', required=True)
    coverage.add_argument('--symbol', default='')
    coverage.add_argument('--start', default='')
    coverage.add_argument('--end', default='')
    action = commands.add_parser('corporate-actions', help='读取一个证券的公司行动候选与来源差异')
    action.add_argument('--data-root', required=True)
    action.add_argument('--symbol', required=True)
    action.add_argument('--start', required=True)
    action.add_argument('--end', required=True)
    action.add_argument('--offset', type=int, default=0)
    action.add_argument('--limit', type=int, default=20)
    for command in ('calendar', 'daily-coverage'):
        sub = commands.add_parser(command, help='显式来源日历/日期集合只读核对')
        sub.add_argument('--source', required=True, choices=('baostock_bronze', 'retro_capture', 'archived_dataset'))
        sub.add_argument('--data-root')
        sub.add_argument('--source-workspace')
        sub.add_argument('--capture-id', default='')
        sub.add_argument('--start', required=True)
        sub.add_argument('--end', required=True)
        if command == 'daily-coverage':
            sub.add_argument('--symbols', required=True)
    for command in ('rights-manifest', 'rights-query'):
        sub = commands.add_parser(command, help='显式指纹绑定的配股候选只读核对')
        add_rights_binding_arguments(sub, required=True)
        if command == 'rights-query':
            sub.add_argument('--symbol', default='')
            sub.add_argument('--start', required=True)
            sub.add_argument('--end', required=True)
            sub.add_argument('--status', required=True, choices=('all','exact','small','conflicts','cninfo_none'))
            sub.add_argument('--offset', type=int, default=0)
            sub.add_argument('--limit', type=int, default=10)
    parsed = parser.parse_args(argv)
    try:
        binding = rights_binding_from_arguments(parsed)
    except ValueError as exc:
        from quantlab.agent.archived_data_tools import _error
        print(encode(_error(parsed.command, getattr(exc, 'code', 'INVALID_BINDING'), str(exc))))
        return 2
    api = ArchivedMarketDataAPI(_NoOtherTools(), None, getattr(parsed, 'data_root', None),
                                source_workspace=getattr(parsed, 'source_workspace', None),
                                rights_candidate_binding=binding)
    if parsed.command == 'contract':
        name, arguments = 'get_adjustment_review_contract', {}
    elif parsed.command in ('rights-manifest', 'rights-query'):
        name = 'get_rights_candidate_manifest' if parsed.command == 'rights-manifest' else 'query_rights_candidates'
        arguments = {} if parsed.command == 'rights-manifest' else {
            key: getattr(parsed, key) for key in ('symbol','start','end','status','offset','limit')}
    elif parsed.command in ('calendar', 'daily-coverage'):
        name = 'get_trading_calendar' if parsed.command == 'calendar' else 'check_daily_date_coverage'
        keys = ['source', 'capture_id', 'start', 'end']
        if parsed.command == 'daily-coverage':
            keys.append('symbols')
        arguments = {key: getattr(parsed, key) for key in keys}
    elif parsed.command == 'tdx-coverage':
        name = 'get_tdx_data_coverage'
        arguments = {key: getattr(parsed, key) for key in ('family', 'symbol', 'start', 'end')}
    else:
        name = 'inspect_corporate_action_sources'
        arguments = {key: getattr(parsed, key) for key in ('symbol', 'start', 'end', 'offset', 'limit')}
    result = api.call(name, arguments)
    print(encode(result))
    if not result.get('ok'):
        return 2
    # A completed read can be incomplete; differences alone do not mean an API failure.
    data = result.get('data') or {}
    return 3 if data.get('incomplete') else 0


if __name__ == '__main__':
    raise SystemExit(main())
