"""Versioned machine rules for the A-share limit-board sentiment cycle and similar-day lookup.

Temperature is the mean causal percentile of selected daily sentiment metrics versus the
previous 250 trading days (today excluded). Phases are host engineering thresholds, not
expert rules or trading signals. All outputs for day T use data available at T's close.
"""
from __future__ import annotations

from datetime import date
import math

import numpy as np
import polars as pl

CYCLE_RULES_VERSION = 'sentiment-cycle-rules-v1'
RULE_ORIGIN = 'host_engineering_policy_not_expert_rule'
WINDOW = 250
MIN_HISTORY = 60
MIN_INDICATORS = 5
CHANGE_SESSIONS = 3
CHANGE_THRESHOLD = 10.0
POSITIVE = ('limit_up_count_non_st', 'max_streak', 'advance_rate_1to2', 'prev_limit_up_avg_return', 'up_ratio')
NEGATIVE = ('limit_down_count_non_st', 'broken_rate', 'big_loss_count')
PHASES = {
    'UNKNOWN': '历史不足或指标缺失', 'ICE': '冰点', 'CLIMAX': '高潮', 'REPAIR': '修复', 'FERMENT': '发酵',
    'DIVERGENCE': '分歧', 'EBB': '退潮', 'RANGE_WARM': '偏暖震荡', 'RANGE_COOL': '偏冷震荡',
}
RULES = [
    '温度为空 → UNKNOWN',
    '温度 ≤ 20 → ICE（冰点）',
    '温度 ≥ 80 → CLIMAX（高潮）',
    '3 日温度变化 ≥ +10：温度 < 50 → REPAIR（修复），否则 FERMENT（发酵）',
    '3 日温度变化 ≤ -10：温度 ≥ 50 → DIVERGENCE（分歧），否则 EBB（退潮）',
    '其余：温度 ≥ 50 → RANGE_WARM（偏暖震荡），否则 RANGE_COOL（偏冷震荡）',
]


def classify(temperature, change):
    if temperature is None or (isinstance(temperature, float) and math.isnan(temperature)):
        return 'UNKNOWN'
    if temperature <= 20:
        return 'ICE'
    if temperature >= 80:
        return 'CLIMAX'
    if change is not None and not (isinstance(change, float) and math.isnan(change)):
        if change >= CHANGE_THRESHOLD:
            return 'REPAIR' if temperature < 50 else 'FERMENT'
        if change <= -CHANGE_THRESHOLD:
            return 'DIVERGENCE' if temperature >= 50 else 'EBB'
    return 'RANGE_WARM' if temperature >= 50 else 'RANGE_COOL'


def _causal_percentiles(values):
    values = np.asarray(values, dtype=float)
    result = np.full(values.shape, np.nan)
    for t in range(values.size):
        current = values[t]
        if np.isnan(current):
            continue
        window = values[max(0, t - WINDOW):t]
        window = window[~np.isnan(window)]
        if window.size < MIN_HISTORY:
            continue
        result[t] = (np.sum(window < current) + 0.5 * np.sum(window == current)) / window.size
    return result


def compute_cycle(daily):
    """Return one row per date with percentiles, temperature, 3-session change and phase."""
    if not isinstance(daily, pl.DataFrame) or 'date' not in daily.columns:
        raise ValueError('daily 必须是带 date 列的 DataFrame。')
    missing = [c for c in POSITIVE + NEGATIVE if c not in daily.columns]
    if missing:
        raise ValueError('情绪指标缺少列：' + ', '.join(missing))
    frame = daily.sort('date')
    if frame['date'].n_unique() != frame.height:
        raise ValueError('date 不能重复。')
    columns = {'date': frame['date'].to_list()}
    percentiles = []
    for name in POSITIVE + NEGATIVE:
        raw = frame[name].cast(pl.Float64).to_numpy()
        pct = _causal_percentiles(raw)
        columns['pct_' + name] = [None if np.isnan(v) else float(v) for v in pct]
        percentiles.append(pct if name in POSITIVE else 1 - pct)
    stack = np.vstack(percentiles)
    available = np.sum(~np.isnan(stack), axis=0)
    totals = np.nansum(stack, axis=0)
    mean = np.divide(totals, available, out=np.full(totals.shape, np.nan), where=available > 0)
    temperature = np.where(available >= MIN_INDICATORS, 100 * mean, np.nan)
    change = np.full(temperature.shape, np.nan)
    change[CHANGE_SESSIONS:] = temperature[CHANGE_SESSIONS:] - temperature[:-CHANGE_SESSIONS]
    columns['indicators_available'] = [int(v) for v in available]
    columns['temperature'] = [None if np.isnan(v) else round(float(v), 6) for v in temperature]
    columns['temperature_change_3d'] = [None if np.isnan(v) else round(float(v), 6) for v in change]
    phases = [classify(t, c) for t, c in zip(columns['temperature'], columns['temperature_change_3d'])]
    columns['phase'] = phases
    columns['phase_zh'] = [PHASES[p] for p in phases]
    columns['cycle_rules_version'] = [CYCLE_RULES_VERSION] * len(phases)
    schema = {'date': pl.Date, **{'pct_' + n: pl.Float64 for n in POSITIVE + NEGATIVE}, 'indicators_available': pl.Int64,
              'temperature': pl.Float64, 'temperature_change_3d': pl.Float64, 'phase': pl.String, 'phase_zh': pl.String,
              'cycle_rules_version': pl.String}
    return pl.DataFrame(columns, schema=schema)


def similar_days(daily, target, *, k=10, exclude_recent=20):
    """Nearest historical days to ``target`` by percentile profile, using only days known before target."""
    if type(k) is not int or not 1 <= k <= 50:
        raise ValueError('k 必须为 1–50。')
    if type(exclude_recent) is not int or not 0 <= exclude_recent <= 250:
        raise ValueError('exclude_recent 必须为 0–250。')
    target = date.fromisoformat(target) if isinstance(target, str) else target
    frame = daily.sort('date')
    dates = frame['date'].to_list()
    if target not in dates:
        raise ValueError('目标日期不在情绪指标中。')
    index = dates.index(target)
    history = frame.head(index + 1)
    cycle = compute_cycle(history)
    features = ['pct_' + n for n in POSITIVE + NEGATIVE]
    matrix = cycle.select(features).to_numpy().astype(float)
    target_vector = matrix[index]
    if np.isnan(target_vector).any():
        raise ValueError('目标日期的分位数特征不完整（历史不足）。')
    limit = index - exclude_recent - 1
    candidates = []
    for i in range(0, max(limit, 0)):
        vector = matrix[i]
        if np.isnan(vector).any():
            continue
        candidates.append((float(np.sqrt(np.mean((vector - target_vector) ** 2))), i))
    candidates.sort()
    next_metrics = ('limit_up_count', 'max_streak', 'prev_limit_up_avg_return', 'advance_rate_1to2', 'broken_rate')
    rows = []
    for distance, i in candidates[:k]:
        row = {'date': dates[i].isoformat(), 'distance': round(distance, 6), 'phase': cycle['phase'][i],
               'temperature': cycle['temperature'][i]}
        following = frame.row(i + 1, named=True)
        row['next_date'] = following['date'].isoformat()
        for name in next_metrics:
            row['next_' + name] = following[name]
        rows.append(row)
    return {'target': target.isoformat(), 'target_phase': cycle['phase'][index], 'target_temperature': cycle['temperature'][index],
            'k': k, 'exclude_recent': exclude_recent, 'candidates_considered': len(candidates), 'neighbors': rows,
            'rules_version': CYCLE_RULES_VERSION, 'note': '相似日只使用目标日之前已知的数据；结果是历史类比，不是预测或交易信号。'}


__all__ = ['CYCLE_RULES_VERSION', 'RULE_ORIGIN', 'WINDOW', 'MIN_HISTORY', 'POSITIVE', 'NEGATIVE', 'PHASES', 'RULES',
           'classify', 'compute_cycle', 'similar_days']
