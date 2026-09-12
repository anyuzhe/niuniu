"""Fixed incremental-evidence proposals over existing derived statistics."""
from contextlib import contextmanager
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import UUID,uuid5
import fcntl
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore,load_record_fields
from quantlab.statistics.permutation import holm

FORMAT='incremental-evidence-v1'
PLAN_KEYS={'candidate_run_id','control_run_ids','train_end','horizon','alpha','return_pair'}


def identifier(value):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise ValueError('需要规范 UUID。') from None
    return value


def now():return datetime.now(timezone.utc).isoformat()

def normalize_plan(plan):
    if not isinstance(plan,dict) or set(plan)!=PLAN_KEYS:raise ValueError('增量证据计划字段不完整')
    candidate=identifier(plan['candidate_run_id']);controls=plan['control_run_ids']
    if not isinstance(controls,list) or not 1<=len(controls)<=5:
        raise ValueError('控制因子须为1–5个已完成研究')
    controls=[identifier(v) for v in controls]
    if candidate in controls or len(set(controls))!=len(controls):raise ValueError('候选与控制因子不能重复')
    split=date.fromisoformat(plan['train_end']);h=plan['horizon'];alpha=plan['alpha']
    if type(h) is not int or not 1<=h<=252:raise ValueError('持有期须为1–252根')
    if type(alpha) not in (int,float) or not 0<alpha<=.2:raise ValueError('family alpha须在0与0.2之间')
    pair=plan['return_pair']
    if pair is not None:
        if not isinstance(pair,dict) or set(pair)!={'candidate_run_id','baseline_run_id','evaluation_start'}:
            raise ValueError('成本后对照字段无效')
        pair={'candidate_run_id':identifier(pair['candidate_run_id']),
            'baseline_run_id':identifier(pair['baseline_run_id']),
            'evaluation_start':date.fromisoformat(pair['evaluation_start']).isoformat()}
        if pair['candidate_run_id']==pair['baseline_run_id']:raise ValueError('成本后候选与基准不能相同')
    return {'candidate_run_id':candidate,'control_run_ids':controls,'train_end':split.isoformat(),
        'horizon':h,'alpha':float(alpha),'return_pair':pair}

def _record(output,run_id,kind):
    path=Path(output).resolve()/identifier(run_id)/'experiment.json'
    if path.is_symlink() or not path.resolve().is_relative_to(Path(output).resolve()):raise ValueError('研究归档路径无效')
    record=load_record_fields(path,{'run_id','experiment_id','kind','status','manifest','children','summary'})
    if record.get('run_id')!=run_id or record.get('status')!='completed' or record.get('kind','factor')!=kind:
        raise ValueError('请选择已完成的'+kind+'归档')
    return record,path.parent


def _factor_sources(output,plan):
    ids=[plan['candidate_run_id'],*plan['control_run_ids']];records=[];fingerprints={}
    for run_id in ids:
        record,path=_record(output,run_id,'factor');records.append(record)
        fingerprints[run_id]=digest(snapshot_tree(output,run_id))
    base=records[0]['manifest'];cfg=base['config'];h=plan['horizon']
    if h not in cfg['horizons']:raise ValueError('候选归档没有所选持有期')
    split=date.fromisoformat(plan['train_end']);start=date.fromisoformat(cfg['data']['start']);end=date.fromisoformat(cfg['data']['end'])
    if not start<=split<end:raise ValueError('训练截止须位于归档区间内并保留样本外区间')
    for record in records[1:]:
        manifest=record['manifest'];other=manifest['config']
        for key in ('data_snapshot','universe'):
            if manifest.get(key)!=base.get(key):raise ValueError('因子来源的'+key+'不同')
        for key in ('data','context','processor','regime','regime_filter'):
            if other.get(key)!=cfg.get(key):raise ValueError('因子研究条件不同：'+key)
        if h not in other['horizons']:raise ValueError('控制因子缺少所选持有期')
        if manifest.get('runtime')!=base.get('runtime'):raise ValueError('因子运行环境不同')
    if base.get('runtime')!=runtime_fingerprint():raise ValueError('来源运行环境与当前代码不同，请先重建基准')
    return records,fingerprints

def _execution_sources(output,pair):
    if pair is None:return [],{}
    ids=[pair['candidate_run_id'],pair['baseline_run_id']];records=[];fingerprints={}
    for run_id in ids:
        record,path=_record(output,run_id,'execution');records.append(record)
        fingerprints[run_id]=digest(snapshot_tree(output,run_id))
    first=records[0]['manifest'];second=records[1]['manifest']
    for key in ('data_snapshot','universe','execution','portfolio','backend','market_rules'):
        if first.get(key)!=second.get(key):raise ValueError('成本后账户不可比较：'+key)
    if first.get('runtime')!=runtime_fingerprint() or second.get('runtime')!=runtime_fingerprint():
        raise ValueError('成本后来源运行环境与当前代码不同')
    start=date.fromisoformat(pair['evaluation_start']);cfg=first['config']['data']
    if not date.fromisoformat(cfg['start'])<=start<=date.fromisoformat(cfg['end']):
        raise ValueError('成本后评价起点超出归档区间')
    return records,fingerprints


def prepare_plan(output,plan):
    output=Path(output).resolve();plan=normalize_plan(plan)
    _,factor_fingerprints=_factor_sources(output,plan)
    _,execution_fingerprints=_execution_sources(output,plan['return_pair'])
    tests=[{'id':'residual_ic','kind':'residual_alpha'}]
    if plan['return_pair'] is not None:tests.append({'id':'net_return_increment','kind':'return_increment'})
    return {'format':FORMAT,'plan':plan,'sources':{**factor_fingerprints,**execution_fingerprints},
        'planned_tests':tests,'runtime':runtime_fingerprint(),
        'limitations':['固定测试族在执行前冻结；失败槽位不会从Holm分母中消失。',
            '残差IC仅检验相对指定控制因子的线性新颖性，不是因果Alpha。',
            '成本后净收益增量仅比较兼容账户模拟，不代表未来可交易收益。']}

class IncrementalEvidenceStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.root=self.output/'_incremental_evidence'
        if not self.output.is_dir():raise ValueError('研究工作空间不存在')
    def folder(self,proposal_id):
        path=self.root/identifier(proposal_id)
        if self.root.is_symlink() or path.is_symlink():raise ValueError('增量证据路径不能是符号链接')
        return path
    @contextmanager
    def locked(self,proposal_id):
        folder=self.folder(proposal_id);folder.mkdir(parents=True,exist_ok=True);lock=folder/'plan.lock'
        if lock.is_symlink():raise ValueError('增量证据锁路径异常')
        with lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield folder
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    def get(self,proposal_id):
        path=self.folder(proposal_id)/'state.json'
        if path.is_symlink() or not path.exists():raise ValueError('增量证据提案不存在')
        value=read_checked(path)
        if value.get('proposal_id')!=proposal_id:raise ValueError('增量证据提案身份不一致')
        return value
    def save(self,state):write_checked(self.folder(state['proposal_id'])/'state.json',state)
    def list(self):
        rows=[];errors=[]
        for folder in sorted(self.root.iterdir()) if self.root.exists() else []:
            try:rows.append(self.get(folder.name))
            except (OSError,ValueError,KeyError,TypeError) as error:errors.append({'entry':folder.name,'error':str(error)[:200]})
        rows.sort(key=lambda v:v['created_at'],reverse=True);return {'proposals':rows,'errors':errors}

class IncrementalEvidenceService:
    def __init__(self,output):
        self.output=Path(output).resolve();self.store=IncrementalEvidenceStore(self.output)
    def preview(self,plan):
        prepared=prepare_plan(self.output,plan)
        return {**prepared,'prepared_digest':digest(prepared),'new_research_jobs':0,'host_confirmation_required':True}
    def propose(self,request_id,plan):
        identifier(request_id);prepared=prepare_plan(self.output,plan);proposal_id=str(uuid5(UUID(request_id),FORMAT))
        with self.store.locked(proposal_id):
            path=self.store.folder(proposal_id)/'state.json'
            if path.exists():
                state=self.store.get(proposal_id)
                if state['request_id']!=request_id or state['prepared_digest']!=digest(prepared):
                    raise ValueError('同一请求编号不能改写已冻结的增量证据计划')
                return state
            state={'format':FORMAT,'proposal_id':proposal_id,'request_id':request_id,
                'status':'pending','created_at':now(),'prepared':prepared,
                'prepared_digest':digest(prepared),'result_run_id':None,'tests':[]}
            self.store.save(state);return state
    def get(self,proposal_id):return self.store.get(proposal_id)
    def list(self):return self.store.list()

    def _source_paths(self,plan):
        factor_ids=[plan['candidate_run_id'],*plan['control_run_ids']]
        factors=[self.output/run_id for run_id in factor_ids]
        pair=plan['return_pair'];accounts=[] if pair is None else [self.output/pair[k] for k in ('candidate_run_id','baseline_run_id')]
        return factors,accounts

    def _reuse_child(self,run_id,kind,source_ids):
        path=self.output/run_id/'experiment.json'
        if not path.exists():return None
        record=load_record_fields(path,{'run_id','kind','status','children','summary'})
        if record.get('run_id')!=run_id or record.get('kind')!=kind or record.get('status')!='completed':
            raise ValueError('确定性子研究编号已被不兼容归档占用')
        actual=[c['run_id'] for c in record.get('children',[])]
        if actual!=source_ids:raise ValueError('已有子研究来源与冻结计划不同')
        return {'run_id':run_id,'artifact_path':str(path.parent),'summary':record['summary'],'reused':True}

    def _run_residual(self,proposal_id,plan):
        from quantlab.experiments.residual import run_residual
        run_id=str(uuid5(UUID(proposal_id),'residual_ic'));sources=[plan['candidate_run_id'],*plan['control_run_ids']]
        existing=self._reuse_child(run_id,'residual_alpha',sources)
        if existing:return existing
        factors,_=self._source_paths(plan)
        result=run_residual(factors[0],factors[1:],date.fromisoformat(plan['train_end']),
            self.output,plan['horizon'],run_id=run_id)
        return {**result,'reused':False}

    def _run_return(self,proposal_id,plan):
        from quantlab.experiments.return_increment import compare_returns
        pair=plan['return_pair'];run_id=str(uuid5(UUID(proposal_id),'net_return_increment'))
        sources=[pair['candidate_run_id'],pair['baseline_run_id']]
        existing=self._reuse_child(run_id,'return_increment',sources)
        if existing:return existing
        _,accounts=self._source_paths(plan)
        result=compare_returns(accounts[0],accounts[1],date.fromisoformat(pair['evaluation_start']),
            self.output,run_id=run_id)
        return {**result,'reused':False}

    def execute(self,proposal_id,expected_digest,*,confirmed=False):
        if confirmed is not True:raise ValueError('必须由宿主明确确认后执行固定证据包')
        with self.store.locked(proposal_id):
            state=self.store.get(proposal_id)
            if state['prepared_digest']!=expected_digest:raise ValueError('显示计划与已冻结记录不一致')
            if state['status']=='completed':return state
            current=prepare_plan(self.output,state['prepared']['plan'])
            if current!=state['prepared']:raise ValueError('来源归档、代码或运行环境变化，请重新提案')
            state['status']='running';state['started_at']=state.get('started_at') or now();self.store.save(state)
            plan=state['prepared']['plan'];slots=[]
            actions=[('residual_ic','residual_alpha',lambda:self._run_residual(proposal_id,plan))]
            if plan['return_pair'] is not None:
                actions.append(('net_return_increment','return_increment',lambda:self._run_return(proposal_id,plan)))
            for test_id,kind,action in actions:
                old=next((r for r in state['tests'] if r['id']==test_id and r['status'] in ('completed','failed')),None)
                if old:slots.append(old);continue
                try:
                    result=action();summary=result['summary']
                    raw=summary['test'] if kind=='residual_alpha' else summary['permutation']
                    row={'id':test_id,'kind':kind,'status':'completed','run_id':result['run_id'],
                        'artifact_path':result['artifact_path'],'p_value':raw.get('p_value'),
                        'test_status':raw.get('status'),'reused':result['reused']}
                except (OSError,ValueError,KeyError,TypeError) as error:
                    row={'id':test_id,'kind':kind,'status':'failed','p_value':None,
                        'error':type(error).__name__+': '+str(error)[:300]}
                state['tests']=[r for r in state['tests'] if r['id']!=test_id]+[row]
                self.store.save(state);slots.append(row)
            adjusted=holm([r.get('p_value') for r in slots])
            for row,p in zip(slots,adjusted):row.update(p_holm=p,reject=p<=plan['alpha'] if p is not None else None)
            summary={'method':'fixed_incremental_evidence_family_v1','alpha':plan['alpha'],
                'planned_tests':len(slots),'available_tests':sum(r['p_holm'] is not None for r in slots),
                'workflow_status':'completed_with_failures' if any(r['status']=='failed' for r in slots) else 'completed',
                'tests':slots,'limitations':['Holm按执行前冻结的全部槽位校正；失败/不可检验项继续占名额。',
                    '残差IC不等于因果Alpha；成本后增量来自模拟账户，不证明未来盈利。',
                    '本包不自动挑选候选、控制因子、训练截止、持有期或评价起点。']}
            run_id=str(uuid5(UUID(proposal_id),'incremental_evidence_parent'));path=self.output/run_id
            children=[{'run_id':r['run_id'],'artifact_path':r['artifact_path'],'name':r['id']}
                for r in slots if r['status']=='completed']
            manifest={'runtime':runtime_fingerprint(),'config':{'research_question':'固定候选增量证据包'},
                'plan':plan,'prepared_digest':state['prepared_digest'],'source_fingerprints':state['prepared']['sources'],
                'code_hash':digest(Path(__file__).read_text())}
            record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':now(),'status':'completed',
                'kind':'incremental_evidence','manifest':manifest,'summary':summary,'children':children}
            if path.exists():
                existing=load_record_fields(path/'experiment.json',{'run_id','kind','status','manifest','summary','children'})
                if existing['run_id']!=run_id or existing['kind']!='incremental_evidence' or existing['manifest']!=manifest or existing['summary']!=summary:
                    raise ValueError('确定性父证据包编号已被不兼容归档占用')
            else:LocalExperimentStore(self.output).save(run_id,record,None)
            state.update(status='completed',finished_at=now(),result_run_id=run_id,tests=slots,summary=summary)
            self.store.save(state);return state
