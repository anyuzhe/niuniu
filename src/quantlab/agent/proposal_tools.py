"""Model-facing proposal tools: no approval, queue, shell or arbitrary path tool."""
import json
import sqlite3
from quantlab.agent.catalog import ReadOnlyResearchAPI, schema, TEXT, compact
from quantlab.agent.planning import parse_spec, ProposalError
from quantlab.agent.proposals import ProposalService
from quantlab.storage.codec import encode

SPEC = {'type':'string','maxLength':65536}
PROPOSAL_TOOLS = [
    schema('qualify_research_data','按research_only/retrospective_reference/strict_pit/official_rule_covered核对本地数据资格；只读，不创建任务。',{'spec_json':SPEC}),
    schema('preview_experiment','校验研究配置并估算规模；严格资格请求会只读核对本地归档，不创建任务。',{'spec_json':SPEC}),
    schema('propose_experiment','保存待用户批准的固定提案；相同 request_id 重试幂等。不会执行研究。',{'request_id':TEXT,'spec_json':SPEC}),
    schema('get_proposal','读取真实提案及状态；批准不在模型工具集合中。',{'proposal_id':TEXT}),
]


class ResearchProposalAPI(ReadOnlyResearchAPI):
    def __init__(self, output, data_root, *, budget=None):
        super().__init__(output)
        self.proposals = ProposalService(output,data_root,budget=budget)

    def schemas(self):
        return super().schemas()+json.loads(json.dumps(PROPOSAL_TOOLS,ensure_ascii=False))

    def call(self, name, arguments):
        if name == 'get_capabilities':
            result = super().call(name,arguments)
            if result['ok']:
                result['data'].update(version='1.1',access='read_and_propose',
                    tools=[t['name'] for t in self.schemas()],host_approval_submission_available=True,
                    approval_tools_available_to_model=False,data_qualification_available=True,
                    qualification_levels=['research_only','retrospective_reference','strict_pit','official_rule_covered'],
                    approval_time_actual_byte_freeze=True,approval_freeze_model_write=False)
                result['data']['limitations'][0]='尚未连接聊天模型；AI 只能查询和生成提案，不能自行批准或启动研究。'
            return result
        definition = next((t for t in PROPOSAL_TOOLS if t['name']==name),None)
        if definition is None: return super().call(name,arguments)
        try:
            props = definition['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):
                raise ProposalError('INVALID_ARGUMENT','工具字段必须与 Schema 完全一致。')
            if any(not isinstance(arguments[k],str) or len(arguments[k])>v['maxLength'] for k,v in props.items()):
                raise ProposalError('INVALID_ARGUMENT','工具字段类型或长度错误。')
            if name == 'qualify_research_data':
                data = self.proposals.qualify(parse_spec(arguments['spec_json'])); evidence=[]
            elif name == 'preview_experiment':
                data = self.proposals.preview(parse_spec(arguments['spec_json'])); evidence=[]
            elif name == 'propose_experiment':
                data = self.proposals.propose(arguments['request_id'],parse_spec(arguments['spec_json']))
                evidence=[{'kind':'proposal','proposal_id':data['proposal_id']}]
            else:
                data = self.proposals.get(arguments['proposal_id'])
                evidence=[{'kind':'proposal','proposal_id':data['proposal_id']}]
            result = {'ok':True,'tool':name,'data':compact(data),'evidence':evidence,
                'warnings':['提案不等于已批准、已执行或数据已验收；完整配置以人工批准面板为准。'],'error':None}
            if len(encode(result))>24000:
                result['data']={'proposal_id':data.get('proposal_id'),'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(result))
        except ProposalError as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':error.code,'message':str(error)[:300]}}
        except (ValueError,KeyError,TypeError,OSError,RecursionError,sqlite3.Error) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'PROPOSAL_FAILED','message':'提案操作未完成：'+type(error).__name__}}
