"""Validated immutable DSL candidate presets; registration is host-only."""
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID,uuid5
import fcntl
import polars as pl
from quantlab.app import default_registry
from quantlab.causal import assert_prefix_invariant
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record_fields
from quantlab.workbench.server import ArtifactCatalog
from quantlab.factors.restricted_dsl import used_fields

NAMESPACE=UUID('762a494b-773f-4ae8-8c48-4aa9961879da')


def canonical_id(value):
    if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError('需要规范UUID')
    return value


class DslCandidateService:
    def __init__(self,output):
        self.output=Path(output).resolve();self.root=self.output/'_dsl_candidates';self.catalog=ArtifactCatalog(self.output)
        if not self.output.is_dir():raise ValueError('候选工作空间不存在')
    @contextmanager
    def locked(self):
        if self.root.is_symlink():raise ValueError('候选目录不能是符号链接')
        self.root.mkdir(exist_ok=True);lock=self.root/'candidate.lock'
        if lock.is_symlink():raise ValueError('候选锁不能是符号链接')
        with lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    def path(self,kind,identifier):
        canonical_id(identifier);folder=self.root/kind
        if folder.is_symlink():raise ValueError('候选记录目录异常')
        return folder/(identifier+'.json')
    def preview(self,name,ast,source_run_id):
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('候选名称须为1–120字符')
        canonical_id(source_run_id);path=self.catalog.file(source_run_id,'experiment.json')
        record=load_record_fields(path,{'run_id','experiment_id','kind','status','manifest'})
        if record.get('status')!='completed' or record.get('kind','factor')!='factor':
            raise ValueError('验证来源必须是已完成单因子归档')
        bars_path=self.catalog.file(source_run_id,'bars.parquet')
        bars=pl.read_parquet(bars_path)
        if not 10<=bars.height<=250000:raise ValueError('验证K线数量须为10–250000')
        factor=default_registry().get('DSL.RESTRICTED','1.0.0');params=factor.parameters({'ast':ast})
        values=__import__('quantlab.factors.engine',fromlist=['compute_factor']).compute_factor(factor,bars,params)
        finite=values['value'].is_not_null().sum()
        if finite<max(3,min(20,bars.height//10)):raise ValueError('候选在验证样本上有效值过少')
        times=bars['available_at'].unique().sort().to_list()
        if len(times)<4:raise ValueError('因果检查至少需要4个不同时点')
        cutoffs=[times[max(1,len(times)//3)-1],times[max(2,2*len(times)//3)-1]]
        try:assert_prefix_invariant(factor,bars,params,cutoffs)
        except AssertionError as error:raise ValueError('候选未通过前缀因果不变性检查') from error
        tree=snapshot_tree(self.output,source_run_id);source_hash=digest(tree)
        core={'name':name.strip(),'factor_id':'DSL.RESTRICTED','factor_version':'1.0.0',
            'parameters':params,'source_run_id':source_run_id,'source_experiment_id':record['experiment_id'],
            'source_fingerprint':source_hash,'factor_code_hash':default_registry().code_hash(factor)}
        candidate_id=str(uuid5(NAMESPACE,digest(core)))
        validation={'rows':bars.height,'finite_rows':finite,'null_rows':bars.height-finite,
            'symbols':bars['symbol'].n_unique(),'timestamps':len(times),'cutoffs':[v.isoformat() for v in cutoffs],
            'used_fields':sorted(used_fields(params['ast'])),'prefix_invariant':True,
            'labels_used':False,'research_jobs':0,'alpha_verified':False}
        return {'version':1,'candidate_id':candidate_id,**core,'validation':validation,
            'limitations':['注册只证明AST合同与所选K线前缀检查通过，不证明所有输入下因果性。',
                '验证不读取未来收益标签，不执行Alpha研究；注册后仍须走原研究提案、成本与增量证据流程。']}
    def propose(self,request_id,name,ast,source_run_id):
        canonical_id(request_id);plan=self.preview(name,ast,source_run_id);proposal_id=str(uuid5(NAMESPACE,'proposal:'+request_id))
        record={'proposal_id':proposal_id,'request_id':request_id,'status':'pending','plan':plan,'plan_digest':digest(plan)}
        path=self.path('proposals',request_id)
        with self.locked():
            path.parent.mkdir(exist_ok=True)
            if path.exists():
                old=read_checked(path)
                if old['plan_digest']!=record['plan_digest']:raise ValueError('同一请求编号不能用于不同候选')
                return old
            write_checked(path,record)
        return record
    def proposal(self,request_id):return read_checked(self.path('proposals',request_id))
    def register(self,request_id,expected_digest,*,confirmed=False):
        if confirmed is not True:raise ValueError('必须在宿主核对候选后明确注册')
        canonical_id(request_id)
        with self.locked():
            proposal=read_checked(self.path('proposals',request_id))
            if proposal['plan_digest']!=expected_digest:raise ValueError('候选预览已变化')
            if proposal['status']=='registered':return self.get(proposal['plan']['candidate_id'])
            if proposal['status']!='pending':raise ValueError('候选提案状态不能注册')
            plan=proposal['plan'];current=self.preview(plan['name'],plan['parameters']['ast'],plan['source_run_id'])
            if current!=plan:raise ValueError('验证来源、DSL代码或结果变化，请重新提案')
            path=self.path('registered',plan['candidate_id']);path.parent.mkdir(exist_ok=True)
            if path.exists():
                registered=read_checked(path)
                if registered['plan']!=plan:raise ValueError('候选编号冲突')
            else:
                from datetime import datetime,timezone
                registered={'candidate_id':plan['candidate_id'],'status':'registered',
                    'registered_at':datetime.now(timezone.utc).isoformat(),'plan':plan}
                write_checked(path,registered)
            proposal['status']='registered';proposal['registered_candidate_id']=plan['candidate_id'];write_checked(self.path('proposals',request_id),proposal)
            return registered
    def get(self,candidate_id):return read_checked(self.path('registered',candidate_id))
    def list(self,*,query='',limit=50):
        if not isinstance(query,str) or type(limit) is not int or not 1<=limit<=100:raise ValueError('候选查询参数无效')
        folder=self.root/'registered';rows=[];errors=[]
        if folder.is_symlink():raise ValueError('候选注册目录异常')
        for path in sorted(folder.glob('*.json')) if folder.exists() else []:
            try:
                value=read_checked(path);plan=value['plan']
                if query.casefold() in (plan['name']+' '+value['candidate_id']).casefold():
                    rows.append({'candidate_id':value['candidate_id'],'name':plan['name'],
                        'registered_at':value['registered_at'],'factor_id':plan['factor_id'],
                        'factor_version':plan['factor_version'],'used_fields':plan['validation']['used_fields']})
            except (OSError,ValueError,KeyError,TypeError) as error:errors.append({'entry':path.name,'error':str(error)[:160]})
        return {'candidates':rows[-limit:],'total':len(rows),'errors':errors}
    def pending(self,limit=50):
        folder=self.root/'proposals';rows=[];errors=[]
        for path in sorted(folder.glob('*.json')) if folder.exists() else []:
            try:
                value=read_checked(path)
                if value['status']=='pending':rows.append(value)
            except (OSError,ValueError,KeyError,TypeError) as error:errors.append({'entry':path.name,'error':str(error)[:160]})
        return {'proposals':rows[-limit:],'errors':errors}
