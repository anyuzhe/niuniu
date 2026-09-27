"""今日市场 / 主线方向 pages over the daily market overview built from DATA-READY files."""
from datetime import datetime, timedelta, timezone

from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit

from quantlab.trading.market_overview import (MarketOverviewError, build_market_overview, latest_overview,
                                              save_overview)
from .business_view import BusinessDetails
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
    # Results from before a feature existed (e.g. no candidates yet) are rebuilt too.
    return (overview is None or overview['trading_day'] < _expected_day()
            or not {'candidates', 'market_returns'} <= set(overview))


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
        if PAGE_KEYS[window.root_current] in ('market', 'themes', 'candidates'):
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


VERDICT_STYLE = {'positive': '✔ ', 'negative': '✘ ', 'unclear': '○ ', 'insufficient': '… '}


def _bounded_candidate_json(overview, rule, caveats, *, max_chars=12000):
    from quantlab.trading.research_evidence import bounded_json, candidate_prompt_payload
    last_error = None
    for shown in (30, 15, 8, 3, 0):
        payload = candidate_prompt_payload(overview, rule, caveats, shown_limit=shown)
        try:
            text = bounded_json(payload, min(16 * 1024, max_chars))
            if len(text) <= max_chars:
                return text
        except ValueError as exc:
            last_error = exc
    raise ValueError('候选证据超过ChatRuntime草稿预算；请缩小候选或单独查看证据详情。') from last_error


def candidate_prompt(overview, rule):
    from quantlab.trading.candidates import CAVEATS
    structured = _bounded_candidate_json(overview, rule, CAVEATS)
    return ('请基于下面JSON结构化证据解读今日候选。JSON包含原规则、当前范围、样本/参数/日期/统计/费用/限制；'
            '它是research_only快速历史参考，不是正式Alpha。若shown_is_complete=false，说明展示股票不是全部候选。不要自动选择相似因子，不要自动批准研究。\n```json\n'
            + structured + '\n```')


def _formal_research_prompt(overview, rule):
    from quantlab.trading.candidates import CAVEATS
    text = _bounded_candidate_json(overview, rule, CAVEATS)
    return ('为这条精确候选规则起草正式研究提案；保留原规则与当前展示范围，列出数据、样本、费用和阻断项。'
            '只生成草稿，不提交、不批准、不替换为相似因子。展示名单不是历史完整股票池。\n```json\n' + text + '\n```')


def _candidate_action(window, overview, rule, action):
    try:
        if action=='details':return _show_candidate_evidence(window,overview,rule)
        if action=='formal':return window.research_chat(profile='research',draft=_formal_research_prompt(overview,rule))
        return window.ask_ai(candidate_prompt(overview,rule))
    except Exception as exc:
        window.status.setText('候选证据操作未完成：'+str(exc))


def _show_candidate_evidence(window, overview, rule):
    from quantlab.trading.candidates import CAVEATS
    from quantlab.trading.research_evidence import candidate_rule_evidence, bounded_json
    dialog = QDialog(window); dialog.setWindowTitle(rule['name'] + ' · 证据详情'); dialog.resize(900, 720)
    layout = QVBoxLayout(dialog)
    layout.addWidget(label('快速历史参考（research_only）：不等于正式Alpha、交易建议或自动批准。', 'note', True))
    layout.addWidget(label('规则身份按key/描述/参数等字段共同识别；仅名称相同不可认定同一规则。', 'muted', True))
    details = BusinessDetails(candidate_rule_evidence(rule, trading_day=overview.get('trading_day'),
        sources=overview.get('sources'), caveats=CAVEATS))
    text = QPlainTextEdit(); text.setReadOnly(True)
    text.setPlainText(bounded_json(candidate_rule_evidence(rule, trading_day=overview.get('trading_day'),
        sources=overview.get('sources'), caveats=CAVEATS), 64 * 1024))
    layout.addWidget(details, 2); layout.addWidget(text, 1)
    window.show_dialog(dialog)


def candidates_page(window):
    box = window.page('今日候选', '几条固定选股规则今天选出了哪些股票；每条规则都附上它过去一年的实际表现。')
    overview = latest_overview(window.output)
    _header(window, box, overview)
    if not overview:
        return
    rules = overview.get('candidates')
    if not rules:
        box.addWidget(label('当前候选为0或旧结果没有候选列表；仍可使用“因子证据发现”查看历史研究归档，或打开研究助手起草新的人工审查草稿。', 'note', True))
        box.addWidget(row(button('查看历史因子证据', lambda: window.show_dialog(__import__('quantlab.desktop.factor_evidence', fromlist=['FactorEvidenceDialog']).FactorEvidenceDialog(window))),
                          button('正式研究草稿', lambda: window.research_chat(profile='research', draft='请基于当前市场页面起草一个正式研究提案草稿；只生成草稿，不提交、不批准。'), True)))
        return
    from quantlab.trading.candidates import CAVEATS
    for rule in rules:
        v = rule['validation']
        card = Card(f"{rule['name']} · 今日 {rule['count']} 只")
        card.add(label(rule['description'], 'muted', True))
        meanings={'positive':'探索性收益差为正','negative':'探索性收益差为负','insufficient':'样本不足','unclear':'未显示明确差异'}
        description=meanings.get(v.get('verdict'),'未知')
        verdict = label('快速历史参考：'+description+'；有效日期数 '+str(v.get('samples','未知'))+
                        '。不是正式样本外或可交易Alpha认证；费用、旧版本叙述与限制见证据详情。', 'note', True)
        card.add(verdict)
        stocks = rule['stocks']
        if stocks:
            grid = table(['股票', '代码', '行业', '今日', '近20日', '入选理由'],
                         [[r['name'], r['code'], r['industry'] or '—', _pct(r['pct']), _pct(r['ret20']), r['reason']]
                          for r in stocks], lambda i, s=stocks: window.open_stock_report(s[i]['code']))
            card.add(_tall(grid, min(len(stocks), 8)))
            more = f"（只列前 {len(stocks)} 只）" if rule['count'] > len(stocks) else ''
            card.add(row(label('双击打开个股报告' + more, 'muted'),
                         button('证据详情', lambda r=rule: _candidate_action(window,overview,r,'details')),
                         button('进入正式研究', lambda r=rule: _candidate_action(window,overview,r,'formal'), True),
                         button('问 AI 看这批股票', lambda r=rule: _candidate_action(window,overview,r,'daily'))))
        else:
            card.add(label('今天没有股票符合这条规则。', 'muted'))
            card.add(row(button('证据详情',lambda r=rule:_candidate_action(window,overview,r,'details')),
                         button('进入正式研究',lambda r=rule:_candidate_action(window,overview,r,'formal'))))
        box.addWidget(card)
    box.addWidget(label('验证方法与局限：\n' + '\n'.join('· ' + c for c in CAVEATS), 'muted', True))


__all__ = ['market_page', 'themes_page', 'candidates_page']
