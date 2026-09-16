"""Daily A-share limit-board sentiment metrics over retrospective full-market captures.

Each row summarizes one trading day and is available only after that day's close: it may
inform decisions for T+1 and later, never for T itself. Limit states come from the dated
research regime, so metrics are research_only and exclude the Beijing Stock Exchange.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import io
import json
import re

import polars as pl

from quantlab.data.retro_daily import RetroDailyStore
from quantlab.storage.codec import digest, encode

from .limit_events import load_inputs, prepare_states
from .limit_states import LIMIT_STATE_VERSION
from .price_limit_regime import REGIME_VERSION

FORMAT = 'market-sentiment-daily-v1'
BUILDER_VERSION = 'market-sentiment-builder-v1'
BUILD = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
SOURCES = ('price_limit_regime.py', 'limit_states.py', 'limit_events.py', 'market_sentiment.py')
METRICS = {
    'tradable_count': '当日可交易股票数',
    'suspended_count': '当日停牌行数（tradestatus=0）',
    'unmodeled_count': '可交易但涨跌幅制度未建模或无涨跌幅（新股期、临近退市等）的行数，不计入涨跌停统计',
    'violation_count': '价格越过推算涨跌停价的行数（数据或制度不一致），不计入涨跌停统计',
    'up_count': '收盘价高于交易所前收的可交易股票数',
    'down_count': '收盘价低于交易所前收的可交易股票数',
    'flat_count': '收盘价等于交易所前收的可交易股票数',
    'up_ratio': 'up_count ÷ tradable_count',
    'limit_up_count': '收盘涨停家数（含 ST）',
    'limit_up_count_non_st': '非 ST 收盘涨停家数',
    'limit_down_count': '收盘跌停家数（含 ST）',
    'limit_down_count_non_st': '非 ST 收盘跌停家数',
    'touched_limit_up_count': '最高价触及涨停价的家数',
    'broken_board_count': '触及涨停但收盘未封住（炸板）的家数',
    'broken_rate': 'broken_board_count ÷ touched_limit_up_count；无触板时为空',
    'one_word_limit_up_count': '开高低收均为涨停价的家数',
    'first_board_count': '收盘涨停且前一可交易日未收盘涨停的家数',
    'consecutive_board_count': '连板数 ≥2 的收盘涨停家数',
    'max_streak': '当日收盘涨停股中的最高连板数；无涨停为 0',
    'streak_2_count': '当日 2 连板家数', 'streak_3_count': '当日 3 连板家数', 'streak_4_count': '当日 4 连板家数',
    'streak_5plus_count': '当日 5 连板及以上家数',
    'prev_first_board_count': '前一交易日首板且今日可交易的家数（晋级率分母）',
    'advance_rate_1to2': '前一交易日首板中今日收盘涨停（成为二板）的比例',
    'prev_consecutive_count': '前一交易日连板数 ≥2 且今日可交易的家数',
    'advance_rate_2plus': '前一交易日连板数 ≥2 中今日继续收盘涨停的比例',
    'prev_limit_up_count': '前一交易日收盘涨停且今日可交易的家数',
    'prev_limit_up_avg_return': '前一交易日收盘涨停股今日收盘相对前收收益均值',
    'prev_limit_up_median_return': '同上中位数',
    'prev_limit_up_win_rate': '同上收益 >0 的比例',
    'prev_broken_count': '前一交易日炸板且今日可交易的家数',
    'prev_broken_avg_return': '前一交易日炸板股今日收益均值',
    'big_loss_count': '前一交易日收盘涨停、今日收益 ≤ -5% 的家数（“大面”）',
    'limit_up_to_down_count': '触及涨停且收盘跌停（天地板）家数',
    'limit_down_to_up_count': '触及跌停且收盘涨停（地天板）家数',
    'amount_total': '可交易股票成交额合计（元）',
    'amount_change': 'amount_total 相对前一交易日的变化率',
    'high_board_height_prev': '前一交易日最高连板数',
    'high_board_broken': '前一交易日最高连板（≥2）股今日均未收盘涨停为真；没有高度板或均停牌为空',
}
LIMITATIONS = [
    '每行在当日收盘后才可用，只能用于 T+1 及以后的决策。',
    '涨跌停由研究制度表推算，不是官方 MarketRules；资格为 research_only；不覆盖北交所。',
    '“前一交易日”指全市场交易日历的前一日；个股前一日停牌则不进入“昨日涨停/首板/炸板”类统计。',
    '收益以交易所前收为基准，未计费用和成交可行性。',
]


class MarketSentimentError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def code_fingerprint():
    folder = Path(__file__).resolve().parent
    parts = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in SOURCES}
    return {'files': parts, 'digest': digest(parts)}


def _cents(name):
    return (pl.col(name) * 100).round(0).cast(pl.Int64)


def daily_metrics(states, calendar):
    """Aggregate an annotated panel (from ``prepare_states``) into one row per trading day."""
    base = states.select('code', 'date', '_pos', 'tradable', 'is_st', 'close', 'preclose', 'amount', 'day_ret',
                         'limit_rule_status', 'limit_price_violation', 'is_limit_up_close', 'touched_limit_up',
                         'is_broken_board', 'is_one_word_limit_up', 'is_limit_down_close', 'is_limit_up_to_down',
                         'is_limit_down_to_up', 'limit_up_streak', 'is_first_board')
    valid = pl.col('tradable') & (pl.col('limit_rule_status') == 'NORMAL') & ~pl.col('limit_price_violation').fill_null(False)
    base = base.with_columns(valid.alias('_valid'))
    yesterday = base.filter(pl.col('_valid')).select(
        'code', (pl.col('_pos') + 1).alias('_pos'),
        pl.col('is_limit_up_close').alias('_y_up'), pl.col('is_broken_board').alias('_y_broken'),
        pl.col('limit_up_streak').alias('_y_streak'))
    frame = base.join(yesterday, on=['code', '_pos'], how='left')
    tradable, valid_col = pl.col('tradable'), pl.col('_valid')
    y_up = pl.col('_y_up').fill_null(False) & tradable
    y_first = y_up & (pl.col('_y_streak') == 1)
    y_consecutive = y_up & (pl.col('_y_streak') >= 2)
    y_broken = pl.col('_y_broken').fill_null(False) & tradable
    up_close = valid_col & pl.col('is_limit_up_close')
    streak = pl.col('limit_up_streak')

    def count(expr):
        return expr.fill_null(False).cast(pl.Int64).sum()

    def ratio(numerator, denominator):
        return pl.when(denominator > 0).then(numerator / denominator)

    daily = frame.group_by('date').agg(
        count(tradable).alias('tradable_count'),
        count(~tradable).alias('suspended_count'),
        count(tradable & (pl.col('limit_rule_status') != 'NORMAL')).alias('unmodeled_count'),
        count(tradable & pl.col('limit_price_violation').fill_null(False)).alias('violation_count'),
        count(tradable & (_cents('close') > _cents('preclose'))).alias('up_count'),
        count(tradable & (_cents('close') < _cents('preclose'))).alias('down_count'),
        count(tradable & (_cents('close') == _cents('preclose'))).alias('flat_count'),
        count(up_close).alias('limit_up_count'),
        count(up_close & ~pl.col('is_st')).alias('limit_up_count_non_st'),
        count(valid_col & pl.col('is_limit_down_close')).alias('limit_down_count'),
        count(valid_col & pl.col('is_limit_down_close') & ~pl.col('is_st')).alias('limit_down_count_non_st'),
        count(valid_col & pl.col('touched_limit_up')).alias('touched_limit_up_count'),
        count(valid_col & pl.col('is_broken_board')).alias('broken_board_count'),
        count(valid_col & pl.col('is_one_word_limit_up')).alias('one_word_limit_up_count'),
        count(up_close & pl.col('is_first_board')).alias('first_board_count'),
        count(up_close & (streak >= 2)).alias('consecutive_board_count'),
        pl.when(up_close).then(streak).otherwise(0).max().fill_null(0).alias('max_streak'),
        count(up_close & (streak == 2)).alias('streak_2_count'),
        count(up_close & (streak == 3)).alias('streak_3_count'),
        count(up_close & (streak == 4)).alias('streak_4_count'),
        count(up_close & (streak >= 5)).alias('streak_5plus_count'),
        count(y_first).alias('prev_first_board_count'),
        count(y_first & up_close).alias('_advanced_1to2'),
        count(y_consecutive).alias('prev_consecutive_count'),
        count(y_consecutive & up_close).alias('_advanced_2plus'),
        count(y_up).alias('prev_limit_up_count'),
        pl.col('day_ret').filter(y_up).mean().alias('prev_limit_up_avg_return'),
        pl.col('day_ret').filter(y_up).median().alias('prev_limit_up_median_return'),
        count(y_up & (pl.col('day_ret') > 0)).alias('_prev_up_wins'),
        count(y_broken).alias('prev_broken_count'),
        pl.col('day_ret').filter(y_broken).mean().alias('prev_broken_avg_return'),
        count(y_up & (pl.col('day_ret') <= -0.05)).alias('big_loss_count'),
        count(valid_col & pl.col('is_limit_up_to_down')).alias('limit_up_to_down_count'),
        count(valid_col & pl.col('is_limit_down_to_up')).alias('limit_down_to_up_count'),
        pl.col('amount').filter(tradable).sum().alias('amount_total'),
    )
    calendar_frame = pl.DataFrame({'date': calendar}, schema={'date': pl.Date})
    daily = calendar_frame.join(daily, on='date', how='left').sort('date')
    daily = daily.with_columns(
        ratio(pl.col('up_count'), pl.col('tradable_count')).alias('up_ratio'),
        ratio(pl.col('broken_board_count'), pl.col('touched_limit_up_count')).alias('broken_rate'),
        ratio(pl.col('_advanced_1to2'), pl.col('prev_first_board_count')).alias('advance_rate_1to2'),
        ratio(pl.col('_advanced_2plus'), pl.col('prev_consecutive_count')).alias('advance_rate_2plus'),
        ratio(pl.col('_prev_up_wins'), pl.col('prev_limit_up_count')).alias('prev_limit_up_win_rate'),
        (pl.col('amount_total') / pl.col('amount_total').shift(1) - 1).alias('amount_change'),
        pl.col('max_streak').shift(1).alias('high_board_height_prev'),
    )
    # High board: yesterday's highest-streak (>=2) stocks; broken when none of the tradable ones sealed today.
    heights = daily.select('date', pl.col('high_board_height_prev'))
    high = frame.join(heights, on='date', how='left').filter(
        tradable & pl.col('_y_up').fill_null(False) & (pl.col('high_board_height_prev') >= 2)
        & (pl.col('_y_streak') == pl.col('high_board_height_prev'))
    ).group_by('date').agg((~up_close.fill_null(False)).all().alias('high_board_broken'))
    daily = daily.join(high, on='date', how='left')
    return daily.select(['date'] + list(METRICS))


class MarketSentimentLibrary:
    def __init__(self, output, now_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise MarketSentimentError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.root = self.output / '_limit_research' / 'market_sentiment'

    def _folder(self, build_id):
        if not isinstance(build_id, str) or not BUILD.fullmatch(build_id):
            raise MarketSentimentError('INVALID_ARGUMENT', 'build_id 无效。')
        folder = self.root / build_id
        if folder.is_symlink() or self.root.is_symlink():
            raise MarketSentimentError('INVALID_WORKSPACE', '情绪指标路径不能是符号链接。')
        return folder

    def _compute(self, capture_ids):
        store = RetroDailyStore(self.output)
        try:
            panel, calendar, reference, inputs = load_inputs(store, list(capture_ids))
        except ValueError as error:
            raise MarketSentimentError(getattr(error, 'code', 'INVALID_INPUT'), str(error)) from None
        states = prepare_states(panel, calendar, reference)
        return daily_metrics(states, calendar), calendar, inputs

    def build(self, capture_ids):
        daily, calendar, inputs = self._compute(capture_ids)
        fingerprint = code_fingerprint()
        identity = {'builder_version': BUILDER_VERSION, 'regime_version': REGIME_VERSION,
                    'limit_state_version': LIMIT_STATE_VERSION, 'code_fingerprint': fingerprint['digest'], 'inputs': inputs}
        build_id = str(uuid5(NAMESPACE_URL, 'niuniu-market-sentiment:' + digest(identity)))
        folder = self._folder(build_id)
        if folder.exists():
            return {**self.get(build_id), 'created': False}
        stream = io.BytesIO()
        daily.write_parquet(stream, compression='zstd')
        payload = stream.getvalue()
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise MarketSentimentError('INVALID_CLOCK', '时钟必须带时区。')
        manifest = {'format': FORMAT, 'build_id': build_id, **identity, 'code_files': fingerprint['files'],
                    'rows': daily.height, 'first_date': calendar[0].isoformat(), 'last_date': calendar[-1].isoformat(),
                    'metrics': METRICS, 'daily_sha256': hashlib.sha256(payload).hexdigest(),
                    'created_at': created.astimezone(timezone.utc).isoformat(), 'available_policy': 'T日收盘后可用，仅用于T+1及以后',
                    'qualification': 'research_only', 'limitations': LIMITATIONS}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ('.tmp-' + str(uuid4()))
        temporary.mkdir()
        (temporary / 'daily.parquet').write_bytes(payload)
        (temporary / 'manifest.json').write_text(encode({**manifest, 'checksum': digest(manifest)}), encoding='utf-8')
        temporary.replace(folder)
        return {**manifest, 'created': True}

    def get(self, build_id):
        path = self._folder(build_id) / 'manifest.json'
        if path.is_symlink() or not path.is_file():
            raise MarketSentimentError('NOT_FOUND', '情绪指标 build 不存在。')
        value = json.loads(path.read_bytes())
        core = {k: v for k, v in value.items() if k != 'checksum'}
        if value.get('checksum') != digest(core) or core.get('format') != FORMAT or core.get('build_id') != build_id:
            raise MarketSentimentError('CORRUPT_ARCHIVE', 'manifest.json 校验失败。')
        return core

    def list(self):
        if not self.root.exists():
            return []
        rows = []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and BUILD.fullmatch(p.name)):
            try:
                m = self.get(folder.name)
                rows.append({'build_id': folder.name, 'first_date': m['first_date'], 'last_date': m['last_date'],
                             'rows': m['rows'], 'created_at': m['created_at']})
            except (MarketSentimentError, ValueError):
                rows.append({'build_id': folder.name, 'error': 'CORRUPT_ARCHIVE'})
        return rows

    def read(self, build_id, *, start=None, end=None):
        manifest = self.get(build_id)
        payload = (self._folder(build_id) / 'daily.parquet').read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['daily_sha256']:
            raise MarketSentimentError('CORRUPT_ARCHIVE', 'daily.parquet 哈希校验失败。')
        frame = pl.read_parquet(io.BytesIO(payload))
        if frame.height != manifest['rows']:
            raise MarketSentimentError('CORRUPT_ARCHIVE', 'daily.parquet 行数与 manifest 不一致。')
        if start is not None:
            frame = frame.filter(pl.col('date') >= (date.fromisoformat(start) if isinstance(start, str) else start))
        if end is not None:
            frame = frame.filter(pl.col('date') <= (date.fromisoformat(end) if isinstance(end, str) else end))
        return frame, manifest

    def verify(self, build_id):
        manifest = self.get(build_id)
        stored, _ = self.read(build_id)
        if code_fingerprint()['digest'] != manifest['code_fingerprint']:
            return {'build_id': build_id, 'verified': False, 'reason': 'CODE_CHANGED_REBUILD_REQUIRED'}
        daily, _, inputs = self._compute([i['capture_id'] for i in manifest['inputs']])
        if inputs != manifest['inputs']:
            return {'build_id': build_id, 'verified': False, 'reason': 'INPUTS_CHANGED'}
        same = daily.equals(stored)
        return {'build_id': build_id, 'verified': bool(same), 'reason': 'RECOMPUTED_IDENTICAL' if same else 'RECOMPUTED_DIFFERS'}


__all__ = ['FORMAT', 'BUILDER_VERSION', 'METRICS', 'LIMITATIONS', 'MarketSentimentError', 'MarketSentimentLibrary',
           'code_fingerprint', 'daily_metrics']
