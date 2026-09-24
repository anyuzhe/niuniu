"""今日市场 / 主线方向 pages over the daily market overview built from DATA-READY files."""
from datetime import datetime, timedelta, timezone

from PyQt6 import sip

from quantlab.trading.market_overview import (MarketOverviewError, build_market_overview, latest_overview,
                                              save_overview)
from .widgets import Card, Chart, button, kpis, label, row, table

BEIJING = timezone(timedelta(hours=8))
READY_HOUR = 18  # DATA's daily files are expected after the evening collection.


def _pct(value, signed=True):
    if value is None:
        return '—'
    return f'{value * 100:+.2f}%' if signed else f'{value * 100:.0f}%'


def _rank(value):
    return '' if value is None else f'近一年 {value * 100:.0f}% 分位'


def market_prompt(overview):
    lines = [f"请帮我解读 {overview['trading_day']} 收盘的A股市场。", *overview['summary']]
    if overview['industries']:
        lines.append('领涨行业：' + '、'.join(f"{r['industry']}（中位 {_pct(r['median_pct'])}）" for r in overview['industries'][:5]))
    if overview['reasons']:
        lines.append('涨停原因集中：' + '、'.join(f"{r['reason']} {r['limit_ups']} 家" for r in overview['reasons'][:6]))
    lines.append('请说明市场处于什么状态、哪些方向在走强、明天需要观察什么；不要给出确定的买卖指令。')
    return '\n'.join(lines)


def _tall(widget, rows):
    widget.setMinimumHeight(min(60 + 39 * max(rows, 1), 60 + 39 * 12))
    return widget


def _expected_day(now=None):
    """Latest session whose close data should exist: today after 18:00, else the previous day."""
    now = (now or datetime.now(timezone.utc)).astimezone(BEIJING)
    day = now.date() if now.hour >= READY_HOUR else now.date() - timedelta(days=1)
    return day.isoformat()


def _stale(overview):
    return overview is None or overview['trading_day'] < _expected_day()


def _start_build(window, force=False):
    if getattr(window, '_overview_building', False):
        return
    window._overview_building = True
    window._overview_error = ''
    catalog = getattr(window, 'data_catalog_path', None)

    def work():
        overview = build_market_overview(catalog)
        existing = latest_overview(window.output)
        if not force and existing and existing['trading_day'] >= overview['trading_day']:
            return existing
        save_overview(window.output, overview)
        return overview

    def done(result, error):
        window._overview_building = False
        window._overview_error = error or ''
        if window.closing:
            return
        from .app import PAGE_KEYS
        if PAGE_KEYS[window.root_current] in ('market', 'themes'):
            window.navigate_root(window.root_current)

    window.async_call(work, done, guarded=False)


def _header(window, box, overview, *, auto=True):
    """Freshness line + update button; starts a background build when the overview is stale."""
    building = getattr(window, '_overview_building', False)
    error = getattr(window, '_overview_error', '')
    if auto and not building and not error and _stale(overview) and window.data_root is not None:
        _start_build(window)
        building = True
    if overview:
        built = datetime.fromisoformat(overview['built_at']).astimezone(BEIJING).strftime('%m-%d %H:%M')
        text = f"数据截至 {overview['trading_day']} 收盘 · {built} 生成"
    else:
        text = '还没有生成过市场总览'
    if building:
        text += ' · 正在用最新数据更新（约 1–2 分钟）…'
    widgets = [label(text, 'muted', True), button('立即更新', lambda: (_start_build(window, force=True),
                                                                   window.navigate_root(window.root_current))),
               button('问 AI 解读', lambda: window.ask_ai(market_prompt(overview)) if overview else window.research_chat())]
    header = row(*widgets)
    header.layout().setStretch(0, 1)
    box.addWidget(header)
    if error:
        box.addWidget(label('更新失败：' + error.split(': ', 1)[-1], 'note', True))
    if window.data_root is None and not overview:
        box.addWidget(label('启动时没有指定数据目录，无法生成。请用启动脚本打开牛牛。', 'note', True))


def market_page(window):
    box = window.page('今日市场', '今天市场整体怎么样：涨跌家数、涨停跌停、连板高度、赚钱效应和资金。')
    overview = latest_overview(window.output)
    _header(window, box, overview)
    if not overview:
        return
    m, p = overview['market'], overview['percentile']
    summary = Card('今日概况')
    for line in overview['summary']:
        summary.add(label(line, '', True))
    box.addWidget(summary)
    box.addWidget(kpis([
        ('上涨占比', _pct(m['up_ratio'], False), _rank(p.get('up_ratio'))),
        ('涨停 / 跌停', f"{m['limit_up']} / {m['limit_down']}", _rank(p.get('limit_up'))),
        ('最高连板', str(m['max_streak'] or 0), _rank(p.get('max_streak'))),
        ('成交额', f"{m['amount'] / 1e8:,.0f} 亿", _rank(p.get('amount'))),
        ('昨日涨停今日', _pct(m['prev_limit_up_avg_pct']), _rank(p.get('prev_limit_up_avg_pct'))),
    ]))
    trend = Card('近 60 个交易日上涨占比')
    chart = Chart([h['up_ratio'] for h in overview['history'] if h['up_ratio'] is not None])
    chart.caption = f"{overview['history'][0]['date']} → {overview['history'][-1]['date']}"
    chart.setMinimumHeight(200)
    trend.add(chart)
    box.addWidget(trend)
    ladder = overview['ladder']
    card = Card('连板梯队（双击查看个股）')
    card.add(_tall(table(['股票', '代码', '连板', '今日涨幅', '涨停原因'],
                   [[r['name'], r['code'], r['streak'], _pct(r['pct']), r.get('reason') or '—'] for r in ladder],
                   lambda i: window.open_stock_report(ladder[i]['code']) if ladder else None), len(ladder)))
    box.addWidget(card)
    box.addWidget(label('说明：\n' + '\n'.join('· ' + c for c in overview['caveats']), 'muted', True))


def themes_page(window):
    box = window.page('主线方向', '今天什么方向最强：领涨行业、涨停原因集中在哪里、持续了几天。')
    overview = latest_overview(window.output)
    _header(window, box, overview)
    if not overview:
        return
    industries = overview['industries']
    card = Card('领涨行业（按行业内涨幅中位数排序）')
    card.add(_tall(table(['行业', '今日中位涨幅', '5日中位涨幅', '涨停数', '成交额占比', '连续进前五', '领涨股'],
                   [[r['industry'], _pct(r['median_pct']), _pct(r['return_5d_median']), r['limit_ups'],
                     _pct(r['amount_share'], False), f"{r['days_in_top5']} 天",
                     '、'.join(x['name'] or x['code'] for x in r['leaders'])] for r in industries]), len(industries)))
    box.addWidget(card)
    reasons = overview['reasons']
    card = Card('涨停原因集中度')
    if reasons:
        card.add(_tall(table(['原因', '今日涨停数', '近几日出现', '代表股票'],
                       [[r['reason'], r['limit_ups'], f"{r['days_in_recent']}/{r['recent_days']} 天",
                         '、'.join(f"{s['name']}（{s['streak']}）" for s in r['stocks'][:5])] for r in reasons]), len(reasons)))
    else:
        card.add(label('当天没有同花顺涨停原因数据（数据侧未提供或非交易日）。', 'muted', True))
    box.addWidget(card)
    box.addWidget(label('说明：行业用证监会行业分类；涨停原因来自同花顺涨停池，一只股票可能对应多个原因。这些是描述性统计，不是买卖信号。',
                        'muted', True))


__all__ = ['market_page', 'themes_page']
