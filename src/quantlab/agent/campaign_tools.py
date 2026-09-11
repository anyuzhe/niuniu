"""Model tools may draft finite packs, never approve or execute them."""
import json
import sqlite3
from pathlib import Path
from quantlab.agent.catalog import schema, TEXT, compact
from quantlab.agent.memory_tools import ResearchMemoryAPI
from quantlab.agent.planning import parse_spec, ProposalError
from quantlab.agent.proposal_store import ProposalStore
from quantlab.experiments.campaign_state import read_checked
from quantlab.experiments.campaign import verify_receipt
from quantlab.storage.codec import encode

SPEC = {'type':'string','maxLength':65536}
TOOLS = [
    schema('preview_campaign','预检固定研究包。spec_json仅含 mode=campaign、question、alpha、failure_policy和nodes；节点为{node_id,depends_on,spec}。统计节点必须明确 replay=true 和 permutation；依赖只按运行成功，不按收益选优。',{'spec_json':SPEC}),
    schema('propose_campaign','保存待人工一次批准的研究包，不执行。先preview_campaign。相同request_id幂等，最多12节点，禁止递归研究包。',{'request_id':TEXT,'spec_json':SPEC}),
    schema('get_campaign','读取研究包提案、节点回执和实际最终报告。不会提交、恢复、追加节点或重算。',{'proposal_id':TEXT}),
]


class ResearchCampaignAPI:
    def __init__(self,output,data_root=None):
        self.base = ResearchMemoryAPI(output,data_root); self.memory = self.base.memory
        self.output = Path(output).resolve(); self.data_root = data_root
        if data_root: self.proposals = self.base.proposals
    def schemas(self):
        available = TOOLS if self.data_root else TOOLS[-1:]
        return self.base.schemas()+json.loads(json.dumps(available,ensure_ascii=False))
    def call(self,name,arguments):
        definition = next((t for t in self.schemas() if t['name']==name and t in TOOLS),None)
        if definition is None:
            result = self.base.call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(version='1.3',campaigns_available=bool(self.data_root),campaign_reproduction_available=True,campaign_artifact_tree_integrity=True,tools=[t['name'] for t in self.schemas()])
                result['data']['limitations'].append('固定研究包须人工批准；执行成功不等于统计支持，失败/跳过项保留。')
            return result
        try:
            props = definition['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props) or any(not isinstance(arguments[k],str) or len(arguments[k])>s['maxLength'] for k,s in props.items()):
                raise ProposalError('INVALID_ARGUMENT','研究包工具字段与合同不一致。')
            refs = []
            if name=='get_campaign':
                proposal = ProposalStore(self.output).get(arguments['proposal_id'])
                if proposal['plan']['spec'].get('mode')!='campaign': raise ProposalError('INVALID_ARGUMENT','该提案不是研究包。')
                data = {'proposal':{k:v for k,v in proposal.items() if k!='plan'},'nodes':[],'result':None}; refs.append({'kind':'proposal','proposal_id':proposal['proposal_id']})
                folder = self.output/'_campaigns'/proposal['job_id']; path = folder/'state.json'
                if folder.is_symlink() or not path.resolve().is_relative_to(self.output): raise ValueError('Invalid campaign receipt path')
                if path.exists():
                    state = read_checked(path); data['nodes'] = {k:{f:v for f,v in r.items() if f!='artifact_tree'} for k,r in state['nodes'].items()}; data['attempts'] = state['attempts'][-20:]; data['total_attempts'] = len(state['attempts'])
                    if state['final']:
                        record = verify_receipt(self.output,state['final']);summary = record['summary'];family=summary.get('family') or {}
                        data['result'] = {k:record[k] for k in ('run_id','experiment_id','kind','status')}
                        data['result']['summary'] = {k:summary[k] for k in ('workflow_status','counts','planned_tests')}
                        data['result']['summary']['available_tests'] = family.get('available_tests',0)
                        data['result']['limitations'] = summary['limitations']
                        refs.append({'kind':'experiment','run_id':state['final']['run_id']})
                if (self.output/'_jobs'/(proposal['job_id']+'.json')).is_file():
                    data['job'] = self.base.call('get_job',{'job_id':proposal['job_id']})
                    refs.append({'kind':'job','job_id':proposal['job_id']})
            else:
                spec = parse_spec(arguments['spec_json'])
                if spec.get('mode')!='campaign': raise ProposalError('INVALID_ARGUMENT','工具仅接受 mode=campaign。')
                if name=='preview_campaign': data = self.proposals.preview(spec)
                else:
                    data = self.proposals.propose(arguments['request_id'],spec)
                    refs.append({'kind':'proposal','proposal_id':data['proposal_id']})
            result = {'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['研究包只能按固定计划运行；模型不能批准、直接执行或追加节点。'],'error':None}
            if len(encode(result)) > 24000:
                result['data'] = {'omitted':True,'reason':'result_size_limit'}
                result['warnings'].append('完整配置和节点保存在人工审批与研究包结果页。')
            return json.loads(encode(result))
        except ProposalError as error: code,message = error.code,str(error)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,RecursionError) as error:
            code,message = 'CAMPAIGN_FAILED','研究包操作未完成：'+type(error).__name__
        return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
            'error':{'code':code,'message':message[:300]}}
