"""Verifiable probability forecasts on next-session limit-board outcomes, scored by Brier (research_only).

Forecasts are recorded before the target session's 09:15 (Asia/Shanghai) against a versioned
catalog of binary questions that resolve mechanically from the daily sentiment metrics. Records
are append-only: one forecast per forecaster, question and target day, no revisions. Two machine
baselines (250-day climatology and a similar-day analog) give every day a reference forecast, so
skill is always measured against them rather than against zero.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo
import json
import math
import re

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'limit-forecast-v1'
RESOLUTION_FORMAT = 'limit-forecast-resolution-v1'
QUESTIONS_VERSION = 'limit-forecast-questions-v1'
TZ = ZoneInfo('Asia/Shanghai')
CUTOFF = time(9, 15)
MAX_LEAD_DAYS = 7
CLIMATOLOGY_WINDOW = 250
ANALOG_K = 10
BASELINES = ('baseline:climatology-250', 'baseline:analog-k10')
FORECASTER = re.compile(r'^(ai|host|baseline):[A-Za-z0-9_.\-]{1,60}$')


def _ge(name, threshold):
    return lambda today, previous: None if today[name] is None else today[name] >= threshold


QUESTIONS = {
    'limit_up_count_increase': {
        'label': '非 ST 涨停家数多于前一交易日', 'metric': 'limit_up_count_non_st',
        'resolve': lambda t, p: None if p is None or t['limit_up_count_non_st'] is None or p['limit_up_count_non_st'] is None
        else t['limit_up_count_non_st'] > p['limit_up_count_non_st']},
    'high_board_continues': {
        'label': '前一交易日最高连板（≥2 板）的股票至少一只今日继续收盘涨停', 'metric': 'high_board_broken',
        'resolve': lambda t, p: None if t['high_board_broken'] is None else not t['high_board_broken']},
    'broken_rate_below_30pct': {
        'label': '炸板率低于 30%', 'metric': 'broken_rate',
        'resolve': lambda t, p: None if t['broken_rate'] is None else t['broken_rate'] < 0.30},
    'advance_1to2_at_least_25pct': {'label': '1 进 2 晋级率不低于 25%', 'metric': 'advance_rate_1to2', 'resolve': _ge('advance_rate_1to2', 0.25)},
    'prev_limit_up_return_positive': {
        'label': '昨日收盘涨停股今日平均收益为正', 'metric': 'prev_limit_up_avg_return',
        'resolve': lambda t, p: None if t['prev_limit_up_avg_return'] is None else t['prev_limit_up_avg_return'] > 0},
    'limit_down_at_least_10': {'label': '非 ST 跌停家数不少于 10 家', 'metric': 'limit_down_count_non_st', 'resolve': _ge('limit_down_count_non_st', 10)},
}
LIMITATIONS = [
    '问题由日度情绪指标机械判定（research_only）：涨跌停由研究制度表推算，不是官方统计口径。',
    '预测须在目标交易日 09:15 前记录，记录后不可修改；非交易日或指标为空的问题判为 VOID，不计分。',
    'Brier 分数越低越好；技能分以同题同日的 250 日气候基准为参照，样本少时不具统计意义，也不代表交易能力。',
]


class ForecastError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def outcomes_frame(daily):
    """Per trading day outcome of every question (True/False/None), from consecutive sentiment rows."""
    rows = daily.sort('date').to_dicts()
    out = []
    for index, today in enumerate(rows):
        previous = rows[index - 1] if index else None
        out.append({'date': today['date'], **{qid: spec['resolve'](today, previous) for qid, spec in QUESTIONS.items()}})
    return pl.DataFrame(out, schema={'date': pl.Date, **{qid: pl.Boolean for qid in QUESTIONS}})


def baseline_probabilities(daily, last_day):
    """Climatology and analog probabilities for the session after ``last_day`` using data up to ``last_day`` only."""
    from quantlab.trading.sentiment_cycle import similar_days
    history = daily.filter(pl.col('date') <= last_day).sort('date')
    if history.height == 0 or history['date'][-1] != last_day:
        raise ForecastError('BASE_DAY_MISSING', f'情绪指标中没有 {last_day}。')
    outcomes = outcomes_frame(history)
    window = outcomes.tail(CLIMATOLOGY_WINDOW)
    result = {'baseline:climatology-250': {}, 'baseline:analog-k10': {}}
    for qid in QUESTIONS:
        values = window[qid].drop_nulls()
        result['baseline:climatology-250'][qid] = None if values.len() < 20 else (int(values.sum()) + 1) / (values.len() + 2)
    try:
        neighbors = similar_days(history, last_day, k=ANALOG_K)['neighbors']
    except ValueError:
        neighbors = []
    lookup = {row['date']: row for row in outcomes.to_dicts()}
    dates = outcomes['date'].to_list()
    for qid in QUESTIONS:
        hits = []
        for neighbor in neighbors:
            following = date.fromisoformat(neighbor['next_date'])
            if following in lookup and lookup[following][qid] is not None and following <= last_day:
                hits.append(lookup[following][qid])
        result['baseline:analog-k10'][qid] = None if len(hits) < 5 else (sum(hits) + 1) / (len(hits) + 2)
    return result, {'last_day': last_day.isoformat(), 'climatology_days': window.height, 'analog_neighbors': len(neighbors), 'history_days': len(dates)}


class LimitForecastJournal:
    def __init__(self, output, *, now_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise ForecastError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.root = self.output / '_limit_research' / 'forecasts'

    def _day_dir(self, day):
        for path in (self.output / '_limit_research', self.root):
            if path.is_symlink():
                raise ForecastError('INVALID_WORKSPACE', '预测目录不能是符号链接。')
        return self.root / (day.isoformat() if isinstance(day, date) else date.fromisoformat(day).isoformat())

    @staticmethod
    def _read(path, fmt):
        value = json.loads(path.read_bytes())
        core = {k: v for k, v in value.items() if k != 'checksum'}
        if value.get('checksum') != digest(core) or core.get('format') != fmt:
            raise ForecastError('CORRUPT_ARCHIVE', path.name + ' 校验失败。')
        return core

    @staticmethod
    def _write(path, value):
        temporary = path.with_name('.' + path.name + '.tmp')
        temporary.write_text(encode({**value, 'checksum': digest(value)}), encoding='utf-8')
        temporary.replace(path)

    # ---- recording ------------------------------------------------------------------------------------
    def record(self, *, request_id, forecaster, question_id, target_day, probability, rationale='', evidence=()):
        try:
            if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            raise ForecastError('INVALID_ARGUMENT', 'request_id 必须为规范 UUID。') from None
        if not isinstance(forecaster, str) or not FORECASTER.fullmatch(forecaster):
            raise ForecastError('INVALID_ARGUMENT', 'forecaster 必须形如 ai:<名称>、host:<名称> 或 baseline:<名称>。')
        if question_id not in QUESTIONS:
            raise ForecastError('UNKNOWN_QUESTION', '未知预测问题：' + str(question_id))
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ForecastError('INVALID_ARGUMENT', 'probability 必须为 0–1 的数。')
        if not isinstance(rationale, str) or len(rationale) > 2000:
            raise ForecastError('INVALID_ARGUMENT', 'rationale 不能超过 2000 字。')
        if not isinstance(evidence, (list, tuple)) or len(evidence) > 20 or any(not isinstance(e, str) or len(e) > 200 for e in evidence):
            raise ForecastError('INVALID_ARGUMENT', 'evidence 必须为至多 20 条、每条不超过 200 字的文本。')
        try:
            target = date.fromisoformat(target_day) if isinstance(target_day, str) else target_day
        except ValueError:
            raise ForecastError('INVALID_ARGUMENT', 'target_day 必须为 YYYY-MM-DD。') from None
        now = self.now_fn()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ForecastError('INVALID_CLOCK', '时钟必须带时区。')
        deadline = datetime.combine(target, CUTOFF, TZ)
        if target.weekday() >= 5:
            raise ForecastError('NOT_A_WEEKDAY', '目标日必须是工作日（非交易日在判定时记为 VOID）。')
        if now >= deadline:
            raise ForecastError('FORECAST_TOO_LATE', f'必须在 {target} 09:15（北京时间）之前记录预测。')
        if deadline - now > timedelta(days=MAX_LEAD_DAYS):
            raise ForecastError('FORECAST_TOO_EARLY', f'只能预测未来 {MAX_LEAD_DAYS} 天内的交易日。')
        folder = self._day_dir(target)
        key = digest({'forecaster': forecaster, 'question_id': question_id, 'target_day': target.isoformat()})
        forecast_id = str(uuid5(NAMESPACE_URL, 'niuniu-limit-forecast:' + key))
        path = folder / f'{forecast_id}.json'
        value = {'format': FORMAT, 'forecast_id': forecast_id, 'request_id': request_id, 'questions_version': QUESTIONS_VERSION,
                 'forecaster': forecaster, 'question_id': question_id, 'question': QUESTIONS[question_id]['label'], 'target_day': target.isoformat(),
                 'probability': float(probability), 'rationale': rationale.strip(), 'evidence': list(evidence),
                 'recorded_at': now.astimezone(timezone.utc).isoformat(), 'deadline': deadline.astimezone(timezone.utc).isoformat()}
        if path.exists():
            existing = self._read(path, FORMAT)
            same = {k: existing[k] for k in ('request_id', 'probability', 'rationale', 'evidence')} == \
                {k: value[k] for k in ('request_id', 'probability', 'rationale', 'evidence')}
            if same:
                return {**existing, 'created': False}
            raise ForecastError('CONFLICT', '该预测者对该问题与目标日已有记录，预测不可修改。')
        folder.mkdir(parents=True, exist_ok=True)
        self._write(path, value)
        return {**value, 'created': True}

    def forecasts(self, target_day):
        folder = self._day_dir(target_day)
        if not folder.is_dir():
            return []
        return sorted((self._read(p, FORMAT) for p in folder.glob('*.json') if not p.name.startswith('resolution')),
                      key=lambda r: (r['question_id'], r['forecaster']))

    def generate_baselines(self, target_day, sentiment_build_id=None):
        """Record climatology and analog forecasts for ``target_day`` from data up to the last session before it."""
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        target = date.fromisoformat(target_day) if isinstance(target_day, str) else target_day
        library = MarketSentimentLibrary(self.output)
        if sentiment_build_id is None:
            rows = [r for r in library.list() if 'error' not in r and r['first_date'] < target.isoformat()]
            if not rows:
                raise ForecastError('RESEARCH_BUILD_MISSING', f'没有 {target} 之前的情绪指标 build。')
            sentiment_build_id = max(rows, key=lambda r: (min(r['last_date'], (target - timedelta(days=1)).isoformat()), r['created_at']))['build_id']
        daily, _ = library.read(sentiment_build_id)
        before = daily.filter(pl.col('date') < target)
        if before.height == 0:
            raise ForecastError('RESEARCH_BUILD_MISSING', '目标日之前没有情绪指标。')
        last_day = before['date'].max()
        probabilities, meta = baseline_probabilities(daily, last_day)
        written = []
        for forecaster, values in probabilities.items():
            for qid, probability in values.items():
                if probability is None:
                    continue
                request_id = str(uuid5(NAMESPACE_URL, f'niuniu-baseline:{forecaster}:{qid}:{target}:{sentiment_build_id}'))
                record = self.record(request_id=request_id, forecaster=forecaster, question_id=qid, target_day=target, probability=probability,
                                     rationale=f"机器基准：数据截至 {meta['last_day']}（情绪 build {sentiment_build_id}）", evidence=[sentiment_build_id])
                written.append({'forecaster': forecaster, 'question_id': qid, 'probability': round(probability, 4), 'created': record['created']})
        return {'target_day': target.isoformat(), 'sentiment_build_id': sentiment_build_id, **meta, 'written': written}

    # ---- resolution -----------------------------------------------------------------------------------
    def resolve(self, target_day, sentiment_build_id=None):
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        target = date.fromisoformat(target_day) if isinstance(target_day, str) else target_day
        library = MarketSentimentLibrary(self.output)
        manifest = library.get(sentiment_build_id) if sentiment_build_id else library.latest_covering(target)
        if manifest is None:
            raise ForecastError('RESEARCH_BUILD_MISSING', f'没有覆盖 {target} 的情绪指标 build。')
        daily, _ = library.read(manifest['build_id'])
        outcomes = {row['date']: row for row in outcomes_frame(daily).to_dicts()}
        trading = target in outcomes
        if not trading and not daily['date'].max() > target:
            raise ForecastError('RESEARCH_BUILD_MISSING', f'情绪指标尚未覆盖 {target}。')
        items = []
        for forecast in self.forecasts(target):
            outcome = outcomes[target][forecast['question_id']] if trading else None
            status = 'RESOLVED' if outcome is not None else ('VOID_NOT_TRADING_DAY' if not trading else 'VOID_UNDEFINED')
            items.append({'forecast_id': forecast['forecast_id'], 'forecaster': forecast['forecaster'], 'question_id': forecast['question_id'],
                          'probability': forecast['probability'], 'outcome': outcome, 'status': status,
                          'brier': None if outcome is None else (forecast['probability'] - float(outcome)) ** 2})
        value = {'format': RESOLUTION_FORMAT, 'target_day': target.isoformat(), 'sentiment_build_id': manifest['build_id'],
                 'questions_version': QUESTIONS_VERSION, 'trading_day': trading,
                 'outcomes': None if not trading else {qid: outcomes[target][qid] for qid in QUESTIONS},
                 'resolved_at': self.now_fn().astimezone(timezone.utc).isoformat(), 'items': items}
        folder = self._day_dir(target)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"resolution-{manifest['build_id']}.json"
        if path.exists():
            existing = self._read(path, RESOLUTION_FORMAT)
            if [i['forecast_id'] for i in existing['items']] == [i['forecast_id'] for i in items]:
                return {**existing, 'created': False}
        self._write(path, value)
        return {**value, 'created': True}

    def resolution(self, target_day):
        folder = self._day_dir(target_day)
        paths = sorted(folder.glob('resolution-*.json')) if folder.is_dir() else []
        records = [self._read(p, RESOLUTION_FORMAT) for p in paths]
        return max(records, key=lambda r: r['resolved_at']) if records else None

    def is_resolved(self, target_day):
        resolution = self.resolution(target_day)
        return resolution is not None and len(resolution['items']) == len(self.forecasts(target_day))

    def days(self):
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name))

    # ---- scoring --------------------------------------------------------------------------------------
    def scorecard(self):
        rows = []
        for day in self.days():
            resolution = self.resolution(day)
            if resolution is None:
                continue
            rows.extend({**item, 'target_day': day} for item in resolution['items'] if item['status'] == 'RESOLVED')
        climatology = {(r['question_id'], r['target_day']): r['brier'] for r in rows if r['forecaster'] == BASELINES[0]}
        by_forecaster = defaultdict(list)
        for row in rows:
            by_forecaster[row['forecaster']].append(row)
        summary = []
        for forecaster, items in sorted(by_forecaster.items()):
            matched = [(r['brier'], climatology[(r['question_id'], r['target_day'])]) for r in items if (r['question_id'], r['target_day']) in climatology]
            reference = sum(b for _, b in matched)
            bins = []
            for low in (0.0, 0.2, 0.4, 0.6, 0.8):
                inside = [r for r in items if low <= r['probability'] < low + 0.2 or (low == 0.8 and r['probability'] == 1.0)]
                if inside:
                    bins.append({'range': f'{low:.1f}–{low + 0.2:.1f}', 'n': len(inside), 'mean_probability': sum(r['probability'] for r in inside) / len(inside),
                                 'observed_rate': sum(bool(r['outcome']) for r in inside) / len(inside)})
            by_question = defaultdict(list)
            for r in items:
                by_question[r['question_id']].append(r['brier'])
            summary.append({'forecaster': forecaster, 'resolved': len(items), 'days': len({r['target_day'] for r in items}),
                            'sample_status': 'NO_SAMPLES' if not items else ('INSUFFICIENT_SAMPLES' if len(items) < 30 else 'MEASURED'),
                            'mean_brier': sum(r['brier'] for r in items) / len(items),
                            'brier_skill_vs_climatology': None if not matched or reference == 0 else 1 - sum(b for b, _ in matched) / reference,
                            'matched_with_climatology': len(matched), 'calibration': bins,
                            'by_question': {q: {'n': len(v), 'mean_brier': sum(v) / len(v)} for q, v in sorted(by_question.items())}})
        return {'format': 'limit-forecast-scorecard-v1', 'questions_version': QUESTIONS_VERSION, 'forecasters': summary,
                'resolved_forecasts': len(rows), 'limitations': LIMITATIONS}


def question_catalog():
    return {'questions_version': QUESTIONS_VERSION, 'cutoff': '目标交易日 09:15（北京时间）之前', 'max_lead_days': MAX_LEAD_DAYS,
            'questions': [{'question_id': qid, 'label': spec['label'], 'metric': spec['metric']} for qid, spec in QUESTIONS.items()],
            'baselines': list(BASELINES), 'limitations': LIMITATIONS}


__all__ = ['FORMAT', 'QUESTIONS', 'QUESTIONS_VERSION', 'BASELINES', 'ForecastError', 'LimitForecastJournal', 'baseline_probabilities',
           'outcomes_frame', 'question_catalog']
