"""Read-only research tools for humans and agents; no execution or write API."""
import json
from pathlib import Path
from uuid import UUID
from quantlab.app import default_registry
from quantlab.storage.codec import encode
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


class ReadOnlyResearchAPI:
    def __init__(self, output):
        self.output = Path(output).resolve()
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
            result = {'ok': True, 'tool': name, 'data': compact(data),
                      'evidence': evidence, 'warnings': [], 'error': None}
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
