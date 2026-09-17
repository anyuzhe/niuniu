"""Pre-registered event studies over the limit-up event library (research_only).

A study spec is frozen and registered before any result is computed. Conditions use a
whitelisted expression language over T-day features (and optional T-day market context);
label columns can only be the outcome. Statistics aggregate to equal-weighted daily means,
test with the existing non-overlapping date-block sign randomization and apply Holm
adjustment across every study registered in the same family.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import ast
import hashlib
import json
import math
import re

import polars as pl

from quantlab.statistics.permutation import PermutationConfig, block_sign_test, holm
from quantlab.storage.codec import digest, encode

from .limit_events import FEATURE_COLUMNS, LABEL_COLUMNS, LimitEventLibrary, iter_state_batches, resolve_inputs
from .limit_execution import EXECUTION_VERSION, TRADE_SCHEMA, ExecutionSpec, fill_summary, simulate_trades
from .market_sentiment import METRICS, MarketSentimentLibrary
from .sentiment_cycle import compute_cycle

FORMAT = 'limit-event-study-v1'
ENGINE_VERSION = 'event-study-engine-v1'
FAMILY = re.compile(r'^[a-z][a-z0-9-]{2,40}$')
STUDY = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
NUMERIC_OUTCOMES = ('t1_open_ret', 't1_high_ret', 't1_low_ret', 't1_close_ret', 't2_open_ret_day', 't2_close_ret_day',
                    'ret_close_to_t2close', 'ret_t1open_to_t1close', 'ret_t1open_to_t2open', 'ret_t1open_to_t2close')
BOOLEAN_OUTCOMES = ('t1_is_limit_up_close', 't1_touched_limit_up', 't1_is_broken_board', 't1_is_limit_down_close',
                    't1_open_at_limit_up', 't1_open_at_limit_down')
CONTEXT_COLUMNS = tuple('mkt_' + name for name in METRICS) + ('mkt_temperature', 'mkt_phase')
CONDITION_COLUMNS = tuple(c for c in FEATURE_COLUMNS if c not in ('date', 'code')) + CONTEXT_COLUMNS
GROUPS = ('board', 'streak_bucket', 'year', 'mkt_phase', 'is_st')
MAX_NODES = 64
MAX_DEPTH = 12
PERMUTATION = PermutationConfig(resamples=999, block_days=5, alpha=0.05)
SPEC_FIELDS = {'family', 'hypothesis', 'expected_sign', 'library_build_id', 'sentiment_build_id', 'condition', 'baseline_condition',
               'outcome', 'start', 'end', 'split_date', 'group_by', 'min_events', 'execution'}
EXECUTION_OUTCOMES = ('net_return', 'gross_return')
# A same-day limit-price order is placed before the close, so only facts known intraday before the fill may select it.
PRE_ENTRY_COLUMNS = ('board', 'limit_rate', 'limit_rule_reason', 'is_st', 'listing_date', 'sessions_since_listing', 'preclose',
                     'open', 'open_gap', 'limit_up_price', 'limit_down_price', 'touched_limit_up', 'prev_is_limit_up_close',
                     'prev_limit_up_streak', 'prev_is_broken_board')
PRE_ENTRY_GROUPS = ('board', 'year', 'is_st')
SIGNAL_LIMITATION = '结果为信号标签统计，未计费用、滑点与成交可行性；可执行性须用 AR-3.2 成交模型复核。'
EXECUTION_LIMITATION = ('结果按成交模型 {version}（{entry} 买入、{exit} 卖出、{scenario} 情景）以日线保守近似：计入 T+1、开盘/收盘涨停买不到、'
                        '一字板排不到、跌停顺延卖出、佣金 {commission} 基点、滑点 {slippage} 基点及按日期的印花税与过户费；'
                        '持有 {hold} 个交易日仍卖不出按最后收盘价计价。没有逐笔委托队列，排板成交只是情景假设，不代表真实可成交数量。')
LIMITATIONS = [
    '事件与标签来自 research_only 事件库；涨跌停由研究制度表推算，不认证 strict PIT。',
    SIGNAL_LIMITATION,
    '检验把每个交易日的事件等权平均为一个观测，采用 5 日不重叠区块符号随机化（双侧，原假设为日均值关于 0 对称）；有基准条件时检验与基准的日度差值。',
    'Holm 校正覆盖同一 family 内全部已登记研究（未运行的也占名额），但不能控制登记之外的探索。',
]


class EventStudyError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ---- restricted condition language -----------------------------------------------------------
_COMPARE = {ast.Eq: 'eq', ast.NotEq: 'ne', ast.Lt: 'lt', ast.LtE: 'le', ast.Gt: 'gt', ast.GtE: 'ge', ast.In: 'in', ast.NotIn: 'notin'}


def _constant(node):
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, (bool, int, float, str))):
        if isinstance(node.value, float) and not math.isfinite(node.value):
            raise EventStudyError('INVALID_CONDITION', '条件常量必须为有限数。')
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) \
            and isinstance(node.operand.value, (int, float)) and not isinstance(node.operand.value, bool):
        return -node.operand.value
    raise EventStudyError('INVALID_CONDITION', '只允许数字、布尔、字符串或 None 常量。')


def compile_condition(text, allowed=CONDITION_COLUMNS):
    """Compile a whitelisted boolean expression into a polars expression and the columns it uses."""
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise EventStudyError('INVALID_CONDITION', '条件表达式必须为 1–500 字符。')
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        raise EventStudyError('INVALID_CONDITION', '条件表达式语法错误。') from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise EventStudyError('INVALID_CONDITION', '条件表达式过长。')
    used = set()

    def build(node, depth=0):
        if depth > MAX_DEPTH:
            raise EventStudyError('INVALID_CONDITION', '条件表达式嵌套过深。')
        if isinstance(node, ast.BoolOp):
            parts = [build(v, depth + 1) for v in node.values]
            result = parts[0]
            for part in parts[1:]:
                result = (result & part) if isinstance(node.op, ast.And) else (result | part)
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return ~build(node.operand, depth + 1)
        if isinstance(node, ast.Name):
            return column(node)
        if isinstance(node, ast.Compare):
            left = operand(node.left)
            result = None
            for op, right_node in zip(node.ops, node.comparators):
                kind = _COMPARE.get(type(op))
                if kind is None:
                    raise EventStudyError('INVALID_CONDITION', '不支持的比较运算。')
                if kind in ('in', 'notin'):
                    if not isinstance(right_node, (ast.List, ast.Tuple)) or not right_node.elts or len(right_node.elts) > 20:
                        raise EventStudyError('INVALID_CONDITION', 'in 右侧必须是 1–20 个常量的列表。')
                    values = [_constant(e) for e in right_node.elts]
                    piece = left.is_in(values)
                    piece = ~piece if kind == 'notin' else piece
                    right = None
                else:
                    right = operand(right_node)
                    piece = {'eq': left == right, 'ne': left != right, 'lt': left < right, 'le': left <= right,
                             'gt': left > right, 'ge': left >= right}[kind]
                result = piece if result is None else (result & piece)
                if right is not None:
                    left = right
            return result
        raise EventStudyError('INVALID_CONDITION', '条件表达式含不允许的语法：' + type(node).__name__)

    def column(node):
        if node.id in LABEL_COLUMNS:
            raise EventStudyError('LABEL_IN_CONDITION', f'标签列 {node.id} 不能用于条件（未来函数）。')
        if node.id not in allowed:
            raise EventStudyError('INVALID_CONDITION', '未知或不允许的列：' + node.id)
        used.add(node.id)
        return pl.col(node.id)

    def operand(node):
        if isinstance(node, ast.Name):
            return column(node)
        return pl.lit(_constant(node))

    expression = build(tree.body)
    return expression.fill_null(False), sorted(used)


# ---- statistics ---------------------------------------------------------------------------------------
def _quantile(values, q):
    return float(values.quantile(q, interpolation='linear')) if values.len() else None


def sample_stats(frame, outcome, calendar, seed, *, baseline=None, min_events=30):
    """Event and day-clustered statistics for one sample; ``calendar`` orders date blocks."""
    events = frame.filter(pl.col(outcome).is_not_null())
    values = events[outcome].cast(pl.Float64)
    daily = events.group_by('date').agg(pl.col(outcome).cast(pl.Float64).mean().alias('value'), pl.len().alias('n')).sort('date')
    result = {'events': events.height, 'days': daily.height, 'mean': float(values.mean()) if values.len() else None,
              'median': _quantile(values, 0.5), 'positive_rate': float((values > 0).mean()) if values.len() else None,
              'p10': _quantile(values, 0.10), 'p25': _quantile(values, 0.25), 'p75': _quantile(values, 0.75),
              'p90': _quantile(values, 0.90)}
    if daily.height:
        daily_values = daily['value']
        result['daily_mean'] = float(daily_values.mean())
        std = daily_values.std()
        result['daily_std'] = float(std) if std is not None else None
        result['t_stat'] = (float(daily_values.mean()) / (float(std) / math.sqrt(daily.height))) if std not in (None, 0.0) and daily.height > 1 else None
        top = daily.sort('n', descending=True).head(5)['n'].sum()
        result['top5_day_event_share'] = float(top / events.height)
        years = events.group_by(pl.col('date').dt.year()).len()
        result['max_year_event_share'] = float(years['len'].max() / events.height)
    series_frame = daily.select('date', 'value')
    if baseline is not None:
        base_daily = baseline.filter(pl.col(outcome).is_not_null()).group_by('date').agg(pl.col(outcome).cast(pl.Float64).mean().alias('base'))
        series_frame = series_frame.join(base_daily, on='date', how='inner').with_columns((pl.col('value') - pl.col('base')).alias('value'))
        result['baseline_days'] = series_frame.height
        result['mean_daily_difference'] = float(series_frame['value'].mean()) if series_frame.height else None
    if events.height < min_events:
        result['test'] = {'status': 'unavailable', 'reason': 'insufficient_events', 'p_value': None, 'min_events': min_events}
        return result
    lookup = dict(zip(series_frame['date'].to_list(), series_frame['value'].to_list()))
    ordered = [lookup.get(day) for day in calendar]
    first = next((i for i, v in enumerate(ordered) if v is not None), None)
    last = max((i for i, v in enumerate(ordered) if v is not None), default=None)
    trimmed = ordered[first:last + 1] if first is not None else []
    result['test'] = block_sign_test([float(v) if v is not None else None for v in trimmed], PERMUTATION, seed)
    return result


# ---- registry & runs ----------------------------------------------------------------------------------
def _checked(value):
    return {**value, 'checksum': digest(value)}


def _read_checked(path, what):
    if path.is_symlink() or not path.is_file():
        raise EventStudyError('NOT_FOUND', what + ' 不存在。')
    value = json.loads(path.read_bytes())
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value.get('checksum') != digest(core):
        raise EventStudyError('CORRUPT_ARCHIVE', what + ' checksum 校验失败。')
    return core


def code_fingerprint():
    folder = Path(__file__).resolve().parent
    names = ('event_study.py', 'limit_events.py', 'limit_states.py', 'price_limit_regime.py', 'market_sentiment.py', 'sentiment_cycle.py',
             'limit_execution.py')
    files = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in names}
    files['statistics/permutation.py'] = hashlib.sha256((folder.parent / 'statistics' / 'permutation.py').read_bytes()).hexdigest()
    return {'files': files, 'digest': digest(files)}


def study_limitations(spec):
    if not spec.get('execution'):
        return list(LIMITATIONS)
    e = spec['execution']
    text = EXECUTION_LIMITATION.format(version=e['model_version'], entry=e['entry'], exit=e['exit'], scenario=e['scenario'],
                                       commission=e['commission_bps'], slippage=e['slippage_bps'], hold=e['max_hold_sessions'])
    return [text if item == SIGNAL_LIMITATION else item for item in LIMITATIONS]


class EventStudyRegistry:
    def __init__(self, output, now_fn=None, event_library=None, sentiment_library=None, state_batches=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise EventStudyError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.event_library = event_library or LimitEventLibrary(self.output)
        self.sentiment_library = sentiment_library or MarketSentimentLibrary(self.output)
        self.state_batches = state_batches or self._default_state_batches
        self.root = self.output / '_limit_research' / 'event_studies'

    def _family_dir(self, family):
        if not isinstance(family, str) or not FAMILY.fullmatch(family):
            raise EventStudyError('INVALID_ARGUMENT', 'family 必须为小写字母开头的 3–41 位 slug。')
        for path in (self.output / '_limit_research', self.root, self.root / family):
            if path.is_symlink():
                raise EventStudyError('INVALID_WORKSPACE', '事件研究路径不能是符号链接。')
        return self.root / family

    def normalize_spec(self, spec):
        if not isinstance(spec, dict) or set(spec) - SPEC_FIELDS or {'family', 'hypothesis', 'library_build_id', 'condition', 'outcome'} - set(spec):
            raise EventStudyError('INVALID_SPEC', '研究规格字段不完整或含未知字段。')
        value = {'family': spec['family'], 'hypothesis': spec['hypothesis'], 'expected_sign': spec.get('expected_sign', 'none'),
                 'library_build_id': spec['library_build_id'], 'sentiment_build_id': spec.get('sentiment_build_id'),
                 'condition': spec['condition'], 'baseline_condition': spec.get('baseline_condition'), 'outcome': spec['outcome'],
                 'start': spec.get('start'), 'end': spec.get('end'), 'split_date': spec.get('split_date'),
                 'group_by': spec.get('group_by'), 'min_events': spec.get('min_events', 30), 'execution': None}
        if spec.get('execution') is not None:
            try:
                value['execution'] = {**asdict(ExecutionSpec.from_dict(spec['execution'])), 'model_version': EXECUTION_VERSION}
            except ValueError as error:
                raise EventStudyError('INVALID_SPEC', 'execution 无效：' + str(error)) from None
        self._family_dir(value['family'])
        if not isinstance(value['hypothesis'], str) or not 5 <= len(value['hypothesis'].strip()) <= 500:
            raise EventStudyError('INVALID_SPEC', 'hypothesis 必须为 5–500 字符。')
        if value['expected_sign'] not in ('positive', 'negative', 'none'):
            raise EventStudyError('INVALID_SPEC', 'expected_sign 必须为 positive/negative/none。')
        allowed_outcomes = EXECUTION_OUTCOMES if value['execution'] else NUMERIC_OUTCOMES + BOOLEAN_OUTCOMES
        if value['outcome'] not in allowed_outcomes:
            raise EventStudyError('INVALID_SPEC', '有成交模型时 outcome 必须为 net_return/gross_return，否则必须是允许的标签列。')
        _, used = compile_condition(value['condition'])
        base_used = compile_condition(value['baseline_condition'])[1] if value['baseline_condition'] is not None else []
        if value['group_by'] is not None and value['group_by'] not in GROUPS:
            raise EventStudyError('INVALID_SPEC', 'group_by 不支持。')
        if value['execution'] and value['execution']['entry'] == 't0_limit_price':
            late = sorted({c for c in used + base_used if c not in PRE_ENTRY_COLUMNS})
            if late or (value['group_by'] is not None and value['group_by'] not in PRE_ENTRY_GROUPS):
                raise EventStudyError('LOOKAHEAD_FOR_ENTRY', '当日涨停价买入只能用盘中买入前已知的列筛选与分组：'
                                      + ', '.join(late or [value['group_by']]))
        needs_context = any(c.startswith('mkt_') for c in used + base_used) or value['group_by'] == 'mkt_phase'
        if needs_context and not value['sentiment_build_id']:
            raise EventStudyError('INVALID_SPEC', '条件或分组使用市场情绪列时必须指定 sentiment_build_id。')
        dates = {}
        for key in ('start', 'end', 'split_date'):
            if value[key] is not None:
                try:
                    dates[key] = date.fromisoformat(value[key])
                except (TypeError, ValueError):
                    raise EventStudyError('INVALID_SPEC', key + ' 必须为 YYYY-MM-DD。') from None
        if 'start' in dates and 'end' in dates and dates['start'] > dates['end']:
            raise EventStudyError('INVALID_SPEC', 'start 不能晚于 end。')
        if 'split_date' in dates and (('start' in dates and dates['split_date'] <= dates['start']) or ('end' in dates and dates['split_date'] > dates['end'])):
            raise EventStudyError('INVALID_SPEC', 'split_date 必须位于 (start, end] 内。')
        if type(value['min_events']) is not int or not 10 <= value['min_events'] <= 100000:
            raise EventStudyError('INVALID_SPEC', 'min_events 必须为 10–100000。')
        self.event_library.get(value['library_build_id'])
        if value['sentiment_build_id']:
            self.sentiment_library.get(value['sentiment_build_id'])
        return value

    def register(self, spec):
        value = self.normalize_spec(spec)
        study_id = str(uuid5(NAMESPACE_URL, 'niuniu-event-study:' + digest(value)))
        folder = self._family_dir(value['family']) / study_id
        if folder.exists():
            return {**self.get(value['family'], study_id), 'created': False}
        record = {'format': FORMAT, 'study_id': study_id, 'spec': value, 'registered_at': self.now_fn().astimezone(timezone.utc).isoformat(),
                  'engine_version': ENGINE_VERSION}
        temporary = folder.with_name('.' + study_id + '.tmp')
        temporary.mkdir(parents=True)
        (temporary / 'spec.json').write_text(encode(_checked(record)), encoding='utf-8')
        temporary.replace(folder)
        return {**record, 'created': True}

    def get(self, family, study_id):
        if not isinstance(study_id, str) or not STUDY.fullmatch(study_id):
            raise EventStudyError('INVALID_ARGUMENT', 'study_id 无效。')
        folder = self._family_dir(family) / study_id
        record = _read_checked(folder / 'spec.json', 'spec.json')
        result = _read_checked(folder / 'result.json', 'result.json') if (folder / 'result.json').exists() else None
        return {**record, 'result': result}

    def _frame(self, spec):
        events, manifest = self.event_library.read_events(spec['library_build_id'])
        calendar = None
        if spec['sentiment_build_id']:
            daily, _ = self.sentiment_library.read(spec['sentiment_build_id'])
            cycle = compute_cycle(daily).select('date', pl.col('temperature').alias('mkt_temperature'), pl.col('phase').alias('mkt_phase'))
            context = daily.rename({name: 'mkt_' + name for name in METRICS}).join(cycle, on='date', how='left')
            events = events.join(context, on='date', how='left')
            calendar = daily['date'].to_list()
        if spec['start']:
            events = events.filter(pl.col('date') >= date.fromisoformat(spec['start']))
        if spec['end']:
            events = events.filter(pl.col('date') <= date.fromisoformat(spec['end']))
        if calendar is None:
            calendar = sorted(set(events['date'].to_list()))
        events = events.with_columns(
            pl.when(pl.col('limit_up_streak') >= 5).then(pl.lit('5+')).otherwise(pl.col('limit_up_streak').cast(pl.String)).alias('streak_bucket'),
            pl.col('date').dt.year().cast(pl.String).alias('year'))
        return events, manifest, calendar

    def _default_state_batches(self, library_manifest):
        from quantlab.data.retro_daily import RetroDailyStore
        store = RetroDailyStore(self.output)
        resolved = resolve_inputs(store, [item['capture_id'] for item in library_manifest['inputs']])
        return {'last_pos': len(resolved['calendar']) - 1, 'batches': iter_state_batches(store, resolved)}

    def _attach_trades(self, frames, library_manifest, execution):
        spec = ExecutionSpec(**{k: v for k, v in execution.items() if k != 'model_version'})
        needed = pl.concat([f.select('date', 'code') for f in frames if f is not None], how='vertical').unique()
        source = self.state_batches(library_manifest)
        parts = []
        for states in source['batches']:
            subset = needed.filter(pl.col('code').is_in(states['code'].unique().implode()))
            if subset.height:
                panel = states.filter(pl.col('code').is_in(subset['code'].unique().implode()))
                try:
                    parts.append(simulate_trades(subset, panel, spec, last_pos=source['last_pos']))
                except ValueError as error:
                    raise EventStudyError('CORRUPT_INPUT', '成交模拟失败：' + str(error)) from None
        trades = pl.concat(parts, how='vertical') if parts else pl.DataFrame(schema=TRADE_SCHEMA)
        missing = needed.join(trades.select('date', 'code'), on=['date', 'code'], how='anti')
        if missing.height:
            raise EventStudyError('CORRUPT_INPUT', f'{missing.height} 个事件在状态面板中找不到对应证券。')
        return [None if f is None else f.join(trades, on=['date', 'code'], how='left') for f in frames]

    def run(self, family, study_id):
        record = self.get(family, study_id)
        if record['result'] is not None:
            return {**record, 'created': False}
        spec = record['spec']
        events, manifest, calendar = self._frame(spec)
        condition, _ = compile_condition(spec['condition'])
        selected = events.filter(condition)
        baseline = events.filter(compile_condition(spec['baseline_condition'])[0]) if spec['baseline_condition'] else None
        if spec['execution']:
            selected, baseline = self._attach_trades([selected, baseline], manifest, spec['execution'])
        outcome = spec['outcome']
        seed = int(hashlib.sha256(study_id.encode()).hexdigest()[:8], 16)
        samples = {'all': sample_stats(selected, outcome, calendar, seed, baseline=baseline, min_events=spec['min_events'])}
        if spec['split_date']:
            split = date.fromisoformat(spec['split_date'])
            before = [d for d in calendar if d < split]
            after = [d for d in calendar if d >= split]
            samples['in_sample'] = sample_stats(selected.filter(pl.col('date') < split), outcome, before, seed,
                                                baseline=None if baseline is None else baseline.filter(pl.col('date') < split), min_events=spec['min_events'])
            samples['out_of_sample'] = sample_stats(selected.filter(pl.col('date') >= split), outcome, after, seed,
                                                    baseline=None if baseline is None else baseline.filter(pl.col('date') >= split), min_events=spec['min_events'])
        primary = 'out_of_sample' if spec['split_date'] else 'all'
        by_year = selected.filter(pl.col(outcome).is_not_null()).group_by('year').agg(
            pl.len().alias('events'), pl.col(outcome).cast(pl.Float64).mean().alias('mean'),
            (pl.col(outcome).cast(pl.Float64) > 0).mean().alias('positive_rate')).sort('year').to_dicts()
        by_group = None
        if spec['group_by']:
            by_group = selected.filter(pl.col(outcome).is_not_null()).group_by(spec['group_by']).agg(
                pl.len().alias('events'), pl.col(outcome).cast(pl.Float64).mean().alias('mean'),
                (pl.col(outcome).cast(pl.Float64) > 0).mean().alias('positive_rate')).sort(spec['group_by']).to_dicts()
        fingerprint = code_fingerprint()
        result = {'format': FORMAT + '-result', 'study_id': study_id, 'computed_at': self.now_fn().astimezone(timezone.utc).isoformat(),
                  'engine_version': ENGINE_VERSION, 'code_fingerprint': fingerprint['digest'], 'library_events_sha256': manifest['events_sha256'],
                  'primary_sample': primary, 'primary_p_value': samples[primary]['test'].get('p_value'), 'samples': samples,
                  'execution': None if not spec['execution'] else {
                      name: fill_summary(frame) for name, frame in (('all', selected),) + (
                          (('in_sample', selected.filter(pl.col('date') < date.fromisoformat(spec['split_date']))),
                           ('out_of_sample', selected.filter(pl.col('date') >= date.fromisoformat(spec['split_date'])))) if spec['split_date'] else ())},
                  'by_year': by_year, 'by_group': by_group, 'permutation': {'resamples': PERMUTATION.resamples, 'block_days': PERMUTATION.block_days},
                  'limitations': study_limitations(spec)}
        path = self._family_dir(family) / study_id / 'result.json'
        temporary = path.with_name('.result.json.tmp')
        temporary.write_text(encode(_checked(result)), encoding='utf-8')
        temporary.replace(path)
        return {**record, 'result': result, 'created': True}

    def family_report(self, family):
        folder = self._family_dir(family)
        rows = []
        if folder.exists():
            for path in sorted(p for p in folder.iterdir() if p.is_dir() and STUDY.fullmatch(p.name)):
                record = self.get(family, path.name)
                result = record['result']
                primary = result['samples'][result['primary_sample']] if result else None
                rows.append({'study_id': path.name, 'registered_at': record['registered_at'], 'hypothesis': record['spec']['hypothesis'],
                             'condition': record['spec']['condition'], 'outcome': record['spec']['outcome'],
                             'status': 'completed' if result else 'registered_not_run',
                             'primary_sample': result['primary_sample'] if result else None,
                             'events': primary['events'] if primary else None, 'mean': primary['mean'] if primary else None,
                             'p_value': result['primary_p_value'] if result else None})
        adjusted = holm([row['p_value'] for row in rows]) if rows else []
        for row, p in zip(rows, adjusted):
            row['p_holm'] = p
            row['reject_at_0_05'] = None if p is None else p <= 0.05
        return {'family': family, 'registered': len(rows), 'completed': sum(r['status'] == 'completed' for r in rows),
                'studies': rows, 'note': 'Holm 以本 family 全部已登记研究为名额；未运行研究占名额但无 p 值。'}


__all__ = ['FORMAT', 'ENGINE_VERSION', 'NUMERIC_OUTCOMES', 'BOOLEAN_OUTCOMES', 'EXECUTION_OUTCOMES', 'CONDITION_COLUMNS', 'GROUPS',
           'LIMITATIONS', 'PRE_ENTRY_COLUMNS', 'PRE_ENTRY_GROUPS', 'EventStudyError', 'EventStudyRegistry', 'compile_condition',
           'sample_stats', 'study_limitations']
