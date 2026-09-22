"""Read-only daily coverage audit against an explicitly supplied calendar."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import polars as pl

ZONE = 'Asia/Shanghai'
VERSION = 'explicit-calendar-daily-coverage-v1'


def _calendar_days(calendar):
    required = {'calendar_date', 'is_trading_day'}
    if not required <= set(calendar.columns) or not 1 <= calendar.height <= 40000:
        raise ValueError('缺少有效交易日历或超出日历预算')
    days = {}
    for row in calendar.select(sorted(required)).iter_rows(named=True):
        value = row['calendar_date']
        if type(value) is date:
            day = value
        elif isinstance(value, str):
            day = date.fromisoformat(value)
            if day.isoformat() != value:
                raise ValueError('交易日历日期必须为YYYY-MM-DD')
        else:
            raise ValueError('交易日历日期为空或类型不明')
        flag = row['is_trading_day']
        if day in days or flag not in ('0', '1'):
            raise ValueError('交易日历重复或交易状态未知')
        days[day] = flag
    return days


def calendar_window(calendar, start, end):
    """Describe exact calendar coverage; unknown days never become holidays."""
    from quantlab.storage.codec import digest
    if type(start) is not date or type(end) is not date or not 0 <= (end-start).days < 4000:
        raise ValueError('覆盖检查须指定1–4000自然日')
    days = _calendar_days(calendar)
    expected = [start+timedelta(days=i) for i in range((end-start).days+1)]
    missing = [d for d in expected if d not in days]
    return {'min_date': str(min(days)), 'max_date': str(max(days)), 'calendar_rows': len(days),
            'calendar_content_hash': digest([(str(d), days[d]) for d in sorted(days)]),
            'content_hash_semantics': 'sorted_calendar_date_and_trading_flag_pairs_v1',
            'range_covered': not missing, 'missing_calendar_dates': [str(d) for d in missing],
            'trading_dates': None if missing else [str(d) for d in expected if days[d] == '1']}


def calendar_sessions(calendar, start, end):
    value = calendar_window(calendar, start, end)
    if not value['range_covered']:
        raise ValueError('交易日历缺日，不推断休市：'+', '.join(value['missing_calendar_dates'][:5]))
    return tuple(date.fromisoformat(d) for d in value['trading_dates'])


def audit_daily_coverage(bars, calendar, symbols, start, end, as_of):
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError('覆盖检查时点必须带时区')
    if not isinstance(symbols, (tuple, list)) or not 1 <= len(symbols) <= 100:
        raise ValueError('覆盖检查限1–100个明确证券')
    if any(not isinstance(s, str) or not s for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError('证券代码为空或重复')
    required = {'symbol', 'datetime', 'available_at', 'timeframe'}
    if not required <= set(bars.columns) or bars.height > 250000:
        raise ValueError('日线字段缺失或超过250000行预算')
    if any(bars[c].null_count() for c in required):
        raise ValueError('日线键或可用时点为空')
    for column in ('datetime', 'available_at'):
        dtype = bars.schema[column]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
            raise ValueError('日线日期及可用时点必须带时区')
    if any(v != '1d' for v in bars['timeframe'].unique()):
        raise ValueError('此覆盖检查仅接受真实日线')
    if bars.filter(pl.col('available_at').dt.convert_time_zone('UTC') < pl.col('datetime').dt.convert_time_zone('UTC')).height:
        raise ValueError('日线可用时点早于行情时点')
    sessions = calendar_sessions(calendar, start, end)
    expected = set(sessions)
    frame = bars.with_columns(pl.col('datetime').dt.convert_time_zone(ZONE).alias('_local'))
    frame = frame.with_columns(pl.col('_local').dt.date().alias('_session'))
    cutoff = as_of.astimezone(ZoneInfo(bars.schema['available_at'].time_zone))
    known = frame.filter(pl.col('available_at') <= cutoff)
    rows = []
    for symbol in symbols:
        source = frame.filter(pl.col('symbol') == symbol)
        available = known.filter(pl.col('symbol') == symbol)
        days = set(available['_session'].to_list())
        missing = sorted(expected-days)
        counts = source.group_by('_session').len()
        duplicate_days = sorted(counts.filter(pl.col('len') > 1)['_session'].to_list())
        extra = sorted(set(source['_session'].to_list())-expected)
        off_close = source.filter((pl.col('_local').dt.hour() != 15) |
            (pl.col('_local').dt.minute() != 0) | (pl.col('_local').dt.second() != 0) |
            (pl.col('_local').dt.microsecond() != 0)).height
        rows.append({'symbol':symbol, 'expected_sessions':len(sessions),
            'available_sessions':len(days & expected), 'missing_sessions':len(missing),
            'missing_examples':[str(d) for d in missing[:10]],
            'duplicate_sessions':len(duplicate_days), 'duplicate_examples':[str(d) for d in duplicate_days[:10]],
            'unexpected_sessions':len(extra), 'unexpected_examples':[str(d) for d in extra[:10]],
            'off_close_rows':off_close, 'not_yet_available_rows':source.height-available.height})
    unknown = sorted(set(frame['symbol'].to_list())-set(symbols))
    blocked = not sessions or bool(unknown) or any(any(r[k] for k in (
        'missing_sessions', 'duplicate_sessions', 'unexpected_sessions', 'off_close_rows',
        'not_yet_available_rows')) for r in rows)
    return {'method':VERSION, 'status':'incomplete' if blocked else 'complete',
        'start':str(start), 'end':str(end), 'as_of':as_of.isoformat(),
        'expected_symbol_sessions':len(sessions)*len(symbols), 'actual_rows':bars.height,
        'unexpected_symbols':unknown[:10], 'unexpected_symbol_count':len(unknown), 'symbols':rows,
        'limitations':['按所选已归档日历逐日核对，不认证交易所官方规则或严格PIT。',
            '缺少日线不推断为停牌或未上市；零成交量停牌行仍须实际存在。',
            '不补零、不前填；此检查不改变因子计算或标签口径。']}
