"""Frozen Alpha Factory over registered DSL candidates; host approval required."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import UUID,uuid5
import fcntl
import json

from quantlab.agent.candidate_review import compare_candidate
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.statistics.permutation import holm
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore,load_record_fields

NAMESPACE=UUID('bba57ed9-e650-4dcb-b7d0-f177bdf7ce91')
FORMAT='alpha-factory-v1'
PLAN_KEYS={'name','candidate_ids','baseline_run_id','control_run_ids','baseline_execution_run_id',
    'train_end','evaluation_start','horizon','alpha','min_common_finite_ratio','max_abs_signal_corr',
    'require_positive_paired_ic_difference','require_net_return'}


def canonical_id(value):
    if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError('需要规范UUID')
    return value


def now():return datetime.now(timezone.utc).isoformat()

def normalize_plan(plan):
    if not isinstance(plan,dict) or set(plan)!=PLAN_KEYS:raise ValueError('Alpha Factory计划字段不完整')
    name=plan['name']
    if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('工厂名称须为1–120字符')
    candidates=plan['candidate_ids']
    if not isinstance(candidates,list) or not 1<=len(candidates)<=12:raise ValueError('一次工厂须冻结1–12个候选')
    candidates=[canonical_id(v) for v in candidates]
    if len(set(candidates))!=len(candidates):raise ValueError('候选不能重复')
    baseline=canonical_id(plan['baseline_run_id']);controls=plan['control_run_ids']
    if not isinstance(controls,list) or not 1<=len(controls)<=5:raise ValueError('控制因子须为1–5个完成归档')
    controls=[canonical_id(v) for v in controls]
    if len(set(controls))!=len(controls):raise ValueError('控制因子不能重复')
    execution=plan['baseline_execution_run_id']
    if execution is not None:execution=canonical_id(execution)
    require_net=plan['require_net_return']
    if type(require_net) is not bool or (require_net and execution is None):
        raise ValueError('启用成本后增量时必须提供基准执行归档')
    horizon=plan['horizon'];alpha=plan['alpha']
    if type(horizon) is not int or not 1<=horizon<=252:raise ValueError('持有期须为1–252根')
    if type(alpha) not in (int,float) or not 0<alpha<=.2:raise ValueError('family alpha须在0与0.2之间')
    split=date.fromisoformat(plan['train_end']);evaluation=date.fromisoformat(plan['evaluation_start'])
    if evaluation<=split:raise ValueError('成本后评价起点必须晚于训练截止')
    ratio=plan['min_common_finite_ratio'];corr=plan['max_abs_signal_corr']
    if type(ratio) not in (int,float) or not 0<ratio<=1:raise ValueError('共同有限样本比例须在0与1之间')
    if type(corr) not in (int,float) or not 0<=corr<=1:raise ValueError('最大绝对相关须在0与1之间')
    positive=plan['require_positive_paired_ic_difference']
    if type(positive) is not bool:raise ValueError('配对IC方向开关必须为布尔值')
    return {'name':name.strip(),'candidate_ids':candidates,'baseline_run_id':baseline,
        'control_run_ids':controls,'baseline_execution_run_id':execution,
        'train_end':split.isoformat(),'evaluation_start':evaluation.isoformat(),'horizon':horizon,'alpha':float(alpha),
        'min_common_finite_ratio':float(ratio),'max_abs_signal_corr':float(corr),
        'require_positive_paired_ic_difference':positive,'require_net_return':require_net}


def _record(output,run_id,kind='factor'):
    path=Path(output).resolve()/canonical_id(run_id)/'experiment.json'
    if path.is_symlink() or not path.resolve().is_relative_to(Path(output).resolve()) or not path.is_file():
        raise ValueError('研究归档路径无效')
    record=load_record_fields(path,{'run_id','experiment_id','kind','status','manifest','children','summary'})
    actual=record.get('kind','factor')
    if record.get('run_id')!=run_id or record.get('status')!='completed' or actual!=kind:
        raise ValueError('请选择已完成的'+kind+'归档')
    return record,path.parent

def _factor_spec(record,name,parameters):
    manifest=record['manifest'];cfg=deepcopy(manifest['config'])
    if manifest['universe'].get('id')!='explicit_symbols' or cfg.get('theory_origin'):
        raise ValueError('Alpha Factory当前只接受显式股票池和注册因子基准')
    names={'research_question':'question','factor_id':'factor','factor_version':'version','random_seed':'seed'}
    spec={names.get(k,k):v for k,v in cfg.items() if k not in ('data','theory_origin') and v is not None}
    spec.update(cfg['data']);spec.update(question=name,factor='DSL.RESTRICTED',version='1.0.0',
        parameters=parameters,mode='single',replay=True,
        adjustment=manifest['data_snapshot']['adjustment'])
    return spec


def _execution_spec(record,name,parameters):
    manifest=record['manifest'];cfg=deepcopy(manifest['config'])
    names={'research_question':'question','factor_id':'factor','factor_version':'version','random_seed':'seed'}
    spec={names.get(k,k):v for k,v in cfg.items() if k not in ('data','theory_origin') and v is not None}
    spec.update(cfg['data']);spec.update(question=name,factor='DSL.RESTRICTED',version='1.0.0',
        parameters=parameters,mode='execution',replay=True,
        adjustment=manifest['signal_data_snapshot']['adjustment'],execution=manifest['execution'],
        portfolio=manifest['portfolio'],execution_backend=manifest['backend'])
    if manifest.get('market_rules') is not None:spec['market_rules']=manifest['market_rules']
    return spec

def prepare_factory(output,plan):
    from quantlab.app import default_registry
    from quantlab.agent.planning import preview_experiment
    output=Path(output).resolve();plan=normalize_plan(plan);runtime=runtime_fingerprint()
    baseline,_=_record(output,plan['baseline_run_id']);base=baseline['manifest'];cfg=base['config']
    if base.get('runtime')!=runtime:raise ValueError('基准运行环境与当前代码不同，请先重建基准')
    if plan['horizon'] not in cfg['horizons']:raise ValueError('基准缺少所选持有期')
    split=date.fromisoformat(plan['train_end']);start=date.fromisoformat(cfg['data']['start']);end=date.fromisoformat(cfg['data']['end'])
    if not start<=split<end:raise ValueError('训练截止须位于基准区间内并保留样本外')
    if not split<date.fromisoformat(plan['evaluation_start'])<=end:raise ValueError('评价起点须位于训练截止之后和基准结束之前')
    source_fingerprints={plan['baseline_run_id']:digest(snapshot_tree(output,plan['baseline_run_id']))}
    for run_id in plan['control_run_ids']:
        record,_=_record(output,run_id);manifest=record['manifest'];other=manifest['config']
        for key in ('data_snapshot','universe'):
            if manifest.get(key)!=base.get(key):raise ValueError('控制因子来源不同：'+key)
        for key in ('data','context','processor','regime','regime_filter'):
            if other.get(key)!=cfg.get(key):raise ValueError('控制因子研究条件不同：'+key)
        if plan['horizon'] not in other['horizons']:raise ValueError('控制因子缺少所选持有期')
        if manifest.get('runtime')!=runtime:raise ValueError('控制因子运行环境与当前代码不同')
        source_fingerprints[run_id]=digest(snapshot_tree(output,run_id))
    registry=default_registry();dsl=registry.get('DSL.RESTRICTED','1.0.0');dsl_hash=registry.code_hash(dsl)
    service=DslCandidateService(output);candidates=[]
    for candidate_id in plan['candidate_ids']:
        record=service.get(candidate_id);candidate=record['plan']
        if candidate['factor_code_hash']!=dsl_hash:raise ValueError('DSL代码变化；请重新验证并注册候选')
        params=dsl.parameters(candidate['parameters'])
        spec=_factor_spec(baseline,plan['name']+' · '+candidate['name'],params)
        preview_experiment(spec)
        candidates.append({'candidate_id':candidate_id,'name':candidate['name'],'parameters':params,
            'registration_hash':digest(record),'factor_spec':spec})
    execution_record=None
    if plan['require_net_return']:
        execution_record,_=_record(output,plan['baseline_execution_run_id'],'execution')
        manifest=execution_record['manifest'];ecfg=manifest['config']
        if manifest.get('runtime')!=runtime:raise ValueError('基准执行归档运行环境与当前代码不同')
        for key in ('factor_id','factor_version','parameters','data'):
            if ecfg.get(key)!=cfg.get(key):raise ValueError('基准执行归档与因子基准不一致：'+key)
        if manifest.get('universe')!=base.get('universe') or manifest.get('signal_data_snapshot')!=base.get('data_snapshot'):
            raise ValueError('基准执行归档的股票池或信号行情快照不同')
        source_fingerprints[plan['baseline_execution_run_id']]=digest(snapshot_tree(output,plan['baseline_execution_run_id']))
        for candidate in candidates:
            spec=_execution_spec(execution_record,plan['name']+' · 成本后 · '+candidate['name'],candidate['parameters'])
            preview_experiment(spec);candidate['execution_spec']=spec
    tests=[]
    for candidate in candidates:
        tests.append({'candidate_id':candidate['candidate_id'],'id':'residual_ic','kind':'residual_alpha'})
        if plan['require_net_return']:
            tests.append({'candidate_id':candidate['candidate_id'],'id':'net_return_increment','kind':'return_increment'})
    return {'format':FORMAT,'plan':plan,'runtime':runtime,'sources':source_fingerprints,
        'candidates':candidates,'planned_tests':tests,'planned_test_count':len(tests),
        'selection_rule':{
            'min_common_finite_ratio':plan['min_common_finite_ratio'],
            'max_abs_signal_corr':plan['max_abs_signal_corr'],
            'require_positive_paired_ic_difference':plan['require_positive_paired_ic_difference'],
            'residual_holm_p_at_most':plan['alpha'],
            'residual_estimate_must_be_positive':True,
            'net_return_required':plan['require_net_return'],
            'net_return_holm_p_at_most':plan['alpha'] if plan['require_net_return'] else None,
            'net_return_estimate_must_be_positive':plan['require_net_return']},
        'limitations':['候选集合、样本、控制因子和测试族在执行前冻结；运行中不得按结果增删候选。',
            'Holm覆盖本Factory全部预设增量检验；失败或不可检验槽位继续占名额。',
            'recommended_for_watchlist只是固定规则筛选结果，不是Alpha认证或自动投资决策。']}

def bind_factory_inputs(prepared,data_root):
    from quantlab.agent.proposals import workspace_identity
    from quantlab.experiments.campaign_state import input_signature
    root=Path(data_root).resolve()
    if not root.is_dir():raise ValueError('Alpha Factory需要可读取的数据目录')
    signatures={}
    for candidate in prepared['candidates']:
        nodes=[('factor:'+candidate['candidate_id'],candidate['factor_spec'])]
        if 'execution_spec' in candidate:nodes.append(('execution:'+candidate['candidate_id'],candidate['execution_spec']))
        for node_id,spec in nodes:
            value=input_signature(spec,root)
            if value.get('status')!='available':raise ValueError('Factory输入尚不可用：'+node_id)
            signatures[node_id]=digest(value)
    return {**prepared,'data_root_binding':workspace_identity(root),'input_signatures':signatures}


class AlphaFactoryStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.root=self.output/'_alpha_factory'
        if not self.output.is_dir():raise ValueError('研究工作空间不存在')
    def folder(self,proposal_id):
        path=self.root/canonical_id(proposal_id)
        if self.root.is_symlink() or path.is_symlink():raise ValueError('Alpha Factory路径不能是符号链接')
        return path
    @contextmanager
    def locked(self,proposal_id):
        folder=self.folder(proposal_id);folder.mkdir(parents=True,exist_ok=True);lock=folder/'factory.lock'
        if lock.is_symlink():raise ValueError('Alpha Factory锁路径异常')
        with lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield folder
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    def get(self,proposal_id):
        path=self.folder(proposal_id)/'state.json'
        if path.is_symlink() or not path.exists():raise ValueError('Alpha Factory提案不存在')
        value=read_checked(path)
        if value.get('proposal_id')!=proposal_id:raise ValueError('Alpha Factory身份不一致')
        return value
    def save(self,state):write_checked(self.folder(state['proposal_id'])/'state.json',state)
    def list(self):
        rows=[];errors=[]
        for folder in sorted(self.root.iterdir()) if self.root.exists() else []:
            try:rows.append(self.get(folder.name))
            except (OSError,ValueError,KeyError,TypeError) as error:errors.append({'entry':folder.name,'error':str(error)[:200]})
        rows.sort(key=lambda v:v['created_at'],reverse=True)
        return {'factories':rows,'errors':errors}


class AlphaFactoryService:
    def __init__(self,output,data_root=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        self.store=AlphaFactoryStore(self.output)
    def _prepare(self,plan):
        prepared=prepare_factory(self.output,plan)
        return bind_factory_inputs(prepared,self.data_root) if self.data_root else prepared
    def preview(self,plan):
        prepared=self._prepare(plan)
        return {**prepared,'prepared_digest':digest(prepared),'new_research_jobs':0,
            'host_confirmation_required':True,'automatic_watchlist_promotion':False}
    def propose(self,request_id,plan):
        canonical_id(request_id);prepared=self._prepare(plan)
        proposal_id=str(uuid5(NAMESPACE,'factory:'+request_id))
        with self.store.locked(proposal_id):
            path=self.store.folder(proposal_id)/'state.json'
            if path.exists():
                old=self.store.get(proposal_id)
                if old['request_id']!=request_id or old['prepared_digest']!=digest(prepared):
                    raise ValueError('同一请求编号不能改写已冻结Factory计划')
                return old
            state={'format':FORMAT,'proposal_id':proposal_id,'request_id':request_id,'status':'pending',
                'created_at':now(),'prepared':prepared,'prepared_digest':digest(prepared),
                'jobs':[],'tests':[],'result_run_id':None,'promotions':[]}
            self.store.save(state);return state
    def get(self,proposal_id):return self.store.get(proposal_id)
    def list(self):return self.store.list()

    def submit(self,proposal_id,expected_digest,get_queue,*,confirmed=False):
        if confirmed is not True:raise ValueError('必须由宿主核对完整Factory计划后明确批准')
        if self.data_root is None:raise ValueError('执行Factory需要数据目录')
        canonical_id(proposal_id)
        with self.store.locked(proposal_id):
            state=self.store.get(proposal_id)
            if state['prepared_digest']!=expected_digest:raise ValueError('显示计划与冻结Factory不一致')
            if state['status'] in ('submitted','running','completed'):return state
            if state['status'] not in ('pending','admitting'):raise ValueError('Factory当前状态不能提交')
            current=self._prepare(state['prepared']['plan'])
            if current!=state['prepared']:raise ValueError('候选、来源归档、输入数据或代码变化，请重新提案')
            if state['status']=='pending':
                jobs=[]
                for candidate in current['candidates']:
                    cid=candidate['candidate_id']
                    jobs.append({'node_id':'factor:'+cid,'candidate_id':cid,'kind':'factor',
                        'job_id':str(uuid5(UUID(proposal_id),'factor:'+cid)),'spec':candidate['factor_spec'],'status':'reserved'})
                    if 'execution_spec' in candidate:
                        jobs.append({'node_id':'execution:'+cid,'candidate_id':cid,'kind':'execution',
                            'job_id':str(uuid5(UUID(proposal_id),'execution:'+cid)),'spec':candidate['execution_spec'],'status':'reserved'})
                state.update(status='admitting',approved_at=now(),jobs=jobs);self.store.save(state)
            queue=get_queue()
            for job in state['jobs']:
                guard={'runtime':current['runtime'],'cooperative_seconds':600,'max_active_jobs':24,
                    'input_signature':current['input_signatures'][job['node_id']]}
                queue.submit(job['job_id'],job['spec'],execution_guard=guard)
                job['status']='submitted'
            state['status']='submitted';state['submitted_at']=now();self.store.save(state);return state

    def _job(self,job_id):
        path=self.output/'_jobs'/(canonical_id(job_id)+'.json')
        if path.is_symlink() or not path.resolve().is_relative_to(self.output) or not path.is_file():
            raise ValueError('Factory任务记录缺失')
        if path.stat().st_size>2_000_000:raise ValueError('Factory任务记录过大')
        record=json.loads(path.read_text())
        if record.get('job_id')!=job_id:raise ValueError('Factory任务身份不一致')
        return record

    def _reuse_derived(self,run_id,kind,source_ids):
        path=self.output/run_id/'experiment.json'
        if not path.exists():return None
        record=load_record_fields(path,{'run_id','kind','status','children','summary'})
        if record.get('run_id')!=run_id or record.get('kind')!=kind or record.get('status')!='completed':
            raise ValueError('确定性Factory派生编号已被不兼容归档占用')
        actual=[c['run_id'] for c in record.get('children',[])]
        if actual!=source_ids:raise ValueError('已有Factory派生来源与冻结计划不同')
        return {'run_id':run_id,'artifact_path':str(path.parent),'summary':record['summary'],'reused':True}

    def _residual(self,proposal_id,candidate_run_id,plan):
        from quantlab.experiments.residual import run_residual
        run_id=str(uuid5(UUID(proposal_id),'residual:'+candidate_run_id))
        sources=[candidate_run_id,*plan['control_run_ids']]
        old=self._reuse_derived(run_id,'residual_alpha',sources)
        if old:return old
        result=run_residual(self.output/candidate_run_id,[self.output/v for v in plan['control_run_ids']],
            date.fromisoformat(plan['train_end']),self.output,plan['horizon'],run_id=run_id)
        return {**result,'reused':False}

    def _return_increment(self,proposal_id,candidate_execution_run_id,plan):
        from quantlab.experiments.return_increment import compare_returns
        run_id=str(uuid5(UUID(proposal_id),'return:'+candidate_execution_run_id))
        sources=[candidate_execution_run_id,plan['baseline_execution_run_id']]
        old=self._reuse_derived(run_id,'return_increment',sources)
        if old:return old
        result=compare_returns(self.output/candidate_execution_run_id,
            self.output/plan['baseline_execution_run_id'],date.fromisoformat(plan['evaluation_start']),
            self.output,run_id=run_id)
        return {**result,'reused':False}

    def _job_map(self,state):
        values={}
        for item in state['jobs']:
            record=self._job(item['job_id']);values[item['node_id']]=record
        return values

    @staticmethod
    def _semantic_test(row):
        return {k:row.get(k) for k in ('candidate_id','id','kind','status','p_value','estimate','p_holm','reject')}

    def sync(self,proposal_id):
        canonical_id(proposal_id)
        with self.store.locked(proposal_id):
            state=self.store.get(proposal_id)
            if state['status']=='completed':return state
            if state['status'] not in ('submitted','running'):raise ValueError('Factory尚未提交或状态不能同步')
            jobs=self._job_map(state);pending={'queued','running'}
            for item in state['jobs']:item['status']=jobs[item['node_id']]['status']
            if any(record['status'] in pending for record in jobs.values()):
                state['status']='running';state['last_sync_at']=now();self.store.save(state);return state
            prepared=state['prepared'];plan=prepared['plan'];tests=[];reviews={};runs={}
            for candidate in prepared['candidates']:
                cid=candidate['candidate_id'];factor_job=jobs['factor:'+cid]
                runs[cid]={'factor_job_id':factor_job['job_id'],'factor_run_id':factor_job.get('run_id')}
                if factor_job['status']!='completed' or not factor_job.get('run_id'):
                    tests.append({'candidate_id':cid,'id':'residual_ic','kind':'residual_alpha',
                        'status':'failed','p_value':None,'estimate':None,'error':'candidate_factor_job_'+factor_job['status']})
                    if plan['require_net_return']:
                        tests.append({'candidate_id':cid,'id':'net_return_increment','kind':'return_increment',
                            'status':'failed','p_value':None,'estimate':None,'error':'candidate_factor_job_'+factor_job['status']})
                    continue
                run_id=factor_job['run_id']
                try:reviews[cid]=compare_candidate(self.output,run_id,plan['baseline_run_id'],plan['horizon'])
                except (OSError,ValueError,KeyError,TypeError) as error:
                    reviews[cid]={'status':'failed','error':type(error).__name__+': '+str(error)[:240]}
                try:
                    result=self._residual(proposal_id,run_id,plan);raw=result['summary']['test']
                    tests.append({'candidate_id':cid,'id':'residual_ic','kind':'residual_alpha',
                        'status':'completed','run_id':result['run_id'],'artifact_path':result['artifact_path'],
                        'p_value':raw.get('p_value'),'estimate':raw.get('estimate'),'test_status':raw.get('status'),
                        'reused':result.get('reused',False)})
                except (OSError,ValueError,KeyError,TypeError) as error:
                    tests.append({'candidate_id':cid,'id':'residual_ic','kind':'residual_alpha',
                        'status':'failed','p_value':None,'estimate':None,'error':type(error).__name__+': '+str(error)[:240]})
                if plan['require_net_return']:
                    execution_job=jobs['execution:'+cid]
                    runs[cid].update(execution_job_id=execution_job['job_id'],execution_run_id=execution_job.get('run_id'))
                    if execution_job['status']!='completed' or not execution_job.get('run_id'):
                        tests.append({'candidate_id':cid,'id':'net_return_increment','kind':'return_increment',
                            'status':'failed','p_value':None,'estimate':None,'error':'candidate_execution_job_'+execution_job['status']})
                    else:
                        try:
                            result=self._return_increment(proposal_id,execution_job['run_id'],plan)
                            raw=result['summary']['permutation']
                            tests.append({'candidate_id':cid,'id':'net_return_increment','kind':'return_increment',
                                'status':'completed','run_id':result['run_id'],'artifact_path':result['artifact_path'],
                                'p_value':raw.get('p_value'),'estimate':result['summary'].get('mean_daily_difference'),
                                'test_status':raw.get('status'),'reused':result.get('reused',False)})
                        except (OSError,ValueError,KeyError,TypeError) as error:
                            tests.append({'candidate_id':cid,'id':'net_return_increment','kind':'return_increment',
                                'status':'failed','p_value':None,'estimate':None,'error':type(error).__name__+': '+str(error)[:240]})
            if len(tests)!=prepared['planned_test_count']:
                raise ValueError('Factory实际测试槽位与冻结计划数量不一致')
            adjusted=holm([row.get('p_value') for row in tests])
            for row,p in zip(tests,adjusted):
                row['p_holm']=p;row['reject']=p<=plan['alpha'] if p is not None else None
            decisions=factory_decisions(prepared,tests,reviews)
            summary={'method':'frozen_alpha_factory_v1','alpha':plan['alpha'],
                'planned_candidates':len(prepared['candidates']),'planned_tests':prepared['planned_test_count'],
                'available_tests':sum(r.get('p_value') is not None for r in tests),
                'tests':tests,'decisions':decisions,'candidate_reviews':reviews,'runs':runs,
                'recommended_candidate_ids':[r['candidate_id'] for r in decisions if r['recommended_for_watchlist']],
                'selection_rule':prepared['selection_rule'],
                'limitations':['Factory级Holm只覆盖本轮执行前冻结的测试族，不覆盖此前探索或其他Factory。',
                    '推荐进入观察池不等于Alpha成立；观察池也不会自动获得交易或新增研究授权。',
                    '共同样本、残差IC和模拟账户增量均依赖来源数据质量及其PIT边界。']}
            run_id=str(uuid5(UUID(proposal_id),'alpha-factory-result'))
            children=[];seen=set()
            for rid,label in [(plan['baseline_run_id'],'基准因子'),
                    *[(v,'控制因子') for v in plan['control_run_ids']],
                    *([(plan['baseline_execution_run_id'],'基准执行')] if plan['require_net_return'] else [])]:
                if rid not in seen:children.append({'run_id':rid,'artifact_path':str((self.output/rid).resolve()),'name':label});seen.add(rid)
            for cid,entry in runs.items():
                for key,label in (('factor_run_id','候选因子'),('execution_run_id','候选执行')):
                    rid=entry.get(key)
                    if rid and rid not in seen:children.append({'run_id':rid,'artifact_path':str((self.output/rid).resolve()),'name':label+' '+cid[:8]});seen.add(rid)
            for row in tests:
                rid=row.get('run_id')
                if rid and rid not in seen:children.append({'run_id':rid,'artifact_path':row['artifact_path'],'name':row['id']+' '+row['candidate_id'][:8]});seen.add(rid)
            manifest={'format':FORMAT,'runtime':runtime_fingerprint(),'config':{'research_question':plan['name'],'data':{k:prepared['candidates'][0]['factor_spec'][k] for k in ('symbols','start','end','timeframe')}},'plan':plan,
                'prepared_digest':state['prepared_digest'],'source_fingerprints':prepared['sources'],
                'job_ids':[j['job_id'] for j in state['jobs']],'selection_rule':prepared['selection_rule']}
            record={'run_id':run_id,'experiment_id':digest(manifest),'created_at':now(),
                'kind':'alpha_factory','status':'completed','manifest':manifest,'summary':summary,'children':children}
            target=self.output/run_id/'experiment.json'
            if target.exists():
                old=load_record_fields(target,{'run_id','kind','status','manifest','summary'})
                if old.get('run_id')!=run_id or old.get('kind')!='alpha_factory' or old.get('status')!='completed' or old.get('manifest')!=manifest or old.get('summary')!=summary:
                    raise ValueError('已有Factory父归档与当前冻结结果不一致')
            else:LocalExperimentStore(self.output).save(run_id,record,None)
            state.update(status='completed',completed_at=now(),last_sync_at=now(),tests=tests,
                decisions=decisions,result_run_id=run_id,recommended_candidate_ids=summary['recommended_candidate_ids'])
            self.store.save(state);return state

    def promote(self,proposal_id,candidate_id,name,*,confirmed=False):
        if confirmed is not True:raise ValueError('进入观察池必须由宿主再次明确确认')
        canonical_id(proposal_id);canonical_id(candidate_id)
        with self.store.locked(proposal_id):
            state=self.store.get(proposal_id)
            if state['status']!='completed' or candidate_id not in state.get('recommended_candidate_ids',[]):
                raise ValueError('只有完成Factory且满足预设规则的候选才能进入观察池')
            if any(r['candidate_id']==candidate_id for r in state.get('promotions',[])):
                return next(r for r in state['promotions'] if r['candidate_id']==candidate_id)
            job=next((j for j in state['jobs'] if j['node_id']=='factor:'+candidate_id),None)
            record=self._job(job['job_id']) if job else None
            if not record or record.get('status')!='completed' or not record.get('run_id'):raise ValueError('候选因子研究归档不可用')
            from quantlab.agent.watchlist import WatchService
            result=WatchService(self.output,self.data_root).create(name,record['run_id'])
            row={'candidate_id':candidate_id,'watch_id':result['watch_id'],'created_at':now(),'authorization_created':False}
            state.setdefault('promotions',[]).append(row);self.store.save(state);return row


def factory_decisions(prepared,tests,reviews):
    plan=prepared['plan'];decisions=[]
    for candidate in prepared['candidates']:
        cid=candidate['candidate_id'];review=reviews.get(cid) or {}
        coverage=review.get('coverage') or {};shared=coverage.get('shared_keys') or 0
        ratio=(coverage.get('both_factors_finite') or 0)/shared if shared else 0.0
        corr=(review.get('signal_rank_correlation') or {}).get('mean_absolute')
        diff=(review.get('paired_rank_ic') or {}).get('difference')
        residual=next((r for r in tests if r['candidate_id']==cid and r['id']=='residual_ic'),None)
        net=next((r for r in tests if r['candidate_id']==cid and r['id']=='net_return_increment'),None)
        checks={'common_finite_ratio':ratio>=plan['min_common_finite_ratio'],
            'signal_correlation':corr is not None and corr<=plan['max_abs_signal_corr'],
            'paired_ic_direction':(not plan['require_positive_paired_ic_difference']) or (diff is not None and diff>0),
            'residual_increment':bool(residual and residual.get('reject') and (residual.get('estimate') or 0)>0),
            'net_return_increment':True if not plan['require_net_return'] else bool(net and net.get('reject') and (net.get('estimate') or 0)>0)}
        decisions.append({'candidate_id':cid,'name':candidate['name'],'recommended_for_watchlist':all(checks.values()),
            'checks':checks,'common_finite_ratio':ratio,'mean_absolute_signal_correlation':corr,
            'paired_rank_ic_difference':diff})
    return decisions
