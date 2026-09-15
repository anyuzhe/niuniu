"""Finite host-approved autonomous research sessions; no shell, network, code or trading grant."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID,uuid4,uuid5
import fcntl,json,os

from quantlab.agent.planning import ProposalError,ResearchBudget
from quantlab.agent.proposals import ProposalService,workspace_identity
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest,encode

FORMAT='niuniu-research-session-grant-v1'
RECEIPT='niuniu-research-session-grant-receipt-v1'
SAFE_MODES={'single','holdout','walkforward','ablation','sweep','correlation'}
TERMINAL_JOBS={'completed','failed','cancelled','interrupted'}

def utc(value=None):
    value=value or datetime.now(timezone.utc)
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError('Research Session Grant 时点必须包含时区')
    return value.astimezone(timezone.utc)

def canonical(value):
    if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError('需要规范 UUID')
    return value

class SessionGrantStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.root=self.output/'_research_session_grants'
        self.current=self.root/'current.json';self.lock=self.root/'grant.lock'
        if not self.output.is_dir():raise ValueError('研究工作空间不存在')
    @contextmanager
    def locked(self,create=True):
        if self.root.is_symlink() or self.current.is_symlink() or self.lock.is_symlink():raise ValueError('Research Session Grant 路径不能是符号链接')
        if create:self.root.mkdir(exist_ok=True)
        if not self.root.exists():yield;return
        with self.lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    def load(self):
        if not self.current.exists():return None
        value=json.loads(self.current.read_text());checksum=value.pop('checksum',None)
        if value.get('format')!=FORMAT or digest(value)!=checksum:raise ValueError('Research Session Grant 回执损坏')
        return value
    def save(self,value):
        payload={**value,'checksum':digest(value)};tmp=self.root/('.'+str(uuid4())+'.pending')
        try:
            with tmp.open('x',encoding='utf-8') as stream:stream.write(encode(payload));stream.flush();os.fsync(stream.fileno())
            tmp.replace(self.current)
        finally:tmp.unlink(missing_ok=True)
    def archive(self,value):
        history=self.root/'history'
        if history.is_symlink():raise ValueError('Research Session Grant 历史路径不能是符号链接')
        history.mkdir(exist_ok=True);target=history/(canonical(value['grant_id'])+'.json')
        payload={**value,'checksum':digest(value)}
        if target.exists():
            existing=json.loads(target.read_text())
            if existing!=payload:raise ValueError('Research Session Grant 历史记录冲突')
            return target
        target.write_text(encode(payload));return target

def _factor_key(value):
    if not isinstance(value,str) or '@' not in value:raise ValueError('allowed_factors 必须使用 FACTOR_ID@version')
    factor,version=value.rsplit('@',1)
    if not factor or not version:raise ValueError('allowed_factors 无效')
    return factor+'@'+version

def preview_grant(output,data_root,scope,*,expires_at,max_jobs=5,max_leaf_studies=32,
                  max_total_leaf_studies=80,max_total_bar_evaluations=20_000_000,
                  max_total_resample_date_draws=100_000_000,cooperative_seconds=300,max_active_jobs=2,now=None):
    stamp=utc(now);expiry=utc(datetime.fromisoformat(expires_at))
    if not timedelta(minutes=5)<=expiry-stamp<=timedelta(hours=24):raise ValueError('Research Session Grant 有效期须为5分钟至24小时')
    if type(max_jobs) is not int or not 1<=max_jobs<=20:raise ValueError('Research Session Grant 最多1–20个任务')
    if type(max_active_jobs) is not int or not 1<=max_active_jobs<=4:raise ValueError('同时活动任务上限须为1–4')
    for value,name,limit in ((max_leaf_studies,'单任务叶子研究',64),(max_total_leaf_studies,'总叶子研究',256)):
        if type(value) is not int or not 1<=value<=limit:raise ValueError(name+'预算无效')
    if type(max_total_bar_evaluations) is not int or not 1<=max_total_bar_evaluations<=100_000_000:raise ValueError('总K线评价量预算无效')
    if type(max_total_resample_date_draws) is not int or not 1<=max_total_resample_date_draws<=500_000_000:raise ValueError('总重采样预算无效')
    if type(cooperative_seconds) is not int or not 30<=cooperative_seconds<=3600:raise ValueError('单任务合作式时限须为30–3600秒')
    scope=_normalize_scope(scope)
    from quantlab.app import default_registry
    registry=default_registry()
    for item in scope['allowed_factors']:
        factor,version=item.rsplit('@',1);registry.get(factor,version)
    output=Path(output).resolve();data_root=Path(data_root).resolve()
    if not output.is_dir() or not data_root.is_dir():raise ValueError('工作空间或行情目录不存在')
    budget=ResearchBudget(max_symbols=len(scope['symbols']),max_calendar_days=(date.fromisoformat(scope['end'])-date.fromisoformat(scope['start'])).days+1,
        max_leaf_studies=max_leaf_studies,max_bar_evaluations=max_total_bar_evaluations,
        max_resample_date_draws=max_total_resample_date_draws,cooperative_seconds=cooperative_seconds,max_active_jobs=max_active_jobs)
    return {'version':1,'prepared_at':stamp.isoformat(),'expires_at':expiry.isoformat(),'scope':scope,
        'limits':{'max_jobs':max_jobs,'max_leaf_studies_per_job':max_leaf_studies,
            'max_total_leaf_studies':max_total_leaf_studies,'max_total_bar_evaluations':max_total_bar_evaluations,
            'max_total_resample_date_draws':max_total_resample_date_draws,'cooperative_seconds':cooperative_seconds,'max_active_jobs':max_active_jobs},
        'binding':{'output':workspace_identity(output),'data_root':workspace_identity(data_root),'runtime':runtime_fingerprint()},
        'research_budget':asdict(budget),'network_allowed':False,'shell_allowed':False,'code_write_allowed':False,
        'real_trade_allowed':False,'approval_required_per_job':False,
        'scope_note':'仅允许本机现有数据；每个授权任务入队前单独冻结实际输入字节。'}

def _normalize_scope(scope):
    if not isinstance(scope,dict) or set(scope)!={'symbols','timeframe','start','end','adjustment','qualification','allowed_modes','allowed_factors'}:raise ValueError('Research Session Grant scope 字段不完整')
    symbols=scope['symbols'];modes=scope['allowed_modes'];factors=scope['allowed_factors']
    if not isinstance(symbols,list) or not symbols or len(symbols)>100 or len(set(symbols))!=len(symbols):raise ValueError('授权证券须为1–100个不同代码')
    import re
    if any(not isinstance(s,str) or not re.fullmatch(r'(sh|sz|bj)\.\d{6}',s) for s in symbols):raise ValueError('授权证券代码无效')
    from quantlab.domain import Timeframe
    Timeframe(scope['timeframe']);start=date.fromisoformat(scope['start']);end=date.fromisoformat(scope['end'])
    if start>end:raise ValueError('授权日期范围无效')
    if scope['adjustment'] not in ('raw','qfq'):raise ValueError('授权复权口径无效')
    if scope['qualification'] not in ('research_only','retrospective_reference','strict_pit'):raise ValueError('Session Grant v1 不开放 official_rule_covered')
    if not isinstance(modes,list) or not modes or set(modes)-SAFE_MODES:raise ValueError('授权研究模式无效')
    if not isinstance(factors,list) or not factors or len(factors)>50:raise ValueError('授权因子须为1–50个注册因子')
    return {'symbols':symbols,'timeframe':scope['timeframe'],'start':scope['start'],'end':scope['end'],
        'adjustment':scope['adjustment'],'qualification':scope['qualification'],
        'allowed_modes':sorted(set(modes)),'allowed_factors':sorted({_factor_key(v) for v in factors})}
def authorize_grant(output,data_root,plan,expected_digest,*,confirmed=False,now=None):
    if confirmed is not True:raise ValueError('必须在宿主界面核对完整 Research Session Grant 并明确授权')
    if digest(plan)!=expected_digest:raise ValueError('授权摘要已变化，请重新预览')
    stamp=utc(now);prepared=utc(datetime.fromisoformat(plan['prepared_at']))
    if not timedelta(0)<=stamp-prepared<=timedelta(minutes=30):raise ValueError('授权预览已过期或时钟回退')
    current=preview_grant(output,data_root,plan['scope'],expires_at=plan['expires_at'],now=prepared,
        max_jobs=plan['limits']['max_jobs'],max_leaf_studies=plan['limits']['max_leaf_studies_per_job'],
        max_total_leaf_studies=plan['limits']['max_total_leaf_studies'],max_total_bar_evaluations=plan['limits']['max_total_bar_evaluations'],
        max_total_resample_date_draws=plan['limits']['max_total_resample_date_draws'],cooperative_seconds=plan['limits']['cooperative_seconds'],max_active_jobs=plan['limits']['max_active_jobs'])
    if current!=plan or stamp>=utc(datetime.fromisoformat(plan['expires_at'])):raise ValueError('授权范围、代码、目录或期限变化')
    store=SessionGrantStore(output)
    with store.locked():
        old=store.load()
        if old:
            if old.get('enabled') and stamp<utc(datetime.fromisoformat(old['plan']['expires_at'])):raise ValueError('已有有效 Research Session Grant；请先撤销')
            job_root=Path(output).resolve()/'_jobs';nonterminal=[]
            for item in old.get('jobs',[]):
                path=job_root/(item['job_id']+'.json')
                if path.is_file():
                    try:status=json.loads(path.read_text()).get('status')
                    except (OSError,ValueError,TypeError):status='unknown'
                    if status not in TERMINAL_JOBS:nonterminal.append(item['job_id'])
            if nonterminal:raise ValueError('旧 Research Session Grant 仍有未终止任务，请先取消或等待结束')
            store.archive(old)
        state={'format':FORMAT,'grant_id':str(uuid4()),'plan':plan,'plan_digest':digest(plan),'enabled':True,'status':'authorized',
            'authorized_at':stamp.isoformat(),'revoked_at':None,'jobs':[],'used':{'jobs':0,'leaf_studies':0,'bar_evaluations':0,'resample_date_draws':0},
            'authorization_source':'explicit_host_confirmation'}
        store.save(state);return state

def revoke_grant(output,grant_id,*,confirmed=False,now=None):
    if confirmed is not True:raise ValueError('撤销 Research Session Grant 需要宿主明确确认')
    store=SessionGrantStore(output);stamp=utc(now)
    with store.locked(False):
        state=store.load()
        if state is None or state['grant_id']!=canonical(grant_id):raise ValueError('Research Session Grant 不存在')
        if not state['enabled']:return state
        state.update(enabled=False,status='revoked',revoked_at=stamp.isoformat());store.save(state);return state
def _binding_matches(plan,output,data_root):
    return plan['binding']=={'output':workspace_identity(output),'data_root':workspace_identity(data_root),'runtime':runtime_fingerprint()}

def grant_status(output,data_root=None,*,now=None):
    store=SessionGrantStore(output)
    with store.locked(False):state=store.load()
    if state is None:return {'format':FORMAT,'status':'not_configured','enabled':False,'grant':None,'jobs':[],'remaining':None}
    stamp=utc(now);expired=stamp>=utc(datetime.fromisoformat(state['plan']['expires_at']))
    enabled=bool(state['enabled'] and not expired)
    status='expired' if expired and state['enabled'] else state['status']
    jobs=[];job_root=Path(output)/'_jobs'
    for item in state['jobs']:
        row={k:item.get(k) for k in ('request_id','job_id','spec_digest','reserved_at','estimate')}
        path=job_root/(item['job_id']+'.json')
        if path.is_file():
            try:row['status']=json.loads(path.read_text()).get('status','unknown')
            except (OSError,ValueError,TypeError):row['status']='unreadable'
        else:row['status']='reserved' if item.get('queue_submitted') is not True else 'missing'
        jobs.append(row)
    limits=state['plan']['limits'];used=state['used']
    remaining={'jobs':max(0,limits['max_jobs']-used['jobs']),
        'leaf_studies':max(0,limits['max_total_leaf_studies']-used['leaf_studies']),
        'bar_evaluations':max(0,limits['max_total_bar_evaluations']-used['bar_evaluations']),
        'resample_date_draws':max(0,limits['max_total_resample_date_draws']-used['resample_date_draws'])}
    binding_ok=None if data_root is None else _binding_matches(state['plan'],Path(output).resolve(),Path(data_root).resolve())
    return {'format':FORMAT,'status':status,'enabled':enabled,'grant':{k:state[k] for k in ('grant_id','authorized_at','revoked_at','authorization_source')},
        'scope':state['plan']['scope'],'expires_at':state['plan']['expires_at'],'used':used,'remaining':remaining,'binding_ok':binding_ok,'jobs':jobs,
        'limitations':['Grant 不允许 Shell、联网下载、代码写入、Campaign、Execution 或真实交易。','失败/取消任务仍消耗已授权任务与计算预算，防止结果导向反复试验。']}
def _validate_spec(plan,spec):
    scope=plan['scope'];mode=spec.get('mode','single')
    if mode not in scope['allowed_modes']:raise ProposalError('GRANT_SCOPE','研究模式超出 Session Grant 范围')
    if any(key in spec for key in ('execution','portfolio','execution_backend','market_rules','theory','theory_version','theory_study','context')):
        raise ProposalError('GRANT_SCOPE','Session Grant v1 不允许 Execution/Theory/Context 等扩展输入')
    universe=spec.get('universe') or {'mode':'explicit'}
    if universe.get('mode','explicit')!='explicit' or universe.get('reference_manifest'):
        raise ProposalError('GRANT_SCOPE','Session Grant v1 只允许显式证券池')
    symbols=spec.get('symbols') or []
    if not symbols or not set(symbols)<=set(scope['symbols']):raise ProposalError('GRANT_SCOPE','证券超出 Session Grant 范围')
    if spec.get('timeframe','1d')!=scope['timeframe']:raise ProposalError('GRANT_SCOPE','K线周期超出 Session Grant 范围')
    if not date.fromisoformat(scope['start'])<=date.fromisoformat(spec['start'])<=date.fromisoformat(spec['end'])<=date.fromisoformat(scope['end']):
        raise ProposalError('GRANT_SCOPE','日期超出 Session Grant 范围')
    if spec.get('adjustment','qfq')!=scope['adjustment']:raise ProposalError('GRANT_SCOPE','复权口径超出 Session Grant 范围')
    if spec.get('qualification','research_only')!=scope['qualification']:raise ProposalError('GRANT_SCOPE','数据资格级别必须与 Session Grant 完全一致')
    key=spec.get('factor','BASE.MOMENTUM')+'@'+spec.get('version','1.0.0')
    if key not in scope['allowed_factors']:raise ProposalError('GRANT_SCOPE','因子不在 Session Grant 白名单')
    if spec.get('replay') is not True:raise ProposalError('GRANT_SCOPE','Session Grant 研究必须 replay=true 以保留完整证据')

def _grant_receipt(state,request_id):
    return {'format':RECEIPT,'grant_id':state['grant_id'],'plan_digest':state['plan_digest'],'request_id':canonical(request_id),
        'authorized_at':state['authorized_at'],'expires_at':state['plan']['expires_at']}
def validate_grant_receipt(value):
    if not isinstance(value,dict) or set(value)!={'format','grant_id','plan_digest','request_id','authorized_at','expires_at'} or value.get('format')!=RECEIPT:
        raise ValueError('Invalid Research Session Grant receipt')
    canonical(value['grant_id']);canonical(value['request_id'])
    if not isinstance(value['plan_digest'],str) or len(value['plan_digest'])!=64:raise ValueError('Invalid Research Session Grant digest')
    for key in ('authorized_at','expires_at'):
        if datetime.fromisoformat(value[key]).tzinfo is None:raise ValueError('Research Session Grant receipt missing timezone')

def assert_grant_active(output,data_root,receipt,*,now=None):
    validate_grant_receipt(receipt);store=SessionGrantStore(output)
    with store.locked(False):state=store.load()
    if state is None or state['grant_id']!=receipt['grant_id'] or state['plan_digest']!=receipt['plan_digest']:
        raise ValueError('Research Session Grant identity changed or missing')
    if digest(state['plan'])!=state['plan_digest']:raise ValueError('Research Session Grant plan changed')
    if not state['enabled'] or state['status']!='authorized':raise ValueError('Research Session Grant 已撤销或不可用')
    if utc(now)>=utc(datetime.fromisoformat(state['plan']['expires_at'])):raise ValueError('Research Session Grant 已过期')
    if not _binding_matches(state['plan'],Path(output).resolve(),Path(data_root).resolve()):raise ValueError('Research Session Grant 代码、工作空间或数据目录已变化')
    if not any(j['request_id']==receipt['request_id'] for j in state['jobs']):raise ValueError('任务不属于当前 Research Session Grant')
    return state

class ResearchSessionGrantService:
    def __init__(self,output,data_root,queue_factory):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve();self.queue_factory=queue_factory;self.store=SessionGrantStore(output)
    def status(self):return grant_status(self.output,self.data_root)
    def _active_state(self,state,grant_id,request_id):
        if state is None or state['grant_id']!=grant_id:raise ProposalError('GRANT_NOT_FOUND','Research Session Grant 不存在')
        receipt=_grant_receipt(state,request_id)
        validate_grant_receipt(receipt)
        if digest(state['plan'])!=state['plan_digest']:raise ProposalError('GRANT_INVALID','Research Session Grant 计划已变化')
        if not state['enabled'] or state['status']!='authorized':raise ProposalError('GRANT_REVOKED','Research Session Grant 已撤销或不可用')
        if utc()>=utc(datetime.fromisoformat(state['plan']['expires_at'])):raise ProposalError('GRANT_EXPIRED','Research Session Grant 已过期')
        if not _binding_matches(state['plan'],self.output,self.data_root):raise ProposalError('GRANT_STALE','代码、工作空间或行情目录已变化')
        return receipt
    def submit(self,grant_id,request_id,spec):
        grant_id=canonical(grant_id);request_id=canonical(request_id);spec=json.loads(encode(spec));spec_digest=digest(spec)
        with self.store.locked(False):
            state=self.store.load();receipt=self._active_state(state,grant_id,request_id)
            item=next((j for j in state['jobs'] if j['request_id']==request_id),None)
            if item is not None:
                if item['spec_digest']!=spec_digest:raise ProposalError('CONFLICT','同一授权请求编号不能用于不同研究配置')
            else:
                _validate_spec(state['plan'],spec);budget=ResearchBudget(**state['plan']['research_budget'])
                preview=ProposalService(self.output,self.data_root,budget=budget).preview(spec);estimate=preview['estimate'];limits=state['plan']['limits'];used=state['used']
                checks=(('jobs',1,limits['max_jobs']),('leaf_studies',estimate['leaf_studies'],limits['max_total_leaf_studies']),('bar_evaluations',estimate['bar_evaluations_upper_estimate'],limits['max_total_bar_evaluations']),('resample_date_draws',estimate['resample_date_draws_upper_estimate'],limits['max_total_resample_date_draws']))
                for key,amount,maximum in checks:
                    if used[key]+amount>maximum:raise ProposalError('GRANT_BUDGET_EXCEEDED','Research Session Grant '+key+' 总预算不足')
                job_id=str(uuid5(UUID(grant_id),'research-session:'+request_id))
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                freeze=ApprovalInputFreezeStore(self.output,self.data_root).capture(job_id,spec,preview['qualification'])
                item={'request_id':request_id,'job_id':job_id,'spec':spec,'spec_digest':spec_digest,'estimate':estimate,'approval_freeze':freeze,'reserved_at':utc().isoformat(),'queue_submitted':False}
                state['jobs'].append(item);used.update(jobs=used['jobs']+1,leaf_studies=used['leaf_studies']+estimate['leaf_studies'],bar_evaluations=used['bar_evaluations']+estimate['bar_evaluations_upper_estimate'],resample_date_draws=used['resample_date_draws']+estimate['resample_date_draws_upper_estimate']);self.store.save(state)
        return self._submit_reserved(item,receipt)
    def _submit_reserved(self,item,receipt):
        assert_grant_active(self.output,self.data_root,receipt);queue=self.queue_factory()
        jobs=queue.list();existing=next((j for j in jobs if j['job_id']==item['job_id']),None)
        limits=SessionGrantStore(self.output).load()['plan']['limits']
        guard={'runtime':runtime_fingerprint(),'cooperative_seconds':limits['cooperative_seconds'],'max_active_jobs':limits['max_active_jobs'],'approval_freeze':item['approval_freeze'],'session_grant':receipt}
        if existing is not None:
            if existing['spec']!=item['spec'] or existing.get('execution_guard')!=guard:raise ProposalError('CONFLICT','授权任务与共享队列已有任务冲突')
            result=existing
        else:
            if item.get('queue_submitted') is True:raise ProposalError('LOST_JOB','授权任务已提交但共享队列记录缺失，拒绝自动重建')
            result=queue.submit(item['job_id'],item['spec'],execution_guard=guard)
        with self.store.locked(False):
            state=self.store.load();current=next(j for j in state['jobs'] if j['request_id']==item['request_id'])
            if not current.get('queue_submitted'):
                current['queue_submitted']=True;current['submitted_at']=utc().isoformat();self.store.save(state)
        return {'grant_id':receipt['grant_id'],'job':result,'estimate':item['estimate'],'remaining':grant_status(self.output,self.data_root)['remaining'],'evidence':[{'kind':'job','job_id':item['job_id']},{'kind':'research_session_grant','grant_id':receipt['grant_id']}]}
