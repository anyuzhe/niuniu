"""日内做T page: backtest 底仓做T strategies on DATA's gst_intraday database and replay single days.

Data comes only from `gst_intraday` (catalog §3.6) after the catalog marks it READY, opened
read-only by `quantlab.intraday.gst.GstIntraday`. Backtests run in the worker pool; the page
polls their progress and can stop them.
"""
import threading
from datetime import date

from PyQt6 import sip
from PyQt6.QtCore import QDate, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from quantlab.data.dataset_catalog import is_data_ready
from quantlab.intraday import backtest
from quantlab.intraday.gst import DATASET, GstIntraday
from quantlab.intraday.strategies import STRATEGIES
from quantlab.intraday.t0 import Costs, T0Config, run_day
from .widgets import Card, Chart, button, kpis, label, row, table

UP, DOWN, GREY = QColor('#f35f62'), QColor('#22d787'), QColor('#5d7182')
MAX_TRIP_ROWS = 2000
COST_PRESETS = {
    'tick': ('普通佣金：万 2.5、最低 5 元，滑点 1 个价位（按盘口实测价差）', Costs(slippage_ticks=1.0)),
    'low': ('低佣金：万 1 免五，滑点 1 个价位', Costs(commission=0.0001, commission_min=0.0, slippage_ticks=1.0)),
    'standard': ('普通佣金：万 2.5、最低 5 元，滑点 0.1%', Costs()),
    'none': ('不计费用和滑点（只看信号本身）', Costs(commission=0, commission_min=0, stamp_before=0, stamp_after=0,
                                        transfer=0, slippage=0)),
}
PART_NAMES = {'all': '全部', 'train': '训练期', 'test': '检验期'}


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def _num(value, digits=2, suffix=''):
    return '—' if value is None else f'{value:+.{digits}f}{suffix}'


def shared_reader(window):
    """One read-only reader per window; opened lazily in a worker."""
    reader = getattr(window, 'intraday_reader', None)
    if reader is None:
        reader = GstIntraday(getattr(window, 'data_catalog_path', None))
        window.intraday_reader = reader
    return reader


def _fill(grid, rows, tones=None):
    grid.setUpdatesEnabled(False)
    grid.setRowCount(len(rows))
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            item = QTableWidgetItem('—' if value is None else str(value))
            if tones and tones[i] is not None and j in tones[i][0] and tones[i][1] is not None:
                item.setForeground(tones[i][1])
            grid.setItem(i, j, item)
    grid.setUpdatesEnabled(True)


def _tone(value):
    return None if not value else (UP if value > 0 else DOWN)


# ---------------------------------------------------------------------- the minute chart

class IntradayChart(Chart):
    """One day: price, VWAP, previous close, limit prices, volume by aggressor side, trade marks."""

    def __init__(self):
        super().__init__([])
        self.day = None
        self.trips = []
        self.setMinimumHeight(420)

    def show_day(self, day, trips=()):
        self.day, self.trips = day, list(trips)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#0b1a24'))
        day = self.day
        if day is None:
            p.setPen(QColor('#8fa4b7'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '选一只股票和日期')
            return
        bars = day.bars
        keep = [i for i, m in enumerate(bars['minute']) if m >= '09:30']
        if not keep:
            return
        minutes = [bars['minute'][i] for i in keep]
        close = [float(bars['close'][i]) for i in keep]
        vwap = [float(v) for v in _cum_vwap(bars)[keep[0]:keep[-1] + 1]]
        high = [float(bars['high'][i]) for i in keep]
        low = [float(bars['low'][i]) for i in keep]
        lo, hi = min(low + [day.prev_close]), max(high + [day.prev_close])
        pad = max((hi - lo) * 0.06, day.prev_close * 0.002)
        lo, hi = lo - pad, hi + pad
        right = 64
        price_rect = QRectF(12, 14, max(1, self.width() - right - 18), (self.height() - 60) * 0.72)
        vol_rect = QRectF(12, price_rect.bottom() + 10, price_rect.width(), (self.height() - 60) * 0.25)
        n = len(keep)
        x = lambda i: price_rect.left() + (i + 0.5) * price_rect.width() / n
        y = lambda v: price_rect.bottom() - (v - lo) / (hi - lo) * price_rect.height()
        p.setPen(QColor('#203343'))
        for k in range(5):
            level = lo + (hi - lo) * k / 4
            p.drawLine(QPointF(price_rect.left(), y(level)), QPointF(price_rect.right(), y(level)))
            pct = (level / day.prev_close - 1) * 100
            p.setPen(UP if pct > 0 else DOWN if pct < 0 else QColor('#8fa4b7'))
            p.drawText(QRectF(price_rect.right() + 6, y(level) - 16, right, 16), f'{level:.2f}')
            p.drawText(QRectF(price_rect.right() + 6, y(level), right, 16), f'{pct:+.2f}%')
            p.setPen(QColor('#203343'))
        # previous close and, when in view, the limit prices
        p.setPen(QPen(QColor('#8fa4b7'), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(price_rect.left(), y(day.prev_close)), QPointF(price_rect.right(), y(day.prev_close)))
        for value, color in ((day.limit_up, UP), (day.limit_down, DOWN)):
            if value is not None and lo <= value <= hi:
                p.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
                p.drawLine(QPointF(price_rect.left(), y(value)), QPointF(price_rect.right(), y(value)))
        for series, color, width in ((vwap, QColor('#4e96ff'), 1.4), (close, QColor('#f6b72f'), 1.8)):
            path = QPainterPath()
            for i, v in enumerate(series):
                point = QPointF(x(i), y(v))
                path.moveTo(point) if i == 0 else path.lineTo(point)
            p.setPen(QPen(color, width))
            p.drawPath(path)
        # volume, coloured by which side was aggressive
        volume = [float(bars['volume'][i]) for i in keep]
        top = max(volume) or 1.0
        w = max(1.0, price_rect.width() / n * 0.7)
        for i, k in enumerate(keep):
            b, s = bars['buy_volume'][k], bars['sell_volume'][k]
            color = GREY if b != b or s != s else (UP if b >= s else DOWN)
            h = volume[i] / top * vol_rect.height()
            p.fillRect(QRectF(x(i) - w / 2, vol_rect.bottom() - h, w, h), color)
        # time axis
        p.setPen(QColor('#8fa4b7'))
        for mark in ('09:31', '10:30', '11:30', '14:00', '15:00'):
            i = next((j for j, m in enumerate(minutes) if m >= mark), None)
            if i is not None:
                left = min(max(x(i) - 24, price_rect.left()), price_rect.right() - 48)
                p.drawText(QRectF(left, vol_rect.bottom() + 2, 48, 16), Qt.AlignmentFlag.AlignCenter,
                           '09:30' if mark == '09:31' else mark)
        # trades: ▲ = buy, ▼ = sell
        index = {m: i for i, m in enumerate(minutes)}
        for trip in self.trips or ():
            first_buy = trip['direction'] == '先买后卖'
            for minute, price, is_buy in ((trip['entry_minute'], trip['entry_price'], first_buy),
                                          (trip.get('exit_minute'), trip.get('exit_price'), not first_buy)):
                if minute not in index or price is None:
                    continue
                cx, cy = x(index[minute]), y(price)
                d = 7 if is_buy else -7
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(UP if is_buy else DOWN)
                p.drawPolygon(QPolygonF([QPointF(cx, cy + d * 0.3), QPointF(cx - 6, cy + d * 1.6),
                                         QPointF(cx + 6, cy + d * 1.6)]))
        p.setPen(QColor('#8fa4b7'))
        limits = ('涨停 {:.2f} / 跌停 {:.2f}'.format(day.limit_up, day.limit_down)
                  if day.limit_up is not None else '涨跌停未推算')
        p.drawText(QRectF(12, self.height() - 22, self.width() - 24, 20),
                   f'黄线 成交价 · 蓝线 均价(VWAP) · 虚线 昨收 {day.prev_close:.2f} · 点线 涨跌停 · {limits}（{day.limit_reason}）'
                   ' · 量柱红=主动买多 绿=主动卖多 · ▲买 ▼卖')


def _cum_vwap(bars):
    import numpy as np
    volume = np.nan_to_num(bars['volume'])
    amount = np.nan_to_num(bars['amount'])
    cum = np.cumsum(volume)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(cum > 0, np.cumsum(amount) / cum, bars['close'])


# ---------------------------------------------------------------------- the page

def _state(window):
    state = getattr(window, 'intraday_state', None)
    if state is None:
        state = {'result': None, 'running': None, 'stocks': [], 'replay': None}
        window.intraday_state = state
    return state


def intraday_page(window):
    box = window.page('日内做T', '用 16 只股票 2019–2024 年的 1 分钟数据，回测“手里有底仓、当天高抛低吸”的日内策略，'
                                 '也可以逐日回放分时走势和每一笔模拟交易。')
    catalog = getattr(window, 'data_catalog_path', None)
    if not is_data_ready(catalog, dataset_id=DATASET):
        box.addWidget(label('数据侧尚未开放日内数据库（gst_intraday）。数据清单里改为 READY 后这里自动可用。', 'note', True))
        return
    state = _state(window)
    status = label('正在打开日内数据库…', 'muted', True)
    box.addWidget(status)
    tabs = QTabWidget()
    box.addWidget(tabs)
    run_tab, replay_tab = QWidget(), QWidget()
    run_box, replay_box = QVBoxLayout(run_tab), QVBoxLayout(replay_tab)
    tabs.addTab(run_tab, '策略回测')
    tabs.addTab(replay_tab, '分时回放')
    box.addWidget(label('说明：底仓做T 指手里已有一笔隔夜持仓（默认 10 万元），当天先卖一部分再买回（先卖后买），或先多买一些'
                        '再卖出同样数量的旧股（先买后卖），收盘时仓位回到原样，所以不违反 T+1。收益按“相对一直拿着不动”计算。'
                        '信号在一根 1 分钟 K 线收完后产生，下一根的开盘价成交并扣滑点（默认 1 个价位，按盘口实测价差）；“研究所得”的两种尾盘策略'
                        '在收盘集合竞价买回；每分钟最多成交该分钟成交量的 20%；'
                        '整分钟都在涨停价成交时买不进、在跌停价成交时卖不出。数据只有这 16 只股票，结论不能直接推广。'
                        '这是研究工具，不是买卖建议。', 'muted', True))

    # ------------------------------------------------------------ controls
    strategy = QComboBox()
    strategy.setAccessibleName('策略')
    for key, item in STRATEGIES.items():
        strategy.addItem(item.name, key)
    describe = label('', 'muted', True)
    params_host = QWidget()
    params_form = QFormLayout(params_host)
    params_form.setContentsMargins(0, 0, 0, 0)
    controls = {}
    costs = QComboBox()
    costs.setAccessibleName('费用')
    for key, (text, _) in COST_PRESETS.items():
        costs.addItem(text, key)
    base = QDoubleSpinBox()
    base.setRange(1, 1000)
    base.setDecimals(0)
    base.setValue(10)
    base.setSuffix(' 万元底仓')
    fraction = QDoubleSpinBox()
    fraction.setRange(10, 100)
    fraction.setDecimals(0)
    fraction.setValue(50)
    fraction.setSuffix('% 底仓用来做T')
    stock = QComboBox()
    stock.setAccessibleName('股票范围')
    stock.addItem('全部', '')
    split = QDateEdit()
    split.setDisplayFormat('yyyy-MM-dd')
    split.setDate(QDate.fromString(backtest.DEFAULT_SPLIT, 'yyyy-MM-dd'))
    split.setToolTip('此日及之前为训练期（用来看、调参数），之后为检验期（调完参数再看，判断是否只是碰巧）')
    run_button = button('开始回测', lambda: start(), True)
    stop_button = button('停止', lambda: stop_run())
    stop_button.setEnabled(False)
    progress = label('', 'muted', True)
    setup = Card('策略设置')
    setup.add(row(label('策略'), strategy, label('费用'), costs, base, fraction))
    setup.add(describe)
    setup.add(params_host)
    setup.add(row(label('股票'), stock, label('训练期截至'), split, run_button, stop_button))
    setup.add(progress)
    run_box.addWidget(setup)

    results = QWidget()
    results_box = QVBoxLayout(results)
    results_box.setContentsMargins(0, 0, 0, 0)
    run_box.addWidget(results)
    saved = QComboBox()
    saved.setAccessibleName('已保存的回测')
    run_box.addWidget(row(label('已保存的回测'), saved, button('打开', lambda: open_saved())))

    def build_params():
        while params_form.rowCount():
            params_form.removeRow(0)
        controls.clear()
        item = STRATEGIES[strategy.currentData()]
        describe.setText(item.description)
        for name, text, low, high, step in item.specs:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(0 if float(step).is_integer() and float(low).is_integer() else 2)
            spin.setValue(float(item.params[name]))
            controls[name] = spin
            params_form.addRow(text, spin)

    strategy.currentIndexChanged.connect(lambda _: build_params())
    build_params()

    def current_config():
        config = T0Config(base_value=base.value() * 10_000, trade_fraction=fraction.value() / 100,
                          costs=COST_PRESETS[costs.currentData()][1])
        return config

    def current_params():
        item = STRATEGIES[strategy.currentData()]
        return {name: (int(spin.value()) if isinstance(item.params[name], int) else spin.value())
                for name, spin in controls.items()}

    # ------------------------------------------------------------ running
    def start():
        if state['running'] is not None:
            return
        key = strategy.currentData()
        job = {'stop': threading.Event(), 'done': 0, 'total': 0, 'symbol': ''}
        state['running'] = job
        params, config = current_params(), current_config()
        symbols = [stock.currentData()] if stock.currentData() else None
        cut = split.date().toString('yyyy-MM-dd')

        def progress_hook(done, total, symbol):
            job.update(done=done, total=total, symbol=symbol)

        def work():
            result = backtest.run_backtest(shared_reader(window), key, params=params, config=config, symbols=symbols,
                                           split=cut, progress=progress_hook, stop=job['stop'])
            result['costs_preset'] = COST_PRESETS[costs.currentData()][0]
            result.pop('days', None)  # per-day records stay in memory only through the summaries
            result['run_id'] = backtest.save_run(window.output, result)
            return result

        run_button.setEnabled(False)
        stop_button.setEnabled(True)
        progress.setText('回测中…')
        timer.start()
        window.async_call(work, finished, guarded=False)

    def stop_run():
        if state['running'] is not None:
            state['running']['stop'].set()
            progress.setText('正在停止…')

    def finished(result, error):
        state['running'] = None
        if not _alive(run_button):
            if result is not None:
                state['result'] = result
            return
        timer.stop()
        run_button.setEnabled(True)
        stop_button.setEnabled(False)
        if error:
            progress.setText('回测没有完成：' + str(error))
            return
        state['result'] = result
        progress.setText(f"完成，用时 {result['seconds']} 秒，已保存为 {result['run_id']}。")
        show_result()
        load_saved_list()
        refresh_replay()

    def tick():
        job = state['running']
        if not _alive(progress):
            timer.stop()
            return
        if job is None:  # finished while this page was rebuilt: the old page stored the result
            timer.stop()
            run_button.setEnabled(True)
            stop_button.setEnabled(False)
            progress.setText('回测已结束。')
            show_result()
            load_saved_list()
            return
        if job['total'] and not job['stop'].is_set():
            progress.setText(f"回测中… 已完成 {job['done']}/{job['total']} 只（{job['symbol']}）")

    timer = QTimer(results)
    timer.setInterval(300)
    timer.timeout.connect(tick)
    if state['running'] is not None:  # a run started before the page was rebuilt
        run_button.setEnabled(False)
        stop_button.setEnabled(True)
        timer.start()

    # ------------------------------------------------------------ results
    def show_result():
        while results_box.count():
            item = results_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        result = state['result']
        if not result:
            results_box.addWidget(label('还没有回测结果。选好策略后点“开始回测”，或打开一个已保存的回测。', 'muted', True))
            return
        summary = result['summary']
        head = Card(f"{result['strategy_name']} · {result.get('costs_preset', '')}")
        head.add(label('参数：' + '，'.join(f'{k}={v}' for k, v in result['params'].items()) +
                       f"；训练期截至 {result['split']}；底仓 {result['config']['base_value'] / 1e4:.0f} 万元，"
                       f"每次做T {result['config']['trade_fraction'] * 100:.0f}%", 'muted', True))
        items = []
        for part in ('train', 'test'):
            s = summary.get(part, {})
            if not s.get('days'):
                items.append((PART_NAMES[part], '—', '没有样本'))
                continue
            items.append((PART_NAMES[part] + '：平均每天', _num(s['portfolio_mean_bps'], 2, ' bp'),
                          f"底仓年化约 {s['annual_pct']:+.1f}%，t={s['t_stat'] if s['t_stat'] is not None else '—'}"))
        test = summary.get('test', {})
        if test.get('trips'):
            items.append(('检验期：每笔', _num(test['avg_trip_bps'], 1, ' bp'),
                          f"不计成本 {test['avg_raw_bps']:+.1f} bp，胜率 {test['win_rate'] * 100:.0f}%"))
        head.add(kpis(items))
        for part in ('train', 'test'):
            if summary.get(part, {}).get('days'):
                head.add(label(f"{PART_NAMES[part]}：{summary[part]['verdict']}", 'note' if part == 'test' else 'muted',
                               True))
        results_box.addWidget(head)
        curve = summary.get('all', {}).get('curve') or []
        if curve:
            chart = Chart([c['bps'] for c in curve])
            chart.setMinimumHeight(220)
            chart.caption = (f"累计收益（每天等权平均，基点，相对拿着底仓不动）{curve[0]['date']} → {curve[-1]['date']}；"
                             f"训练期截至 {result['split']}")
            card = Card('累计收益曲线')
            card.add(chart)
            results_box.addWidget(card)
        headers = ['区间', '股票日', '交易', '平均每天(bp)', 't', '每笔扣费后(bp)', '每笔不计成本(bp)', '胜率', '最大回撤(bp)', '未能回补']

        def stat_row(name, s):
            if not s.get('days'):
                return [name] + ['—'] * (len(headers) - 1)
            return [name, s['days'], s['trips'], _num(s['portfolio_mean_bps']), s['t_stat'],
                    _num(s.get('avg_trip_bps'), 1), _num(s.get('avg_raw_bps'), 1),
                    '—' if s.get('win_rate') is None else f"{s['win_rate'] * 100:.0f}%", s['max_drawdown_bps'],
                    s['unfinished']]
        parts = Card('按区间 / 年份 / 股票')
        rows = [stat_row(PART_NAMES[k], summary.get(k, {})) for k in ('train', 'test', 'all')]
        rows += [stat_row(y['year'] + ' 年', y) for y in result.get('per_year', [])]
        rows += [stat_row(f"{s['name']} {s['symbol']}", s) for s in result.get('per_symbol', [])]
        grid = table(headers, [])
        _fill(grid, rows, [({3}, _tone(_float(r[3]))) for r in rows])
        grid.setMinimumHeight(min(900, 60 + 39 * len(rows)))
        parts.add(grid)
        results_box.addWidget(parts)
        trips = result.get('trips', [])
        trip_card = Card(f"交易明细（共 {len(trips)} 笔" + (f"，显示最近 {MAX_TRIP_ROWS} 笔" if len(trips) > MAX_TRIP_ROWS else '')
                         + '；双击在分时回放里打开那一天）')
        shown = trips[-MAX_TRIP_ROWS:]
        trip_grid = table(['日期', '股票', '方向', '数量', '开仓', '价格', '平仓', '价格', '原因', '扣费后(元)', '扣费后(bp)'], [],
                          lambda i: open_replay(shown[len(shown) - 1 - i]))
        view = list(reversed(shown))
        _fill(trip_grid, [[t['date'], t['symbol'], t['direction'], t['qty'], t['entry_minute'], t['entry_price'],
                           t['exit_minute'], t['exit_price'], t['reason'], t['pnl'], t['bps']] for t in view],
              [({9, 10}, _tone(t['pnl'])) for t in view])
        trip_grid.setMinimumHeight(420)
        trip_card.add(trip_grid)
        results_box.addWidget(trip_card)

    def load_saved_list():
        if not _alive(saved):
            return
        saved.clear()
        for item in backtest.list_runs(window.output):
            test = (item.get('summary') or {}).get('test') or {}
            mean = test.get('portfolio_mean_bps')
            saved.addItem(f"{item['run_id']} · {item.get('strategy_name')} · 检验期 "
                          + ('—' if mean is None else f'{mean:+.2f} bp/天'), item['run_id'])

    def refresh_replay():
        if state['replay'] and _alive(chart):
            load_day(*state['replay'])

    def open_saved():
        run_id = saved.currentData()
        if not run_id:
            return
        try:
            state['result'] = backtest.load_run(window.output, run_id)
        except (OSError, ValueError) as exc:
            progress.setText(f'打不开这个回测：{exc}')
            return
        show_result()
        refresh_replay()

    # ------------------------------------------------------------ replay
    r_stock = QComboBox()
    r_stock.setAccessibleName('回放股票')
    r_day = QComboBox()
    r_day.setAccessibleName('回放日期')
    r_info = label('', 'muted', True)
    chart = IntradayChart()
    r_trips = table(['方向', '数量', '开仓', '价格', '平仓', '价格', '原因', '扣费后(元)', '扣费后(bp)'], [])
    r_trips.setMinimumHeight(160)
    simulate = button('用上面设置的策略模拟这一天', lambda: simulate_day())
    replay_card = Card('分时回放')
    replay_card.add(row(label('股票'), r_stock, label('日期'), r_day, button('‹ 前一天', lambda: step(1)),
                        button('后一天 ›', lambda: step(-1)), simulate))
    replay_card.add(r_info)
    replay_card.add(chart)
    replay_card.add(r_trips)
    replay_box.addWidget(replay_card)

    def trips_for(symbol, day):
        result = state['result'] or {}
        return [t for t in result.get('trips', []) if t['symbol'] == symbol and t['date'] == day]

    def show_replay(day, trips, source):
        if not _alive(chart):
            return
        state['replay'] = (day.symbol, day.date.isoformat())
        chart.show_day(day, trips)
        closes = day.bars['close']
        change = (closes[-1] / day.prev_close - 1) * 100 if day.prev_close else 0
        r_info.setText(f"{day.name} {day.symbol} {day.date} · 昨收 {day.prev_close:.2f} · 收盘 {closes[-1]:.2f}（{change:+.2f}%）"
                       f" · {len(day.bars['minute'])} 根 1 分钟K · {day.limit_reason} · 交易：{source}")
        _fill(r_trips, [[t['direction'], t['qty'], t['entry_minute'], t['entry_price'], t['exit_minute'], t['exit_price'],
                         t['reason'], t['pnl'], t['bps']] for t in trips], [({7, 8}, _tone(t['pnl'])) for t in trips])

    def load_day(symbol, day_text, trips=None, source=None):
        def work():
            return shared_reader(window).day(symbol, date.fromisoformat(day_text))

        def done(day, error):
            if error or day is None:
                if _alive(r_info):
                    r_info.setText(f'{symbol} {day_text} 没有可用的分钟数据。' if not error else '读取失败：' + str(error))
                return
            listed = trips if trips is not None else trips_for(symbol, day_text)
            show_replay(day, listed, source or (f"当前回测结果中 {len(listed)} 笔" if state['result'] else '没有打开回测结果'))
        window.async_call(work, done)

    def load_days(symbol, select=None):
        def work():
            return [d.isoformat() for d in shared_reader(window).usable_days(symbol)]

        def done(days, error):
            if error or not _alive(r_day):
                return
            r_day.blockSignals(True)
            r_day.clear()
            for d in reversed(days):
                r_day.addItem(d, d)
            index = r_day.findData(select) if select else 0
            r_day.setCurrentIndex(max(0, index))
            r_day.blockSignals(False)
            if r_day.currentData():
                load_day(symbol, r_day.currentData())
        window.async_call(work, done)

    def open_replay(trip):
        tabs.setCurrentIndex(1)
        index = r_stock.findData(trip['symbol'])
        r_stock.blockSignals(True)
        r_stock.setCurrentIndex(max(0, index))
        r_stock.blockSignals(False)
        load_days(trip['symbol'], trip['date'])

    def step(direction):
        index = r_day.currentIndex() + direction
        if 0 <= index < r_day.count():
            r_day.setCurrentIndex(index)

    def simulate_day():
        symbol, day_text = r_stock.currentData(), r_day.currentData()
        if not symbol or not day_text:
            return
        key, params = strategy.currentData(), current_params()
        config = backtest.config_for(key, current_config())

        def work():
            day = shared_reader(window).day(symbol, date.fromisoformat(day_text))
            if day is None:
                return None
            _, trips = run_day(day, STRATEGIES[key], params, config)
            return day, trips

        def done(value, error):
            if error or not value:
                return
            day, trips = value
            show_replay(day, trips, f"{STRATEGIES[key].name} 模拟 {len(trips)} 笔（{COST_PRESETS[costs.currentData()][0]}）")
        window.async_call(work, done)

    r_stock.currentIndexChanged.connect(lambda _: load_days(r_stock.currentData()) if r_stock.currentData() else None)
    r_day.currentIndexChanged.connect(lambda _: load_day(r_stock.currentData(), r_day.currentData())
                                      if r_day.currentData() else None)

    # ------------------------------------------------------------ open the database
    def opened(stocks, error):
        if not _alive(status):
            return
        if error:
            status.setText('日内数据库打不开：' + str(error))
            run_button.setEnabled(False)
            return
        state['stocks'] = stocks
        stock.setItemText(0, f'全部 {len(stocks)} 只')
        first = min((s['tick_from'] for s in stocks if s.get('tick_from')), default=None)
        last = max((s['tick_to'] for s in stocks if s.get('tick_to')), default=None)
        status.setText(f"日内数据库：{len(stocks)} 只股票，成交与 1 分钟K {first} 至 {last}（数据侧 gst_intraday，只读）。")
        for s in stocks:
            stock.addItem(f"{s['name']} {s['symbol']}", s['symbol'])
        r_stock.blockSignals(True)
        for s in stocks:
            r_stock.addItem(f"{s['name']} {s['symbol']}", s['symbol'])
        r_stock.blockSignals(False)
        if state['replay']:
            symbol, day_text = state['replay']
            r_stock.blockSignals(True)
            r_stock.setCurrentIndex(max(0, r_stock.findData(symbol)))
            r_stock.blockSignals(False)
            load_days(symbol, day_text)
        elif stocks:
            load_days(stocks[0]['symbol'])

    show_result()
    load_saved_list()
    window.async_call(lambda: shared_reader(window).stocks(), opened)


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ['intraday_page', 'IntradayChart', 'shared_reader', 'COST_PRESETS']
