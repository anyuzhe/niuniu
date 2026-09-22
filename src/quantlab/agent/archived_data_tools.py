"""Generic read-only access to host-bound archived market data.

This wrapper performs no collection or research execution. Explicit input checks may
read the finite package Provider; no retrospective observation becomes a PIT fact.
"""
from __future__ import annotations

import json
import os
from datetime import date

from quantlab.agent.catalog import TEXT, schema
from quantlab.storage.codec import encode

MAX_RESPONSE_BYTES = 64 * 1024

WARNINGS = [
    '只读归档访问；工具不写入、不采集、不联网、不授权模型执行或交易。',
    '供应商数据为回顾性观察，非PIT/完整历史认证；observed_at保留为观察时点。',
    'preclose不是reference_price，turn不是流通股本或成交额，竞价/成交量未知单位按原单位保留。',
]

TOOLS = [
    schema('list_archived_daily_sources', '只读列出宿主绑定source_workspace中的回溯日线capture；最多检查有界候选，坏capture作为错误披露，不回退到其他根。', {}),
    schema('list_archived_daily_symbols', '对指定capture分页列出证券清单。filter_kind=all/has_st/has_suspension仅作诊断过滤，不代表历史候选池。',
           {'capture_id': TEXT, 'offset': {'type': 'integer', 'minimum': 0, 'maximum': 20000},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}, 'filter_kind': TEXT}),
    schema('inspect_archived_daily', '读取并核验指定capture中1-10只证券、最多371自然日日线；保留供应商原字段，不推导涨跌停价、流通股本或PIT。',
           {'capture_id': TEXT, 'symbols': TEXT, 'start': TEXT, 'end': TEXT}),
    schema('get_archived_daily_dataset', '只读核验宿主data_root中已显式生成的归档日线研究输入包；返回固定证券、范围、源证据和限制。只支持raw日线，不创建输入包、不批准、不执行；不能代替原始QM50规格。', {}),
    schema('check_archived_daily_research', '只读核对明确研究spec与宿主选定F9日线包：证券、日期、周期、复权和背景输入；返回全部不匹配原因。不是审批或统计样本充分性证明，不改配置、不创建任务。',
           {'spec_json': {'type': 'string', 'maxLength': 65536}}),
    schema('get_trading_calendar', '只读核对明确来源的日历和1–371自然日窗口。source必选baostock_bronze/retro_capture/archived_dataset；retro须精确capture_id，其他留空。返回内容哈希、max_date与全部缺日，不默认日历、不以未知日推断休市，不认证PIT。',
           {'source': TEXT, 'capture_id': TEXT, 'start': TEXT, 'end': TEXT}),
    schema('check_daily_date_coverage', '按同一明确来源的日历、上市区间和raw日线核对1–10只沪深证券、1–371自然日。返回完整missing/unexpected/duplicate日期集，停牌和未知状态另列。complete仅日期存在，不证明价格、交易资格或F9可导出；不得换源补洞。',
           {'source': TEXT, 'capture_id': TEXT, 'symbols': TEXT, 'start': TEXT, 'end': TEXT}),
    schema('get_rights_candidate_manifest', '只读验证宿主显式绑定的配股候选CSV与摘要JSON；重核完整SHA、事件唯一性、分类和候选公式。标签只是数据侧声明，不认证官方真值、因子未变或重建/发布许可。未绑定不自动查找文件。', {}),
    schema('query_rights_candidates', '在同一绑定版本内按证券/日期/分桶分页查询配股候选；status为all/exact/small/conflicts/cninfo_none。保留原始字段、来源行定位、冲突和未知；不默认选源，不把空结果当无缺口，不执行原脚本或改因子。',
           {'symbol': TEXT, 'start': TEXT, 'end': TEXT, 'status': TEXT,
            'offset': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}}),
    schema('get_adjustment_review_contract', '读取公司行动候选对账与复权风险合同；不读行情、不把供应商一致性认证为官方真值或独立血缘，不批准重建。', {}),
    schema('inspect_corporate_action_sources', '只读核对宿主data_root中一个证券、最多3660自然日的TDX/东财/同花顺公司行动与已存qfq因子诊断。按源保留候选、原文、冲突和未识别项；不跨供应商相加、不判最终真值、不生成修正因子。errors/incomplete和分页必须披露，缺源不等于零事件。',
           {'symbol': TEXT, 'start': TEXT, 'end': TEXT,
            'offset': {'type': 'integer', 'minimum': 0, 'maximum': 20000},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}),
    schema('get_tdx_data_coverage', '只读聚合一个TDX族的真实行数、不同证券数、日期范围与逐证券日数分位。返回date_axis；全局跨度不代表每只证券覆盖，非事件族不伪造事件日期。不选择版本、不校验源页字节、不认证完整性或PIT。',
           {'family': TEXT, 'symbol': TEXT, 'start': TEXT, 'end': TEXT}),
    schema('get_tdx_data_status', '只读查看已配置TDX湖状态；剔除大体计划字段。不联网、不采集，能力不代表数据存在。', {}),
    schema('read_tdx_data', '只读查询TDX catalog中的tdx_*数据；返回original_record、单位、observed_at和source_id，不标准化、不PIT升级。',
           {'family': TEXT, 'symbol': TEXT, 'start': TEXT, 'end': TEXT,
            'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}),
]
NAMES = {tool['name'] for tool in TOOLS}


def _error(tool: str, code: str, message: str, *, evidence=None, warnings=None, detail=None) -> dict:
    err = {'code': code, 'message': str(message)[:600]}
    if len(str(message)) > 600:
        err['message_truncated'] = True
    if detail is not None:
        err['detail'] = detail
    result = {'ok': False, 'tool': tool, 'data': None, 'evidence': evidence or [],
              'warnings': warnings if warnings is not None else list(WARNINGS), 'error': err}
    # Error envelopes also obey the budget. Never reattach an oversized source
    # payload as evidence after rejecting that payload in _ok().
    if len(encode(result).encode('utf-8')) > MAX_RESPONSE_BYTES:
        result['evidence'] = []
        result['warnings'] = list(WARNINGS)
        result['error'] = {'code': code, 'message': str(message)[:600],
                           'response_details_omitted': True,
                           'evidence_omitted': len(evidence or [])}
    return result


def _ok(tool: str, data, *, evidence=None, warnings=None) -> dict:
    response = {'ok': True, 'tool': tool, 'data': data, 'evidence': evidence or [],
                'warnings': warnings or WARNINGS, 'error': None}
    try:
        size = len(encode(response).encode('utf-8'))
    except Exception as exc:  # non-JSON / non-encodable responses must be explicit failures
        return _error(tool, 'NON_JSON_RESULT', type(exc).__name__ + ': ' + str(exc))
    if size > MAX_RESPONSE_BYTES:
        return _error(tool, 'RESULT_TOO_LARGE', '完整响应超过64KiB；请缩小symbols/date范围或limit后重试。',
                      evidence=evidence, detail={'encoded_bytes': size, 'limit_bytes': MAX_RESPONSE_BYTES})
    return json.loads(encode(response))


def _classify(exc: Exception) -> str:
    text = (type(exc).__name__ + ': ' + str(exc)).lower()
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        if 'TDX data root not configured' in str(exc):
            return 'TDX_NOT_CONFIGURED'
        if '工具参数' in str(exc):
            return 'INVALID_ARGUMENT'
        if 'symlink' in text or 'junction' in text or 'escaped' in text or 'outside' in text:
            return 'PATH_REJECTED'
        if 'corrupt' in text or 'changed' in text or 'checksum' in text or 'schema' in text or 'parquet' in text:
            return 'CORRUPT_ARCHIVE'
        if 'not found' in text or 'missing' in text or '不存在' in text or '缺失' in text:
            return 'NOT_FOUND'
        if 'json' in text:
            return 'NON_JSON_SOURCE'
        return 'INVALID_ARGUMENT'
    if isinstance(exc, PermissionError):
        return 'PERMISSION_DENIED'
    if isinstance(exc, FileNotFoundError):
        return 'NOT_FOUND'
    if isinstance(exc, TimeoutError):
        return 'LOCKED_OR_BUSY'
    if isinstance(exc, OSError):
        if 'lock' in text or 'busy' in text:
            return 'LOCKED_OR_BUSY'
        if 'permission' in text or 'denied' in text:
            return 'PERMISSION_DENIED'
        return 'IO_ERROR'
    return 'READ_FAILED'


def _validate_args(tool: dict, args: dict) -> None:
    props = tool['parameters']['properties']
    if not isinstance(args, dict) or set(args) != set(props):
        raise ValueError('工具参数与schema不一致，且不接受path/root/SQL等额外参数')
    for key, rule in props.items():
        value = args[key]
        if rule['type'] == 'string':
            if not isinstance(value, str) or len(value) > rule.get('maxLength', 200):
                raise ValueError('参数无效: ' + key)
        elif rule['type'] == 'integer':
            if type(value) is not int or not rule['minimum'] <= value <= rule['maximum']:
                raise ValueError('参数无效: ' + key)
        else:
            raise ValueError('未知参数类型: ' + key)


def _daily_evidence(data: dict) -> list[dict]:
    refs = []
    if isinstance(data, dict) and data.get('capture_id'):
        refs.append({'kind': 'archived_daily_capture', 'capture_id': data['capture_id']})
    source = data.get('source_evidence') if isinstance(data, dict) else None
    if isinstance(source, dict):
        refs.append({'kind': 'archived_daily_source_evidence', **{k: source[k] for k in source if k in ('capture_id', 'capture_plan_sha256', 'calendar_sha256', 'stock_basic_sha256', 'packed')}})
        for symbol, manifest in source.get('symbols', {}).items():
            refs.append({'kind': 'archived_daily_symbol', 'capture_id': source.get('capture_id'), 'symbol': symbol,
                         'parquet_sha256': manifest.get('parquet_sha256'), 'fetched_at': manifest.get('fetched_at')})
    return refs


def _daily_sources(bridge):
    from quantlab.data.retro_daily import CAPTURE
    # Bound candidate discovery before the existing reader opens any plans.
    root = bridge.store.root
    if root.exists():
        candidates = 0
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 1000:
                    raise ValueError('Archive discovery exceeds 1000 directory entries')
                if not CAPTURE.fullmatch(entry.name):
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise ValueError('Archive capture candidate is a symlink or not a directory')
                candidates += 1
                if candidates > 50:
                    raise ValueError('More than 50 captures; source inventory requires pagination')
    data = bridge.list_sources()
    data['errors'] = [row for row in data.get('captures', []) if row.get('error')]
    data['incomplete'] = bool(data['errors'])
    data['verification'] = 'plan_metadata_only'
    data['history_complete'] = False
    return data


def _tdx_status(data_root):
    if data_root is None:
        raise ValueError('TDX data root not configured')
    from quantlab.data.tdx_lake import TdxLake
    data = TdxLake(data_root).status()
    large = {'symbols', 'trading_days', 'server_handshake', 'calendar_extension'}
    data['plans'] = [{k: v for k, v in plan.items() if k not in large} for plan in data.get('plans', [])]
    return data


def _tdx_read(data_root, args):
    if data_root is None:
        raise ValueError('TDX data root not configured')
    start = date.fromisoformat(args['start']) if args['start'] else None
    end = date.fromisoformat(args['end']) if args['end'] else None
    if start and end and start > end:
        raise ValueError('start must be <= end')
    from quantlab.data.tdx_lake import TdxLake
    data = TdxLake(data_root).read(args['family'], args['symbol'], args['start'], args['end'], args['offset'], args['limit'])
    for row in data['rows']:
        original = json.loads(row.pop('record_json'))
        if not isinstance(original, dict):
            raise ValueError('TDX record_json must be a JSON object')
        row['original_record'] = original
    data['verification'] = 'catalog_rows_only'
    data['source_bytes_verified'] = False
    data['note'] = 'record_json解析为original_record；保留单位、observed_at和source_id。本工具不重新深验每页原始字节，也不认证历史覆盖。'
    return data


class ArchivedMarketDataAPI:
    def __init__(self, inner, output, data_root=None, *, source_workspace=None, rights_candidate_binding=None):
        self.inner = inner
        self.output = output
        self.data_root = data_root
        self.source_workspace = source_workspace if source_workspace is not None else output
        self.rights_candidate_binding = rights_candidate_binding

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def schemas(self):
        original = self.inner.schemas()
        own = {tool['name'] for tool in TOOLS}
        return [tool for tool in original if tool.get('name') not in own] + json.loads(json.dumps(TOOLS, ensure_ascii=False))

    def get_capabilities(self, args):
        if not isinstance(args, dict) or args:
            return _error('get_capabilities', 'INVALID_ARGUMENT', '能力查询不接受参数。')
        base = self.inner.call('get_capabilities', args)
        if not isinstance(base, dict):
            return _error('get_capabilities', 'INVALID_RESULT', '内层能力接口返回无效结果。')
        if not base.get('ok'):
            return base  # An inner failure must not become a successful capability claim.
        if not isinstance(base.get('data'), dict):
            return _error('get_capabilities', 'INVALID_RESULT', '内层能力接口缺少data对象。')
        data = {**base['data'], 'archived_daily_read_available': True, 'tdx_read_available': True,
                'tdx_coverage_read_available': True, 'corporate_action_review_available': True,
                'calendar_source_review_available': True, 'calendar_review_write_authorized': False,
                'rights_candidate_review_available': True,
                'rights_candidate_configured': self.rights_candidate_binding is not None,
                'rights_candidate_write_authorized': False,
                'adjustment_rebuild_authorized': False, 'corporate_action_official_verification': False,
                'archived_data_write_authorized': False,
                'tools': [tool['name'] for tool in self.schemas()]}
        return _ok('get_capabilities', data, evidence=base.get('evidence'),
                   warnings=[*base.get('warnings', []), *WARNINGS])

    def call(self, name, args):
        if name == 'get_capabilities':
            return self.get_capabilities(args)
        tool = next((item for item in TOOLS if item['name'] == name), None)
        if tool is None:
            return self.inner.call(name, args)
        try:
            _validate_args(tool, args)
            evidence = []
            if name.startswith('list_archived_daily') or name == 'inspect_archived_daily':
                from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge
                bridge = ArchivedDailyBridge(self.source_workspace)
                if name == 'list_archived_daily_sources':
                    data = _daily_sources(bridge)
                    evidence = [{'kind': 'archived_daily_capture', 'capture_id': row['capture_id'],
                                 'verification': 'plan_metadata_only'}
                                for row in data['captures'] if not row.get('error')]
                elif name == 'list_archived_daily_symbols':
                    data = bridge.inspect_symbols(args['capture_id'], args['offset'], args['limit'], args['filter_kind'])
                    evidence = _daily_evidence(data)
                else:
                    data = bridge.inspect(args['capture_id'], args['symbols'], args['start'], args['end'])
                    evidence = _daily_evidence(data)
            elif name == 'get_archived_daily_dataset':
                if self.data_root is None:
                    raise ValueError('Archived daily dataset root not configured')
                from quantlab.data.archived_daily_dataset import inspect_archived_daily_dataset
                data = {key: value for key, value in inspect_archived_daily_dataset(self.data_root).items()
                        if key != 'path'}  # The host binds the root; model output need not expose it.
                evidence = [{'kind': 'archived_daily_dataset', 'dataset_id': data['dataset_id'],
                             'qualification': 'research_only', 'historical_available_at_verified': False}]
            elif name == 'check_archived_daily_research':
                from quantlab.agent.planning import parse_spec
                from quantlab.data.archived_research_check import check_archived_daily_research
                data = check_archived_daily_research(self.data_root, parse_spec(args['spec_json']))
                evidence = [{'kind': 'archived_daily_dataset', 'dataset_id': data['dataset_id'],
                             'spec_digest': data['spec_digest'], 'check_hash': data['check_hash'],
                             'compatible': data['compatible'], 'qualification': 'research_only'}]
            elif name in ('get_trading_calendar', 'check_daily_date_coverage'):
                from quantlab.data.calendar_review import get_trading_calendar, check_daily_date_coverage
                reader = get_trading_calendar if name == 'get_trading_calendar' else check_daily_date_coverage
                data = reader(self.data_root, source_workspace=self.source_workspace, **args)
                evidence = [{'kind': 'calendar_review_source', **item} for item in data.get('evidence', [])]
            elif name in ('get_rights_candidate_manifest', 'query_rights_candidates'):
                from quantlab.data.rights_candidates import get_rights_candidate_manifest, query_rights_candidates
                reader = get_rights_candidate_manifest if name == 'get_rights_candidate_manifest' else query_rights_candidates
                data = reader(self.rights_candidate_binding, **args)
                evidence = data['evidence']
            elif name == 'get_adjustment_review_contract':
                from quantlab.data.corporate_action_review import get_adjustment_review_contract
                data = get_adjustment_review_contract()
            elif name == 'inspect_corporate_action_sources':
                if self.data_root is None:
                    raise ValueError('Corporate action data root not configured')
                from quantlab.data.corporate_action_review import inspect_corporate_action_sources
                data = inspect_corporate_action_sources(self.data_root, **args)
                evidence = data.get('evidence', [])
            elif name == 'get_tdx_data_coverage':
                if self.data_root is None:
                    raise ValueError('TDX data root not configured')
                from quantlab.data.tdx_lake import TdxLake
                data = TdxLake(self.data_root).coverage(**args)
                evidence = [{'kind': 'tdx_coverage_query', 'family': args['family'],
                             'date_axis': data['date_axis'], 'verification': 'catalog_rows_only'}]
            elif name == 'get_tdx_data_status':
                data = _tdx_status(self.data_root)
                evidence = [{'kind': 'tdx_root_config', 'configured': bool(data.get('configured'))}]
            elif name == 'read_tdx_data':
                data = _tdx_read(self.data_root, args)
                evidence = [{'kind': 'tdx_page_source', 'source_id': sid, 'family': args['family']}
                            for sid in sorted({row.get('source_id') for row in data.get('rows', []) if row.get('source_id')})]
            else:  # defensive; NAMES and TOOLS should be fixed together
                raise ValueError('Unknown archived data tool')
            return _ok(name, data, evidence=evidence)
        except Exception as exc:
            return _error(name, getattr(exc, 'code', None) or _classify(exc), type(exc).__name__ + ': ' + str(exc), detail={'exception_type': type(exc).__name__})


__all__ = ['ArchivedMarketDataAPI', 'TOOLS', 'NAMES']
