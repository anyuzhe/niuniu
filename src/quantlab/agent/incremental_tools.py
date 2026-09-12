"""Model may freeze incremental-evidence proposals, never execute them."""
import json
from quantlab.agent.catalog import schema,TEXT,compact
from quantlab.agent.tracking_tools import TrackingResearchAPI
from quantlab.agent.model_config import strict_json,ModelError
from quantlab.agent.incremental_evidence import IncrementalEvidenceService
from quantlab.storage.codec import encode

PLAN={'type':'string','maxLength':12000}
TOOLS=[
    schema('preview_incremental_evidence','预检固定候选增量证据包；冻结候选、1–5个控制因子、训练截止、持有期、family alpha和可选成本后账户对照。不执行。',{'plan_json':PLAN}),
    schema('propose_incremental_evidence','保存待宿主人工确认的固定增量证据包，不执行。request_id须为UUID。',{'request_id':TEXT,'plan_json':PLAN}),
    schema('get_incremental_evidence','读取已保存的增量证据计划、执行槽位和结果；不执行或重试。',{'proposal_id':TEXT}),
]


class IncrementalEvidenceAPI(TrackingResearchAPI):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root);self.incremental=IncrementalEvidenceService(output)
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        tool=next((t for t in TOOLS if t['name']==name),None)
        if tool is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(incremental_evidence_available=True,
                    incremental_evidence_host_execution_only=True,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=tool['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('字段必须与工具合同一致')
            if any(not isinstance(arguments[k],str) or len(arguments[k])>p['maxLength'] for k,p in props.items()):
                raise ValueError('增量证据工具参数无效')
            refs=[]
            if name=='get_incremental_evidence':
                data=self.incremental.get(arguments['proposal_id'])
                refs=[{'kind':'proposal','proposal_id':arguments['proposal_id']}]
                if data.get('result_run_id'):refs.append({'kind':'experiment','run_id':data['result_run_id']})
            else:
                plan=strict_json(arguments['plan_json'])
                if name=='preview_incremental_evidence':data=self.incremental.preview(plan)
                else:
                    data=self.incremental.propose(arguments['request_id'],plan)
                    refs=[{'kind':'proposal','proposal_id':data['proposal_id']}]
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['模型不能执行证据包；宿主人工确认后才运行固定测试族。'],'error':None}
            if len(encode(reply))>24000:reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (ValueError,TypeError,KeyError,OSError,ModelError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'INCREMENTAL_EVIDENCE_FAILED','message':str(error)[:300]}}
