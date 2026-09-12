"""Model may validate and propose restricted DSL candidates, never register them."""
import json
from quantlab.agent.catalog import schema,TEXT,LIMIT,OFFSET,compact
from quantlab.agent.incremental_tools import IncrementalEvidenceAPI
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.agent.model_config import strict_json,ModelError
from quantlab.storage.codec import encode

AST={'type':'string','maxLength':12000}
TOOLS=[
    schema('preview_dsl_candidate','用已完成replay归档K线验证白名单AST、有效值与前缀因果不变性；不注册、不研究。',
        {'name':TEXT,'ast_json':AST,'source_run_id':TEXT}),
    schema('propose_dsl_candidate','保存待宿主人工注册的DSL候选提案；request_id须为UUID。不执行研究。',
        {'request_id':TEXT,'name':TEXT,'ast_json':AST,'source_run_id':TEXT}),
    schema('get_dsl_candidate_proposal','读取DSL候选提案状态；不注册。',{'request_id':TEXT}),
    schema('list_dsl_candidates','查询已经人工注册的不可变DSL候选预设。',{'query':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_dsl_candidate','读取已注册候选的AST、验证来源和可直接用于DSL.RESTRICTED的参数。',{'candidate_id':TEXT}),
]

class DslCandidateAPI(IncrementalEvidenceAPI):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root);self.dsl=DslCandidateService(output)
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        tool=next((t for t in TOOLS if t['name']==name),None)
        if tool is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(restricted_dsl_candidates=True,dsl_registration_host_only=True,
                    tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=tool['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('DSL工具字段与合同不一致')
            for key,spec in props.items():
                value=arguments[key]
                valid=isinstance(value,str) and len(value)<=spec['maxLength'] if spec['type']=='string' else (
                    type(value) is int and spec['minimum']<=value<=spec['maximum'])
                if not valid:raise ValueError('DSL工具参数无效：'+key)
            refs=[]
            if name=='preview_dsl_candidate':
                ast=strict_json(arguments['ast_json']);data=self.dsl.preview(arguments['name'],ast,arguments['source_run_id'])
                refs=[{'kind':'experiment','run_id':arguments['source_run_id']}]
            elif name=='propose_dsl_candidate':
                ast=strict_json(arguments['ast_json']);data=self.dsl.propose(arguments['request_id'],arguments['name'],ast,arguments['source_run_id'])
                refs=[{'kind':'experiment','run_id':arguments['source_run_id']}]
            elif name=='get_dsl_candidate_proposal':
                data=self.dsl.proposal(arguments['request_id'])
            elif name=='list_dsl_candidates':
                listing=self.dsl.list(query=arguments['query'],limit=min(100,arguments['offset']+arguments['limit']))
                rows=listing['candidates'][arguments['offset']:arguments['offset']+arguments['limit']]
                data={'candidates':rows,'total':listing['total'],'errors':listing['errors']}
                refs=[{'kind':'dsl_candidate','candidate_id':r['candidate_id']} for r in rows]
            else:
                data=self.dsl.get(arguments['candidate_id'])
                refs=[{'kind':'dsl_candidate','candidate_id':arguments['candidate_id']}]
                refs.append({'kind':'experiment','run_id':data['plan']['source_run_id']})
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['DSL候选注册必须由宿主人工确认；注册不等于Alpha认证，也不会自动启动研究。'],'error':None}
            if len(encode(reply))>24000:reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (ValueError,TypeError,KeyError,OSError,ModelError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'DSL_CANDIDATE_FAILED','message':str(error)[:300]}}
