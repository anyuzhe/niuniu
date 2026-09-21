"""Read-only research tools for humans and agents; no execution or write API."""
import json
from pathlib import Path
from uuid import UUID
from quantlab.app import default_registry
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields
from quantlab.workbench.server import ArtifactCatalog


def schema(name, description, properties):
    return {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': properties, 'required': list(properties),
        'additionalProperties': False}}


TEXT = {'type': 'string', 'maxLength': 200}
LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 20}
OFFSET = {'type': 'integer', 'minimum': 0, 'maximum': 100000}
TOOLS = [
    schema('get_capabilities', '查询当前只读研究接口的能力和限制。', {}),
    schema('search_factors', '搜索实际注册因子，空关键词列出全部。', {'query': TEXT, 'offset': OFFSET, 'limit': LIMIT}),
    schema('describe_factor', '先用 search_factors 获取真实版本，再读取定义和默认参数；version 不支持 latest 或空字符串，不能猜测。', {'factor_id': TEXT, 'version': TEXT}),
    schema('list_research_templates', '只读检索实际组合研究模板，空query列出全部；模板不是成品交易策略，不创建研究。', {'query': TEXT, 'offset': OFFSET, 'limit': LIMIT}),
    schema('get_research_template', '读取精确版本模板的规则、组件、来源哈希与theory/theory_version提案字段；不批准、不执行，不替代QM50原始规格。', {'template_id': TEXT, 'version': TEXT}),
    schema('get_strategy_package_contract', '只读查看统一策略包v1必填字段与实际支持的持有退出合同；不给出资金或交易参数建议。', {}),
    schema('preview_strategy_package', '纯配置校验：编译用户明确提供的完整策略包JSON，返回完整绑定spec和哈希；不读取行情、不保存提案、不批准或执行。不得用模板代替缺失资金/费用/持有规则。', {'package_json': {'type': 'string', 'maxLength': 65536}}),
    schema('list_strategy_runs', '按名称/版本/标识查找本工作空间策略实验（含失败）；目录仅核验元信息，不代表结果可用。offset是UUID候选扫描位置，续页使用next_offset，须披露errors/incomplete及has_more。', {'query': TEXT, 'offset': OFFSET, 'limit': LIMIT}),
    schema('get_strategy_run', '重新核验明确策略实验的完整归档，读取策略身份、绩效与证据指纹；不执行、不回测，不把内部一致性或完成状态当作Alpha。', {'run_id': TEXT}),
    schema('compare_strategy_runs', '只读比较两个明确策略实验，复用宿主归档核验；不可比时披露blockers并保留空delta，不能按收益挑赢家或扩大研究。', {'left_run_id': TEXT, 'right_run_id': TEXT}),
    schema('list_experiments', '检索当前目录实际实验，包含失败记录。', {'query': TEXT, 'status': TEXT, 'kind': TEXT, 'offset': OFFSET, 'limit': LIMIT}),
    schema('get_experiment', '读取指定实验的统计摘要和实际证据引用。', {'run_id': TEXT}),
    schema('get_job', '读取现有任务状态，不提交或取消任务。', {'job_id': TEXT}),
]


def compact(value, depth=0):
    if depth > 7:
        return {'omitted': True, 'reason': 'nested_summary_limit'}
    if isinstance(value, dict):
        result = {k: compact(v, depth+1) for k, v in list(value.items())[:40]
                  if k not in ('artifact_path', 'source_path', 'path', 'data_root')}
        if len(value) > 40: result['_omitted_fields'] = len(value)-40
        return result
    if isinstance(value, list):
        result = [compact(v, depth+1) for v in value[:30]]
        if len(value) > 30: result.append({'omitted_items': len(value)-30})
        return result
    if isinstance(value, str) and len(value) > 1500:
        return value[:1500] + '\n[摘要已缩减，请在工作台查看完整记录]'
    return value


def restricted_dsl_contract():
    """Expose the evaluator whitelist without modifying the factor implementation."""
    from quantlab.factors.restricted_dsl import FIELDS, BINARY, UNARY, ROLLING, MAX_NODES, MAX_DEPTH, MAX_WINDOW
    return {'fields': sorted(FIELDS), 'binary': sorted(BINARY), 'unary': sorted(UNARY),
            'rolling': sorted(ROLLING), 'temporal': ['lag','delta','pct_change'],
            'max_nodes': MAX_NODES, 'max_depth': MAX_DEPTH, 'max_window': MAX_WINDOW,
            'temporal_nesting_allowed': False,
            'node_fields': {'field': ['op','name'], 'const': ['op','value'],
                'binary': ['op','left','right'], 'unary': ['op','arg'],
                'temporal': ['op','arg','bars'], 'rolling': ['op','arg','window']},
            'registration_is_host_only': True, 'arbitrary_code_allowed': False}


def resolve_research_output(output):
    """Preserve the explicit workspace-root policy before resolving its spelling."""
    path = Path(output)
    if path.is_symlink():
        raise ValueError('Research output root must not be a symlink')
    return path.resolve()


class ReadOnlyResearchAPI:
    def __init__(self, output):
        self.output = resolve_research_output(output)
        self.catalog = ArtifactCatalog(self.output)
        self.registry = default_registry()

    def schemas(self):
        return json.loads(json.dumps(TOOLS, ensure_ascii=False))

    @staticmethod
    def validate(name, arguments):
        definition = next((item for item in TOOLS if item['name'] == name), None)
        if definition is None:
            raise ValueError('UNKNOWN_TOOL：当前只读接口未注册此工具。')
        props = definition['parameters']['properties']
        if not isinstance(arguments, dict) or set(arguments) != set(props):
            raise ValueError('INVALID_ARGUMENT：字段必须与工具 Schema 一致。')
        for key, spec in props.items():
            value = arguments[key]
            valid = (isinstance(value, str) and len(value) <= spec['maxLength']) if spec['type'] == 'string' else (
                type(value) is int and spec['minimum'] <= value <= spec['maximum'])
            if not valid: raise ValueError('INVALID_ARGUMENT：字段类型或范围错误：'+key)

    @staticmethod
    def identifier(value):
        if str(UUID(value)) != value: raise ValueError('INVALID_ARGUMENT：必须使用规范 UUID。')
        return value

    def _read(self, name, args):
        if name == 'get_capabilities':
            return {'version': '1.0', 'access': 'read_only', 'tools': [t['name'] for t in TOOLS],
                    'model_connected': False, 'execution_tools_available': False,
                    'research_template_catalog_available': True, 'template_execution_authorized': False,
                    'strategy_package_preview_available': True, 'strategy_package_execution_authorized': False,
                    'strategy_archive_discovery_available': True, 'strategy_result_comparison_available': True,
                    'strategy_archive_write_authorized': False,
                    'limitations': ['只读研究接口，不是已经接入大模型的对话助手。',
                        '历史行业/每日市值、严格 PIT 与官方历史涨跌停规则仍有资料缺口。',
                        '实验成功状态不代表统计有效、真实可成交或未来盈利。',
                        '只检索指定产物目录的直接实验；未递归聚合其他工作空间。']}, []
        if name == 'search_factors':
            values = [json.loads(encode(v)) for v in self.registry.describe()
                      if args['query'].casefold() in encode(v).casefold()]
            selected = values[args['offset']:args['offset']+args['limit']]
            fields = ('factor_id', 'version', 'name_cn', 'category', 'factor_type')
            rows = [{key: item['definition'][key] for key in fields} for item in selected]
            return {'factors': rows, 'total': len(values), 'offset': args['offset']}, [
                {'kind': 'factor', 'factor_id': r['factor_id'], 'version': r['version']} for r in rows]
        if name == 'describe_factor':
            from dataclasses import asdict
            try: factor = self.registry.get(args['factor_id'], args['version'])
            except ValueError:
                raise ValueError('INVALID_ARGUMENT：找不到精确因子版本；请先调用 search_factors 获取实际版本，不接受 latest 或空版本。') from None
            description = {'definition': asdict(factor.definition), 'defaults': factor.parameters({})}
            if args['factor_id']=='DSL.RESTRICTED':
                description['expression_contract']=restricted_dsl_contract()
            return json.loads(encode(description)), [
                {'kind': 'factor', 'factor_id': args['factor_id'], 'version': args['version']}]
        if name == 'list_research_templates':
            from quantlab.theory.templates import templates
            values = [item for item in templates() if args['query'].casefold() in encode(item).casefold()]
            fields = ('template_id', 'version', 'name', 'scope', 'concepts')
            rows = [{key: item[key] for key in fields}
                    for item in values[args['offset']:args['offset'] + args['limit']]]
            return {'templates': rows, 'total': len(values), 'offset': args['offset'],
                    'category': 'COMBINATION_RESEARCH_TEMPLATE', 'complete_trading_strategy': False}, []
        if name == 'get_research_template':
            from quantlab.theory.templates import resolve_template
            try:
                parameters, origin = resolve_template(args['template_id'], self.registry, args['version'])
            except ValueError as error:
                raise ValueError('INVALID_ARGUMENT：找不到精确模板版本；请先列出模板，不接受空版本或latest。') from error
            components = [{'kind': 'factor', 'factor_id': spec['factor_id'], 'version': spec['version']}
                          for spec in parameters['inputs'].values()]
            return {'template': origin, 'template_digest': digest(origin),
                    'submission_fields': {'theory': args['template_id'], 'theory_version': args['version']},
                    'category': 'COMBINATION_RESEARCH_TEMPLATE', 'complete_trading_strategy': False,
                    'execution_authorized': False,
                    'limitations': ['沿用原模板定义和现有提案审批；证券、日期、周期与预算必须由宿主范围确定。',
                        '不能同时覆盖factor/version/parameters/grid；需要改规则时应另建明确版本。',
                        'Research Session Grant v1不允许theory/context/execution；读取模板不扩大授权。',
                        '模板是研究假设，不包含完整仓位、持有退出与成交合同，不构成盈利证明。']}, components
        if name == 'get_strategy_package_contract':
            from quantlab.trading.strategy_package import (FORMAT, LIFECYCLE, LIMITATIONS, QUALIFICATIONS,
                _SPEC_REQUIRED, _EXECUTION_REQUIRED, _PORTFOLIO_REQUIRED)
            return {'format': FORMAT, 'required': ['format', 'strategy_key', 'name', 'version', 'lifecycle', 'spec'],
                    'lifecycle': dict(LIFECYCLE), 'supported_qualifications': list(QUALIFICATIONS),
                    'spec_required': sorted(_SPEC_REQUIRED),
                    'execution_required': sorted(_EXECUTION_REQUIRED), 'portfolio_required': sorted(_PORTFOLIO_REQUIRED),
                    'signal_alternatives': [['factor', 'version', 'parameters'], ['theory', 'theory_version']],
                    'version_policy': '非空固定版本标签，例如1.0.0或draft-1；不接受latest。',
                    'execution_authorized': False, 'data_checked': False,
                    'limitations': list(LIMITATIONS)}, []
        if name == 'preview_strategy_package':
            from quantlab.agent.planning import parse_spec
            from quantlab.trading.strategy_package import compile_strategy
            try:
                result = compile_strategy(parse_spec(args['package_json']))
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                raise ValueError('INVALID_ARGUMENT：' + str(error)[:240]) from error
            return {**result, 'data_checked': False, 'proposal_created': False}, []
        if name == 'list_strategy_runs':
            from quantlab.trading.strategy_run_catalog import list_strategy_runs
            result = list_strategy_runs(self.output, **args)
            return result, [{'kind': 'experiment', 'run_id': row['run_id']} for row in result['runs']]
        if name == 'get_strategy_run':
            from quantlab.trading.strategy_run_catalog import get_strategy_run
            result = get_strategy_run(self.output, self.identifier(args['run_id']))
            # This is evidence reading, not a new executable spec or an implicit recompile.
            result.pop('package', None)
            return result, [{'kind': 'experiment', 'run_id': args['run_id'],
                             'uri': 'quantlab://run/' + args['run_id']}]
        if name == 'compare_strategy_runs':
            from quantlab.trading.strategy_comparison import compare_strategy_runs
            result = compare_strategy_runs(self.output, self.identifier(args['left_run_id']),
                                           self.identifier(args['right_run_id']))
            return result, [{'kind': 'experiment', 'run_id': args[key],
                             'uri': 'quantlab://run/' + args[key]} for key in ('left_run_id', 'right_run_id')]
        if name == 'list_experiments':
            result = self.catalog.list(**args)
            for row in result['runs']:
                symbols = row.pop('symbols', [])
                row.update(symbol_count=len(symbols), symbols_preview=symbols[:20])
            return result, [{'kind': 'experiment', 'run_id': r['run_id']} for r in result['runs']]
        if name == 'get_experiment':
            self.identifier(args['run_id'])
            path = self.catalog.file(args['run_id'], 'experiment.json')
            record = load_record_fields(path, {'run_id','experiment_id','kind','status','created_at',
                'metrics','execution','summary','limitations','inference','error'})
            if record.get('run_id') != args['run_id']: raise ValueError('INVALID_ARTIFACT：归档身份不一致。')
            return record, [{'kind': 'experiment', 'run_id': args['run_id'],
                             'uri': 'quantlab://run/'+args['run_id']}]
        if name == 'get_job':
            job_id = self.identifier(args['job_id'])
            path = self.output/'_jobs'/(job_id+'.json')
            if path.is_symlink() or not path.resolve().is_relative_to(self.output):
                raise ValueError('INVALID_ARTIFACT：任务路径越出工作空间。')
            if path.stat().st_size > 1000000: raise ValueError('RESULT_TOO_LARGE：任务日志请在工作台查看。')
            record = json.loads(path.read_text())
            if record.get('job_id') != job_id: raise ValueError('INVALID_ARTIFACT：任务身份不一致。')
            result = {k: record.get(k) for k in ('job_id','status','run_id','experiment_id','error',
                'attempt','progress','checkpoint_summary','created_at','finished_at')}
            evidence = [{'kind': 'job', 'job_id': job_id}]
            if result.get('run_id'):
                self.catalog.file(result['run_id'], 'experiment.json')
                evidence.append({'kind': 'experiment', 'run_id': result['run_id']})
            return result, evidence
        raise ValueError('UNKNOWN_TOOL：未实现工具。')

    def call(self, name, arguments):
        try:
            self.validate(name, arguments)
            data, evidence = self._read(name, arguments)
            exact = name in {'preview_strategy_package', 'list_strategy_runs', 'get_strategy_run', 'compare_strategy_runs'}
            result = {'ok': True, 'tool': name, 'data': data if exact else compact(data),
                      'evidence': evidence, 'warnings': [], 'error': None}
            if name == 'list_strategy_runs' and data.get('incomplete'):
                result['warnings'].append('归档目录存在读取错误；当前返回不是完整有效样本，详情见errors。')
            if exact and len(encode(result)) > 24000:
                raise ValueError('RESULT_TOO_LARGE：完整策略配置或证据超过模型输出预算；缩小分页或使用宿主CLI/工作台，不返回截断配置、遗漏错误或不完整比较。')
            if len(encode(result)) > 24000:
                result['data'] = {'omitted': True, 'reason': 'result_size_limit'}
                result['warnings'].append('超过摘要预算；请缩小查询或在工作台打开证据。')
            return json.loads(encode(result))
        except (ValueError, KeyError, TypeError, OSError, AttributeError, RecursionError) as error:
            message = str(error)
            known = ('UNKNOWN_TOOL','INVALID_ARGUMENT','INVALID_ARTIFACT','RESULT_TOO_LARGE')
            code = next((key for key in known if message.startswith(key)), 'READ_FAILED')
            return {'ok': False, 'tool': str(name)[:160], 'data': None, 'evidence': [],
                    'warnings': [], 'error': {'code': code, 'message': message[:300] if code in known else
                    '指定定义、归档或任务不可读取：'+type(error).__name__}}
