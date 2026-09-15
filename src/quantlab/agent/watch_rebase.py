"""Host-confirmed baseline version links; old history and grants stay untouched."""
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid5
import json
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.agent.watchlist import WatchService, rule_identity
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.agent.proposals import ProposalService, workspace_identity
from quantlab.agent.proposal_store import ProposalStore
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.codec import digest

FIELDS = {'run_id','experiment_id','kind','status','manifest','metrics'}


def canonical(value):
    if not isinstance(value,str) or str(UUID(value)) != value:
        raise ValueError('Invalid baseline version UUID')
    return value


class WatchRebaseService:
    def __init__(self, output, data_root=None):
        self.watch = WatchService(output,data_root)
        self.output = self.watch.output; self.data_root = data_root
    def source(self, watch_id):
        canonical(watch_id)
        definition,state = self.watch.store.read(watch_id)
        if state['active']: raise ValueError('请先暂停旧跟踪，再核对新版基准')
        control = ControlStore(self.output).get(watch_id)
        cycles = control['cycles'] if control else []
        if control and (control['enabled'] or any(c['status'] in ('reserved','queued','running') for c in cycles)):
            raise ValueError('请先撤销旧授权并处理未完成任务')
        jobs = {c['job_id'] for c in cycles if c['status'] != 'abandoned'}
        for request in state['refresh_requests']:
            proposal = ProposalStore(self.output).get(request['proposal_id'])
            if proposal['status'] in ('pending','approved'):
                raise ValueError('旧跟踪仍有待批准提案，请先处理')
            if proposal['status'] == 'submitted': jobs.add(proposal['job_id'])
        for job_id in jobs:
            path = self.output/'_jobs'/(canonical(job_id)+'.json')
            if path.is_symlink() or not path.resolve().is_relative_to(self.output):
                raise ValueError('原任务路径无效')
            job = json.loads(path.read_text())
            if job.get('job_id') != job_id or job.get('status') not in ('completed','failed','cancelled','interrupted'):
                raise ValueError('原任务尚未终止，不能换版')
        if not state['history']: raise ValueError('旧跟踪没有快照')
        snapshot = self.watch.store.snapshot(watch_id,state['history'][-1])
        tree = snapshot_tree(self.output,snapshot['source_run_id'])
        if digest(tree) != snapshot['preview']['source_fingerprint']:
            raise ValueError('旧基准来源已变化，不能作为换版证据')
        record = load_record_fields(self.watch.catalog.file(snapshot['source_run_id'],'experiment.json'),FIELDS)
        if record['status'] != 'completed' or rule_identity(record) != definition['rule']:
            raise ValueError('旧基准与跟踪定义不一致')
        return definition,state,record,digest(tree),digest(control)
    def propose(self, watch_id, request_id):
        """Rebuild the same historical interval through normal human approval."""
        if self.data_root is None: raise ValueError('请先选择研究行情目录')
        definition,state,record,_,_ = self.source(watch_id)
        cfg = deepcopy(record['manifest']['config'])
        if record['manifest']['universe']['id']!='explicit_symbols' or cfg.get('theory_origin'):
            raise ValueError('重建提案仅支持显式证券池和实际注册因子')
        names = {'research_question':'question','factor_id':'factor',
                 'factor_version':'version','random_seed':'seed'}
        spec = {names.get(k,k):v for k,v in cfg.items()
                if k not in ('data','theory_origin') and v is not None}
        spec.update(cfg['data']);spec.update(mode='single',replay=True,
            question=definition['name']+' · 同区间新版基准',
            adjustment=record['manifest']['data_snapshot']['adjustment'])
        return ProposalService(self.output,self.data_root).propose(request_id,spec)

    def preview(self, watch_id, candidate_run_id, name):
        canonical(candidate_run_id)
        if not isinstance(name,str) or not name.strip() or len(name)>120:
            raise ValueError('新跟踪名称须为1–120字符')
        definition,state,old,old_hash,control_hash = self.source(watch_id)
        if candidate_run_id == old['run_id']: raise ValueError('必须选择独立完成的新版基准')
        new,preview = self.watch.capture(candidate_run_id,None,definition['windows'],definition['min_dates'])
        if new['manifest']['runtime'] != runtime_fingerprint():
            raise ValueError('候选基准不是当前代码和依赖下的结果，请重新计算')
        rules = [rule_identity(record) for record in (old,new)]
        for rule in rules: rule.pop('source_runtime')
        if rules[0] != rules[1]:
            raise ValueError('规则、因子代码或研究口径变化；请另建研究，不作为等值换版')
        if old['manifest']['config']['data'] != new['manifest']['config']['data']:
            raise ValueError('新版基准必须保持完全相同的历史区间和证券')
        checks = []
        for filename in ('bars.parquet','observations.parquet'):
            frames = []
            for run_id in (old['run_id'],candidate_run_id):
                path = self.watch.catalog.file(run_id,filename)
                if path.stat().st_size>150_000_000: raise ValueError('换版文件超出150MB预算')
                frame = pl.scan_parquet(path)
                if frame.select(pl.len()).collect().item()>250000:
                    raise ValueError('换版输入超过250000行')
                frames.append(frame.collect().sort('symbol','datetime'))
            try: assert_frame_equal(*frames,check_exact=True,check_column_order=False)
            except AssertionError as error:
                raise ValueError('历史数据或观测值不一致：'+filename) from error
            checks.append({'file':filename,'rows':frames[0].height,'exact_match':True})
        if digest(snapshot_tree(self.output,old['run_id'])) != old_hash or digest(
                snapshot_tree(self.output,candidate_run_id)) != preview['source_fingerprint']:
            raise ValueError('归档在核对过程中发生变化')
        identity = {'source_watch':watch_id,'candidate':candidate_run_id,'name':name.strip()}
        seq=definition.get('sequential_monitor')
        sequential_settings=None if not seq else {'family_alpha':seq['family_alpha'],'min_effect':seq['min_effect'],
            'min_new_dates':seq['min_new_dates'],'block_sessions':seq.get('block_sessions',5)}
        return {'version':1,'watch_id':watch_id,'candidate_run_id':candidate_run_id,
            'new_watch_id':str(uuid5(UUID(watch_id),'baseline:'+digest(identity))),
            'name':name.strip(),'old_run_id':old['run_id'],
            'old_definition_hash':digest(definition),'old_state_hash':digest(state),
            'old_control_hash':control_hash,'old_source_hash':old_hash,
            'new_source_hash':preview['source_fingerprint'],
            'old_runtime':old['manifest']['runtime'],'runtime':runtime_fingerprint(),
            'workspace':workspace_identity(self.output),'checks':checks,
            'windows':definition['windows'],'min_dates':definition['min_dates'],'sequential_settings':sequential_settings,
            'limitations':['只证明本次同区间归档数值一致，不证明所有输入下算法等价或未来盈利。',
                '旧快照不拼接到新统计；新跟踪完成创建后暂停，不继承研究授权。',
                '行情修订、因子代码变化或区间变化须另建研究，不能走等值换版。']}

    def receipt_path(self, new_watch_id):
        parent = self.output/'_watch_rebases';folder = parent/canonical(new_watch_id)
        if parent.is_symlink() or folder.is_symlink(): raise ValueError('换版回执目录异常')
        return folder/'receipt.json'

    def accept(self, plan, expected_digest, *, confirmed=False):
        """Host only; never register this method as an assistant tool."""
        if confirmed is not True: raise ValueError('请在宿主界面明确确认换版')
        if not isinstance(plan,dict) or digest(plan) != expected_digest:
            raise ValueError('换版计划校验值变化')
        controls = ControlStore(self.output)
        with controls.locked(plan['watch_id']), self.watch.store.locked(plan['watch_id']):
            path = self.receipt_path(plan['new_watch_id'])
            receipt = read_checked(path) if path.exists() else None
            if receipt and receipt.get('plan_digest') != expected_digest:
                raise ValueError('同一新版跟踪存在不同换版计划')
            if receipt and receipt.get('status') == 'completed':
                definition,_ = self.watch.store.read(plan['new_watch_id'])
                if digest(definition) != receipt['new_definition_hash']:
                    raise ValueError('已创建的新跟踪定义变化')
                return {**receipt,'created':False}
            current = self.preview(plan['watch_id'],plan['candidate_run_id'],plan['name'])
            if current != plan: raise ValueError('来源、跟踪状态或运行环境变化，请重新预览')
            folder = self.watch.store.folder(plan['new_watch_id'])
            if receipt is None and folder.exists():
                raise ValueError('目标跟踪已存在，拒绝覆盖')
            path.parent.mkdir(parents=True,exist_ok=True)
            receipt = {'status':'prepared','plan':plan,'plan_digest':expected_digest,
                'old_watch_id':plan['watch_id'],'new_watch_id':plan['new_watch_id'],
                'candidate_run_id':plan['candidate_run_id'],'new_research_jobs':0,
                'inherited_authorizations':0}
            write_checked(path,receipt)
            if (folder/'state.json').is_file():
                existing,existing_state = self.watch.store.read(plan['new_watch_id'])
                if existing['base_run_id'] != plan['candidate_run_id'] or existing_state['refresh_requests'] or controls.get(plan['new_watch_id']) is not None:
                    raise ValueError('未完成换版出现额外状态，需人工核对')
                if not existing_state['history']:
                    self.watch.store.set_active(plan['new_watch_id'],True)
            try:
                seq=plan.get('sequential_settings')
                result = self.watch.create(plan['name'],plan['candidate_run_id'],
                    windows=plan['windows'],min_dates=plan['min_dates'],watch_id=plan['new_watch_id'],
                    enable_sequential=seq is not None,
                    sequential_alpha=seq['family_alpha'] if seq else .05,
                    sequential_min_effect=seq['min_effect'] if seq else .02,
                    sequential_min_new_dates=seq['min_new_dates'] if seq else 10,
                    sequential_block_sessions=seq.get('block_sessions',5) if seq else 5)
                if result['snapshot']['preview']['source_fingerprint'] != plan['new_source_hash'] or digest(snapshot_tree(self.output,plan['old_run_id'])) != plan['old_source_hash']:
                    raise ValueError('换版期间来源变化，未完成记录，新跟踪保持暂停')
            finally:
                if (folder/'state.json').is_file():
                    self.watch.store.set_active(plan['new_watch_id'],False)
            definition,state = self.watch.store.read(plan['new_watch_id'])
            if state['refresh_requests'] or controls.get(plan['new_watch_id']) is not None:
                raise ValueError('新跟踪出现额外授权或提案，需人工核对')
            receipt.update(status='completed',new_definition_hash=digest(definition),
                snapshot_id=result['snapshot']['snapshot_id'],new_watch_active=False)
            write_checked(path,receipt)
            return {**receipt,'created':True}
    def history(self, watch_id):
        canonical(watch_id);parent=self.output/'_watch_rebases'
        if parent.is_symlink(): raise ValueError('换版历史目录异常')
        records=[];unreadable=0
        for path in sorted(parent.glob('*/receipt.json')):
            try:
                canonical(path.parent.name)
                if path.parent.is_symlink() or path.is_symlink() or path.stat().st_size>2_000_000:
                    raise ValueError('换版历史路径或大小异常')
                value=read_checked(path)
                if value['plan_digest']!=digest(value['plan']): raise ValueError('换版记录身份变化')
                if watch_id in (value['old_watch_id'],value['new_watch_id']):
                    records.append(value)
            except (OSError,ValueError,KeyError,TypeError):unreadable+=1
        return {'records':records[-20:],'omitted':max(0,len(records)-20),'unreadable':unreadable,
            'scope':'历史换版回执；不重算，不证明当前来源仍完整，也不改变授权。'}
