"""Finite, static research DAGs. Dependencies never select by observed returns."""
from dataclasses import dataclass, asdict
import json
import re
from quantlab.agent.planning import ProposalError, ResearchBudget, parse_spec
from quantlab.storage.codec import encode, digest

REGISTERED = {'single','holdout','walkforward','sweep','ablation','theory_study'}
DIAGNOSTIC = {'execution','correlation'}
MAX_NODES = 12


@dataclass(frozen=True)
class CampaignSubmission:
    plan: dict
    mode: str = 'campaign'
    def preview(self): return json.loads(encode(asdict(self)))


def prepare_campaign(spec, budget=None):
    from quantlab.agent.planning import preview_experiment
    from quantlab.workbench.trial_submission import planned_trial
    from quantlab.experiments.trial_registry import _validate_plan
    from quantlab.experiments.trial_layout import hypotheses
    budget = budget or ResearchBudget(); spec = parse_spec(encode(spec))
    if set(spec) != {'mode','question','alpha','failure_policy','nodes'} or spec['mode'] != 'campaign':
        raise ProposalError('INVALID_ARGUMENT','研究包字段须为 mode/question/alpha/failure_policy/nodes。')
    if not isinstance(spec['question'],str) or not spec['question'].strip():
        raise ProposalError('INVALID_ARGUMENT','研究包需要名称。')
    if spec['failure_policy'] not in ('continue_independent','stop'):
        raise ProposalError('INVALID_ARGUMENT','失败策略仅支持 continue_independent 或 stop。')
    nodes = spec['nodes']
    if not isinstance(nodes,list) or not 1 <= len(nodes) <= MAX_NODES:
        raise ProposalError('BUDGET_EXCEEDED','一个研究包须有 1–12 个固定节点。')
    seen = set(); signatures = set(); previews = {}; trials = []; all_symbols = set()
    for node in nodes:
        if not isinstance(node,dict) or set(node) != {'node_id','depends_on','spec'}:
            raise ProposalError('INVALID_ARGUMENT','节点仅包含 node_id/depends_on/spec。')
        key = node['node_id']; deps = node['depends_on']; child = node['spec']
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',key) or key in seen:
            raise ProposalError('INVALID_ARGUMENT','节点编号无效或重复。')
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(deps)!=len(set(deps)) or key in deps:
            raise ProposalError('INVALID_ARGUMENT','依赖须为不同的其他节点编号。')
        if not isinstance(child,dict) or child.get('mode','single') not in REGISTERED|DIAGNOSTIC:
            raise ProposalError('UNSUPPORTED_SCOPE','不支持嵌套研究包或动态节点。')
        if child.get('replay') is not True:
            raise ProposalError('INVALID_ARGUMENT','研究包的每个节点必须明确设置 replay=true。')
        preview = preview_experiment(child,budget)
        signature = json.loads(encode(preview['resolved']))
        signature['config'].pop('research_question',None)
        fingerprint = digest(signature)
        if fingerprint in signatures:
            raise ProposalError('INVALID_ARGUMENT','研究包包含相同解析配置；改名称不能增加一个试验。')
        signatures.add(fingerprint); seen.add(key); previews[key] = preview
        all_symbols.update(child['symbols'])
        if child.get('mode','single') in REGISTERED: trials.append(planned_trial(child,key))
    if any(set(n['depends_on'])-seen for n in nodes):
        raise ProposalError('INVALID_ARGUMENT','存在未知依赖节点。')
    order = []; remaining = list(nodes)
    while remaining:
        ready = next((n for n in remaining if set(n['depends_on']) <= set(order)),None)
        if ready is None: raise ProposalError('INVALID_ARGUMENT','研究依赖存在循环。')
        order.append(ready['node_id']); remaining.remove(ready)
    if not trials: raise ProposalError('INVALID_ARGUMENT','至少需要一个启用 permutation 的统计节点。')
    registry = {'name':spec['question'],'alpha':spec['alpha'],'trials':trials}
    _validate_plan(registry)
    estimate = {k:sum(p['estimate'][k] for p in previews.values()) for k in
        ('leaf_studies','bar_evaluations_upper_estimate','resample_date_draws_upper_estimate')}
    estimate.update(symbols=len(all_symbols),calendar_days=max(p['estimate']['calendar_days'] for p in previews.values()),
        nodes=len(nodes),planned_tests=sum(len(hypotheses(t)) for t in trials))
    for key,maximum in [('symbols',budget.max_symbols),('leaf_studies',budget.max_leaf_studies),
        ('bar_evaluations_upper_estimate',budget.max_bar_evaluations),('resample_date_draws_upper_estimate',budget.max_resample_date_draws)]:
        if estimate[key] > maximum: raise ProposalError('BUDGET_EXCEEDED','整个研究包的 '+key+' 超出预算。')
    return {'spec':spec,'spec_digest':digest(spec),'resolved':CampaignSubmission(spec).preview(),
        'estimate':estimate,'budget':asdict(budget),'order':order,'registry_plan':registry,
        'node_previews':previews,'data_policy':'execution_time_fingerprint_not_approval_time_freeze',
        'warnings':['一次批准固定全部节点和总预算；依赖只按执行成功判断，不按显著性或收益择优。',
            '统计节点须显式配置 permutation；失败、跳过和不可检验项保留原检验族名额。',
            '成交与相关性节点仅为诊断，不混入 IC 检验族；没有新增净收益显著性检验。',
            '仅在本机任务运行期间推进；退出、取消后需人工恢复。不是24小时服务。',
            '首次执行记录数据指纹，恢复与各节点前后复查；不是批准时冻结数据字节。',
            '合作式时限覆盖一次整包尝试；中断保留已完成节点，终止失败节点不自动重跑。',
            'Holm仅覆盖本包固定检验族；本地登记不证明未见数据，也不控制跨包探索与反复查看。']}
