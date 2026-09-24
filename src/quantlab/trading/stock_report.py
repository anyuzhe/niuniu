"""One-page stock report for everyday use, built from DATA-READY data.

Local part (instant): the per-stock snapshot saved with the daily market overview,
the stock's own adjusted daily bars, and DATA files for earnings forecasts,
upcoming lock-up expiries and shareholder trades.
Online part (optional): recent announcements and broker reports through DATA's
ResearchDataProvider, only when the catalog lists those APIs as READY.

Everything here is descriptive. "需要留意" items are plain facts that often matter
(ST, sharp drawdown, unlock soon, shareholder selling...), not trading signals.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from quantlab.data.dataset_catalog import DataCatalogError, get_ready_data_source
from quantlab.trading.market_overview import latest_stocks

CODE = re.compile(r'^(sh|sz|bj)\.\d{6}$')
KLINE_SESSIONS = 120
UNLOCK_DAYS = 30
HOLDER_TRADE_DAYS = 30


class StockReportError(ValueError):
    pass


def normalize_code(text: str) -> str | None:
    """Accept sh.600000 / 600000 / 600000.SH / SH600000."""
    value = (text or '').strip().lower()
    if CODE.match(value):
        return value
    digits = re.sub(r'\D', '', value)
    if len(digits) != 6:
        return None
    prefix = 'sh' if digits[0] == '6' else 'sz' if digits[0] in '03' else 'bj' if digits[0] in '489' else None
    return f'{prefix}.{digits}' if prefix else None


def resolve_stock(stocks: pl.DataFrame, text: str) -> str | None:
    """Code or exact/unique partial name -> code."""
    code = normalize_code(text)
    if code:
        return code
    name = (text or '').strip()
    if not name or stocks is None:
        return None
    exact = stocks.filter(pl.col('name') == name)
    if exact.height == 1:
        return exact['code'][0]
    partial = stocks.filter(pl.col('name').str.contains(name, literal=True))
    return partial['code'][0] if partial.height == 1 else None


def _optional_path(catalog_path, dataset_id):
    try:
        source = get_ready_data_source(catalog_path, dataset_id=dataset_id)
    except DataCatalogError:
        return None
    paths = source['technical_check']['paths']
    return Path(paths[0]['path']) if paths else None


def _partitions(folder: Path | None, start: date, end: date):
    if folder is None or not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob('*.parquet'))
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.stem) and start.isoformat() <= p.stem <= end.isoformat()]


def _events(catalog_path, code: str, day: date) -> dict:
    digits = code[3:]
    events = {'earnings': [], 'unlocks': [], 'holder_trades': []}
    folder = _optional_path(catalog_path, 'earnings_forecast_em')
    files = _partitions(folder, day - timedelta(days=30), day)
    if files:
        frame = pl.read_parquet(files[-1]).filter(pl.col('code') == digits)
        for row in frame.sort('notice_date', descending=True).head(4).iter_rows(named=True):
            events['earnings'].append({k: row.get(k) for k in (
                'notice_date', 'report_date', 'indicator', 'forecast_type', 'change_pct_lower', 'change_pct_upper')})
    folder = _optional_path(catalog_path, 'lockup_expiry_em')
    for path in _partitions(folder, day, day + timedelta(days=UNLOCK_DAYS)):
        frame = pl.read_parquet(path).filter(pl.col('SECURITY_CODE') == digits)
        for row in frame.iter_rows(named=True):
            events['unlocks'].append({'date': path.stem, 'type': row.get('FREE_SHARES_TYPE')})
    folder = _optional_path(catalog_path, 'holder_trades_em')
    for path in reversed(_partitions(folder, day - timedelta(days=HOLDER_TRADE_DAYS), day)):
        frame = pl.read_parquet(path).filter(pl.col('code') == digits)
        for row in frame.iter_rows(named=True):
            events['holder_trades'].append({k: row.get(k) for k in (
                'notice_date', 'holder', 'direction', 'change_shares_10k', 'channel')})
    return events


def _kline(catalog_path, code: str, day: date) -> list[dict]:
    folder = _optional_path(catalog_path, 'qfq_published_f24')
    if folder is None:
        return []
    path = folder / f"{code.replace('.', '_')}.parquet"
    if not path.is_file():
        return []
    bars = (pl.read_parquet(path, columns=['date', 'open', 'high', 'low', 'close'])
            .filter(pl.col('date') <= day).sort('date').tail(KLINE_SESSIONS))
    return [{'date': r['date'].isoformat(), 'open': r['open'], 'high': r['high'], 'low': r['low'],
             'close': r['close'], 'available_at': r['date'].isoformat() + 'T15:00:00+08:00'}
            for r in bars.iter_rows(named=True)]


def _p(value):
    return '—' if value is None else f'{value * 100:+.1f}%'


def _flags(row: dict, events: dict) -> list[str]:
    flags = []
    if row.get('is_st'):
        flags.append('风险警示（ST）股票，涨跌幅和交易规则与普通股票不同。')
    if not row.get('tradable'):
        flags.append('今天停牌。')
    if (row.get('high60_gap') or 0) <= -0.25:
        flags.append(f"比近60日最高点低 {_p(row['high60_gap'])}，处于明显回撤中。")
    if row.get('ma20_gap') is not None and row['ma20_gap'] < 0 and (row.get('ma60_gap') or 0) < 0:
        flags.append('收盘价在20日和60日均线下方。')
    if (row.get('amount_ratio') or 0) >= 2.5:
        flags.append(f"成交额是近20日均值的 {row['amount_ratio']:.1f} 倍，明显放量。")
    if (row.get('streak') or 0) >= 3:
        flags.append(f"已经 {row['streak']} 连板，高位波动通常更大。")
    for item in events['unlocks']:
        flags.append(f"{item['date']} 有限售股解禁（{item['type'] or '类型未注明'}）。")
    sells = [t for t in events['holder_trades'] if t.get('direction') == '减持']
    if sells:
        flags.append(f"近{HOLDER_TRADE_DAYS}天有 {len(sells)} 条股东减持公告。")
    for item in events['earnings']:
        if item.get('forecast_type') in ('预减', '首亏', '续亏', '增亏', '略减'):
            flags.append(f"{item['report_date']} 业绩预告：{item['indicator']}{item['forecast_type']}。")
            break
    return flags


def _summary(row: dict) -> str:
    parts = [f"{row['name']}（{row['code']}）收盘 {row['close']:.2f} 元，今日 {_p(row.get('pct'))}"]
    parts.append(f"近5日 {_p(row.get('ret5'))}、近20日 {_p(row.get('ret20'))}、近60日 {_p(row.get('ret60'))}")
    if row.get('rank20') is not None:
        parts.append(f"近20日涨幅强于全市场 {row['rank20'] * 100:.0f}% 的股票")
    if row.get('industry') and row.get('industry_rank20') is not None:
        parts.append(f"在“{row['industry']}”{row['industry_size']} 只股票中强于 {row['industry_rank20'] * 100:.0f}%")
    return '；'.join(parts) + '。'


def build_stock_report(output, query: str, catalog_path=None) -> dict:
    overview, stocks = latest_stocks(output)
    if overview is None or stocks is None:
        raise StockReportError('还没有今日市场数据，请先打开“今日市场”生成一次。')
    code = resolve_stock(stocks, query)
    if code is None:
        raise StockReportError(f'找不到“{query}”，请输入6位代码或完整股票名称。')
    match = stocks.filter(pl.col('code') == code)
    if match.is_empty():
        raise StockReportError(f'{code} 不在 {overview["trading_day"]} 的在市A股数据里。')
    row = match.row(0, named=True)
    day = date.fromisoformat(overview['trading_day'])
    events = _events(catalog_path, code, day)
    peers = (stocks.filter((pl.col('industry') == row['industry']) & pl.col('ret20').is_not_null()
                           & (pl.col('code') != code))
             .sort('ret20', descending=True).head(5)) if row.get('industry') else stocks.head(0)
    return {
        'format': 'niuniu-stock-report-v1',
        'code': code, 'name': row['name'], 'trading_day': overview['trading_day'],
        'facts': row,
        'summary': _summary(row),
        'flags': _flags(row, events),
        'events': events,
        'peers': [{'code': r['code'], 'name': r['name'], 'ret20': r['ret20'], 'pct': r['pct']}
                  for r in peers.iter_rows(named=True)],
        'kline': _kline(catalog_path, code, day),
        'matched_rules': [{'name': r['name'], 'verdict': r['validation']['verdict'], 'text': r['validation'].get('text')}
                          for r in overview.get('candidates', []) if any(x['code'] == code for x in r['stocks'])],
        'caveats': ['数据截至 ' + overview['trading_day'] + ' 收盘，涨跌按前复权计算。',
                    '“需要留意”是客观事实提示，不是买卖建议。'],
    }


def online_context(code: str, catalog_path=None, provider=None) -> dict:
    """Announcements and broker reports via DATA's provider; each section fails independently."""
    sections = {}
    for name, call in (('announcements', lambda p: p.stock_announcements(code, limit=8)),
                       ('research_reports', lambda p: p.stock_research_reports(code, limit=6))):
        dataset = 'stock_announcements' if name == 'announcements' else 'stock_research_reports'
        try:
            get_ready_data_source(catalog_path, dataset_id=dataset)
            if provider is None:
                from quantlab.data.research_provider import ResearchDataProvider
                provider = ResearchDataProvider.from_env()
            sections[name] = {'rows': [dict(r) for r in call(provider).rows], 'error': None}
        except DataCatalogError:
            sections[name] = {'rows': [], 'error': '数据侧尚未开放这个接口'}
        except Exception as exc:
            kind = type(exc).__name__
            reason = ('缺少接口密钥' if kind == 'ProviderNotConfigured' else
                      '网络或数据源暂时不可用' if kind == 'DataProviderError' else '查询失败')
            sections[name] = {'rows': [], 'error': f'{reason}（{str(exc)[:120]}）'}
    return sections


def report_prompt(report: dict) -> str:
    """Plain-text context handed to the AI assistant when the user clicks 问 AI."""
    f = report['facts']
    lines = [f"请帮我分析 {report['name']}（{report['code']}），数据截至 {report['trading_day']} 收盘。",
             report['summary'],
             f"相对20日均线 {_p(f.get('ma20_gap'))}，相对60日均线 {_p(f.get('ma60_gap'))}，距60日高点 {_p(f.get('high60_gap'))}；"
             f"成交额/20日均值 {f.get('amount_ratio') or 0:.2f}；连板 {f.get('streak') or 0}。"]
    if report['flags']:
        lines.append('需要留意：' + ' '.join(report['flags']))
    lines.append('请按“结论、依据、需要观察的条件、什么情况说明判断错了、强/中/弱三种情景”回答，'
                 '可以查询公告、研报和财报；不要给出确定的买卖指令。')
    return '\n'.join(lines)


__all__ = ['StockReportError', 'normalize_code', 'resolve_stock', 'build_stock_report', 'online_context',
           'report_prompt']
