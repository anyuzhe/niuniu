"""Host-side read-only data review; no download, repair, export or execution commands."""
from __future__ import annotations

import argparse
from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI
from quantlab.storage.codec import encode
from quantlab.data.rights_candidates import add_rights_binding_arguments, rights_binding_from_arguments
from quantlab.data.rights_conflict_evidence import add_rights_evidence_binding_arguments, rights_evidence_binding_from_arguments
from quantlab.data.version_ledger import add_version_ledger_binding_arguments, version_ledger_binding_from_arguments


class _NoOtherTools:
    def schemas(self):
        return []

    def call(self, name, args):
        raise ValueError('This command supports only explicit read-only review tools')


def main(argv=None):
    parser = argparse.ArgumentParser(description='牛牛只读覆盖和公司行动候选复核；不改库、不重算因子')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('contract', help='只读取复权候选复核合同，不需要数据根')
    commands.add_parser('rights-preview-contract', help='读取配股事件预览合同，不读取数据')
    catalog_list = commands.add_parser('data-catalog-list', help='列出DATA交付清单；默认只看READY')
    catalog_list.add_argument('--catalog')
    catalog_list.add_argument('--status', default='READY', choices=('READY','NOT_READY','REVIEW_REQUIRED','DEPRECATED','ALL'))
    catalog_list.add_argument('--delivery', default='ALL', choices=('FILE','DATABASE','API','STREAM','ALL'))
    catalog_list.add_argument('--offset', type=int, default=0)
    catalog_list.add_argument('--limit', type=int, default=20)
    catalog_get = commands.add_parser('data-catalog-get', help='取得一个DATA已标记READY的数据入口')
    catalog_get.add_argument('--catalog')
    catalog_get.add_argument('--dataset-id', required=True)
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
    for command in ('rights-manifest', 'rights-query', 'rights-preview'):
        sub = commands.add_parser(command, help='显式指纹绑定的配股候选只读核对')
        add_rights_binding_arguments(sub, required=True)
        if command == 'rights-preview':
            sub.add_argument('--request-json', required=True, help='完整预览请求JSON；只输出草案，不写因子')
        if command == 'rights-query':
            sub.add_argument('--symbol', default='')
            sub.add_argument('--start', required=True)
            sub.add_argument('--end', required=True)
            sub.add_argument('--status', required=True, choices=('all','exact','small','conflicts','cninfo_none'))
            sub.add_argument('--offset', type=int, default=0)
            sub.add_argument('--limit', type=int, default=10)
    for command in ('rights-evidence-manifest', 'rights-evidence-query'):
        sub = commands.add_parser(command, help='显式指纹绑定的未决配股补充证据只读核对')
        add_rights_binding_arguments(sub, required=True)
        add_rights_evidence_binding_arguments(sub, required=True)
        if command == 'rights-evidence-query':
            sub.add_argument('--symbol', default='')
            sub.add_argument('--start', required=True)
            sub.add_argument('--end', required=True)
            sub.add_argument('--offset', type=int, default=0)
            sub.add_argument('--limit', type=int, default=5)
    # rights-preview可选择额外绑定S1证据；不绑定时保持F18原行为。
    add_rights_evidence_binding_arguments(commands.choices['rights-preview'])
    for command in ('version-ledger-manifest','version-ledger-query','version-selection-preview'):
        sub = commands.add_parser(command, help='显式双SHA绑定的F21观察/修订版本账本只读核对')
        add_version_ledger_binding_arguments(sub, required=True)
        if command == 'version-ledger-query':
            sub.add_argument('--domain', default='')
            sub.add_argument('--event-type', default='')
            sub.add_argument('--event-id', default='')
            sub.add_argument('--source-id', default='')
            sub.add_argument('--offset', type=int, default=0)
            sub.add_argument('--limit', type=int, default=20)
        if command == 'version-selection-preview':
            sub.add_argument('--request-json', required=True)
    commands.add_parser('version-selection-contract', help='读取F21版本选择合同，不读取账本')
    parsed = parser.parse_args(argv)
    try:
        binding = rights_binding_from_arguments(parsed)
        evidence_binding = rights_evidence_binding_from_arguments(parsed)
        version_binding = version_ledger_binding_from_arguments(parsed)
    except ValueError as exc:
        from quantlab.agent.archived_data_tools import _error
        print(encode(_error(parsed.command, getattr(exc, 'code', 'INVALID_BINDING'), str(exc))))
        return 2
    api = ArchivedMarketDataAPI(_NoOtherTools(), None, getattr(parsed, 'data_root', None),
                                source_workspace=getattr(parsed, 'source_workspace', None),
                                rights_candidate_binding=binding, rights_evidence_binding=evidence_binding,
                                version_ledger_binding=version_binding,
                                data_catalog_path=getattr(parsed, 'catalog', None))
    if parsed.command == 'data-catalog-list':
        name = 'list_data_catalog'
        arguments = {key:getattr(parsed,key) for key in ('status','delivery','offset','limit')}
    elif parsed.command == 'data-catalog-get':
        name, arguments = 'get_ready_data_source', {'dataset_id': parsed.dataset_id}
    elif parsed.command == 'version-selection-contract':
        name, arguments = 'get_version_selection_contract', {}
    elif parsed.command == 'version-ledger-manifest':
        name, arguments = 'get_version_ledger_manifest', {}
    elif parsed.command == 'version-ledger-query':
        name = 'query_version_ledger'
        arguments = {key:getattr(parsed,key) for key in ('domain','event_type','event_id','source_id','offset','limit')}
    elif parsed.command == 'version-selection-preview':
        name, arguments = 'preview_version_selection', {'request_json': parsed.request_json}
    elif parsed.command == 'contract':
        name, arguments = 'get_adjustment_review_contract', {}
    elif parsed.command in ('rights-evidence-manifest', 'rights-evidence-query'):
        name = ('get_rights_conflict_evidence_manifest' if parsed.command == 'rights-evidence-manifest'
                else 'query_rights_conflict_evidence')
        arguments = {} if parsed.command == 'rights-evidence-manifest' else {
            key:getattr(parsed,key) for key in ('symbol','start','end','offset','limit')}
    elif parsed.command == 'rights-preview-contract':
        name, arguments = 'get_rights_rebuild_contract', {}
    elif parsed.command == 'rights-preview':
        name, arguments = 'preview_rights_rebuild', {'request_json': parsed.request_json}
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
