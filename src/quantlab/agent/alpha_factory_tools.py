"""Model may freeze Alpha Factory proposals, never execute or promote them."""
import json
from quantlab.agent.catalog import schema,TEXT,OFFSET,LIMIT,compact
from quantlab.agent.dsl_tools import DslCandidateAPI
from quantlab.agent.model_config import strict_json,ModelError
from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.agent.factory_report import build_factory_report
from quantlab.storage.codec import encode

PLAN={'type':'string','maxLength':24000}
TOOLS=[
    schema('preview_alpha_factory','预检固定Alpha Factory：旧合同用candidate_ids冻结已注册DSL候选；v2须增加format=alpha-factory-plan-v2并改用candidate_refs（不能有candidate_ids）；每项严格为kind=registered_factor、factor_id、version、parameters、name，参数按实际注册表规范化。不执行。',{'plan_json':PLAN}),
    schema('propose_alpha_factory','保存待宿主一次批准的固定Alpha Factory，不执行研究。request_id须为UUID。plan_json支持旧candidate_ids，或format=alpha-factory-plan-v2加candidate_refs；模型不能approve/execute/promote。',{'request_id':TEXT,'plan_json':PLAN}),
    schema('get_alpha_factory','读取Factory计划、任务、全族Holm和观察池建议；不提交、同步或晋级。',{'proposal_id':TEXT}),
    schema('get_alpha_factory_report','分页读取有界、同源只读Factory研究报告；首次expected_digest传空字符串，后续页回传report_digest。最多6个候选；不重算、不同步、不执行。',{'proposal_id':TEXT,'offset':OFFSET,'limit':{'type':'integer','minimum':1,'maximum':6},'expected_digest':{'type':'string','maxLength':64}}),
    schema('list_alpha_factories','查询已保存Factory；status留空表示全部。',{'status':TEXT,'offset':OFFSET,'limit':LIMIT}),
]


class AlphaFactoryAPI(DslCandidateAPI):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root);self.factory=AlphaFactoryService(output,data_root)
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        tool=next((t for t in TOOLS if t['name']==name),None)
        if tool is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(alpha_factory_available=True,alpha_factory_host_execution_only=True,
                    alpha_factory_auto_promotion=False,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=tool['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('字段必须与工具合同一致')
            if name in ('preview_alpha_factory','propose_alpha_factory'):
                plan_text=arguments['plan_json']
                if not isinstance(plan_text,str) or len(plan_text)>PLAN['maxLength']:raise ValueError('Factory计划文本无效')
                plan=strict_json(plan_text)
                if name=='preview_alpha_factory':data=self.factory.preview(plan);refs=[]
                else:
                    if not isinstance(arguments['request_id'],str) or len(arguments['request_id'])>200:raise ValueError('request_id无效')
                    data=self.factory.propose(arguments['request_id'],plan);refs=[{'kind':'alpha_factory','proposal_id':data['proposal_id']}]
            elif name=='get_alpha_factory':
                if not isinstance(arguments['proposal_id'],str) or len(arguments['proposal_id'])>200:raise ValueError('proposal_id无效')
                data=self.factory.get(arguments['proposal_id']);refs=[{'kind':'alpha_factory','proposal_id':arguments['proposal_id']}]
                if data.get('result_run_id'):refs.append({'kind':'experiment','run_id':data['result_run_id']})
            elif name=='get_alpha_factory_report':
                proposal_id=arguments['proposal_id'];offset=arguments['offset'];limit=arguments['limit'];expected=arguments['expected_digest']
                if not isinstance(proposal_id,str) or len(proposal_id)>64 or type(offset) is not int or type(limit) is not int or not 0<=offset<=100000 or not 1<=limit<=6 or not isinstance(expected,str) or len(expected)>64:
                    raise ValueError('Factory报告分页参数无效')
                data=build_factory_report(self.output,proposal_id,offset=offset,limit=limit,expected_digest=expected or None)
                refs=[{'kind':source['kind'],'proposal_id':source['proposal_id'],'sha256':source['sha256']} if source['kind']=='alpha_factory'
                      else {'kind':'experiment','run_id':source['run_id'],'sha256':source['sha256']} for source in data['sources']]
            else:
                status=arguments['status'];offset=arguments['offset'];limit=arguments['limit']
                if not isinstance(status,str) or len(status)>200 or type(offset) is not int or type(limit) is not int or not 0<=offset<=100000 or not 1<=limit<=20:
                    raise ValueError('Factory列表参数无效')
                rows=self.factory.list();selected=[r for r in rows['factories'] if not status or r['status']==status]
                data={'factories':selected[offset:offset+limit],'total':len(selected),'errors':rows['errors']};refs=[]
            reply={'ok':True,'tool':name,'data':data if name=='get_alpha_factory_report' else compact(data),'evidence':refs,
                'warnings':['Factory必须宿主批准后才能执行；模型不能同步结果或把候选自动加入观察池。'],'error':None}
            if name=='get_alpha_factory_report' and len(encode(reply).encode('utf-8'))>32000:
                raise ValueError('Factory报告响应超过32000字节，请减少每页候选；不截断统计或错误信息')
            if len(encode(reply))>32000:raise ValueError('Factory响应超过预算，请缩小候选或分页；不返回空成功结果')
            return json.loads(encode(reply))
        except (ValueError,TypeError,KeyError,OSError,ModelError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'ALPHA_FACTORY_FAILED','message':str(error)[:300]}}
