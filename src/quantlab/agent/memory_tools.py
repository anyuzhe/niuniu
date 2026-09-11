"""Research-memory tools compose with the existing query/proposal boundary."""
import json
import sqlite3
from quantlab.agent.catalog import ReadOnlyResearchAPI, schema, TEXT, LIMIT, OFFSET, compact
from quantlab.agent.proposal_tools import ResearchProposalAPI
from quantlab.agent.research_memory import ResearchMemory, payload
from quantlab.agent.memory_store import MemoryError
from quantlab.storage.codec import encode

JSON_TEXT = {'type':'string','maxLength':65536}
MEMORY_TOOLS = [
    schema('record_hypothesis',
        '保存假设，不运行研究。hypothesis_json 字段必须是 title、statement、factor_id、factor_version、parameters、mechanism、falsification、supersedes（新记录为null，修订为旧记忆UUID）。先查已注册因子和已有记忆。',
        {'request_id':TEXT,'hypothesis_json':JSON_TEXT}),
    schema('record_finding',
        '保存证据支持的结论草稿，不认证Alpha。finding_json须含 hypothesis_id、title、statement、assessment、limitations、next_action、evidence、supersedes。assessment为supported/contradicted/inconclusive/unavailable/implementation_failure；evidence是1–8个{run_id,pointer,relation}，relation为supports/contradicts/context。数值由程序读取，禁止自填。',
        {'request_id':TEXT,'finding_json':JSON_TEXT}),
    schema('search_research_memory',
        '检索结构化研究笔记，包含失败/反对结论。空过滤表示全部；不是搜索聊天。引用前需 get_research_memory 核对当前来源。',
        {'query':TEXT,'kind':TEXT,'factor_id':TEXT,'status':TEXT,'include_superseded':{'type':'boolean'},'offset':OFFSET,'limit':LIMIT}),
    schema('get_research_memory',
        '读取研究笔记及修订关系，复核当前归档校验值；claim_verified始终为false，不能把引用一致当结论成立。',
        {'memory_id':TEXT}),
    schema('inspect_research_evidence',
        '读取真实归档字段，例如 /metrics/5/rank_ic、/status、/error；返回准确值、样本范围和来源校验。不得由模型推测不存在的字段。',
        {'run_id':TEXT,'pointer':{'type':'string','maxLength':400}}),
]


class ResearchMemoryAPI:
    def __init__(self, output, data_root=None, *, origin='model_draft'):
        self.base = ResearchProposalAPI(output,data_root) if data_root else ReadOnlyResearchAPI(output)
        self.memory = ResearchMemory(output,origin=origin)
        if data_root: self.proposals = self.base.proposals

    def schemas(self):
        return self.base.schemas()+json.loads(json.dumps(MEMORY_TOOLS,ensure_ascii=False))

    def call(self, name, arguments):
        tool = next((t for t in MEMORY_TOOLS if t['name']==name),None)
        if tool is None:
            result = self.base.call(name,arguments)
            if name=='get_capabilities' and result['ok']:
                result['data'].update(version='1.2',research_memory_available=True,
                    memory_write_requires_research_approval=False,tools=[t['name'] for t in self.schemas()])
                result['data']['limitations'].append('研究记忆是有来源的草稿，不是已经确认的Alpha；读取时复核归档，未做向量检索或自动追踪。')
            return result
        try:
            props = tool['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):
                raise MemoryError('INVALID_ARGUMENT','参数字段必须与工具合同一致。')
            for key,spec in props.items():
                value = arguments[key]; kind = spec['type']
                valid = (isinstance(value,str) and len(value)<=spec['maxLength']) if kind=='string' else type(value) is bool if kind=='boolean' else type(value) is int and spec['minimum']<=value<=spec['maximum']
                if not valid: raise MemoryError('INVALID_ARGUMENT','参数类型或范围无效：'+key)
            if name=='search_research_memory':
                data = self.memory.store.search(**arguments)
                refs = [{'kind':'memory','memory_id':r['memory_id']} for r in data['records']]
            elif name=='inspect_research_evidence':
                data = self.memory.resolver.capture(**arguments)
                refs = [{'kind':'experiment','run_id':data['run_id'],'pointer':data['pointer']}]
            else:
                if name=='get_research_memory': data = self.memory.get(arguments['memory_id'])
                else:
                    kind = 'hypothesis' if name=='record_hypothesis' else 'finding'
                    data = self.memory.save(kind,arguments['request_id'],payload(arguments[kind+'_json']))
                record = data['record']
                refs = [{'kind':'memory','memory_id':record['memory_id'],'uri':'quantlab://memory/'+record['memory_id']}]
                refs += [{'kind':'experiment','run_id':e['run_id'],'pointer':e['pointer']}
                         for e in data['evidence_checks'] if e['status']=='verified']
            result = {'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                      'warnings':['历史笔记及模型解释不是新的实测事实；来源一致不等于结论成立。'],'error':None}
            if len(encode(result))>24000:
                result['data'] = {'omitted':True,'reason':'result_size_limit'}
                result['warnings'].append('完整记录保留在研究记忆面板；请缩小检索范围。')
            return json.loads(encode(result))
        except MemoryError as error:
            code, message = error.code,str(error)
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error,RecursionError) as error:
            code, message = 'MEMORY_FAILED','研究记忆操作未完成：'+type(error).__name__
        return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':code,'message':message[:300]}}
