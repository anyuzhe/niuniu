"""个股报告 / 我的股票 pages."""
from PyQt6 import sip
from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit

from quantlab.trading.judgments import HORIZONS, SOURCES, STANCES, load_judgments, save_judgment
from quantlab.trading.market_overview import latest_stocks
from quantlab.trading.my_stocks import add_stock, inspect_my_stocks, my_stocks_prompt, remove_stock
from quantlab.trading.stock_report import (StockReportError, build_stock_report, online_context, report_prompt,
                                           resolve_stock)
from .widgets import Card, Chart, button, kpis, label, row, table


def _p(value, signed=True):
    if value is None:
        return '—'
    return f'{value * 100:+.2f}%' if signed else f'{value * 100:.0f}%'


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def stock_page(window):
    box = window.page('个股报告', '输入代码或名称，查看走势、相对强弱、需要留意的事项、公告和研报，并可交给 AI 分析。')
    query = QLineEdit()
    query.setPlaceholderText('6位代码或股票名称，例如 600519 或 贵州茅台')
    query.setAccessibleName('个股代码或名称')
    status = label('', 'muted', True)
    holder = Card()
    holder.setVisible(False)

    def show(report):
        if not _alive(holder):
            return
        holder.setVisible(True)
        f = report['facts']
        head = row(label(f"{report['name']}  {report['code']}  ·  {f.get('industry') or '行业未知'}", 'panelTitle'),
                   button('加入我的股票', lambda: _add(window, report['code'], status)),
                   button('问 AI 分析', lambda: window.ask_ai(report_prompt(report)), True),
                   button('历史判断与研究记录', lambda: window.open_stock_dossier(report['code'])))
        head.layout().setStretch(0, 1)
        holder.add(head)
        holder.add(label(report['summary'], '', True))
        holder.add(kpis([
            ('收盘 / 今日', f"{f['close']:.2f}", _p(f.get('pct'))),
            ('近20日', _p(f.get('ret20')), '强于全市场 ' + _p(f.get('rank20'), False) if f.get('rank20') is not None else ''),
            ('行业内', _p(f.get('industry_rank20'), False) if f.get('industry_rank20') is not None else '—',
             f"近20日强于同行比例（{f.get('industry_size') or 0} 只）"),
            ('距60日高点', _p(f.get('high60_gap')), f"20日线 {_p(f.get('ma20_gap'))}"),
            ('成交额/20日均', f"{f['amount_ratio']:.2f} 倍" if f.get('amount_ratio') else '—', f"连板 {f.get('streak') or 0}"),
        ]))
        if report['kline']:
            chart = Chart(candles=report['kline'])
            chart.caption = f"日K（前复权）{report['kline'][0]['date']} → {report['kline'][-1]['date']}"
            chart.setMinimumHeight(280)
            holder.add(chart)
        for rule in report.get('matched_rules', []):
            holder.add(label(f"今日入选“{rule['name']}”规则。历史验证：{rule['text']}", 'note', True))
        flags = Card('需要留意')
        for item in report['flags'] or ['暂无特别需要留意的事项。']:
            flags.add(label('· ' + item, '', True))
        holder.add(flags)
        holder.add(_judgment_card(window, report))
        events = report['events']
        if events['earnings']:
            holder.add(label('业绩预告：' + '；'.join(
                f"{e['report_date']} {e['indicator']} {e['forecast_type']}" for e in events['earnings']), 'muted', True))
        if events['holder_trades']:
            holder.add(label('近30天股东增减持：' + '；'.join(
                f"{t['notice_date']} {t['holder']} {t['direction']} {abs(t['change_shares_10k'] or 0):.0f}万股"
                for t in events['holder_trades'][:5]), 'muted', True))
        peers = report['peers']
        if peers:
            card = Card('同行业近20日最强（双击查看）')
            card.add(table(['股票', '代码', '近20日', '今日'], [[r['name'], r['code'], _p(r['ret20']), _p(r['pct'])] for r in peers],
                           lambda i: window.open_stock_report(peers[i]['code'])))
            holder.add(card)
        online = Card('最新公告与研报')
        online_status = label('正在查询…', 'muted', True)
        online.add(online_status)
        holder.add(online)
        holder.add(label('说明：' + ' '.join(report['caveats']), 'muted', True))

        def got(result, error):
            if not _alive(online_status):
                return
            if error:
                online_status.setText('查询失败：' + error)
                return
            online_status.setText('')
            ann = result['announcements']
            if ann['rows']:
                online.add(table(['日期', '公告'], [[r.get('publish_date'), r.get('title')] for r in ann['rows']]))
            else:
                online.add(label('公告：' + (ann['error'] or '没有查到'), 'muted', True))
            rep = result['research_reports']
            if rep['rows']:
                online.add(table(['日期', '机构', '评级', '标题'], [[r.get('publish_date'), r.get('org'), r.get('rating'), r.get('title')]
                                                                for r in rep['rows']]))
            else:
                online.add(label('研报：' + (rep['error'] or '没有查到'), 'muted', True))

        window.async_call(lambda: online_context(report['code'], getattr(window, 'data_catalog_path', None)), got)

    def load(text=None):
        text = (text or query.text()).strip()
        if not text:
            return
        status.setText('正在生成报告…')

        def done(result, error):
            if not _alive(status):
                return
            if error:
                status.setText(error.split(': ', 1)[-1])
                return
            status.setText('')
            show(result)

        window.async_call(lambda: build_stock_report(window.output, text, getattr(window, 'data_catalog_path', None)), done)

    query.returnPressed.connect(load)
    box.addWidget(row(query, button('查看', load, True)))
    box.addWidget(status)
    box.addWidget(holder)
    pending = getattr(window, 'pending_stock', None)
    if pending:
        window.pending_stock = None
        query.setText(pending)
        load(pending)


def _price_box(suffix):
    box = QDoubleSpinBox()
    box.setRange(0, 100000)
    box.setDecimals(2)
    box.setSpecialValueText('不设')
    box.setSuffix(suffix)
    box.setToolTip('按实际收盘价核对；0 表示不设')
    return box


def _judgment_card(window, report):
    """保存判断: recorded against this report's close, checked later on 复盘验证."""
    f = report['facts']
    card = Card('保存判断（之后自动核对）')
    card.add(label(f"从 {report['trading_day']} 收盘价 {f['close']:.2f} 元算起；失效价、目标价按每天的实际收盘价核对，"
                   '先到哪个就在哪天结束；否则到期按涨跌判断对错。结果在“复盘验证”里。', 'muted', True))
    stance = QComboBox()
    for key, text in STANCES.items():
        stance.addItem(text, key)
    horizon = QComboBox()
    for days in HORIZONS:
        horizon.addItem(f'{days} 个交易日', days)
    horizon.setCurrentIndex(HORIZONS.index(5))
    source = QComboBox()
    for key, text in SOURCES.items():
        source.addItem(text, key)
    stop, target = _price_box(' 元'), _price_box(' 元')
    for box, name in ((stance, '判断'), (horizon, '核对周期'), (source, '来源'), (stop, '失效价'), (target, '目标价')):
        box.setAccessibleName(name)
    reason = QLineEdit()
    reason.setPlaceholderText('理由（可不填），例如：放量突破平台，行业走强')
    reason.setAccessibleName('判断理由')
    status = label('', 'muted', True)
    previous = [j for j in load_judgments(window.output) if j['code'] == report['code']]
    if previous:
        last = previous[-1]
        status.setText(f"这只股票已保存 {len(previous)} 条判断，最近一次：{last['made_on']} {STANCES[last['stance']]}"
                       f"（{last['horizon']} 日）。")

    def save():
        try:
            record = save_judgment(window.output, code=report['code'], name=report['name'],
                                   made_on=report['trading_day'], close=f['close'], stance=stance.currentData(),
                                   horizon=horizon.currentData(), source=source.currentData(),
                                   stop=stop.value() or None, target=target.value() or None, reason=reason.text())
        except (ValueError, OSError) as exc:
            status.setText('没有保存：' + str(exc))
            return
        reason.clear()
        status.setText(f"已保存：{STANCES[record['stance']]}，{record['horizon']} 个交易日后核对。在“复盘验证”查看。")

    card.add(row(stance, horizon, source, label('失效价', 'muted'), stop, label('目标价', 'muted'), target))
    card.add(row(reason, button('保存判断', save, True)))
    card.add(status)
    card.judgment_controls = {'stance': stance, 'horizon': horizon, 'source': source, 'stop': stop, 'target': target,
                              'reason': reason, 'status': status, 'save': save}
    return card


def _add(window, text, status, weight=None, cost=None):
    try:
        _, stocks = latest_stocks(window.output)
        code = resolve_stock(stocks, text)
        if code is None:
            raise ValueError(f'找不到“{text}”')
        add_stock(window.output, code, weight=weight, cost=cost)
    except (ValueError, OSError) as exc:
        status.setText('没有加入：' + str(exc))
        return False
    status.setText(f'已加入我的股票：{code}')
    return True


def mine_page(window):
    box = window.page('我的股票', '我的自选和持仓每天怎么样：逐只状态、需要留意的事项，以及整体集中度。')
    query = QLineEdit()
    query.setPlaceholderText('代码或名称')
    query.setAccessibleName('添加股票')
    weight = QDoubleSpinBox()
    weight.setRange(0, 100)
    weight.setSuffix(' % 仓位（可不填）')
    cost = QDoubleSpinBox()
    cost.setRange(0, 100000)
    cost.setDecimals(3)
    cost.setSuffix(' 成本（可不填）')
    status = label('', 'muted', True)

    def add():
        if _add(window, query.text().strip(), status, weight.value() / 100 or None, cost.value() or None):
            window.navigate_page('mine')

    box.addWidget(row(query, weight, cost, button('添加', add, True)))
    box.addWidget(status)
    result_card = Card()
    box.addWidget(result_card)

    def done(result, error):
        if not _alive(result_card):
            return
        if error:
            result_card.add(label(error.split(': ', 1)[-1], 'note', True))
            return
        rows = result['rows']
        if not rows:
            result_card.add(label('还没有添加股票。在上面输入代码或名称添加；仓位和成本可以不填。', 'muted', True))
            return
        head = row(label(f"数据截至 {result['trading_day']} 收盘 · {len(rows)} 只", 'muted'),
                   button('问 AI 巡检', lambda: window.ask_ai(my_stocks_prompt(result)), True))
        head.layout().setStretch(0, 1)
        result_card.add(head)
        for note in result['notes']:
            result_card.add(label(note, '', True))
        grid = table(['股票', '代码', '行业', '收盘', '今日', '近20日', '强于全市场', '仓位', '盈亏', '需要留意'],
                     [[r.get('name') or '—', r['code'], r.get('industry') or '—',
                       f"{r['close']:.2f}" if r.get('close') else '—', _p(r.get('pct')), _p(r.get('ret20')),
                       _p(r.get('rank20'), False) if r.get('rank20') is not None else '—',
                       _p(r.get('weight'), False) if r.get('weight') else '—', _p(r.get('pnl')),
                       f"{len(r['flags'])} 项：{r['flags'][0]}" if r['flags'] else '—'] for r in rows],
                     lambda i: window.open_stock_report(rows[i]['code']))
        grid.setMinimumHeight(min(60 + 39 * len(rows), 520))
        result_card.add(grid)

        def remove():
            selected = grid.currentRow()
            if 0 <= selected < len(rows):
                remove_stock(window.output, rows[selected]['code'])
                window.navigate_page('mine')

        result_card.add(row(label('双击一行打开个股报告。', 'muted'), button('移除选中', remove)))
        if result['industries']:
            result_card.add(label('仓位分布：' + '、'.join(f"{i['industry']} {i['weight'] * 100:.0f}%"
                                                        for i in result['industries']), 'muted', True))

    window.async_call(lambda: inspect_my_stocks(window.output, getattr(window, 'data_catalog_path', None)), done)


__all__ = ['stock_page', 'mine_page']
