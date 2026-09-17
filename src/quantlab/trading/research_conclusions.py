"""Research conclusions (research_only): host promotion into a locked out-of-sample confirmation, and forward decay monitoring.

Every proposal, screened or not, stays in the autonomous research queue; this library records what happens after screening.
Only the host can promote a SCREENED_PASS proposal (into its plan's single confirmation family, over the locked window) or retire
a conclusion. A confirmation is judged with the confirmation-stage skeptic checklist on the Holm-adjusted p-value over every
registered confirmation in the family, and is re-judged whenever the family grows. Confirmed rules are then measured every day on
data after the confirmation window; a reversed or shrunken rolling effect (or failed execution checks) marks them DECAYING.
Nothing here is a trading signal.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import fcntl
import re

from quantlab.storage.codec import digest
from quantlab.trading.auto_research import (CONFIRM_P, THRESHOLDS, TZ, AutoResearch, AutoResearchError, _iso_day, _moment, _read, _utc,
                                            _write, evaluate_checklist)

PROMOTION_FORMAT = 'limit-research-promotion-v1'
CONCLUSION_FORMAT = 'limit-research-conclusion-v1'
MONITOR_VERSION = 'conclusion-monitor-v1'
PREVIEW_TTL = timedelta(minutes=30)
MIN_CONFIRM_WINDOW_DAYS = 90
MIN_FORWARD_DAYS = 20
RECENT_WINDOW_DAYS = 180
DECAY_RATIO = 0.5
MAX_EVALUATIONS = 120
STATUSES = ('PENDING_RUN', 'NOT_CONFIRMED', 'MONITORING', 'DECAYING', 'RETIRED')
ACTIVE = ('MONITORING', 'DECAYING')
ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
LIMITATIONS = [
    '确认只在计划锁定的样本外区间进行，并以确认族内全部已登记确认研究做 Holm 校正；之后每晋级一项，早先的确认都会重新评估，可能由确认变为未确认。',
    'AI 在日常只读工具中可能看过锁定区间的行情，历史区间上的确认只是弱确认；确认后按确认区间之后的新数据每日滚动监控，效果反向、缩水一半以上或成交检查不过即标为 DECAYING。',
    '监控窗口为确认区间之后的全部数据与最近 180 天两段；少于 20 个事件日时只记录、不判断衰减。',
    '结论库只记录研究事实与机器状态，不是交易信号；只有宿主可以晋级或退役结论。',
]


def _window_summary(window, statistic):
    sample, execution = window['sample'], window.get('execution') or {}
    return {'start': window['start'], 'end': window['end'], 'events': sample['events'], 'days': sample['days'], 'value': sample.get(statistic),
            'p_value': (sample.get('test') or {}).get('p_value'), 'fill_rate': execution.get('fill_rate'), 'mean_net_return': execution.get('mean_net_return')}


def decay_state(conclusion, recent):
    """Monitor rule ``conclusion-monitor-v1`` on the rolling window: (state, reasons, tested value)."""
    statistic = 'mean_daily_difference' if conclusion['baseline_condition'] else 'daily_mean'
    sample = recent['sample']
    value = sample.get(statistic)
    if sample['days'] < MIN_FORWARD_DAYS:
        return 'INSUFFICIENT_FORWARD_DATA', [], value
    positive = conclusion['expected_sign'] == 'positive'
    reference = conclusion['confirmation']['tested_value']
    reasons = []
    if value is None or value == 0 or (value > 0) != positive:
        reasons.append('SIGN_REVERSED')
    elif reference is not None and abs(value) < DECAY_RATIO * abs(reference):
        reasons.append('EFFECT_SHRUNK')
    execution = recent.get('execution')
    if conclusion['execution'] and execution:
        if execution.get('fill_rate') is None or execution['fill_rate'] < THRESHOLDS['min_fill_rate']:
            reasons.append('FILL_RATE_LOW')
        if positive and (execution.get('mean_net_return') is None or execution['mean_net_return'] <= 0):
            reasons.append('NET_RETURN_NOT_POSITIVE')
    return ('DECAYING' if reasons else 'HEALTHY'), reasons, value


class ConclusionLibrary:
    def __init__(self, output, *, now_fn=None, registry=None, auto=None, event_library=None, sentiment_library=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise AutoResearchError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._registry, self._auto, self._events, self._sentiment = registry, auto, event_library, sentiment_library
        self.root = self.output / '_limit_research' / 'conclusions'

    # ---- dependencies ----------------------------------------------------------------------------------
    def registry(self):
        if self._registry is None:
            from quantlab.trading.event_study import EventStudyRegistry
            self._registry = EventStudyRegistry(self.output, now_fn=self.now_fn)
        return self._registry

    def auto(self):
        if self._auto is None:
            self._auto = AutoResearch(self.output, now_fn=self.now_fn)
        return self._auto

    def events(self):
        if self._events is None:
            from quantlab.trading.limit_events import LimitEventLibrary
            self._events = LimitEventLibrary(self.output)
        return self._events

    def sentiment(self):
        if self._sentiment is None:
            from quantlab.trading.market_sentiment import MarketSentimentLibrary
            self._sentiment = MarketSentimentLibrary(self.output)
        return self._sentiment

    # ---- storage ----------------------------------------------------------------------------------------
    def _check(self):
        for path in (self.output / '_limit_research', self.root, self.root / 'lock'):
            if path.is_symlink():
                raise AutoResearchError('INVALID_WORKSPACE', '结论库目录与文件不能是符号链接。')

    @contextmanager
    def _lock(self):
        self._check()
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'lock').open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _path(self, conclusion_id):
        if not isinstance(conclusion_id, str) or not ID.fullmatch(conclusion_id):
            raise AutoResearchError('NOT_FOUND', '结论不存在。')
        return self.root / f'{conclusion_id}.json'

    def get(self, conclusion_id):
        self._check()
        path = self._path(conclusion_id)
        if not path.exists():
            raise AutoResearchError('NOT_FOUND', '结论不存在。')
        return _read(path, CONCLUSION_FORMAT)

    def _all(self):
        self._check()
        if not self.root.is_dir():
            return []
        return sorted((_read(p, CONCLUSION_FORMAT) for p in self.root.glob('*.json')), key=lambda c: (c['promoted_at'], c['conclusion_id']))

    @staticmethod
    def _transition(conclusion, status, reason, now):
        if conclusion['status'] != status:
            conclusion['status'] = status
            conclusion['status_history'] = (conclusion['status_history'] + [{'at': now.isoformat(), 'status': status, 'reason': reason}])[-50:]
            return True
        return False

    # ---- promotion (host only) ----------------------------------------------------------------------
    def preview_promotion(self, item_id, confirm_end):
        auto = self.auto()
        item = auto.item(item_id)
        if item['state'] != 'SCREENED_PASS':
            raise AutoResearchError('NOT_PROMOTABLE', '只有通过样本内筛选（SCREENED_PASS）的提案可以晋级确认。')
        plan = auto.plan_record(item['plan_id'])['plan']
        now = _utc(self.now_fn())
        start = date.fromisoformat(plan['locked_out_of_sample_start'])
        end = _iso_day(confirm_end, 'confirm_end', 'INVALID_WINDOW')
        if (end - start).days < MIN_CONFIRM_WINDOW_DAYS or end >= now.astimezone(TZ).date():
            raise AutoResearchError('INVALID_WINDOW', f'确认区间从锁定样本外起点 {start} 开始，须至少 {MIN_CONFIRM_WINDOW_DAYS} 天，且终点早于今天。')
        conclusion_id = str(uuid5(NAMESPACE_URL, 'niuniu-research-conclusion:' + item_id))
        if self._path(conclusion_id).exists():
            raise AutoResearchError('ALREADY_PROMOTED', '该提案已经晋级过，不能重复确认。')
        library = self.events().latest_covering(end.isoformat())
        if library is None:
            raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖确认区间终点的涨停事件库 build。')
        sentiment_id = None
        if item['spec']['sentiment_build_id'] is not None:
            sentiment = self.sentiment().latest_covering(end.isoformat())
            if sentiment is None:
                raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖确认区间终点的情绪指标 build。')
            sentiment_id = sentiment['build_id']
        spec = {**item['spec'], 'family': plan['confirmation_family'], 'library_build_id': library['build_id'], 'sentiment_build_id': sentiment_id,
                'start': start.isoformat(), 'end': end.isoformat(), 'split_date': None}
        try:
            self.registry().normalize_spec(spec)
            registered = len(self.registry().family_report(plan['confirmation_family'])['studies'])
        except ValueError as error:
            raise AutoResearchError(getattr(error, 'code', None) or 'INVALID_SPEC', str(error)) from None
        return {'format': PROMOTION_FORMAT, 'prepared_at': now.isoformat(), 'conclusion_id': conclusion_id, 'item_id': item_id,
                'plan_id': item['plan_id'], 'screening_study': {'family': item['spec']['family'], 'study_id': item['study_id']},
                'confirmation_family': plan['confirmation_family'], 'confirmation_window': {'start': start.isoformat(), 'end': end.isoformat()},
                'confirmation_spec': spec, 'registered_confirmations_before': registered,
                'rules': {'p_threshold': CONFIRM_P, 'adjustment': 'holm_over_all_registered_confirmations', 'checklist_stage': 'confirmation',
                          'monitor_version': MONITOR_VERSION, 'min_forward_days': MIN_FORWARD_DAYS, 'recent_window_days': RECENT_WINDOW_DAYS,
                          'decay_ratio': DECAY_RATIO},
                'limitations': LIMITATIONS}

    def promote(self, preview, expected_digest, *, confirmed=False):
        if confirmed is not True:
            raise AutoResearchError('CONFIRMATION_REQUIRED', '晋级确认必须由宿主核对后明确确认。')
        if not isinstance(preview, dict) or not isinstance(expected_digest, str) or digest(preview) != expected_digest:
            raise AutoResearchError('DIGEST_MISMATCH', '晋级预览摘要不一致，请重新预览。')
        now = _utc(self.now_fn())
        prepared = _moment(preview.get('prepared_at'), 'prepared_at', 'INVALID_PROMOTION')
        if not timedelta(0) <= now - prepared <= PREVIEW_TTL:
            raise AutoResearchError('PREVIEW_EXPIRED', '晋级须在预览后 30 分钟内确认（或时钟回退），请重新预览。')
        rebuilt = self.preview_promotion(preview.get('item_id'), (preview.get('confirmation_window') or {}).get('end'))
        core = ('conclusion_id', 'item_id', 'plan_id', 'screening_study', 'confirmation_family', 'confirmation_window', 'confirmation_spec', 'rules')
        if any(rebuilt[key] != preview.get(key) for key in core):
            raise AutoResearchError('PROMOTION_TAMPERED', '晋级预览与按当前数据和规则重建的结果不一致，请重新预览。')
        spec = rebuilt['confirmation_spec']
        with self._lock():
            path = self._path(rebuilt['conclusion_id'])
            if path.exists():
                raise AutoResearchError('ALREADY_PROMOTED', '该提案已经晋级过，不能重复确认。')
            try:
                record = self.registry().register(spec)
            except ValueError as error:
                raise AutoResearchError(getattr(error, 'code', None) or 'INVALID_SPEC', str(error)) from None
            value = {'format': CONCLUSION_FORMAT, 'conclusion_id': rebuilt['conclusion_id'], 'item_id': rebuilt['item_id'], 'plan_id': rebuilt['plan_id'],
                     'promoted_at': now.isoformat(), 'promotion_digest': expected_digest, 'hypothesis': spec['hypothesis'],
                     'expected_sign': spec['expected_sign'], 'condition': spec['condition'], 'baseline_condition': spec['baseline_condition'],
                     'outcome': spec['outcome'], 'execution': spec['execution'], 'group_by': spec['group_by'],
                     'screening_study': rebuilt['screening_study'],
                     'confirmation': {'family': rebuilt['confirmation_family'], 'study_id': record['study_id'], 'window': rebuilt['confirmation_window'],
                                      'spec': spec, 'outcome': None, 'p_value': None, 'p_holm': None, 'family_size': None, 'tested_value': None,
                                      'checklist': None, 'evaluated_at': None},
                     'status': 'PENDING_RUN', 'status_history': [{'at': now.isoformat(), 'status': 'PENDING_RUN', 'reason': 'PROMOTED_BY_HOST'}],
                     'evaluations': [], 'retired_at': None, 'retire_reason': None}
            _write(path, value)
        return value

    def retire(self, conclusion_id, reason, *, confirmed=False):
        if confirmed is not True:
            raise AutoResearchError('CONFIRMATION_REQUIRED', '退役结论需要宿主明确确认。')
        if not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 300:
            raise AutoResearchError('INVALID_ARGUMENT', '退役原因须为 5–300 字符。')
        now = _utc(self.now_fn())
        with self._lock():
            conclusion = self.get(conclusion_id)
            if self._transition(conclusion, 'RETIRED', 'RETIRED_BY_HOST', now):
                conclusion.update(retired_at=now.isoformat(), retire_reason=reason.strip())
                _write(self._path(conclusion_id), conclusion)
        return conclusion

    # ---- confirmation ------------------------------------------------------------------------------------
    def confirm(self):
        """Run pending confirmation studies, then re-judge every confirmation against its whole family (Holm)."""
        registry, ran, errors = self.registry(), [], []
        for conclusion in self._all():
            if conclusion['status'] != 'PENDING_RUN':
                continue
            try:
                registry.run(conclusion['confirmation']['family'], conclusion['confirmation']['study_id'])
                ran.append(conclusion['conclusion_id'])
            except Exception as error:  # noqa: BLE001 - recorded and retried by the next evaluation
                errors.append({'conclusion_id': conclusion['conclusion_id'], 'code': getattr(error, 'code', None) or type(error).__name__,
                               'message': str(error)[:200]})
        changed = []
        now = _utc(self.now_fn())
        with self._lock():
            conclusions = self._all()
            for family in sorted({c['confirmation']['family'] for c in conclusions}):
                rows = {row['study_id']: row for row in registry.family_report(family)['studies']}
                for conclusion in conclusions:
                    c = conclusion['confirmation']
                    if c['family'] != family or conclusion['status'] == 'RETIRED':
                        continue
                    record = registry.get(family, c['study_id'])
                    row = rows.get(c['study_id'])
                    if record['result'] is None or row is None:
                        continue
                    checklist = evaluate_checklist(record['spec'], record['result'], stage='confirmation', p_value=row['p_holm'])
                    outcome = 'CONFIRMED' if checklist['passed'] else 'NOT_CONFIRMED'
                    before = (c['outcome'], c['p_holm'], c['family_size'], conclusion['status'])
                    c.update(outcome=outcome, p_value=row['p_value'], p_holm=row['p_holm'], family_size=len(rows), tested_value=row['tested_value'],
                             checklist=checklist)
                    if outcome == 'NOT_CONFIRMED':
                        status = 'NOT_CONFIRMED'
                    else:
                        status = 'MONITORING' if conclusion['status'] in ('PENDING_RUN', 'NOT_CONFIRMED') else conclusion['status']
                    self._transition(conclusion, status, f'CONFIRMATION_{outcome}_HOLM_M{len(rows)}', now)
                    if (c['outcome'], c['p_holm'], c['family_size'], conclusion['status']) != before:
                        c['evaluated_at'] = now.isoformat()
                        _write(self._path(conclusion['conclusion_id']), conclusion)
                        changed.append({'conclusion_id': conclusion['conclusion_id'], 'outcome': outcome, 'p_holm': row['p_holm'],
                                        'family_size': len(rows), 'status': conclusion['status']})
        return {'ran': ran, 'errors': errors, 'changed': changed}

    # ---- monitoring --------------------------------------------------------------------------------------
    def _due(self, conclusion, day):
        return conclusion['status'] in ACTIVE and date.fromisoformat(conclusion['confirmation']['window']['end']) < day

    def is_current(self, day):
        day = day if isinstance(day, date) and not isinstance(day, datetime) else _iso_day(day, 'day', 'INVALID_ARGUMENT')
        conclusions = self._all()
        if any(c['status'] == 'PENDING_RUN' for c in conclusions):
            return False
        due = [c for c in conclusions if self._due(c, day)]
        if not due:
            return True
        library = self.events().latest_covering(day.isoformat())
        return library is not None and all(
            c['evaluations'] and c['evaluations'][-1]['as_of_day'] == day.isoformat() and c['evaluations'][-1]['library_build_id'] == library['build_id']
            and c['evaluations'][-1]['health'] != 'ERROR' for c in due)

    def evaluate(self, day):
        day = day if isinstance(day, date) and not isinstance(day, datetime) else _iso_day(day, 'day', 'INVALID_ARGUMENT')
        confirmation = self.confirm()
        due = [c for c in self._all() if self._due(c, day)]
        library = self.events().latest_covering(day.isoformat()) if due else None
        if due and library is None:
            raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖监控日期的涨停事件库 build。')
        evaluated, errors = [], list(confirmation['errors'])
        for conclusion in due:
            last = conclusion['evaluations'][-1] if conclusion['evaluations'] else None
            if last and last['as_of_day'] == day.isoformat() and last['library_build_id'] == library['build_id'] and last['health'] != 'ERROR':
                continue
            window_end = date.fromisoformat(conclusion['confirmation']['window']['end'])
            forward_start = window_end + timedelta(days=1)
            recent_start = max(forward_start, day - timedelta(days=RECENT_WINDOW_DAYS - 1))
            statistic = 'mean_daily_difference' if conclusion['baseline_condition'] else 'daily_mean'
            evaluation = {'as_of_day': day.isoformat(), 'library_build_id': library['build_id'], 'sentiment_build_id': None,
                          'computed_at': _utc(self.now_fn()).isoformat(), 'monitor_version': MONITOR_VERSION}
            try:
                spec = {**conclusion['confirmation']['spec'], 'library_build_id': library['build_id'], 'start': forward_start.isoformat(), 'end': day.isoformat()}
                if spec['sentiment_build_id'] is not None:
                    sentiment = self.sentiment().latest_covering(day.isoformat())
                    if sentiment is None:
                        raise AutoResearchError('RESEARCH_BUILD_MISSING', '没有覆盖监控日期的情绪指标 build。')
                    spec['sentiment_build_id'] = evaluation['sentiment_build_id'] = sentiment['build_id']
                measured = self.registry().measure(spec, {'forward': (forward_start.isoformat(), day.isoformat()),
                                                          'recent': (recent_start.isoformat(), day.isoformat())},
                                                   seed_key=f"{conclusion['conclusion_id']}:{day.isoformat()}")
                health, reasons, value = decay_state(conclusion, measured['windows']['recent'])
                evaluation.update(health=health, reasons=reasons, recent_value=value, library_events_sha256=measured['library_events_sha256'],
                                  windows={name: _window_summary(window, statistic) for name, window in measured['windows'].items()})
            except Exception as error:  # noqa: BLE001 - kept as an ERROR evaluation; the scheduler retries with its own limits
                evaluation.update(health='ERROR', reasons=[], error={'code': getattr(error, 'code', None) or type(error).__name__, 'message': str(error)[:200]})
                errors.append({'conclusion_id': conclusion['conclusion_id'], **evaluation['error']})
            now = _utc(self.now_fn())
            with self._lock():
                current = self.get(conclusion['conclusion_id'])
                if current['status'] not in ACTIVE:
                    continue
                current['evaluations'] = (current['evaluations'] + [evaluation])[-MAX_EVALUATIONS:]
                if evaluation['health'] == 'DECAYING':
                    self._transition(current, 'DECAYING', 'MONITOR_' + '+'.join(evaluation['reasons']), now)
                elif evaluation['health'] in ('HEALTHY', 'INSUFFICIENT_FORWARD_DATA'):
                    self._transition(current, 'MONITORING', 'MONITOR_' + evaluation['health'], now)
                _write(self._path(current['conclusion_id']), current)
            evaluated.append({'conclusion_id': conclusion['conclusion_id'], 'health': evaluation['health'], 'reasons': evaluation['reasons'],
                              'status': current['status']})
        result = {'as_of_day': day.isoformat(), 'library_build_id': library['build_id'] if library else None, 'confirmations': confirmation,
                  'evaluated': evaluated, 'errors': errors}
        if errors:
            raise AutoResearchError('MONITOR_ERROR', f'{len(errors)} 项确认或监控失败（已记录）：' + '；'.join(e['code'] for e in errors)[:200])
        return result

    # ---- reads ---------------------------------------------------------------------------------------
    @staticmethod
    def summary(conclusion):
        c = conclusion['confirmation']
        last = conclusion['evaluations'][-1] if conclusion['evaluations'] else None
        return {'conclusion_id': conclusion['conclusion_id'], 'status': conclusion['status'], 'hypothesis': conclusion['hypothesis'],
                'expected_sign': conclusion['expected_sign'], 'condition': conclusion['condition'], 'baseline_condition': conclusion['baseline_condition'],
                'outcome': conclusion['outcome'], 'execution': conclusion['execution'], 'promoted_at': conclusion['promoted_at'],
                'screening_study': conclusion['screening_study'],
                'confirmation': {'family': c['family'], 'study_id': c['study_id'], 'window': c['window'], 'outcome': c['outcome'], 'p_value': c['p_value'],
                                 'p_holm': c['p_holm'], 'family_size': c['family_size'], 'tested_value': c['tested_value'],
                                 'failed_checks': None if c['checklist'] is None else c['checklist']['failed']},
                'latest_monitoring': None if last is None else {k: last.get(k) for k in ('as_of_day', 'health', 'reasons', 'windows', 'error')},
                'status_history': conclusion['status_history'][-5:], 'retired_at': conclusion['retired_at'], 'retire_reason': conclusion['retire_reason']}

    def list(self, *, status=None):
        if status is not None and status not in STATUSES:
            raise AutoResearchError('INVALID_ARGUMENT', 'status 无效。')
        return [self.summary(c) for c in self._all() if status is None or c['status'] == status]

    def ledger(self):
        """Everything researched: proposal states per family (failures included) and conclusion statuses."""
        families, states = {}, {}
        for item in self.auto().items():
            family = families.setdefault(item['spec']['family'], {})
            family[item['state']] = family.get(item['state'], 0) + 1
            states[item['state']] = states.get(item['state'], 0) + 1
        statuses = {}
        for conclusion in self._all():
            statuses[conclusion['status']] = statuses.get(conclusion['status'], 0) + 1
        return {'proposals': sum(states.values()), 'proposal_states': states, 'proposal_families': families,
                'conclusions': sum(statuses.values()), 'conclusion_statuses': statuses, 'limitations': LIMITATIONS}


__all__ = ['PROMOTION_FORMAT', 'CONCLUSION_FORMAT', 'MONITOR_VERSION', 'STATUSES', 'LIMITATIONS', 'ConclusionLibrary', 'decay_state']
