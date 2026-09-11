"""Data-free, bounded proposal validation over the existing research contracts."""
import json
from dataclasses import asdict, dataclass
from datetime import date
from math import prod
from quantlab.storage.codec import digest, encode


class ProposalError(ValueError):
    def __init__(self, code, message):
        super().__init__(message); self.code = code


@dataclass(frozen=True)
class ResearchBudget:
    max_symbols: int = 100
    max_calendar_days: int = 4000
    max_leaf_studies: int = 64
    max_bar_evaluations: int = 20_000_000
    max_resamples: int = 10_000
    max_resample_date_draws: int = 100_000_000
    max_pending_proposals: int = 50
    max_active_jobs: int = 4
    cooperative_seconds: int = 300

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise ValueError('Budget fields must be positive integers')
        if self.cooperative_seconds > 3600: raise ValueError('Cooperative budget is limited to one hour per attempt')


def parse_spec(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > 65536:
        raise ProposalError('INVALID_ARGUMENT', '研究配置须为不超过 64 KiB 的 JSON。')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON field: '+key)
            result[key] = value
        return result
    def constant(value): raise ValueError('Nonfinite JSON constant')
    try: value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:
        raise ProposalError('INVALID_ARGUMENT', 'JSON 配置无效。') from error
    if not isinstance(value, dict): raise ProposalError('INVALID_ARGUMENT', '研究配置必须为对象。')
    count = 0
    def visit(node, depth=0):
        nonlocal count
        count += 1
        if depth > 16 or count > 5000:
            raise ProposalError('BUDGET_EXCEEDED', '配置嵌套或元素数量超出限制。')
        if isinstance(node, dict):
            for child in node.values(): visit(child, depth+1)
        elif isinstance(node, list):
            for child in node: visit(child, depth+1)
    visit(value)
    return value


def preview_experiment(spec, budget=None):
    if isinstance(spec,dict) and spec.get("mode")=="campaign":
        from quantlab.agent.campaign_plan import prepare_campaign
        return prepare_campaign(spec,budget)
    from quantlab.workbench.jobs import prepare
    from quantlab.app import default_registry
    from quantlab.experiments.ablation import variants
    from quantlab.experiments.theory_study import component_specs
    budget = budget or ResearchBudget()
    spec = parse_spec(encode(spec))
    def check(value, maximum, title):
        if value > maximum: raise ProposalError('BUDGET_EXCEEDED', title+'超出预算。')
    try:
        symbols = spec.get('symbols', [])
        check(len(symbols), budget.max_symbols, '证券数量')
        days = (date.fromisoformat(spec['end'])-date.fromisoformat(spec['start'])).days+1
        check(days, budget.max_calendar_days, '日期跨度')
        if len(spec.get('horizons', [1,5,20])) > 5:
            raise ProposalError('BUDGET_EXCEEDED', '一次研究最多 5 个持有期。')
        for name in ('bootstrap','permutation'):
            cfg = spec.get(name) or {}
            check(cfg.get('resamples',1000), budget.max_resamples, '重采样次数')
        if (spec.get('universe') or {}).get('reference_manifest'):
            raise ProposalError('UNSUPPORTED_SCOPE', '智能体提案暂不接受任意资料文件路径；请使用工作空间内置资料或人工研究入口。')
        submission = prepare(spec); config = submission.config
        registry = default_registry(); factor = registry.get(config.factor_id, config.factor_version)
        phases = 3 if submission.split else 3*len(submission.schedule.windows(config.data)) if submission.schedule else 1
        mode = submission.mode
        leaves = 1
        if mode in ('holdout','walkforward'): leaves = phases
        elif mode == 'sweep': leaves = len(submission.grid.variants(factor,config.parameters))*phases
        elif mode == 'ablation': leaves = 1+len(variants(factor,config.parameters))
        elif mode == 'correlation': leaves = len(config.parameters['inputs'])*phases
        elif mode == 'theory_study':
            plan = submission.theory_study; parameters = factor.parameters(config.parameters)
            grid = plan.variants(config,registry)
            leaves = len(component_specs(parameters,registry))+1+1+len(variants(factor,parameters))+3
            leaves += 3*len(plan.schedule.windows(config.data))+3*len(grid.variants(factor,parameters))
        check(leaves,budget.max_leaf_studies,'叶子研究数量')
        per_day = lambda tf: 1 if tf.value == '1d' else 240//tf.minutes
        rows = len(symbols)*days*per_day(config.data.timeframe)
        if config.context:
            request = config.context.request(config.data)
            context_days = (request.end-request.start).days+1
            check(context_days,budget.max_calendar_days,'背景数据跨度')
            rows += len(symbols)*context_days*per_day(request.timeframe)
        factor_units = 1+len(config.parameters.get('inputs',{}))
        work = rows*leaves*factor_units*(1+len(config.horizons))
        check(work,budget.max_bar_evaluations,'保守 K 线评价量')
        resamples = sum(c.resamples for c in (config.bootstrap,config.permutation) if c)
        draws = days*leaves*len(config.horizons)*max(1,factor_units)*resamples*4
        check(draws,budget.max_resample_date_draws,'保守重采样工作量')
    except ProposalError: raise
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as error:
        raise ProposalError('INVALID_ARGUMENT', '研究配置未通过原有校验：'+str(error)[:240]) from error
    estimate = {'symbols':len(symbols),'calendar_days':days,'leaf_studies':leaves,
        'bar_evaluations_upper_estimate':work,'resample_date_draws_upper_estimate':draws}
    warnings = ['这是配置与规模预检，未读取行情，也不证明历史资料覆盖。',
        '数据字节尚未在批准时冻结；执行时使用现有数据源并由原引擎保存快照。',
        '预算是保守工作量估算，不是内存、耗时或磁盘空间的精确预测。',
        '执行时限在合作式检查点生效，不能强行中断正在运行的原生计算。',
        '任务完成不等于发现 Alpha；标签收益、成本后模拟与真实可成交性必须区分。']
    if submission.universe.mode != 'explicit':
        warnings.append('已选择历史资格算法，但尚未检查具体历史资料；缺失时由原引擎报错，不静默降级。')
    return {'spec':spec,'spec_digest':digest(spec),'resolved':submission.preview(),
        'estimate':estimate,'budget':asdict(budget),'warnings':warnings,
        'data_policy':'execution_time_snapshot_not_approval_time_freeze'}
