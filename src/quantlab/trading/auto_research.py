"""Bounded autonomous limit-board research: host-authorized plan, proposal queue, nightly in-sample screening (research_only).

The host authorizes a research plan (at most 30 days) fixing the family prefix, the in-sample window, the allowed outcomes and
execution specs, whether sentiment or vendor-detail columns may be used, weekly and nightly budgets, and a locked out-of-sample
window that begins only after an embargo longer than every label horizon. Agents may only propose studies into the queue. The
nightly runner registers each proposal as an in-sample-only event study, runs it, applies a versioned skeptic checklist and keeps
the screening (pass or fail) permanently. The locked window is used only later, when the host explicitly promotes a screened
study into the plan's single confirmation family (AR-5.3). Nothing here has shell, network, code-writing or trading capability.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo
import ast
import fcntl
import json
import re

from quantlab.storage.codec import digest, encode

PLAN_FORMAT = 'limit-research-plan-v1'
AUTHORIZATION_FORMAT = 'limit-research-plan-authorization-v1'
QUEUE_FORMAT = 'limit-research-queue-item-v1'
NIGHT_FORMAT = 'limit-research-night-v1'
CHECKLIST_VERSION = 'auto-research-checklist-v1'
TZ = ZoneInfo('Asia/Shanghai')
MAX_PLAN_DAYS = 30
MIN_IN_SAMPLE_DAYS = 3 * 365
EARLIEST_START = date(2019, 1, 2)
PREVIEW_TTL = timedelta(minutes=30)
PREFIX = re.compile(r'^auto-[a-z0-9]+(?:-[a-z0-9]+)*$')
MAX_PREFIX_LENGTH = 25
MAX_FAMILY_LENGTH = 33  # leaves room for CONFIRM_SUFFIX inside the 41-character event-study family limit
CONFIRM_SUFFIX = '-confirm'
PROPOSAL_FIELDS = ('family', 'hypothesis', 'expected_sign', 'condition', 'baseline_condition', 'outcome', 'execution', 'group_by',
                   'use_sentiment')
ONE_SIGNED_OUTCOMES = ('t1_high_ret', 't1_low_ret')  # like boolean rates, their raw mean has one sign by construction
QUEUE_LIMIT = 50
EMBARGO_BUFFER_DAYS = 14
STATES = ('PENDING', 'REGISTERED', 'SCREENED_PASS', 'SCREENED_FAIL', 'REJECTED', 'ERROR', 'CANCELLED')
# A year counts toward stability with at least 5 event days and 20 events, so rare regimes (e.g. climax days) are still judged.
THRESHOLDS = {'p_value': 0.01, 'min_days': 20, 'max_year_event_share': 0.4, 'max_top5_day_event_share': 0.2, 'min_stable_years': 3,
              'min_year_days': 5, 'min_year_events': 20, 'min_expected_sign_year_share': 0.6, 'min_fill_rate': 0.5,
              'max_unresolved_share': 0.05, 'min_return_effect': 0.002, 'min_rate_effect': 0.02}
BOUNDARIES = {'shell_allowed': False, 'network_allowed': False, 'code_write_allowed': False, 'real_trade_allowed': False,
              'agent_actions': 'propose_only', 'out_of_sample_access': 'host_promotion_only', 'authorization': 'host_only'}
LIMITATIONS = [
    '筛选只用计划的样本内区间；通过筛选只表示值得宿主决定是否晋级到锁定样本外区间确认，不是结论，更不是交易信号。',
    f"筛选显著性门槛为原始 p ≤ {THRESHOLDS['p_value']}（不做族内校正）；确认阶段在计划唯一的确认族内做 Holm 校正。",
    '样本内与锁定样本外之间留有隔离期（按最长标签与持有期计算），样本内结果列不会用到锁定区间的价格。',
    '失败、被拒绝和出错的研究同样消耗预算并永久保留；同一检验（条件、对照、结果列、区间、成交模型相同）只运行一次，改族名、改假设文字或改方向不能重跑。',
    '语义等价但写法不同的条件无法自动识别为同一检验，仍会消耗预算并计入确认阶段的多重检验。',
    'AI 在日常只读工具中可能看过锁定区间的行情，历史锁定区间上的确认只是弱确认；确认后的前瞻滚动监控才是主要检验（AR-5.3）。',
]


class AutoResearchError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AutoResearchError('INVALID_CLOCK', '时钟必须返回带时区的时间。')
    return value.astimezone(timezone.utc)


def _moment(value, name, code='INVALID_PLAN'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AutoResearchError(code, name + ' 必须为带时区的 ISO 时间。')
    return value.astimezone(timezone.utc)


def _iso_day(value, name, code='INVALID_PLAN'):
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise AutoResearchError(code, name + ' 必须为 YYYY-MM-DD。')


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _read(path, fmt):
    if path.is_symlink() or not path.is_file():
        raise AutoResearchError('CORRUPT_ARCHIVE', path.name + ' 缺失或不是普通文件。')
    try:
        value = json.loads(path.read_bytes())
    except ValueError:
        raise AutoResearchError('CORRUPT_ARCHIVE', path.name + ' 不是合法 JSON。') from None
    core = {k: v for k, v in value.items() if k != 'checksum'} if isinstance(value, dict) else None
    if core is None or value.get('checksum') != digest(core) or core.get('format') != fmt:
        raise AutoResearchError('CORRUPT_ARCHIVE', path.name + ' 校验失败。')
    return core


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(encode(_checked(value)), encoding='utf-8')
    temporary.replace(path)


def week_key(day):
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def embargo_days(executions):
    """Calendar days between in-sample end and the locked window: twice the longest label horizon in sessions, plus holidays."""
    sessions = max([2] + [item['max_hold_sessions'] + 2 for item in executions])
    return 2 * sessions + EMBARGO_BUFFER_DAYS


def _canonical(text):
    return None if text is None else ast.dump(ast.parse(text.strip(), mode='eval'))


def study_test_key(spec):
    """Identity of the statistical test itself; family, hypothesis text, direction, grouping and build ids cannot re-roll it."""
    return digest({'condition': _canonical(spec['condition']), 'baseline_condition': _canonical(spec['baseline_condition']),
                   'outcome': spec['outcome'], 'start': spec['start'], 'end': spec['end'], 'execution': spec['execution'],
                   'min_events': spec['min_events'], 'sentiment_calendar': spec['sentiment_build_id'] is not None})


def evaluate_checklist(spec, result, *, p_value=None, p_threshold=None):
    """Versioned skeptic checklist on a finished study; ``p_value``/``p_threshold`` replace the raw screening test (confirmation)."""
    from quantlab.trading.event_study import BOOLEAN_OUTCOMES, EXECUTION_OUTCOMES, NUMERIC_OUTCOMES, PRE_ENTRY_COLUMNS, compile_condition
    t = THRESHOLDS
    sample = result['samples']['all']
    test = sample.get('test') or {}
    statistic = 'mean_daily_difference' if spec.get('baseline_condition') else 'daily_mean'
    value = sample.get(statistic)
    positive = spec['expected_sign'] == 'positive'
    items = []

    def add(key, passed, detail, applicable=True):
        items.append({'key': key, 'status': ('PASS' if passed else 'FAIL') if applicable else 'NOT_APPLICABLE', 'detail': detail})

    add('sample_size', sample['events'] >= spec['min_events'] and sample['days'] >= t['min_days'],
        {'events': sample['events'], 'days': sample['days'], 'min_events': spec['min_events'], 'min_days': t['min_days']})
    tested_p = test.get('p_value') if p_value is None else p_value
    threshold = t['p_value'] if p_threshold is None else p_threshold
    add('significance', tested_p is not None and tested_p <= threshold, {'p_value': tested_p, 'threshold': threshold, 'test_status': test.get('status')})
    add('direction', value is not None and value != 0 and (value > 0) == positive,
        {'statistic': statistic, 'value': value, 'expected_sign': spec['expected_sign']})
    effect = t['min_rate_effect'] if spec['outcome'] in BOOLEAN_OUTCOMES else t['min_return_effect']
    add('economic_magnitude', value is not None and abs(value) >= effect, {'value': value, 'threshold': effect})
    year_share, day_share = sample.get('max_year_event_share'), sample.get('top5_day_event_share')
    add('year_concentration', year_share is not None and year_share <= t['max_year_event_share'],
        {'max_year_event_share': year_share, 'threshold': t['max_year_event_share']})
    add('day_concentration', day_share is not None and day_share <= t['max_top5_day_event_share'],
        {'top5_day_event_share': day_share, 'threshold': t['max_top5_day_event_share']})
    years = [row for row in result.get('by_year_tested') or []
             if row['days'] >= t['min_year_days'] and row['events'] >= t['min_year_events'] and row['value'] is not None]
    expected = [row['year'] for row in years if row['value'] != 0 and (row['value'] > 0) == positive]
    add('year_stability', len(years) >= t['min_stable_years'] and len(expected) / len(years) >= t['min_expected_sign_year_share'],
        {'years': [row['year'] for row in years], 'expected_sign_years': expected, 'min_years': t['min_stable_years'],
         'min_share': t['min_expected_sign_year_share'], 'min_year_days': t['min_year_days'], 'min_year_events': t['min_year_events']})
    execution = (result.get('execution') or {}).get('all') or {}
    if spec.get('execution'):
        entered, fill_rate = execution.get('entered') or 0, execution.get('fill_rate')
        unresolved = execution['unresolved_exits'] / entered if entered else None
        add('execution_feasibility', fill_rate is not None and fill_rate >= t['min_fill_rate'] and unresolved is not None
            and unresolved <= t['max_unresolved_share'], {'fill_rate': fill_rate, 'unresolved_share': unresolved,
                                                           'min_fill_rate': t['min_fill_rate'], 'max_unresolved_share': t['max_unresolved_share']})
        net = execution.get('mean_net_return')
        add('net_of_costs', net is not None and net > 0, {'mean_net_return': net}, applicable=positive)
    else:
        add('execution_feasibility', False, {'note': '未指定成交模型：只是信号标签统计'}, applicable=False)
        add('net_of_costs', False, {'note': '未指定成交模型'}, applicable=False)
    used = compile_condition(spec['condition'])[1] + (compile_condition(spec['baseline_condition'])[1] if spec.get('baseline_condition') else [])
    late = {c for c in used if c in set(NUMERIC_OUTCOMES + BOOLEAN_OUTCOMES + EXECUTION_OUTCOMES)}
    if (spec.get('execution') or {}).get('entry') == 't0_limit_price':
        late |= {c for c in used if c not in PRE_ENTRY_COLUMNS}
    add('lookahead_guard', not late, {'violations': sorted(late)})
    applicable = [item for item in items if item['status'] != 'NOT_APPLICABLE']
    return {'version': CHECKLIST_VERSION, 'passed': all(item['status'] == 'PASS' for item in applicable),
            'failed': [item['key'] for item in items if item['status'] == 'FAIL'], 'items': items,
            'warnings': [] if spec.get('execution') else ['未经成交模型复核：即使通过也只是信号标签统计，不能称为可执行。']}


class AutoResearch:
    def __init__(self, output, *, now_fn=None, registry=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise AutoResearchError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._registry = registry
        self.root = self.output / '_limit_research' / 'auto_research'

    def registry(self):
        if self._registry is None:
            from quantlab.trading.event_study import EventStudyRegistry
            self._registry = EventStudyRegistry(self.output, now_fn=self.now_fn)
        return self._registry

    def _check(self):
        for path in (self.output / '_limit_research', self.root, self.root / 'plan', self.root / 'plan' / 'history', self.root / 'queue',
                     self.root / 'nights', self.root / 'plan' / 'active.json', self.root / 'state.lock', self.root / 'run.lock'):
            if path.is_symlink():
                raise AutoResearchError('INVALID_WORKSPACE', '自主研究目录与文件不能是符号链接。')

    @contextmanager
    def _flock(self, name, *, blocking):
        self._check()
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / name).open('a+b') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AutoResearchError('ALREADY_RUNNING', '另一个自主研究夜间任务正在运行。') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    # ---- plan -----------------------------------------------------------------------------------------
    def _build_plan(self, scope, expires_at, studies_per_week, runs_per_night, prepared):
        from quantlab.trading.event_study import BOOLEAN_OUTCOMES, EXECUTION_OUTCOMES, NUMERIC_OUTCOMES
        from quantlab.trading.limit_execution import ExecutionSpec
        expiry = _moment(expires_at, 'expires_at')
        if not timedelta(hours=1) <= expiry - prepared <= timedelta(days=MAX_PLAN_DAYS):
            raise AutoResearchError('INVALID_PLAN', f'研究计划有效期须为 1 小时至 {MAX_PLAN_DAYS} 天。')
        required = {'family_prefix', 'start', 'in_sample_end', 'outcomes', 'executions', 'allow_sentiment', 'allow_details', 'min_events'}
        if not isinstance(scope, dict) or set(scope) != required:
            raise AutoResearchError('INVALID_PLAN', '研究计划 scope 字段必须恰好为：' + '、'.join(sorted(required)))
        prefix = scope['family_prefix']
        if not isinstance(prefix, str) or len(prefix) > MAX_PREFIX_LENGTH or not PREFIX.fullmatch(prefix) or prefix.endswith(CONFIRM_SUFFIX):
            raise AutoResearchError('INVALID_PLAN', f'family_prefix 必须形如 auto-xxx（小写字母、数字与单个连字符，至多 {MAX_PREFIX_LENGTH} 字符）。')
        start, end = _iso_day(scope['start'], 'start'), _iso_day(scope['in_sample_end'], 'in_sample_end')
        if start < EARLIEST_START or end >= prepared.astimezone(TZ).date() or (end - start).days < MIN_IN_SAMPLE_DAYS:
            raise AutoResearchError('INVALID_PLAN', f'须满足 start ≥ {EARLIEST_START}、in_sample_end 早于今天，且样本内区间至少 3 年（年份稳定性检查需要）。')
        outcomes = scope['outcomes']
        allowed = set(NUMERIC_OUTCOMES + BOOLEAN_OUTCOMES + EXECUTION_OUTCOMES)
        if not isinstance(outcomes, list) or not outcomes or not all(isinstance(o, str) and o in allowed for o in outcomes):
            raise AutoResearchError('INVALID_PLAN', 'outcomes 必须是非空的允许结果列列表。')
        if not isinstance(scope['executions'], list) or len(scope['executions']) > 6:
            raise AutoResearchError('INVALID_PLAN', 'executions 必须是至多 6 个成交模型规格的列表。')
        executions = []
        for item in scope['executions']:
            try:
                normalized = asdict(ExecutionSpec.from_dict(item))
            except (ValueError, TypeError) as error:
                raise AutoResearchError('INVALID_PLAN', 'execution 无效：' + str(error)) from None
            if normalized not in executions:
                executions.append(normalized)
        if bool(set(outcomes) & set(EXECUTION_OUTCOMES)) != bool(executions):
            raise AutoResearchError('INVALID_PLAN', 'net_return/gross_return 结果列与成交模型必须同时授权。')
        if type(scope['allow_sentiment']) is not bool or type(scope['allow_details']) is not bool:
            raise AutoResearchError('INVALID_PLAN', 'allow_sentiment/allow_details 必须为布尔值。')
        if type(scope['min_events']) is not int or not 30 <= scope['min_events'] <= 100000:
            raise AutoResearchError('INVALID_PLAN', 'min_events 必须为 30–100000 的整数。')
        if type(studies_per_week) is not int or not 1 <= studies_per_week <= 50 or type(runs_per_night) is not int or not 1 <= runs_per_night <= 10:
            raise AutoResearchError('INVALID_PLAN', '每周研究数须为 1–50，每晚运行数须为 1–10。')
        embargo = embargo_days(executions)
        return {'format': PLAN_FORMAT, 'prepared_at': prepared.isoformat(), 'expires_at': expiry.isoformat(),
                'scope': {**scope, 'start': start.isoformat(), 'in_sample_end': end.isoformat(), 'outcomes': sorted(set(outcomes)),
                          'executions': sorted(executions, key=digest)},
                'budget': {'studies_per_week': studies_per_week, 'runs_per_night': runs_per_night}, 'embargo_days': embargo,
                'locked_out_of_sample_start': (end + timedelta(days=embargo + 1)).isoformat(), 'confirmation_family': prefix + CONFIRM_SUFFIX,
                'checklist_version': CHECKLIST_VERSION, 'thresholds': THRESHOLDS, 'queue_limit': QUEUE_LIMIT, 'boundaries': BOUNDARIES,
                'limitations': LIMITATIONS}

    def preview_plan(self, scope, *, expires_at, studies_per_week=10, runs_per_night=3):
        return self._build_plan(scope, expires_at, studies_per_week, runs_per_night, _utc(self.now_fn()))

    def authorize_plan(self, plan, expected_digest, *, confirmed=False):
        if confirmed is not True:
            raise AutoResearchError('CONFIRMATION_REQUIRED', '研究计划必须由宿主核对后明确授权。')
        if not isinstance(plan, dict) or not isinstance(expected_digest, str) or digest(plan) != expected_digest:
            raise AutoResearchError('DIGEST_MISMATCH', '研究计划摘要不一致，请重新预览。')
        now = _utc(self.now_fn())
        prepared = _moment(plan.get('prepared_at'), 'prepared_at')
        if not timedelta(0) <= now - prepared <= PREVIEW_TTL:
            raise AutoResearchError('PREVIEW_EXPIRED', '授权须在预览后 30 分钟内完成（或时钟回退），请重新预览。')
        budget = plan.get('budget') if isinstance(plan.get('budget'), dict) else {}
        rebuilt = self._build_plan(plan.get('scope'), plan.get('expires_at'), budget.get('studies_per_week'), budget.get('runs_per_night'), prepared)
        if digest(rebuilt) != expected_digest:
            raise AutoResearchError('PLAN_TAMPERED', '研究计划与按当前规则重建的结果不一致（内容被修改或规则已更新），请重新预览。')
        with self._flock('state.lock', blocking=True):
            path = self.root / 'plan' / 'active.json'
            if path.exists():
                current = _read(path, AUTHORIZATION_FORMAT)
                if current['status'] == 'active':
                    if now < _moment(current['plan']['expires_at'], 'expires_at'):
                        raise AutoResearchError('PLAN_ACTIVE', '已有有效研究计划，请先撤销。')
                    current = {**current, 'status': 'expired'}
                _write(self.root / 'plan' / 'history' / f"{current['plan_id']}.json", current)
            state = {'format': AUTHORIZATION_FORMAT, 'plan_id': str(uuid4()), 'plan': rebuilt, 'plan_digest': expected_digest, 'status': 'active',
                     'authorized_at': now.isoformat(), 'revoked_at': None, 'authorization_source': 'explicit_host_confirmation'}
            _write(path, state)
            cancelled = self._cancel(lambda item: item['plan_id'] != state['plan_id'], 'PLAN_REPLACED', now)
        return {**state, 'cancelled_pending': cancelled}

    def revoke_plan(self, plan_id, *, confirmed=False):
        if confirmed is not True:
            raise AutoResearchError('CONFIRMATION_REQUIRED', '撤销研究计划需要宿主明确确认。')
        now = _utc(self.now_fn())
        with self._flock('state.lock', blocking=True):
            path = self.root / 'plan' / 'active.json'
            state = _read(path, AUTHORIZATION_FORMAT) if path.exists() else None
            if state is None or state['plan_id'] != plan_id:
                raise AutoResearchError('NOT_FOUND', '研究计划不存在。')
            if state['status'] == 'active':
                state.update(status='revoked', revoked_at=now.isoformat())
                _write(path, state)
            cancelled = self._cancel(lambda item: item['plan_id'] == plan_id, 'PLAN_REVOKED', now)
        return {**state, 'cancelled_pending': cancelled}

    def active_plan(self):
        self._check()
        path = self.root / 'plan' / 'active.json'
        if not path.exists():
            return None
        state = _read(path, AUTHORIZATION_FORMAT)
        if state['status'] != 'active' or _utc(self.now_fn()) >= _moment(state['plan']['expires_at'], 'expires_at'):
            return None
        return state

    # ---- queue ----------------------------------------------------------------------------------------
    def _items(self):
        self._check()
        folder = self.root / 'queue'
        if not folder.is_dir():
            return []
        return sorted((_read(p, QUEUE_FORMAT) for p in folder.glob('*.json')), key=lambda r: (r['proposed_at'], r['item_id']))

    def _save(self, item):
        _write(self.root / 'queue' / f"{item['item_id']}.json", item)

    def _cancel(self, predicate, reason, now):
        count = 0
        for item in self._items():
            if item['state'] == 'PENDING' and predicate(item):
                item.update(state='CANCELLED', finished_at=now.isoformat(),
                            error={'code': reason, 'message': '研究计划已被替换或撤销：提案未运行，也未消耗预算。'})
                self._save(item)
                count += 1
        return count

    def _to_spec(self, state, proposal):
        from quantlab.trading.event_details import DETAIL_COLUMNS
        from quantlab.trading.event_study import BOOLEAN_OUTCOMES, CONTEXT_COLUMNS, compile_condition
        from quantlab.trading.limit_events import LimitEventLibrary
        from quantlab.trading.limit_execution import ExecutionSpec
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        scope = state['plan']['scope']
        if not isinstance(proposal, dict) or set(proposal) != set(PROPOSAL_FIELDS):
            raise AutoResearchError('INVALID_PROPOSAL', '提案字段必须恰好为：' + '、'.join(PROPOSAL_FIELDS))
        family, prefix = proposal['family'], scope['family_prefix']
        if not isinstance(family, str) or not (family == prefix or family.startswith(prefix + '-')) or len(family) > MAX_FAMILY_LENGTH:
            raise AutoResearchError('OUT_OF_PLAN', f'研究族必须是 {prefix} 或以 {prefix}- 开头，且至多 {MAX_FAMILY_LENGTH} 字符。')
        if family.endswith(CONFIRM_SUFFIX):
            raise AutoResearchError('OUT_OF_PLAN', '确认族只能由宿主晋级产生。')
        if proposal['expected_sign'] not in ('positive', 'negative'):
            raise AutoResearchError('INVALID_PROPOSAL', '自主研究必须预登记方向：expected_sign 为 positive 或 negative。')
        if proposal['outcome'] not in scope['outcomes']:
            raise AutoResearchError('OUT_OF_PLAN', '结果列不在研究计划授权范围内。')
        if (proposal['outcome'] in BOOLEAN_OUTCOMES or proposal['outcome'] in ONE_SIGNED_OUTCOMES) and proposal['baseline_condition'] is None:
            raise AutoResearchError('INVALID_PROPOSAL', '布尔结果与 t1_high_ret/t1_low_ret 的均值天然单边，必须给出对照条件 baseline_condition。')
        execution = proposal['execution']
        if execution is not None:
            try:
                execution = asdict(ExecutionSpec.from_dict(execution))
            except (ValueError, TypeError) as error:
                raise AutoResearchError('INVALID_PROPOSAL', 'execution 无效：' + str(error)) from None
            if execution not in scope['executions']:
                raise AutoResearchError('OUT_OF_PLAN', '成交模型规格不在研究计划授权范围内。')
        if type(proposal['use_sentiment']) is not bool:
            raise AutoResearchError('INVALID_PROPOSAL', 'use_sentiment 必须为布尔值。')
        try:
            used = compile_condition(proposal['condition'])[1]
            if proposal['baseline_condition'] is not None:
                used = used + compile_condition(proposal['baseline_condition'])[1]
        except ValueError as error:
            raise AutoResearchError(getattr(error, 'code', None) or 'INVALID_CONDITION', str(error)) from None
        needs_sentiment = proposal['use_sentiment'] or any(c in CONTEXT_COLUMNS for c in used) or proposal['group_by'] == 'mkt_phase'
        if needs_sentiment and not scope['allow_sentiment']:
            raise AutoResearchError('OUT_OF_PLAN', '研究计划未授权使用 mkt_ 情绪列或情绪分组。')
        if any(c in DETAIL_COLUMNS for c in used) and not scope['allow_details']:
            raise AutoResearchError('OUT_OF_PLAN', '研究计划未授权使用 em_ 前瞻明细列。')
        end = scope['in_sample_end']
        library = LimitEventLibrary(self.output).latest_covering(end)
        if library is None:
            raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖样本内终点的涨停事件库 build。')
        sentiment_id = None
        if needs_sentiment:
            sentiment = MarketSentimentLibrary(self.output).latest_covering(end)
            if sentiment is None:
                raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖样本内终点的情绪指标 build。')
            sentiment_id = sentiment['build_id']
        spec = {'family': family, 'hypothesis': proposal['hypothesis'], 'expected_sign': proposal['expected_sign'],
                'library_build_id': library['build_id'], 'sentiment_build_id': sentiment_id, 'condition': proposal['condition'],
                'baseline_condition': proposal['baseline_condition'], 'outcome': proposal['outcome'], 'start': scope['start'], 'end': end,
                'split_date': None, 'group_by': proposal['group_by'], 'min_events': scope['min_events'], 'execution': execution}
        try:
            self.registry().normalize_spec(spec)
        except ValueError as error:
            raise AutoResearchError(getattr(error, 'code', None) or 'INVALID_PROPOSAL', str(error)) from None
        return spec

    def propose(self, request_id, proposal, *, proposer):
        try:
            valid_request = isinstance(request_id, str) and str(UUID(request_id)) == request_id
        except ValueError:
            valid_request = False
        if not valid_request:
            raise AutoResearchError('INVALID_ARGUMENT', 'request_id 必须为规范 UUID。')
        if not isinstance(proposer, str) or not re.fullmatch(r'(ai|host):[A-Za-z0-9_.\-]{1,60}', proposer):
            raise AutoResearchError('INVALID_ARGUMENT', 'proposer 必须形如 ai:<名称> 或 host:<名称>。')
        state = self.active_plan()
        if state is None:
            raise AutoResearchError('PLAN_INACTIVE', '没有有效的研究计划授权，不能提交自主研究提案。')
        spec = self._to_spec(state, proposal)
        key, proposal_digest = study_test_key(spec), digest(proposal)
        item_id = str(uuid5(NAMESPACE_URL, 'niuniu-auto-study-request:' + request_id))
        with self._flock('state.lock', blocking=True):
            current = self.active_plan()
            if current is None or current['plan_id'] != state['plan_id']:
                raise AutoResearchError('PLAN_INACTIVE', '研究计划已变化，请重新提交。')
            items = self._items()
            same = next((item for item in items if item['item_id'] == item_id), None)
            if same is not None:
                if same['proposal_digest'] != proposal_digest or same['plan_id'] != state['plan_id']:
                    raise AutoResearchError('REQUEST_CONFLICT', 'request_id 已用于另一份提案。')
                return {**same, 'created': False, 'duplicate_of': None}
            duplicate = next((item for item in items if item['test_key'] == key and item['state'] not in ('CANCELLED', 'ERROR')), None)
            if duplicate is not None:
                return {**duplicate, 'created': False, 'duplicate_of': duplicate['item_id']}
            if sum(1 for item in items if item['state'] == 'PENDING') >= QUEUE_LIMIT:
                raise AutoResearchError('QUEUE_FULL', f'待运行队列已满（{QUEUE_LIMIT}）。')
            item = {'format': QUEUE_FORMAT, 'item_id': item_id, 'request_id': request_id, 'plan_id': state['plan_id'], 'proposer': proposer,
                    'proposed_at': _utc(self.now_fn()).isoformat(), 'proposal_digest': proposal_digest, 'test_key': key, 'spec': spec,
                    'state': 'PENDING', 'night': None, 'registered_at': None, 'study_id': None, 'finished_at': None, 'screening': None, 'error': None}
            self._save(item)
        return {**item, 'created': True, 'duplicate_of': None}

    # ---- nightly runner --------------------------------------------------------------------------------
    def _recover(self, now):
        count = 0
        for item in self._items():
            if item['state'] == 'REGISTERED':
                item.update(state='ERROR', finished_at=now.isoformat(),
                            error={'code': 'INTERRUPTED', 'message': '上次夜间任务在研究完成前中断；预算已消耗，不自动重跑。'})
                self._save(item)
                count += 1
        return count

    def _screen(self, item):
        registry = self.registry()
        try:
            record = registry.register(item['spec'])
        except ValueError as error:
            item.update(state='REJECTED', error={'code': getattr(error, 'code', None) or 'INVALID_SPEC', 'message': str(error)[:300]})
        else:
            item['study_id'] = record['study_id']
            try:
                result = registry.run(record['spec']['family'], record['study_id'])['result']
                checklist = evaluate_checklist(record['spec'], result)
                item.update(state='SCREENED_PASS' if checklist['passed'] else 'SCREENED_FAIL', screening=checklist)
            except Exception as error:  # noqa: BLE001 - a failed study is recorded and never silently retried
                item.update(state='ERROR', error={'code': getattr(error, 'code', None) or type(error).__name__, 'message': str(error)[:300]})
        item['finished_at'] = _utc(self.now_fn()).isoformat()
        return item

    def run(self, *, night=None, max_runs=None):
        now = _utc(self.now_fn())
        today = now.astimezone(TZ).date()
        if night is None:
            night = today
        elif not (isinstance(night, date) and not isinstance(night, datetime)):
            night = _iso_day(night, 'night', 'INVALID_ARGUMENT')
        if not today - timedelta(days=7) <= night <= today:
            raise AutoResearchError('INVALID_ARGUMENT', 'night 必须是最近 7 天内的日期。')
        if max_runs is not None and (type(max_runs) is not int or not 1 <= max_runs <= 10):
            raise AutoResearchError('INVALID_ARGUMENT', 'max_runs 必须为 1–10。')
        ran, status, plan_id = [], None, None
        with self._flock('run.lock', blocking=False):
            with self._flock('state.lock', blocking=True):
                interrupted = self._recover(now)
            while status is None:
                item = None
                with self._flock('state.lock', blocking=True):
                    state = self.active_plan()
                    if state is None:
                        status = 'PLAN_INACTIVE'
                    else:
                        plan_id, budget = state['plan_id'], state['plan']['budget']
                        mine = [i for i in self._items() if i['plan_id'] == plan_id]
                        tonight = sum(1 for i in mine if i['night'] == night.isoformat())
                        this_week = sum(1 for i in mine if i['night'] and week_key(date.fromisoformat(i['night'])) == week_key(night))
                        pending = next((i for i in mine if i['state'] == 'PENDING'), None)
                        if max_runs is not None and len(ran) >= max_runs:
                            status = 'MAX_RUNS_REACHED'
                        elif tonight >= budget['runs_per_night']:
                            status = 'NIGHTLY_BUDGET_EXHAUSTED'
                        elif this_week >= budget['studies_per_week']:
                            status = 'WEEKLY_BUDGET_EXHAUSTED'
                        elif pending is None:
                            status = 'QUEUE_EMPTY'
                        else:
                            item = {**pending, 'state': 'REGISTERED', 'night': night.isoformat(), 'registered_at': _utc(self.now_fn()).isoformat()}
                            self._save(item)  # the budget is consumed before the study runs
                if item is not None:
                    item = self._screen(item)
                    with self._flock('state.lock', blocking=True):
                        self._save(item)
                    ran.append({'item_id': item['item_id'], 'study_id': item['study_id'], 'state': item['state'],
                                'failed_checks': (item['screening'] or {}).get('failed'), 'error': item['error']})
            with self._flock('state.lock', blocking=True):
                path = self.root / 'nights' / f'{night.isoformat()}.json'
                log = _read(path, NIGHT_FORMAT) if path.exists() else {'format': NIGHT_FORMAT, 'night': night.isoformat(), 'runs': []}
                log['runs'] = (log['runs'] + [{'started_at': now.isoformat(), 'finished_at': _utc(self.now_fn()).isoformat(), 'status': status,
                                               'plan_id': plan_id, 'ran': ran, 'interrupted': interrupted}])[-20:]
                _write(path, log)
        return {'status': status, 'night': night.isoformat(), 'week': week_key(night), 'plan_id': plan_id, 'ran': ran, 'interrupted': interrupted}

    def night_done(self, night):
        self._check()
        night = night if isinstance(night, date) and not isinstance(night, datetime) else _iso_day(night, 'night', 'INVALID_ARGUMENT')
        return (self.root / 'nights' / f'{night.isoformat()}.json').is_file()

    # ---- reads ---------------------------------------------------------------------------------------
    @staticmethod
    def summary(item):
        spec, screening = item['spec'], item['screening']
        return {'item_id': item['item_id'], 'state': item['state'], 'proposer': item['proposer'], 'proposed_at': item['proposed_at'],
                'night': item['night'], 'finished_at': item['finished_at'], 'family': spec['family'], 'hypothesis': spec['hypothesis'],
                'expected_sign': spec['expected_sign'], 'condition': spec['condition'], 'baseline_condition': spec['baseline_condition'],
                'outcome': spec['outcome'], 'execution': spec['execution'], 'study_id': item['study_id'],
                'screening_passed': None if screening is None else screening['passed'],
                'failed_checks': None if screening is None else screening['failed'], 'error': item['error']}

    def items(self, *, state=None):
        if state is not None and state not in STATES:
            raise AutoResearchError('INVALID_ARGUMENT', 'state 无效。')
        return [item for item in self._items() if state is None or item['state'] == state]

    def status(self, *, limit=20):
        self._check()
        path = self.root / 'plan' / 'active.json'
        stored = _read(path, AUTHORIZATION_FORMAT) if path.exists() else None
        active = self.active_plan()
        items = self._items()
        today = _utc(self.now_fn()).astimezone(TZ).date()
        counts = {}
        for item in items:
            counts[item['state']] = counts.get(item['state'], 0) + 1
        plan = None
        if stored is not None:
            body = stored['plan']
            plan = {'plan_id': stored['plan_id'], 'status': 'expired' if stored['status'] == 'active' and active is None else stored['status'],
                    'authorized_at': stored['authorized_at'], 'revoked_at': stored['revoked_at'], 'expires_at': body['expires_at'],
                    'scope': body['scope'], 'budget': body['budget'], 'embargo_days': body['embargo_days'],
                    'locked_out_of_sample_start': body['locked_out_of_sample_start'], 'confirmation_family': body['confirmation_family'],
                    'checklist_version': body['checklist_version'], 'thresholds': body['thresholds']}
        used = None if active is None else sum(1 for item in items if item['plan_id'] == active['plan_id'] and item['night']
                                               and week_key(date.fromisoformat(item['night'])) == week_key(today))
        recent = [self.summary(item) for item in reversed(items[max(0, len(items) - limit):])] if limit else []
        return {'active': active is not None, 'plan': plan, 'week': week_key(today), 'weekly_used': used, 'queue_counts': counts,
                'recent': recent, 'boundaries': BOUNDARIES, 'limitations': LIMITATIONS}


__all__ = ['PLAN_FORMAT', 'AUTHORIZATION_FORMAT', 'QUEUE_FORMAT', 'CHECKLIST_VERSION', 'THRESHOLDS', 'BOUNDARIES', 'LIMITATIONS',
           'PROPOSAL_FIELDS', 'STATES', 'AutoResearch', 'AutoResearchError', 'embargo_days', 'evaluate_checklist', 'study_test_key', 'week_key']
