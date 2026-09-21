"""Validated research submissions and one local worker; never executes shell input."""

import fcntl
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from threading import RLock,Event
from uuid import UUID

from quantlab.data.universe import UniverseConfig
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.portfolio import PortfolioConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.experiments.theory_study import TheoryStudyPlan, TheoryStudyRunner
from quantlab.app import build_runner, default_registry
from quantlab.data.base import DataRequest
from quantlab.domain import FactorType, Timeframe
from quantlab.experiments.ablation import AblationRunner
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.sweep import ParameterGrid, SweepRunner
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.multitimeframe.config import DailyContextConfig
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.processing.pipeline import PipelineConfig
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.permutation import PermutationConfig
from quantlab.storage.codec import encode
from quantlab.theory.templates import resolve_template


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Submission:
    config: ExperimentConfig
    mode: str
    adjustment: str
    split: ChronologicalSplit | None
    schedule: WalkForwardConfig | None
    grid: ParameterGrid | None
    universe: UniverseConfig = UniverseConfig()
    execution: ExecutionConfig | None = None
    theory_study: TheoryStudyPlan | None = None
    portfolio: PortfolioConfig | None = None
    execution_backend: str = "open"
    market_rules: list | None = None
    correlation: dict | None = None
    qualification: str = 'research_only'
    strategy_package: dict | None = None

    def preview(self):
        value = json.loads(encode(asdict(self)))
        if self.strategy_package is None:
            value.pop('strategy_package')
        return value


def prepare(spec):
    """Validate before enqueueing, using the existing factor/config contracts."""
    if not isinstance(spec, dict):
        raise ValueError('配置必须是JSON对象')
    strategy_package = None
    if 'strategy_package' in spec:
        if spec.get('mode') != 'execution':
            raise ValueError('strategy_package 仅允许用于 execution 模式')
        from quantlab.trading.strategy_package import validate_strategy_envelope_spec
        strategy_package = validate_strategy_envelope_spec(spec)
        spec = {key:value for key,value in spec.items() if key != 'strategy_package'}
    if spec.get("mode")=="campaign":
        from quantlab.agent.campaign_plan import prepare_campaign,CampaignSubmission
        return CampaignSubmission(prepare_campaign(spec)["spec"])
    allowed = {'question', 'symbols', 'timeframe', 'start', 'end', 'factor', 'version',
        'parameters', 'theory', 'theory_version', 'horizons', 'quantiles', 'seed',
        'adjustment', 'mode', 'split', 'schedule', 'grid', 'sequence_audit',
        'regime', 'regime_filter', 'context', 'processor', 'bootstrap', 'permutation', 'incremental_test', 'universe', 'replay', 'execution', 'theory_study', 'portfolio', 'execution_backend', 'market_rules', 'correlation', 'qualification'}
    unknown=set(spec)-allowed
    if unknown:
        names=', '.join(sorted(str(key) for key in unknown))[:160]
        raise ValueError('配置包含不支持的字段：'+names+'；研究配置使用factor/version，parameters只保存因子参数；factor_id/factor_version用于假设记录，不用于研究spec。')
    symbols = spec.get('symbols')
    if not isinstance(symbols, list) or not symbols or any(
            not isinstance(s, str) or not re.fullmatch(r'(sh|sz|bj)\.\d{6}', s) for s in symbols):
        raise ValueError('symbols 必须是股票代码列表，例如 ["sh.600519", "sz.000001"]')
    request = DataRequest(tuple(symbols), Timeframe(spec.get('timeframe', '1d')),
        date.fromisoformat(spec['start']), date.fromisoformat(spec['end']))
    qualification=spec.get('qualification','research_only')
    if qualification not in ('research_only','retrospective_reference','strict_pit','official_rule_covered'):
        raise ValueError('qualification须为research_only/retrospective_reference/strict_pit/official_rule_covered')
    mode = spec.get('mode', 'single')
    if mode not in {'single', 'holdout', 'walkforward', 'ablation', 'sweep', 'execution', 'theory_study', 'correlation'}:
        raise ValueError('不支持的实验类型')
    if spec.get('incremental_test') and mode != 'ablation':
        raise ValueError('incremental_test 仅用于逐输入消融')
    adjustment = spec.get('adjustment', 'qfq')
    if adjustment not in {'raw', 'qfq'}:
        raise ValueError('复权口径必须为 raw 或 qfq')
    universe=UniverseConfig(**spec.get('universe',{}))
    execution=ExecutionConfig(**spec.get('execution',{})) if mode=='execution' else None
    if 'execution' in spec and mode!='execution':raise ValueError('execution 配置仅用于独立回测')
    registry = default_registry()
    origin = None
    if spec.get('theory'):
        if any(k in spec for k in ('factor', 'version', 'parameters', 'grid')):
            raise ValueError('固定研究模板不能同时覆盖因子、参数或网格')
        parameters, origin = resolve_template(spec['theory'], registry, spec.get('theory_version', '1.0.0'))
        factor_id, version = 'COMB.CONDITION', '1.0.0'
    else:
        if 'theory_version' in spec:
            raise ValueError('theory_version 需要 theory')
        factor_id, version = spec.get('factor', 'BASE.MOMENTUM'), spec.get('version', '1.0.0')
        parameters = spec.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('因子参数必须为 JSON 对象')
    factor = registry.get(factor_id, version)
    parameters = factor.parameters(parameters)
    if request.timeframe not in factor.definition.timeframes:
        raise ValueError('因子不支持所选周期')
    processor = (PipelineConfig(**spec['processor']) if isinstance(spec.get('processor'),dict) else CrossSectionConfig(spec['processor'])) if spec.get('processor') else None
    if processor and factor.definition.factor_type != FactorType.SCALAR:
        raise ValueError('截面预处理仅支持标量因子')
    context = spec.get('context')
    if context is not None:
        context = DailyContextConfig(**{**context, 'start': date.fromisoformat(context['start'])})
        background = registry.get(context.factor_id, context.version)
        background.parameters(context.parameters)
        if context.request(request).timeframe not in background.definition.timeframes:
            raise ValueError('背景因子不支持所选高周期')
    regime = RegimeConfig(**spec['regime']) if spec.get('regime') is not None else None
    selection = RegimeFilter(**spec['regime_filter']) if spec.get('regime_filter') is not None else None
    if selection and regime is None:
        regime = RegimeConfig()
    config = ExperimentConfig(spec.get('question', '工作台因子研究'), request, factor_id, version,
        parameters, tuple(spec.get('horizons', [1, 5, 20])), spec.get('quantiles', 5), spec.get('seed', 0),
        regime=regime, regime_filter=selection, context=context, processor=processor,
        bootstrap=BootstrapConfig(**spec['bootstrap']) if spec.get('bootstrap') is not None else None,
        permutation=PermutationConfig(**spec['permutation']) if spec.get('permutation') is not None else None,
        incremental_test=spec.get('incremental_test',False),
        replay=spec.get('replay',False) or mode=='execution',
        theory_origin=origin, sequence_audit=spec.get('sequence_audit', False))
    split = schedule = grid = None
    if spec.get('split') is not None:
        split = ChronologicalSplit(**{k: date.fromisoformat(v) for k, v in spec['split'].items()})
        split.periods(request)
    if spec.get('schedule') is not None:
        schedule = WalkForwardConfig(**spec['schedule'])
        schedule.windows(request)
    if split and schedule:
        raise ValueError('分段日期和滚动窗口不能同时设置')
    if mode == 'holdout' and not split:
        raise ValueError('留出验证需要 split.train_end 和 split.valid_end')
    if mode == 'walkforward' and not schedule:
        raise ValueError('滚动验证需要 schedule 的 train_days、valid_days、test_days')
    if split and mode not in {'holdout', 'sweep', 'correlation'} or schedule and mode not in {'walkforward', 'sweep', 'correlation'}:
        raise ValueError('分段或滚动配置与实验类型不一致')
    if mode == 'sweep':
        grid = ParameterGrid(spec.get('grid'))
        grid.variants(factor, parameters)
    elif 'grid' in spec:
        raise ValueError('grid 仅用于参数扫描')
    if mode == 'ablation' and (factor_id not in {'COMB.CONDITION', 'COMB.SCORE'} or len(parameters['inputs']) < 2):
        raise ValueError('消融需要至少两个输入的条件或评分组合')
    study=TheoryStudyPlan.parse(spec.get('theory_study',{})) if mode=='theory_study' else None
    if 'theory_study' in spec and mode!='theory_study':raise ValueError('theory_study 配置需要理论全流程模式')
    if study:study.variants(config,registry)
    portfolio=PortfolioConfig(**spec.get('portfolio',{})) if mode=='execution' else None
    if 'portfolio' in spec and mode!='execution':raise ValueError('portfolio 仅用于独立回测')
    backend=spec.get('execution_backend','open')
    if backend not in ('open','vnpy_open','vnpy_rules') or (mode!='execution' and 'execution_backend' in spec):
        raise ValueError('execution_backend requires execution mode and open/vnpy_open/vnpy_rules')
    market_rules=spec.get('market_rules')
    if market_rules is not None:
        if mode!='execution' or backend=='vnpy_open':raise ValueError('market_rules requires execution and open/vnpy_rules')
        from quantlab.execution.rules import MarketRules
        MarketRules(market_rules)
    if backend=='vnpy_open':
        from quantlab.adapters.vnpy import validate_config
        validate_config(execution)
    if execution:execution.validate_price_inputs(MarketRules(market_rules) if market_rules is not None else None)
    correlation=None
    if mode=='correlation':
        from quantlab.statistics.correlation import complete_link_groups
        if factor_id!='COMB.SCORE' or len(parameters['inputs'])<2:raise ValueError('相关性研究请选择 COMB.SCORE 并提供至少两个输入，权重不参与相关计算')
        if isinstance(processor,PipelineConfig) or config.permutation is not None:raise ValueError('相关性研究使用截面预处理和 Bootstrap，不支持拟合管道或收益置换')
        correlation={'min_symbols':3,'min_periods':5,'cluster_threshold':.8,**spec.get('correlation',{})}
        if set(correlation)!={'min_symbols','min_periods','cluster_threshold'}:raise ValueError('未知相关性设置')
        if type(correlation['min_symbols']) is not int or correlation['min_symbols']<3 or type(correlation['min_periods']) is not int or correlation['min_periods']<1:raise ValueError('相关研究至少 3 证券、1 个时间点')
        complete_link_groups([],[],correlation['cluster_threshold'])
    elif 'correlation' in spec:raise ValueError('correlation 配置需要相关性研究模式')
    submission = Submission(config, mode, adjustment, split, schedule, grid, universe, execution, study, portfolio, backend, market_rules, correlation, qualification, strategy_package)
    if strategy_package is not None:
        from quantlab.trading.strategy_package import validate_prepared_strategy_envelope
        validate_prepared_strategy_envelope(strategy_package, submission, registry)
    return submission


def execute(submission, data_root, artifact_root, *, campaign_job_id=None):
    if submission.mode == "campaign":
        from quantlab.experiments.campaign import run_campaign
        return run_campaign(submission,data_root,artifact_root,campaign_job_id)
    config = submission.config
    runner = build_runner(data_root, artifact_root, config.data.symbols, submission.adjustment, submission.universe)
    if submission.mode == 'correlation':
        from quantlab.experiments.correlation import CorrelationConfig,CorrelationRunner
        from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
        from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner
        cfg=CorrelationConfig(config.research_question,config.data,config.parameters['inputs'],**submission.correlation,
            processor=config.processor,regime=config.regime,regime_filter=config.regime_filter,context=config.context,
            bootstrap=config.bootstrap,random_seed=config.random_seed)
        if submission.split:return CorrelationHoldoutRunner(runner).run(cfg,submission.split)
        if submission.schedule:return CorrelationWalkForwardRunner(runner).run(cfg,submission.schedule)
        return CorrelationRunner(runner).run(cfg)
    if submission.mode == 'theory_study':
        return TheoryStudyRunner(runner).run(config,submission.theory_study)
    if submission.mode == 'execution':
        from quantlab.execution.rules import MarketRules
        execution_data=None
        if submission.execution.price_mode=='account' and submission.adjustment!='raw':
            from quantlab.data.provider import local_data_provider
            execution_data=local_data_provider(data_root,'raw')
        return ExecutionStudy(runner,execution_data).run(config, submission.execution, submission.portfolio, submission.execution_backend, MarketRules(submission.market_rules) if submission.market_rules is not None else None, strategy_package=submission.strategy_package)
    if submission.mode == 'sweep':
        return SweepRunner(runner).run(config, submission.grid, split=submission.split, schedule=submission.schedule)
    if submission.mode == 'holdout':
        return HoldoutRunner(runner).run(config, submission.split)
    if submission.mode == 'walkforward':
        return WalkForwardRunner(runner).run(config, submission.schedule)
    if submission.mode == 'ablation':
        return AblationRunner(runner).run(config)
    return runner.run(config)


def validate_execution_guard(guard):
    if guard is None: return
    base={'runtime','cooperative_seconds','max_active_jobs'};optional={'input_signature','approval_freeze','session_grant'}
    if not isinstance(guard,dict) or not base<=set(guard) or set(guard)-base-optional:
        raise ValueError('Invalid approved execution guard')
    if 'input_signature' in guard and (not isinstance(guard['input_signature'],str) or not re.fullmatch(r'[0-9a-f]{64}',guard['input_signature'])):
        raise ValueError('Invalid approved input signature')
    if 'approval_freeze' in guard:
        from quantlab.storage.approval_inputs import validate_approval_freeze_receipt
        validate_approval_freeze_receipt(guard['approval_freeze'])
    if 'session_grant' in guard:
        from quantlab.agent.research_session_grant import validate_grant_receipt
        validate_grant_receipt(guard['session_grant'])
    if type(guard['max_active_jobs']) is not int or guard['max_active_jobs'] < 1:
        raise ValueError('Invalid approved active-job budget')
    seconds = guard['cooperative_seconds']
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError('Approved cooperative time limit must be 1–3600 seconds')
    from quantlab.experiments.runner import runtime_fingerprint
    if guard['runtime'] != runtime_fingerprint():
        raise ValueError('批准后的代码或依赖环境已变化；请重新生成研究提案')


class JobQueue:
    """Journal submissions across restarts; interrupted work is never auto-replayed."""

    def __init__(self, artifact_root, data_root):
        self.root = Path(artifact_root).resolve()
        self.data_root = Path(data_root).resolve()
        if not self.data_root.is_dir():
            raise ValueError('行情数据目录不存在')
        self.directory = self.root / '_jobs'
        if self.directory.is_symlink():
            raise ValueError('任务目录不能是符号链接')
        self.directory.mkdir(exist_ok=True)
        if (self.directory / 'worker.lock').is_symlink():
            raise ValueError('任务锁不能是符号链接')
        self.lockfile = (self.directory / 'worker.lock').open('a')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lockfile.close()
            raise ValueError('同一产物目录已有实验工作台在执行任务') from None
        self.lock = RLock()
        self.jobs = {}
        self.cancellations = {}
        self.closed = False
        try:
            for path in self.directory.glob('*.json'):
                record = json.loads(path.read_text(encoding='utf-8'))
                if str(UUID(path.stem)) != path.stem or record['job_id'] != path.stem:
                    raise ValueError('任务日志标识不一致')
                if record['status'] in {'queued', 'running'}:
                    record.update(status='interrupted', finished_at=now(), error='上次服务中断；可恢复任务，通过校验的计算断点会继续使用。')
                    self._save(record)
                self.jobs[path.stem] = record
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='quantlab-research')
        except Exception:
            self.lockfile.close()
            raise

    def _save(self, record):
        path = self.directory / (record['job_id'] + '.json')
        temporary = path.with_suffix('.tmp')
        if temporary.is_symlink():
            raise ValueError('任务临时文件不能是符号链接')
        temporary.write_text(encode(record), encoding='utf-8')
        temporary.replace(path)

    def list(self):
        with self.lock:
            return json.loads(encode(sorted(self.jobs.values(), key=lambda j: (j['created_at'], j['job_id']), reverse=True)))

    def submit(self, job_id, spec, *, execution_guard=None):
        if not isinstance(job_id, str) or str(UUID(job_id)) != job_id:
            raise ValueError('job_id 必须为规范 UUID')
        # Round-trip also rejects non-JSON and non-finite inputs before persistence.
        spec = json.loads(encode(spec))
        execution_guard = json.loads(encode(execution_guard))
        validate_execution_guard(execution_guard)
        if execution_guard and 'session_grant' in execution_guard:
            from quantlab.agent.research_session_grant import assert_grant_active
            assert_grant_active(self.root,self.data_root,execution_guard['session_grant'])
        with self.lock:
            if self.closed:
                raise ValueError('服务正在关闭，不再接收任务')
            if job_id in self.jobs:
                if self.jobs[job_id]['spec'] != spec or self.jobs[job_id].get('execution_guard') != execution_guard:
                    raise ValueError('同一 job_id 不可用于不同配置')
                return json.loads(encode(self.jobs[job_id]))
            if execution_guard and sum(j['status'] in ('queued','running') for j in self.jobs.values()) >= execution_guard['max_active_jobs']:
                raise ValueError('BUDGET_EXCEEDED：共享队列活动任务已达本次批准上限')
            submission = prepare(spec)
            if execution_guard and 'approval_freeze' in execution_guard:
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                frozen=ApprovalInputFreezeStore(self.root,self.data_root).verify(execution_guard['approval_freeze'],spec)
                qualification=frozen['manifest']['qualification']
            else:
                from quantlab.data.qualification import qualify_spec
                qualification=qualify_spec(self.data_root,spec)
            if not qualification['qualified']:
                raise ValueError('DATA_QUALIFICATION_BLOCKED：'+', '.join(qualification.get('blockers',[])[:12]))
            record = {'job_id': job_id, 'status': 'queued', 'created_at': now(),
                'started_at': None, 'finished_at': None, 'spec': spec,
                'resolved': submission.preview(), 'qualification':qualification, 'run_id': None, 'error': None, 'attempt': 1}
            if execution_guard is not None: record['execution_guard'] = execution_guard
            self._save(record)
            self.jobs[job_id] = record
            self.cancellations[job_id]=Event()
            self.executor.submit(self._run, job_id, submission, 1)
            return json.loads(encode(record))

    def resume(self, job_id):
        """Explicitly retry the original specification; only verified state is reused."""
        with self.lock:
            if self.closed:raise ValueError('服务正在关闭，不再接收任务')
            record=self.jobs.get(job_id)
            if record is None:raise ValueError('未知任务')
            if record['status'] not in ('interrupted','cancelled','failed'):
                raise ValueError('只有中断、取消或失败的任务可以恢复')
            validate_execution_guard(record.get('execution_guard'))
            submission=prepare(record['spec'])
            guard=record.get('execution_guard')
            if guard and 'session_grant' in guard:
                from quantlab.agent.research_session_grant import assert_grant_active
                assert_grant_active(self.root,self.data_root,guard['session_grant'])
            if guard and 'approval_freeze' in guard:
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                frozen=ApprovalInputFreezeStore(self.root,self.data_root).verify(guard['approval_freeze'],record['spec'])
                qualification=frozen['manifest']['qualification']
            else:
                from quantlab.data.qualification import qualify_spec
                qualification=qualify_spec(self.data_root,record['spec'])
            stored_qualification=record.get('qualification')
            if not qualification['qualified'] or (stored_qualification is not None and qualification!=stored_qualification):
                raise ValueError('数据资格或审批冻结证据已变化，请新建研究并重新批准')
            if stored_qualification is None and qualification.get('required_level')!='research_only':
                raise ValueError('旧任务没有严格资格回执，请新建研究并重新批准')
            current_resolved=submission.preview()
            if stored_qualification is None:
                legacy_resolved=dict(current_resolved);legacy_resolved.pop('qualification',None)
                if record['resolved'] not in (current_resolved,legacy_resolved):
                    raise ValueError('当前解析规则与原任务不一致，请新建研究并核对配置')
            elif current_resolved!=record['resolved']:
                raise ValueError('当前解析规则与原任务不一致，请新建研究并核对配置')
            attempt=record.get('attempt',1)+1
            updated={**record,'attempt':attempt,'attempts':[*record.get('attempts',[]),
                {k:record.get(k) for k in ('attempt','status','started_at','finished_at','error','progress')}],
                'status':'queued','started_at':None,'finished_at':None,'error':None,
                'cancel_requested':False,'run_id':None,'qualification':qualification,'resolved':current_resolved,
                'progress':{'stage':'等待恢复；仅复用通过校验的断点','completed':None,'total':None,'updated_at':now()}}
            self._save(updated);self.jobs[job_id]=updated
            self.cancellations[job_id]=Event()
            self.executor.submit(self._run,job_id,submission,attempt)
            return json.loads(encode(updated))

    def cancel(self,job_id):
        with self.lock:
            record=self.jobs.get(job_id)
            if record is None:raise ValueError('未知任务')
            if record['status'] not in ('queued','running'):return {'status':record['status']}
            self.cancellations[job_id].set();record['cancel_requested']=True
            if record['status']=='queued':
                record.update(status='cancelled',finished_at=now(),error='用户取消排队任务；未开始计算')
                self._save(record)
                return {'status':'cancelled'}
            self._save(record)
            return {'status':'cancel_requested'}

    def _run(self, job_id, submission, attempt):
        try:
            with self.lock:
                record = self.jobs[job_id]
                # A cancelled queued attempt can still be present in the executor.
                # It must not execute, or consume the cancellation token of a retry.
                if record.get('attempt',1)!=attempt:return
                if record['status']=='cancelled':
                    self.cancellations.pop(job_id,None)
                    return
                record.update(status='running', started_at=now())
                self._save(record)
            from quantlab.progress import research_progress,ResearchCancelled
            import time
            guard = record.get('execution_guard'); validate_execution_guard(guard)
            if guard and 'session_grant' in guard:
                from quantlab.agent.research_session_grant import assert_grant_active
                try:assert_grant_active(self.root,self.data_root,guard['session_grant'])
                except ValueError as error:raise ResearchCancelled('Research Session Grant 已失效：'+str(error)) from error
            deadline = time.monotonic()+guard['cooperative_seconds'] if guard else None
            effective_data_root=self.data_root
            if guard and 'approval_freeze' in guard:
                from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                frozen=ApprovalInputFreezeStore(self.root,self.data_root).verify(guard['approval_freeze'],record['spec'])
                if frozen['manifest']['qualification']!=record.get('qualification'):
                    raise ValueError('审批冻结的数据资格回执与任务记录不一致')
                effective_data_root=frozen['path']
            def check_inputs():
                if guard and 'session_grant' in guard:
                    from quantlab.agent.research_session_grant import assert_grant_active
                    try:assert_grant_active(self.root,self.data_root,guard['session_grant'])
                    except ValueError as error:raise ResearchCancelled('Research Session Grant 已失效：'+str(error)) from error
                if guard and 'approval_freeze' in guard:
                    from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
                    frozen_now=ApprovalInputFreezeStore(self.root,self.data_root).verify(guard['approval_freeze'],record['spec'])
                    if frozen_now['manifest']['qualification']!=record.get('qualification'):
                        raise ValueError('审批冻结输入或资格证据发生变化；停止执行')
                    return
                from quantlab.data.qualification import qualify_spec
                current_qualification=qualify_spec(self.data_root,record['spec'])
                if not current_qualification['qualified'] or current_qualification!=record.get('qualification'):
                    raise ValueError('研究数据资格或资格证据在入队后发生变化；停止执行')
                if guard and 'input_signature' in guard:
                    from quantlab.experiments.campaign_state import input_signature
                    from quantlab.storage.codec import digest
                    if digest(input_signature(record['spec'],self.data_root))!=guard['input_signature']:
                        raise ValueError('受控任务的行情或资格输入已变化；停止自动纳入跟踪')
            def progress(stage,completed,total):
                if guard and 'session_grant' in guard:
                    from quantlab.agent.research_session_grant import assert_grant_active
                    try:assert_grant_active(self.root,self.data_root,guard['session_grant'])
                    except ValueError as error:raise ResearchCancelled('Research Session Grant 已失效：'+str(error)) from error
                if self.cancellations[job_id].is_set():raise ResearchCancelled('用户取消；已完成的子实验与缓存保留')
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('已到批准的研究执行时限；在检查点停止，已有归档和断点保留')
                if stage is not None:
                    with self.lock:
                        record['progress']={'stage':stage,'completed':completed,'total':total,'updated_at':now()}
                        self._save(record)
            from quantlab.experiments.child_checkpoints import child_checkpoint_scope
            with research_progress(progress),child_checkpoint_scope(self.root,job_id,record['spec']) as children:
                progress('准备执行',None,None)
                check_inputs()
                try:
                    result = execute(submission, effective_data_root, self.root, **({"campaign_job_id":job_id} if submission.mode=="campaign" else {}))
                    check_inputs()
                finally:
                    with self.lock:record['checkpoint_summary']=children.summary()
                with self.lock:record['progress']={'stage':'已完成','completed':None,'total':None,'updated_at':now()}
            outcome = {'status': 'completed', 'run_id': result.run_id, 'experiment_id': result.experiment_id}
        except Exception as error:
            from quantlab.progress import ResearchCancelled
            outcome = {'status': 'cancelled' if isinstance(error,ResearchCancelled) else 'failed', 'error': f'{type(error).__name__}: {error}'}
        with self.lock:
            self.cancellations.pop(job_id,None)
            record.update(**outcome, finished_at=now())
            try:
                self._save(record)
            except (OSError, ValueError) as error:
                record.update(status='failed', error=f'任务状态无法持久化：{error}；{record.get("error") or "请检查已保存的实验结果"}')

    def close(self):
        with self.lock:
            self.closed = True
        try:
            self.executor.shutdown(wait=True)
        finally:
            self.lockfile.close()
