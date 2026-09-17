"""Model-facing Research Session Grant tools; creation/revocation stay host-only."""
import json
from pathlib import Path
from quantlab.agent.catalog import schema,TEXT,compact
from quantlab.agent.planning import parse_spec,ProposalError
from quantlab.agent.research_session_grant import ResearchSessionGrantService,grant_status
from quantlab.storage.codec import encode

SPEC={'type':'string','maxLength':65536}
STATUS=schema('get_research_session_grant','读取当前有限研究授权、剩余任务/计算预算和任务状态；不会创建或修改授权。',{})
SUBMIT=schema('submit_granted_experiment','仅在宿主已明确授权的Research Session Grant范围内提交一个研究任务；超范围、过期、撤销或预算不足会拒绝。',
    {'grant_id':TEXT,'request_id':TEXT,'spec_json':SPEC})

class ResearchSessionGrantAPI:
    def __init__(self,inner,output,data_root=None,queue_factory=None):
        self.inner=inner;self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        self.service=ResearchSessionGrantService(self.output,self.data_root,queue_factory) if self.data_root and queue_factory else None
    def schemas(self):return self.inner.schemas()+[json.loads(json.dumps(STATUS,ensure_ascii=False))]+([json.loads(json.dumps(SUBMIT,ensure_ascii=False))] if self.service else [])
    def __getattr__(self,name):return getattr(self.inner,name)
    def call(self,name,arguments):
        if name=='get_capabilities':
            result=self.inner.call(name,arguments)
            if result.get('ok'):
                result['data'].update(research_session_grant_available=True,research_session_grant_submit_available=bool(self.service),
                    research_session_grant_host_authorization_only=True,execution_tools_available=bool(self.service),
                    research_execution_requires_active_grant=True,tools=[t['name'] for t in self.schemas()])
                result['data']['limitations'].append('Research Session Grant 只能由宿主创建/撤销；模型只能在有效授权范围内提交有限研究。')
            return result
        if name=='get_research_session_grant':
            if arguments!={}:return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],'error':{'code':'INVALID_ARGUMENT','message':'该工具不接受参数'}}
            data=grant_status(self.output,self.data_root);refs=[]
            if data.get('grant'):refs=[{'kind':'research_session_grant','grant_id':data['grant']['grant_id']}]
            return {'ok':True,'tool':name,'data':compact(data),'evidence':refs,'warnings':['授权存在不等于Alpha成立；授权只扩大研究执行范围，不扩大真实交易权限。'],'error':None}
        if name!='submit_granted_experiment' or self.service is None:return self.inner.call(name,arguments)
        try:
            props=SUBMIT['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props) or any(not isinstance(arguments[k],str) or len(arguments[k])>v['maxLength'] for k,v in props.items()):
                raise ProposalError('INVALID_ARGUMENT','Session Grant 工具字段与Schema不一致')
            data=self.service.submit(arguments['grant_id'],arguments['request_id'],parse_spec(arguments['spec_json']))
            result={'ok':True,'tool':name,'data':compact(data),'evidence':data['evidence'],
                'warnings':['任务消耗Research Session Grant预算；失败/取消也不会退回试验槽位。','任务成功仅表示研究执行完成，不表示发现Alpha。'],'error':None}
            if len(encode(result))>24000:result['data']={'job_id':data['job']['job_id'],'grant_id':data['grant_id'],'remaining':data['remaining']}
            return json.loads(encode(result))
        except ProposalError as error:code,message=error.code,str(error)
        except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:code,message='SESSION_GRANT_FAILED',str(error)[:300]
        return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],'error':{'code':code,'message':message[:300]}}
