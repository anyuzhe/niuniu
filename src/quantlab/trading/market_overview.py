"""Daily market overview and leading directions, built only from DATA-READY files.

Answers two everyday questions after the close:
  * 今日市场: breadth, limit-up/down, streak height, turnover, next-day premium, margin.
  * 主线方向: strongest industries (with persistence) and concentrated limit-up reasons.

Inputs are resolved through the DATA -> CODE catalog; nothing else in the data root
is scanned and nothing is written there. Figures are descriptive research facts
(research_only), not trading signals. Percentiles compare today with the same
statistic over the preceding sessions in the loaded window.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from quantlab.data.dataset_catalog import DataCatalogError, get_ready_data_source, read_data_catalog
from quantlab.trading.limit_states import annotate_limit_states
from quantlab.trading.candidates import screen_candidates

FORMAT = 'niuniu-market-overview-v1'
DEFAULT_LOOKBACK_SESSIONS = 250
TOP_INDUSTRIES = 10
FEATURE_WARMUP = 60
TOP_REASONS = 12
MIN_INDUSTRY_MEMBERS = 10
INDUSTRY_TOP_RANK = 5


class MarketOverviewError(ValueError):
    pass


@dataclass(frozen=True)
class Sources:
    qfq_daily: Path
    status: Path
    limit_pool: Path | None
    margin: Path | None
    reference: Path
    labels: dict


def _ready_path(catalog_path, dataset_id, *, optional=False):
    try:
        source = get_ready_data_source(catalog_path, dataset_id=dataset_id)
    except DataCatalogError as exc:
        if optional:
            return None
        raise MarketOverviewError(f'数据侧尚未交付 {dataset_id}：{exc}') from exc
    paths = source['technical_check']['paths']
    if not paths:
        raise MarketOverviewError(f'{dataset_id} 在数据清单中没有文件路径')
    return Path(paths[0]['path'])


def resolve_sources(catalog_path=None) -> Sources:
    """Locate inputs through the DATA catalog only (READY entries)."""
    references = [row['dataset_id'] for row in read_data_catalog(catalog_path)['entries']
                  if row['status'] == 'READY' and row['dataset_id'].startswith('reference_snapshot_baostock_')]
    if len(references) != 1:
        raise MarketOverviewError('数据清单里应恰好有一个 READY 的 Baostock 参考快照，实际 %d 个' % len(references))
    return Sources(
        qfq_daily=_ready_path(catalog_path, 'qfq_published_f24'),
        status=_ready_path(catalog_path, 'security_status_baostock_v2'),
        limit_pool=_ready_path(catalog_path, 'limit_up_pool_ths', optional=True),
        margin=_ready_path(catalog_path, 'margin_detail_exchange', optional=True),
        reference=_ready_path(catalog_path, references[0]),
        labels={'reference': references[0]},
    )


def _vendor_code(code: str) -> str | None:
    """THS/exchange six-digit code -> internal sh./sz./bj. code."""
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):
        return None
    if code[0] == '6':
        return 'sh.' + code
    if code[0] in '03':
        return 'sz.' + code
    if code[0] in '489':
        return 'bj.' + code
    return None


def _industry_name(value: str) -> str:
    return re.sub(r'^[A-Z]\d*', '', value or '').strip()


def _trading_days(reference: Path) -> list[date]:
    calendar = pl.read_parquet(reference / 'trade_calendar.parquet')
    days = calendar.filter(pl.col('is_trading_day') == '1')['calendar_date'].to_list()
    return [date.fromisoformat(d) for d in days]


def _load_panel(sources: Sources, start: date, end: date) -> pl.DataFrame:
    files = sorted(p for p in sources.qfq_daily.glob('*.parquet') if not p.name.startswith('._'))
    if not files:
        raise MarketOverviewError('前复权日线目录为空')
    bars = (pl.scan_parquet(files)
            .filter(pl.col('date').is_between(start, end))
            .select('date', 'code', 'open', 'high', 'low', 'close', 'amount', 'factor')
            .collect())
    status_files = sorted(p for p in sources.status.glob('*.parquet') if not p.name.startswith('._'))
    status = (pl.scan_parquet(status_files)
              .select(pl.col('date').str.to_date(), 'code', 'tradestatus', 'isST')
              .filter(pl.col('date').is_between(start, end))
              .collect())
    panel = bars.join(status, on=['code', 'date'], how='left')
    return panel.with_columns(
        (pl.col('tradestatus') == '1').fill_null(False).alias('tradable'),
        (pl.col('isST') == '1').fill_null(False).alias('is_st'),
    )


def _annotate(panel: pl.DataFrame, reference: Path, sessions: list[date]) -> pl.DataFrame:
    basic = pl.read_parquet(reference / 'stock_basic.parquet').filter(pl.col('type') == '1')
    index = {day: i for i, day in enumerate(sessions)}
    listing = basic.select('code', pl.col('ipoDate').str.to_date(strict=False).alias('listing_date'),
                           pl.col('code_name').alias('name'))
    panel = panel.sort('code', 'date').with_columns(
        # Returns and exchange-style previous close use the adjusted series, so ex-rights
        # days are not counted as drops. Raw price = qfq / factor.
        (pl.col('close') / pl.col('close').shift(1).over('code') - 1).alias('pct'),
        (pl.col('close').shift(1).over('code') / pl.col('factor')).alias('preclose'),
        *[(pl.col(c) / pl.col('factor')).alias('raw_' + c) for c in ('open', 'high', 'low', 'close')],
    ).join(listing, on='code', how='left')
    first_session = {d: i for d, i in index.items()}
    listing_idx = pl.Series([first_session.get(d) if d is not None else None
                             for d in panel['listing_date'].to_list()], dtype=pl.Int64)
    day_idx = pl.Series([index.get(d) for d in panel['date'].to_list()], dtype=pl.Int64)
    panel = panel.with_columns((day_idx - listing_idx + 1).alias('sessions_since_listing'))
    panel = panel.with_columns(
        pl.when(pl.col('sessions_since_listing') >= 1).then(pl.col('sessions_since_listing')).otherwise(None)
        .alias('sessions_since_listing'))
    frame = panel.select(
        'date', 'code', pl.col('raw_open').alias('open'), pl.col('raw_high').alias('high'),
        pl.col('raw_low').alias('low'), pl.col('raw_close').alias('close'), 'preclose', 'tradable', 'is_st',
        'listing_date', 'sessions_since_listing')
    states = annotate_limit_states(frame.filter(pl.col('preclose').is_not_null()))
    keep = ['date', 'code', 'limit_rule_status', 'is_limit_up_close', 'is_limit_down_close', 'is_broken_board',
            'is_one_word_limit_up',
            'limit_up_streak', 'prev_is_limit_up_close', 'prev_limit_up_streak']
    return panel.join(states.select(keep), on=['date', 'code'], how='left')


def _daily_stats(panel: pl.DataFrame) -> pl.DataFrame:
    live = panel.filter(pl.col('tradable') & pl.col('pct').is_not_null())
    return (live.group_by('date').agg(
        pl.len().alias('trading'),
        (pl.col('pct') > 1e-9).sum().alias('up'),
        (pl.col('pct') < -1e-9).sum().alias('down'),
        pl.col('pct').median().alias('median_pct'),
        pl.col('pct').mean().alias('mean_pct'),
        pl.col('is_limit_up_close').fill_null(False).sum().alias('limit_up'),
        pl.col('is_limit_down_close').fill_null(False).sum().alias('limit_down'),
        pl.col('is_broken_board').fill_null(False).sum().alias('broken'),
        pl.col('limit_up_streak').max().alias('max_streak'),
        pl.col('amount').sum().alias('amount'),
        pl.col('pct').filter(pl.col('prev_is_limit_up_close').fill_null(False)).mean().alias('prev_limit_up_avg_pct'),
        pl.col('is_limit_up_close').fill_null(False).filter(pl.col('prev_limit_up_streak').fill_null(0) >= 1)
          .mean().alias('promotion_rate'),
    ).sort('date').with_columns(
        (pl.col('up') / pl.col('trading')).alias('up_ratio'),
        (pl.col('broken') / (pl.col('limit_up') + pl.col('broken'))).alias('broken_rate'),
    ))


def _percentile(history: list, value) -> float | None:
    values = [v for v in history if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if value is None or not values:
        return None
    return round(sum(v <= value for v in values) / len(values), 4)


def _num(value, digits=4):
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    return round(float(value), digits)


def _margin(sources: Sources, day: date):
    if sources.margin is None:
        return None
    files = sorted(p for p in sources.margin.glob('*.parquet')
                   if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.parquet', p.name) and p.stem <= day.isoformat())
    if len(files) < 2:
        return None
    previous, latest = [pl.read_parquet(p, columns=['margin_balance'])['margin_balance'].sum() for p in files[-2:]]
    return {'date': files[-1].stem, 'balance': _num(latest, 0), 'change': _num(latest - previous, 0),
            'note': '交易所两融明细 T+1 发布，日期为数据所属交易日'}


def _limit_pool(sources: Sources, days: list[date]):
    if sources.limit_pool is None:
        return {}
    pools = {}
    for day in days:
        path = sources.limit_pool / f'{day.isoformat()}.parquet'
        if path.is_file():
            pools[day] = pl.read_parquet(path, columns=['code', 'name', 'reason', 'high_days', 'board_type'])
    return pools


def _reasons(pools: dict, day: date, names: dict) -> list[dict]:
    today = pools.get(day)
    if today is None or today.is_empty():
        return []
    recent = sorted(pools)[-5:]
    counts, members = {}, {}
    for row in today.iter_rows(named=True):
        for token in {t.strip() for t in (row['reason'] or '').split('+') if t.strip()}:
            counts[token] = counts.get(token, 0) + 1
            members.setdefault(token, []).append({'code': _vendor_code(row['code']) or row['code'],
                                                  'name': row['name'], 'streak': row['high_days']})
    appearance = {}
    for pool_day in recent:
        tokens = set()
        for reason in pools[pool_day]['reason'].to_list():
            tokens.update(t.strip() for t in (reason or '').split('+') if t.strip())
        for token in tokens:
            appearance[token] = appearance.get(token, 0) + 1
    ranked = sorted(counts, key=lambda t: (-counts[t], t))[:TOP_REASONS]
    return [{'reason': t, 'limit_ups': counts[t], 'days_in_recent': appearance.get(t, 0),
             'recent_days': len(recent), 'stocks': members[t][:8]} for t in ranked]


def _industries(panel: pl.DataFrame, reference: Path, sessions: list[date]) -> list[dict]:
    industry = pl.read_parquet(reference / 'industry.parquet').select(
        'code', pl.col('industry').map_elements(_industry_name, return_dtype=pl.String).alias('industry'))
    live = (panel.filter(pl.col('tradable') & pl.col('pct').is_not_null())
            .join(industry.filter(pl.col('industry') != ''), on='code', how='inner'))
    per_day = (live.group_by('date', 'industry').agg(
        pl.len().alias('members'), pl.col('pct').median().alias('median_pct'),
        pl.col('is_limit_up_close').fill_null(False).sum().alias('limit_up'),
        pl.col('amount').sum().alias('amount'))
        .filter(pl.col('members') >= MIN_INDUSTRY_MEMBERS)
        .with_columns(pl.col('median_pct').rank('ordinal', descending=True).over('date').alias('rank')))
    day = sessions[-1]
    today = per_day.filter(pl.col('date') == day).sort('rank')
    if today.is_empty():
        return []
    ranks = {(r['industry'], r['date']): r['rank'] for r in per_day.select('industry', 'date', 'rank').iter_rows(named=True)}
    five_back = sessions[-6] if len(sessions) >= 6 else sessions[0]
    closes = panel.filter(pl.col('date').is_in([five_back, day])).pivot(on='date', index='code', values='close')
    five = {}
    if five_back.isoformat() in closes.columns and day.isoformat() in closes.columns:
        change = closes.select('code', (pl.col(day.isoformat()) / pl.col(five_back.isoformat()) - 1).alias('r5'))
        five = dict(change.join(industry, on='code').group_by('industry').agg(pl.col('r5').median())
                    .iter_rows())
    total_amount = today['amount'].sum()
    result = []
    for row in today.head(TOP_INDUSTRIES).iter_rows(named=True):
        streak = 0
        for session in reversed(sessions):
            if ranks.get((row['industry'], session), 10**9) <= INDUSTRY_TOP_RANK:
                streak += 1
            else:
                break
        leaders = (live.filter((pl.col('date') == day) & (pl.col('industry') == row['industry']))
                   .sort(['is_limit_up_close', 'pct'], descending=True, nulls_last=True).head(3))
        result.append({
            'industry': row['industry'], 'members': row['members'], 'median_pct': _num(row['median_pct']),
            'return_5d_median': _num(five.get(row['industry'])), 'limit_ups': row['limit_up'],
            'amount_share': _num(row['amount'] / total_amount if total_amount else None),
            'days_in_top5': streak,
            'leaders': [{'code': r['code'], 'name': r['name'], 'pct': _num(r['pct']),
                         'limit_up': bool(r['is_limit_up_close'])} for r in leaders.iter_rows(named=True)],
        })
    return result


STOCK_COLUMNS = ['code', 'name', 'industry', 'close', 'pct', 'ret5', 'ret20', 'ret60', 'ma20_gap', 'ma60_gap',
                 'high60_gap', 'amount', 'amount_ratio', 'vol20', 'streak', 'limit_ups_10d', 'is_st', 'tradable',
                 'rank20', 'industry_rank20', 'industry_size']


def _features(panel: pl.DataFrame, reference: Path) -> pl.DataFrame:
    """Per-stock, per-session features over the whole loaded window.

    The same numbers feed the day's stock snapshot, today's candidate screens and
    their historical check, so what is shown and what is validated cannot drift apart.
    """
    industry = pl.read_parquet(reference / 'industry.parquet').select(
        'code', pl.col('industry').map_elements(_industry_name, return_dtype=pl.String).alias('industry'))
    close = pl.col('close')
    frame = panel.sort('code', 'date').with_columns(
        *[(close / close.shift(n).over('code') - 1).alias(f'ret{n}') for n in (5, 20, 60)],
        (close / close.rolling_mean(20).over('code') - 1).alias('ma20_gap'),
        (close / close.rolling_mean(60).over('code') - 1).alias('ma60_gap'),
        (close / pl.col('high').rolling_max(60).over('code') - 1).alias('high60_gap'),
        (pl.col('amount') / pl.col('amount').rolling_mean(20).shift(1).over('code')).alias('amount_ratio'),
        pl.col('pct').rolling_std(20).over('code').alias('vol20'),
        pl.col('is_limit_up_close').fill_null(False).cast(pl.Int64).rolling_sum(10, min_samples=1)
        .over('code').alias('limit_ups_10d'),
        pl.col('limit_up_streak').fill_null(0).alias('streak'),
        pl.col('raw_close').alias('close_raw'),
        # Forward outcome for validation: buy at the next session's open, sell at the close
        # five sessions after the signal. A one-word limit-up next day cannot be bought.
        (close.shift(-5).over('code') / pl.col('open').shift(-1).over('code') - 1).alias('fwd5'),
        pl.col('is_one_word_limit_up').shift(-1).over('code').fill_null(False).alias('next_one_word'),
        pl.col('tradable').shift(-1).over('code').fill_null(False).alias('next_tradable'),
    ).join(industry, on='code', how='left')
    live = pl.col('tradable') & pl.col('ret20').is_not_null()
    return frame.with_columns(
        pl.when(live).then(pl.col('ret20').rank('average').over('date') / pl.col('ret20').filter(live).count().over('date'))
        .otherwise(None).alias('rank20'),
        pl.when(live).then(pl.col('ret20').rank('average').over('date', 'industry')
                           / pl.col('ret20').count().over('date', 'industry')).otherwise(None).alias('industry_rank20'),
        pl.len().over('date', 'industry').alias('industry_size'),
    )


def _stock_snapshot(features: pl.DataFrame, day: date) -> pl.DataFrame:
    """Per-stock facts for one session, so stock pages need no full-market scan."""
    frame = features.filter(pl.col('date') == day)
    return frame.select(*[pl.col('close_raw').alias('close') if c == 'close' else pl.col(c) for c in STOCK_COLUMNS])


def _pct_text(value):
    return '—' if value is None else f'{value * 100:+.2f}%'


def _summary(today: dict, pct: dict, margin) -> list[str]:
    lines = [
        f"上涨 {today['up']} 家、下跌 {today['down']} 家，上涨占比 {today['up_ratio'] * 100:.0f}%"
        + (f"（近一年 {pct['up_ratio'] * 100:.0f}% 分位）" if pct.get('up_ratio') is not None else '') + '。',
        f"涨停 {today['limit_up']} 家、跌停 {today['limit_down']} 家，炸板 {today['broken']} 家；"
        f"最高 {today['max_streak'] or 0} 连板。",
    ]
    if today['amount_change'] is not None:
        lines.append(f"全市场成交额 {today['amount'] / 1e8:,.0f} 亿元，较前一交易日 {_pct_text(today['amount_change'])}。")
    if today['prev_limit_up_avg_pct'] is not None:
        lines.append(f"昨日涨停股今天平均 {_pct_text(today['prev_limit_up_avg_pct'])}，"
                     f"连板晋级率 {(today['promotion_rate'] or 0) * 100:.0f}%。")
    if margin:
        lines.append(f"两融余额 {margin['balance'] / 1e8:,.0f} 亿元（{margin['date']}），较前一日 {margin['change'] / 1e8:+,.1f} 亿元。")
    return lines


def build_market_overview(catalog_path=None, trading_day: str | None = None,
                          lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS, *, now=None) -> dict:
    sources = resolve_sources(catalog_path)
    calendar = _trading_days(sources.reference)
    if trading_day:
        end = date.fromisoformat(trading_day)
    else:
        beijing_today = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=8))).date()
        end = max(d for d in calendar if d <= beijing_today)
    # 60 extra sessions warm up the 60-day features used by the candidate screens.
    sessions = [d for d in calendar if d <= end][-(lookback_sessions + 25 + FEATURE_WARMUP):]
    if len(sessions) < 7:
        raise MarketOverviewError('交易日历过短，无法计算')
    panel = _load_panel(sources, sessions[0], end)
    if panel.is_empty():
        raise MarketOverviewError('所选区间没有日线数据')
    data_end = panel['date'].max()
    if data_end < end:
        if trading_day:
            raise MarketOverviewError(f'数据侧日线只到 {data_end}，还没有 {end} 的数据')
        end = data_end
        sessions = [d for d in sessions if d <= end]
    panel = _annotate(panel, sources.reference, sessions)
    features = _features(panel, sources.reference)
    stats = _daily_stats(panel).with_columns(
        (pl.col('amount') / pl.col('amount').shift(1) - 1).alias('amount_change'))
    stats = stats.filter(pl.col('date').is_in(sessions[max(20, len(sessions) - lookback_sessions - 5):]))
    if stats.is_empty() or stats['date'].max() != end:
        raise MarketOverviewError(f'{end} 没有可交易的日线')
    rows = stats.to_dicts()
    today = rows[-1]
    history = rows[:-1]
    percentile = {key: _percentile([r[key] for r in history], today[key])
                  for key in ('up_ratio', 'median_pct', 'limit_up', 'limit_down', 'max_streak', 'amount',
                              'prev_limit_up_avg_pct', 'promotion_rate', 'broken_rate')}
    margin = _margin(sources, end)
    pools = _limit_pool(sources, [d for d in sessions if d <= end][-5:])
    names = dict(panel.select('code', 'name').unique('code').iter_rows())
    ladder = (panel.filter((pl.col('date') == end) & pl.col('is_limit_up_close').fill_null(False))
              .sort(['limit_up_streak', 'pct'], descending=True).head(20))
    pool_reason = {}
    if end in pools:
        pool_reason = {(_vendor_code(r['code']) or r['code']): r['reason'] for r in pools[end].iter_rows(named=True)}
    today_clean = {k: (_num(v) if isinstance(v, float) else (v.isoformat() if isinstance(v, date) else v))
                   for k, v in today.items()}
    result = {
        'format': FORMAT,
        'trading_day': end.isoformat(),
        'built_at': (now or datetime.now(timezone.utc)).isoformat(),
        'market': today_clean,
        'percentile': percentile,
        'percentile_window_sessions': len(history),
        'summary': _summary(today_clean, percentile, margin),
        'margin': margin,
        'ladder': [{'code': r['code'], 'name': r['name'], 'streak': r['limit_up_streak'], 'pct': _num(r['pct']),
                    'reason': pool_reason.get(r['code'])} for r in ladder.iter_rows(named=True)],
        'history': [{'date': r['date'].isoformat(), 'up_ratio': _num(r['up_ratio']), 'limit_up': r['limit_up'],
                     'limit_down': r['limit_down'], 'max_streak': r['max_streak'], 'amount': _num(r['amount'], 0)}
                    for r in rows[-60:]],
        # Equal-weight average of all tradable stocks, per session: the benchmark that
        # 复盘验证 compares saved judgments against.
        'market_returns': [{'date': r['date'].isoformat(), 'mean_pct': _num(r['mean_pct'], 6)} for r in rows],
        'industries': _industries(panel, sources.reference, [d for d in sessions if d <= end]),
        '_stocks': _stock_snapshot(features, end),
        'candidates': screen_candidates(features, end, [d for d in sessions if d <= end]),
        'reasons': _reasons(pools, end, names),
        'sources': {
            'daily': 'qfq_published_f24（前复权日线，涨跌按复权计算）',
            'status': 'security_status_baostock_v2（停牌/ST）',
            'limit_pool': 'limit_up_pool_ths（涨停原因）' if sources.limit_pool else None,
            'margin': 'margin_detail_exchange（两融）' if sources.margin else None,
            'reference': sources.labels['reference'] + '（行业、证券名称、交易日历）',
        },
        'caveats': [
            '收盘后数据，非盘中实时；指数行情数据侧尚未提供，因此不显示指数。',
            '涨跌停按板块规则和前复权前收推算，未使用逐日官方涨跌停价；新股上市初期和退市整理期不计。',
            '行业用参考快照当天的证监会行业分类，不回溯历史归属。',
            '这些是描述性统计，不是买卖信号。',
        ],
    }
    return result


def overview_root(output) -> Path:
    return Path(output).resolve() / '_home' / 'market'


def save_overview(output, overview: dict) -> Path:
    root = overview_root(output)
    if root.parent.is_symlink() or root.is_symlink():
        raise MarketOverviewError('输出目录不能是符号链接')
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{overview['trading_day']}.json"
    stocks = overview.get('_stocks')
    if stocks is not None:
        # Written first: a JSON on disk always has its stock snapshot next to it.
        target = root / f"{overview['trading_day']}.stocks.parquet"
        partial = root / f"{overview['trading_day']}.stocks.tmp"
        stocks.write_parquet(partial)
        partial.replace(target)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({k: v for k, v in overview.items() if k != '_stocks'},
                                    ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)
    return path


def latest_stocks(output):
    """Per-stock snapshot of the newest overview, or None."""
    overview = latest_overview(output)
    if overview is None:
        return None, None
    path = overview_root(output) / f"{overview['trading_day']}.stocks.parquet"
    if not path.is_file():
        return overview, None
    return overview, pl.read_parquet(path)


def latest_overview(output) -> dict | None:
    root = overview_root(output)
    if not root.is_dir():
        return None
    files = sorted(p for p in root.glob('*.json') if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', p.name))
    for path in reversed(files):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get('format') == FORMAT:
            return value
    return None


__all__ = ['FORMAT', 'MarketOverviewError', 'build_market_overview', 'save_overview', 'latest_overview',
           'latest_stocks', 'resolve_sources', 'overview_root', 'STOCK_COLUMNS']
