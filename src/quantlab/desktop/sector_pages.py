"""盘中板块 page: live board ranking and the selected board's constituents.

Data comes only from DATA's SectorIntradayProvider, after the catalog marks it READY.
The page refreshes in place (boards every 10 s, the open board every 5 s) while the
market is in session; the provider's own caches enforce DATA's minimum intervals.
"""
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QComboBox, QTableWidgetItem
from PyQt6.QtGui import QColor

from quantlab.trading.intraday_sectors import (LIVE_STATUSES, TYPE_NAMES, error_text, filter_note, freshness, is_ready,
                                               member_state,
                                               not_ready_text, pick_boards, sector_prompt, shared_provider)
from .widgets import Card, Chart, button, label, row, table

TICK_MS = 5000          # members every tick, boards every other tick
IDLE_TICKS = 12         # outside trading hours: check once a minute
UP, DOWN = QColor('#f35f62'), QColor('#22d787')


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def _pct(value):
    return '—' if value is None else f'{value:+.2f}%'


def _yi(value):
    return '—' if value is None else f'{value / 1e8:,.1f}'


def _fill(grid, rows, colors=None):
    grid.setUpdatesEnabled(False)
    grid.setRowCount(len(rows))
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            item = QTableWidgetItem('—' if value is None else str(value))
            if colors and colors[i][1] is not None and j in colors[i][0]:
                item.setForeground(colors[i][1])
            grid.setItem(i, j, item)
    grid.setUpdatesEnabled(True)


def _tone(value):
    return None if value is None or value == 0 else (UP if value > 0 else DOWN)


def sectors_page(window):
    box = window.page('盘中板块', '交易时间里哪些概念和行业在涨、涨了多少，点开一个板块看成分股的实时表现。')
    catalog = getattr(window, 'data_catalog_path', None)
    if not is_ready(catalog):
        box.addWidget(label(not_ready_text(catalog), 'note', True))
        if not getattr(window, 'pro_mode', False) or not getattr(window, 'sector_preview', False):
            if getattr(window, 'pro_mode', False):
                box.addWidget(button('开发预览（接口尚未开放，仅供开发核对）',
                                     lambda: (setattr(window, 'sector_preview', True), window.navigate_page('sectors'))))
            return
        box.addWidget(label('开发预览：数据侧尚未开放，结果只用于核对页面，不作为看盘依据。', 'note', True))
    provider = getattr(window, 'sector_provider', None) or shared_provider(window.data_root)
    state = {'snapshot': None, 'members': None, 'board': None, 'tick': 0, 'busy': set(), 'boards_view': []}

    status = label('正在读取板块…', 'muted', True)
    kind = QComboBox()
    for key, text in (('all', '概念+行业'), ('concept', '概念'), ('industry', '行业')):
        kind.addItem(text, key)
    kind.setAccessibleName('板块类型')
    order = QComboBox()
    for key, text in (('up', '涨幅榜'), ('down', '跌幅榜'), ('amount', '成交额')):
        order.addItem(text, key)
    order.setAccessibleName('排序')
    tidy = QCheckBox('过滤全市场标签和小板块')
    tidy.setChecked(getattr(window, 'sector_filter', True))
    tidy.setToolTip('隐藏数据侧标为全市场标签（融资融券、沪股通、精选指数、次新股、业绩标签等）的板块，以及成分股少于 10 只的板块')
    ask = button('问 AI 解读', lambda: window.ask_ai(sector_prompt(state['snapshot'], state['board'], state['members']))
                 if state['snapshot'] else None, True)
    head = row(status, kind, order, tidy, button('立即刷新', lambda: refresh(force=True)), ask)
    head.layout().setStretch(0, 1)
    box.addWidget(head)

    boards_card = Card('板块排行（单击查看成分股）')
    filter_label = label('', 'muted', True)
    boards_card.add(filter_label)
    boards_grid = table(['板块', '类型', '涨跌幅', '成交额（亿）', '指数'], [])
    boards_grid.setMinimumHeight(520)
    boards_card.add(boards_grid)
    members_card = Card('成分股')
    members_title = label('在左侧选一个板块。', 'muted', True)
    series = Chart([])
    series.setMinimumHeight(150)
    series.setVisible(False)
    members_grid = table(['股票', '代码', '现价', '涨跌幅', '成交额（亿）', '状态'], [],
                         lambda i: window.open_stock_report(state['members']['members'][i]['symbol'])
                         if state['members'] else None)
    members_grid.setMinimumHeight(420)
    members_card.add(members_title)
    members_card.add(series)
    members_card.add(members_grid)
    members_card.add(label('双击一只股票打开个股报告。成分为当前成分；涨跌停由数据侧按板块规则推算并与扶摇涨跌停池对照；'
                           '行情与腾讯、新浪核对，对不上的暂不显示价格。走势是本次打开页面后的采样，不是分时线。',
                           'muted', True))
    grids = row(boards_card, members_card)
    grids.layout().setStretch(0, 2)
    grids.layout().setStretch(1, 3)
    box.addWidget(grids)
    box.addWidget(label('说明：盘中行情来自数据侧的盘中板块接口（扶摇/同花顺板块指数，单一来源无法交叉校验）；'
                        '交易时间板块每 10 秒、成分股每 5 秒刷新，非交易时间显示最近一次行情。这是研究参考，不是买卖指令。',
                        'muted', True))

    def show_boards():
        snapshot = state['snapshot']
        if snapshot is None or not _alive(boards_grid):
            return
        status.setText(freshness(snapshot) + f" · 共 {snapshot['counts']['returned']} 个板块")
        view = pick_boards(snapshot, kind.currentData(), order.currentData(), filtered=tidy.isChecked())
        filter_label.setText(filter_note(snapshot) if tidy.isChecked() else '显示全部板块（含全市场标签和小板块）。')
        state['boards_view'] = view
        _fill(boards_grid, [[b['name'], TYPE_NAMES[b['type']], _pct(b['change_pct']), _yi(b['amount']),
                             f"{b['last']:,.2f}"] for b in view],
              [({2}, _tone(b['change_pct'])) for b in view])
        selected = state['board']
        if selected:
            state['board'] = next((b for b in snapshot['boards'] if b['code'] == selected['code']), selected)
            index = next((i for i, b in enumerate(view) if b['code'] == selected['code']), None)
            if index is not None:
                boards_grid.blockSignals(True)
                boards_grid.selectRow(index)
                boards_grid.blockSignals(False)

    def show_members():
        members, board = state['members'], state['board']
        if members is None or board is None or not _alive(members_grid):
            return
        c = members['counts']
        members_title.setText(f"{board['name']}（{TYPE_NAMES[board['type']]}） {_pct(board.get('change_pct'))} · "
                              f"{c['constituents']} 只，涨停 {c['limit_up']}、炸板 {c['limit_break']}、跌停 {c['limit_down']}"
                              + (f"、暂不显示 {c['withheld']}" if c['withheld'] else '') + ' · ' + freshness(members))
        rows = members['members']
        _fill(members_grid, [[r['name'], r['symbol'], '—' if r['last'] is None else f"{r['last']:.2f}", _pct(r['change_pct']),
                              _yi(r['amount']) if r['amount'] else '—', member_state(r)] for r in rows],
              [({3}, _tone(r['change_pct'])) for r in rows])
        points = [p['change_pct'] for p in provider.board_series(board['code'])['points'] if p['change_pct'] is not None]
        series.values = points
        series.caption = '本次打开后的板块涨跌幅采样（%）'
        series.setVisible(len(points) >= 2)
        series.update()

    def fetch(name, work, done):
        if name in state['busy']:
            return
        state['busy'].add(name)

        def guarded():
            # Errors are shown on this page, not in the window's global status bar.
            try:
                return {'value': work()}
            except Exception as exc:  # DataProviderError, network, configuration
                return {'error': exc}

        def finished(result, error):
            state['busy'].discard(name)
            if not _alive(status):
                return
            failure = error or (result or {}).get('error')
            if failure:
                status.setText(error_text(failure))
                return
            done(result['value'])

        window.async_call(guarded, finished)

    def got_boards(value):
        state['snapshot'] = value
        show_boards()

    def got_members(value):
        state['members'] = value
        show_members()

    def refresh(force=False):
        fetch('boards', lambda: provider.board_snapshot(('concept', 'industry')), got_boards)
        if state['board']:
            code = state['board']['code']
            fetch('members', lambda: provider.board_members(code), got_members)

    def select(r, _c=None):
        view = state['boards_view']
        if not 0 <= r < len(view):
            return
        if state['board'] and state['board']['code'] == view[r]['code']:
            return
        state['board'], state['members'] = view[r], None
        members_title.setText(f"正在读取 {view[r]['name']} 的成分股…")
        _fill(members_grid, [])
        series.setVisible(False)
        code = view[r]['code']
        fetch('members', lambda: provider.board_members(code), got_members)

    def tick():
        if not _alive(status):
            return
        state['tick'] += 1
        live = (state['snapshot'] or {}).get('market_status') in LIVE_STATUSES
        if live:
            if state['board']:
                code = state['board']['code']
                fetch('members', lambda: provider.board_members(code), got_members)
            if state['tick'] % 2 == 0:
                fetch('boards', lambda: provider.board_snapshot(('concept', 'industry')), got_boards)
        elif state['tick'] % IDLE_TICKS == 0:
            fetch('boards', lambda: provider.board_snapshot(('concept', 'industry')), got_boards)

    boards_grid.cellClicked.connect(select)
    kind.currentIndexChanged.connect(lambda _: show_boards())
    order.currentIndexChanged.connect(lambda _: show_boards())
    tidy.toggled.connect(lambda on: (setattr(window, 'sector_filter', on), show_boards()))
    timer = QTimer(status)  # dies with the page
    timer.timeout.connect(tick)
    timer.start(TICK_MS)
    window.sector_page_state = state  # for tests and the assistant prompt
    refresh()


__all__ = ['sectors_page']
