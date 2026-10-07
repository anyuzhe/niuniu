"""策略工作台：把“恐慌日抄底”策略做成可看、可调、可跟踪的页面。

六个标签：今日信号 / 回测与风险 / 参数沙盒 / 前向跟踪 / 行业恐慌（只看信号，单独一份回测和前向记录）/ 策略 D（大盘、成交额分档、行业三层恐慌共用一笔钱，单独一份回测和前向记录）。
数据只来自数据清单里 READY 的前复权日线和日状态（quantlab.dipbuy.panel），第一次要读 5000 多个文件，
结果缓存在输出目录里；回测在后台线程里跑，页面轮询进度。这里不下单、不连券商。
"""
import math
import threading
from dataclasses import replace

from PyQt6 import sip
from PyQt6.QtCore import QRectF, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from quantlab.data.dataset_catalog import is_data_ready
from quantlab.dipbuy import backtest, engine, fusion, industry, panel as dpanel, tracker
from .strategy_calendar import CalendarCard
from .widgets import Card, button, kpis, label, row, table

UP, DOWN, GOLD, BLUE, GREY = QColor('#f35f62'), QColor('#22d787'), QColor('#f6b72f'), QColor('#4e96ff'), QColor('#8fa4b7')
TABS = (('signal', '今日信号'), ('risk', '回测与风险'), ('sandbox', '参数沙盒'), ('forward', '前向跟踪'), ('industry', '行业恐慌'), ('fusion', '策略 D'))
DISCLAIMER = ('这是研究工具，不是买卖建议，也不会下单。回测是历史结果：样本只有约 45 段恐慌期，参数是看过数据后定的，'
              '面板只含现存股票（有幸存者偏差），没有计入冲击成本和跌停卖不出；融资需要券商两融资格，2 倍杠杆的历史最大回撤约 −51%。')
YEAR_CHOICES = ('2008', '2012', '2017', '2020')
MAX_ROWS = 400


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def _pct(value, digits=1, sign=True):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return '—'
    return f'{value * 100:+.{digits}f}%' if sign else f'{value * 100:.{digits}f}%'


def _num(value, digits=2):
    return '—' if value is None or (isinstance(value, float) and not math.isfinite(value)) else f'{value:.{digits}f}'


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _state(window):
    state = getattr(window, 'bench_state', None)
    if state is None:
        state = {'panel': None, 'names': {}, 'default': None, 'forward': None, 'industry': None, 'fusion': None, 'fusion_variant': 'D', 'loading': None,
                 'running': None, 'sandbox': None, 'error': None}
        window.bench_state = state
    return state


# ---------------------------------------------------------------------- charts
class SeriesChart(QWidget):
    """多条折线（允许断点），可选对数坐标；只画传进来的真实结果。"""

    def __init__(self, name='', log=False, y_format='{:.2f}', height=260):
        super().__init__()
        self.setAccessibleName(name)
        self.series, self.labels, self.log, self.y_format = [], ('', ''), log, y_format
        self.hlines = []
        self.setMinimumHeight(height)

    def set_data(self, series, labels=('', ''), hlines=()):
        self.series, self.labels, self.hlines = series, labels, list(hlines)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#0b1a24'))
        vals = [v for s in self.series for v in s['values'] if v is not None and math.isfinite(v) and (not self.log or v > 0)]
        vals += [h[0] for h in self.hlines]
        if not vals:
            p.setPen(GREY)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '暂无数据')
            return
        tf = (lambda v: math.log(v)) if self.log else (lambda v: v)
        inv = (lambda v: math.exp(v)) if self.log else (lambda v: v)
        lo, hi = tf(min(vals)), tf(max(vals))
        if hi - lo < 1e-12:
            lo, hi = lo - 0.5, hi + 0.5
        pad = (hi - lo) * 0.05
        lo, hi = lo - pad, hi + pad
        ticks = [inv(hi - (hi - lo) * i / 4) for i in range(5)]
        names = [self.y_format.format(t) for t in ticks]
        lw = max(p.fontMetrics().horizontalAdvance(n) for n in names) + 12
        rect = QRectF(12, 26, max(1, self.width() - lw - 24), self.height() - 56)
        y = lambda v: rect.bottom() - (tf(v) - lo) / (hi - lo) * rect.height()
        for i in range(5):
            line = rect.top() + rect.height() * i / 4
            p.setPen(QColor('#203343'))
            p.drawLine(QPointF(rect.left(), line), QPointF(rect.right(), line))
            p.setPen(GREY)
            p.drawText(QRectF(rect.right() + 6, line - 10, lw, 20), Qt.AlignmentFlag.AlignLeft, names[i])
        for value, color, text in self.hlines:
            if self.log and value <= 0:
                continue
            p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(rect.left(), y(value)), QPointF(rect.right(), y(value)))
        for s in self.series:
            n = len(s['values'])
            path = QPainterPath()
            pen_up = True
            for i, v in enumerate(s['values']):
                if v is None or not math.isfinite(v) or (self.log and v <= 0):
                    pen_up = True
                    continue
                pt = QPointF(rect.left() + i * rect.width() / max(1, n - 1), y(v))
                if pen_up:
                    path.moveTo(pt)
                    pen_up = False
                else:
                    path.lineTo(pt)
            p.setPen(QPen(QColor(s['color']), s.get('width', 1.8)))
            p.drawPath(path)
        x = 14
        for s in self.series:
            p.setPen(QColor(s['color']))
            p.drawText(QPointF(x, 16), '━ ' + s['name'])
            x += p.fontMetrics().horizontalAdvance('━ ' + s['name']) + 18
        for value, color, text in self.hlines:
            p.setPen(QColor(color))
            p.drawText(QPointF(x, 16), '┄ ' + text)
            x += p.fontMetrics().horizontalAdvance('┄ ' + text) + 18
        p.setPen(GREY)
        p.drawText(QRectF(12, self.height() - 24, 200, 20), Qt.AlignmentFlag.AlignLeft, self.labels[0])
        p.drawText(QRectF(self.width() - lw - 212, self.height() - 24, 200, 20), Qt.AlignmentFlag.AlignRight, self.labels[1])


class BarChart(QWidget):
    def __init__(self, name='', height=200):
        super().__init__()
        self.setAccessibleName(name)
        self.items = []
        self.setMinimumHeight(height)

    def set_items(self, items):
        self.items = items
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#0b1a24'))
        if not self.items:
            p.setPen(GREY)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '暂无数据')
            return
        top = max(max(v for _, v in self.items), 0.0)
        bottom = min(min(v for _, v in self.items), 0.0)
        span = (top - bottom) or 1.0
        rect = QRectF(12, 30, self.width() - 24, self.height() - 76)
        zero = rect.bottom() - (0 - bottom) / span * rect.height()
        step = rect.width() / len(self.items)
        p.setPen(QColor('#203343'))
        p.drawLine(QPointF(rect.left(), zero), QPointF(rect.right(), zero))
        for i, (name, value) in enumerate(self.items):
            x = rect.left() + i * step + step * 0.15
            h = abs(value) / span * rect.height()
            color = UP if value >= 0 else DOWN
            p.setPen(color)
            p.setBrush(color)
            p.drawRect(QRectF(x, zero - h if value >= 0 else zero, step * 0.7, max(1.0, h)))
            p.setPen(GREY)
            p.drawText(QRectF(x - step * 0.15, self.height() - 24, step, 20), Qt.AlignmentFlag.AlignHCenter, name[-2:])
            p.drawText(QRectF(x - step * 0.2, (zero - h - 16) if value >= 0 else (zero + h + 1), step * 1.1, 16),
                       Qt.AlignmentFlag.AlignHCenter, f'{value * 100:.0f}')


def _align(curves):
    """多条曲线按日期并集对齐，缺的补 None。curves: [(name, color, dates, values)]"""
    days = sorted({d for _, _, ds, _ in curves for d in ds})
    out = []
    for name, color, ds, vs in curves:
        m = dict(zip(ds, vs))
        out.append({'name': name, 'color': color, 'values': [m.get(d) for d in days]})
    return days, out


# ---------------------------------------------------------------------- the page
def strategy_bench_page(window):
    box = window.page('策略工作台', '恐慌日抄底：大盘恐慌时（闸门）买入个股布林下轨收复的票，20 只等权、持有 20 个交易日，可加融资杠杆。'
                                  '看今日信号、回测与风险、调参数、记前向结果；“行业恐慌”标签是另一套入场条件，只看信号。')
    catalog = getattr(window, 'data_catalog_path', None)
    missing = [d for d in (dpanel.QFQ_DATASET, dpanel.STATUS_DATASET) if not is_data_ready(catalog, dataset_id=d)]
    if missing:
        box.addWidget(label('数据侧尚未开放：' + '、'.join(missing) + '。数据清单里改为 READY 后这里自动可用。', 'note', True))
        return
    page = BenchPage(window, box, catalog)
    page.open()


class BenchPage:
    def __init__(self, window, box, catalog):
        self.window, self.catalog, self.state = window, catalog, _state(window)
        self.rendered = False
        self.status = label('', 'muted', True)
        self.reload_button = button('重新读取数据', self.reload)
        box.addWidget(row(self.status, self.reload_button))
        self.tabs = QTabWidget()
        box.addWidget(self.tabs)
        self.boxes = {}
        for key, title in TABS:
            tab = QWidget()
            lay = QVBoxLayout(tab)
            lay.setContentsMargins(0, 12, 0, 0)
            lay.setSpacing(12)
            self.tabs.addTab(tab, title)
            self.boxes[key] = lay
        box.addWidget(label(DISCLAIMER, 'muted', True))
        self.timer = QTimer(self.tabs)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.tick)
        self.equity_spin = None
        self.pick_host = None
        self.message = {}

    # ---- loading
    def open(self):
        if self.state['panel'] is not None and self.state['loading'] is None:
            self.render_all()
        elif self.state['loading'] is not None:
            self.status.setText('正在准备数据…')
            self.reload_button.setEnabled(False)
            self.timer.start()
        elif dpanel.cached_meta(self.window.output):
            self.load()          # 已经读过一次：直接读缓存（源数据变了会自动重建）
        else:
            self.show_first_run()

    def show_first_run(self):
        self.status.setText('还没有读取过数据。')
        v = self.boxes['signal']
        _clear(v)
        card = Card('第一次使用')
        card.add(label('需要读取全市场日线（约 5000 个文件，2007 年至今）并拼成面板，大约几分钟；读完缓存在输出目录里，'
                       '以后打开页面只读缓存。数据只来自数据清单里 READY 的前复权日线和日状态。', 'muted', True))
        self.first_button = button('读取数据并回测', self.load, True)
        card.add(self.first_button)
        v.addWidget(card)
        v.addStretch(1)

    def reload(self):
        if self.state['loading'] is None and self.state['running'] is None:
            self.state.update(panel=None, default=None, sandbox=None, industry=None, fusion=None)
            self.rendered = False
            self.load()

    def load(self):
        win, catalog = self.window, self.catalog
        job = {'stop': threading.Event(), 'done': 0, 'total': 1, 'label': '准备数据'}
        self.state.update(loading=job, error=None)

        def hook(done, total, text):
            job.update(done=done, total=max(total, 1), label=text)

        def work():
            panel = dpanel.load_panel(win.output, catalog, progress=hook, stop=job['stop'])
            job.update(label='计算信号并回测', done=0, total=1)
            names = dpanel.load_names(catalog)
            default = backtest.run_backtest(panel, engine.DipConfig(), progress=hook, stop=job['stop'])
            job.update(label='行业恐慌', done=0, total=1)
            ind = _industry_bundle(win.output, panel, catalog, hook, job['stop'])
            job.update(label='策略 D', done=0, total=1)
            return {'panel': panel, 'names': names, 'default': default, 'forward': _forward(win.output, panel),
                    'industry': ind, 'fusion': _fusion_bundle(win.output, panel, ind, hook, job['stop'])}

        self.reload_button.setEnabled(False)
        self.timer.start()
        win.async_call(work, self.loaded, guarded=False)

    def loaded(self, result, error):
        self.state['loading'] = None
        if error:
            self.state['error'] = error
        elif result:
            self.state.update(result)
        if not _alive(self.tabs):
            return
        self.timer.stop()
        self.reload_button.setEnabled(True)
        if error:
            self.status.setText('数据面板没有准备好：' + str(error))
            return
        self.render_all()

    def tick(self):
        if not _alive(self.tabs):
            self.timer.stop()
            return
        job = self.state['loading']
        if job is not None:
            self.status.setText(f"{job['label']}… {job['done']}/{job['total']}")
            return
        self.timer.stop()
        self.reload_button.setEnabled(True)
        if self.state['error']:
            self.status.setText('数据面板没有准备好：' + str(self.state['error']))
        elif self.state['panel'] is not None and not self.rendered:
            self.render_all()

    def render_all(self):
        panel = self.state['panel']
        self.rendered = True
        meta = panel.meta or {}
        self.status.setText(f"数据面板：{panel.shape[1]} 只股票，{panel.dates[0]} 至 {panel.dates[-1]}（{panel.shape[0]} 个交易日）。")
        self.build_signal()
        self.build_risk()
        self.build_sandbox()
        self.build_forward()
        self.build_industry()
        self.build_fusion()

    # ---- tab 1: today's signal
    def build_signal(self):
        v = self.boxes['signal']
        _clear(v)
        panel, cfg = self.state['panel'], engine.DipConfig()
        market, cand = engine.compute_features(panel, cfg.min_amount, cfg.min_price)
        sig = engine.latest_signal(panel, market, cand, cfg, names=self.state['names'])
        self.signal = sig
        gate = '开' if sig['gate_open'] else '关'
        v.addWidget(kpis([
            ('数据截至', sig['date'], '面板最后一个交易日'),
            ('大盘 20 日涨跌', _pct(sig['mk20']), f"等权 {sig['n_market']} 只流动性股票"),
            ('z 值', _num(sig['z']), f"闸门阈值 {sig['z_threshold']:g}（越低越恐慌）"),
            ('闸门', gate, '开 = 允许明天开盘买入' if sig['gate_open'] else '关 = 不开新仓'),
            ('布林下轨收复', f"{sig['n_e6']} 只", '今天满足个股条件的数量')]))
        recent = sig['recent']
        chart = SeriesChart('近期z值', y_format='{:+.2f}', height=170)
        chart.set_data([{'name': 'z', 'color': '#f6b72f', 'values': [r['z'] for r in recent]}],
                       (recent[0]['date'], recent[-1]['date']), [(sig['z_threshold'], '#f35f62', f"闸门 {sig['z_threshold']:g}")])
        card = Card('大盘恐慌度（最近 10 个交易日）')
        card.add(chart)
        v.addWidget(card)
        plan = Card('明天的计划' if sig['gate_open'] else '今天不用买（闸门没开）')
        self.equity_spin = QDoubleSpinBox()
        self.equity_spin.setAccessibleName('账户本金')
        self.equity_spin.setRange(1, 100000)
        self.equity_spin.setDecimals(1)
        self.equity_spin.setValue(50)
        self.equity_spin.setSuffix(' 万元本金')
        self.equity_spin.valueChanged.connect(lambda _: self.fill_picks())
        self.record_button = button('把今天的信号记入前向跟踪', self.record, True)
        self.record_button.setEnabled(bool(sig['gate_open'] and sig['picks']))
        self.record_message = label('', 'muted', True)
        plan.add(row(label('按'), self.equity_spin, label(f"本金、{cfg.leverage:g} 倍杠杆、{cfg.positions} 只等权估算每只金额："), self.record_button))
        plan.add(self.record_message)
        self.pick_host = QWidget()
        self.pick_box = QVBoxLayout(self.pick_host)
        self.pick_box.setContentsMargins(0, 0, 0, 0)
        plan.add(self.pick_host)
        if sig['gate_open']:
            text = (f"规则：明天开盘买入排名前 {cfg.positions} 只（20 日跌幅最大优先），持有 {cfg.hold_days} 个交易日后收盘卖出；"
                    '明天开盘一字涨停买不进的，顺延到下一名。股数按今天收盘价估算，实际以明天开盘价为准；融资部分按借款利息计成本。')
        else:
            text = '闸门没开时不开新仓，已有的仓位按 20 个交易日到期卖出。下面只是“如果闸门开了”会选到的票，仅供观察，不要据此买入。'
        plan.add(label(text, 'muted', True))
        v.addWidget(plan)
        self.fill_picks()
        v.addStretch(1)

    def fill_picks(self):
        if self.pick_host is None or not _alive(self.pick_host):
            return
        _clear(self.pick_box)
        cfg = engine.DipConfig()
        panel = self.state['panel']
        market, cand = engine.compute_features(panel, cfg.min_amount, cfg.min_price)
        sig = engine.latest_signal(panel, market, cand, cfg, equity=self.equity_spin.value() * 1e4, names=self.state['names'])
        self.signal = sig
        if not sig['picks']:
            self.pick_box.addWidget(label('今天没有满足“布林下轨收复”的股票。', 'muted', True))
            return
        open_gate = sig['gate_open']
        rows = [[p['rank'], p['code'], p['name'] or '—', f"{p['close']:.2f}", _pct(p['ret20']),
                 ('计划内' if p['in_plan'] else '备选') if open_gate else '仅观察',
                 f"{p.get('plan_amount', 0):,.0f}" if p['in_plan'] and open_gate else '—',
                 f"{p.get('plan_shares', 0):,}" if p['in_plan'] and open_gate else '—']
                for p in sig['picks'][:MAX_ROWS]]
        self.pick_box.addWidget(table(['排名', '代码', '名称', '收盘价', '20日涨跌', '位置', '计划金额（元）', '估算股数'], rows))

    def record(self):
        try:
            record = tracker.record_signal(self.window.output, self.signal, engine.DipConfig())
        except ValueError as exc:
            self.record_message.setText(str(exc))
            return
        self.record_message.setText(f"已记录 {record['signal_date']} 的信号（{len(record['picks'])} 只），后续用真实行情结算。")
        self.record_button.setEnabled(False)
        self.state['forward'] = _forward(self.window.output, self.state['panel'])
        self.build_forward()

    # ---- tab 2: backtest and risk
    def build_risk(self):
        v = self.boxes['risk']
        _clear(v)
        result = self.state['default']
        v.addWidget(label(_config_text(result['config']) + f"　引擎 {result['engine_version']}　哈希 {result['content_hash']}", 'muted', True))
        v.addWidget(result_view(result, self.state['panel']))
        v.addStretch(1)

    # ---- tab 3: sandbox
    def build_sandbox(self):
        v = self.boxes['sandbox']
        _clear(v)
        base = engine.DipConfig()
        setup = Card('参数沙盒（改参数重跑，对照默认策略）')
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        c = {}

        def spin(key, text, low, high, step, value, decimals=0, suffix=''):
            use_double = decimals > 0 or any(isinstance(x, float) for x in (low, high, step, value))
            w = QDoubleSpinBox() if use_double else QSpinBox()
            w.setRange(low, high)
            if use_double:
                w.setDecimals(decimals)
            w.setSingleStep(step)
            w.setValue(value)
            w.setSuffix(suffix)
            w.setAccessibleName(text)
            c[key] = w
            form.addRow(text, w)

        spin('z', 'z 阈值（越低越恐慌，开仓越少）', -4.0, 0.0, 0.25, base.z_threshold, 2)
        spin('n', '持仓只数', 1, 100, 1, base.positions)
        spin('hold', '持有交易日', 1, 60, 1, base.hold_days)
        spin('lev', '杠杆倍数', 0.5, 3.0, 0.5, base.leverage, 1, ' 倍')
        spin('cy', '闲置资金年化收益（货基/逆回购）', 0.0, 10.0, 0.5, 0.0, 1, ' %')
        spin('fr', '融资利率（0 = 按年代：8.5/7/6%）', 0.0, 30.0, 0.5, 0.0, 1, ' %')
        spin('slip', '每边冲击成本', 0.0, 200.0, 5.0, 0.0, 0, ' 基点')
        spin('amt', '候选股 20 日均成交额下限', 0, 100000, 500, int(base.min_amount / 1e4), 0, ' 万元')
        spin('px', '候选股原始价下限', 0.0, 1000.0, 1.0, base.min_price, 1, ' 元')
        rank = QComboBox()
        rank.setAccessibleName('排序')
        for key, name in engine.RANKS.items():
            rank.addItem(name, key)
        form.addRow('排序', rank)
        start = QComboBox()
        start.setAccessibleName('起始年份')
        for y in YEAR_CHOICES:
            start.addItem(y + ' 年起', y + '-01-01')
        form.addRow('回测起点', start)
        self.sandbox_controls = (c, rank, start)
        setup.add(form_host)
        self.run_button = button('运行回测', self.run_sandbox, True)
        self.stop_button = button('停止', self.stop_sandbox)
        self.stop_button.setEnabled(False)
        self.reset_button = button('恢复默认参数', lambda: self.build_sandbox())
        self.sandbox_message = label('', 'muted', True)
        setup.add(row(self.run_button, self.stop_button, self.reset_button))
        setup.add(self.sandbox_message)
        v.addWidget(setup)
        self.sandbox_host = QWidget()
        self.sandbox_box = QVBoxLayout(self.sandbox_host)
        self.sandbox_box.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.sandbox_host)
        saved = backtest.list_runs(self.window.output, 10)
        self.saved = QComboBox()
        self.saved.setAccessibleName('已保存的回测')
        for r in saved:
            self.saved.addItem(f"{r['run_id']}　年化 {_pct(r['cagr'])}　回撤 {_pct(r['max_drawdown'], 0)}", r['run_id'])
        v.addWidget(row(label('已保存的沙盒回测'), self.saved, button('打开', self.open_saved)))
        v.addStretch(1)
        if self.state['running'] is not None:
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.timer.start()
        elif self.state['sandbox'] is not None:
            self.show_sandbox(self.state['sandbox'])

    def sandbox_config(self):
        c, rank, start = self.sandbox_controls
        return engine.DipConfig(
            z_threshold=c['z'].value(), positions=c['n'].value(), hold_days=c['hold'].value(), leverage=c['lev'].value(),
            rank=rank.currentData(), cash_yield=c['cy'].value() / 100, financing_rate=(c['fr'].value() / 100) or None,
            slippage_bp=c['slip'].value(), min_amount=c['amt'].value() * 1e4, min_price=c['px'].value(), start=start.currentData())

    def run_sandbox(self):
        if self.state['running'] is not None or self.state['panel'] is None:
            return
        try:
            cfg = self.sandbox_config()
        except ValueError as exc:
            self.sandbox_message.setText(str(exc))
            return
        job = {'stop': threading.Event(), 'done': 0, 'total': 1, 'label': '回测'}
        self.state['running'] = job
        panel, out = self.state['panel'], self.window.output

        def hook(done, total, text):
            job.update(done=done, total=max(total, 1), label=text)

        def work():
            result = backtest.run_backtest(panel, cfg, progress=hook, stop=job['stop'])
            result['run_id'] = backtest.save_run(out, result)
            return result

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.sandbox_message.setText('回测中…')
        self.timer.start()
        self.window.async_call(work, self.sandbox_done, guarded=False)

    def stop_sandbox(self):
        job = self.state['running']
        if job is not None:
            job['stop'].set()
            self.sandbox_message.setText('正在停止…')

    def sandbox_done(self, result, error):
        self.state['running'] = None
        if result is not None:
            self.state['sandbox'] = result
        if not _alive(self.tabs) or not _alive(self.run_button):
            return
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if error:
            self.sandbox_message.setText('回测没有完成：' + ('已停止' if 'Cancelled' in str(error) else str(error)))
            return
        self.sandbox_message.setText(f"完成，已保存为 {result['run_id']}。")
        self.show_sandbox(result)

    def open_saved(self):
        run_id = self.saved.currentData()
        if not run_id:
            return
        try:
            result = backtest.load_run(self.window.output, run_id)
        except (OSError, ValueError) as exc:
            self.sandbox_message.setText('打不开：' + str(exc))
            return
        self.state['sandbox'] = result
        self.show_sandbox(result)

    def show_sandbox(self, result):
        if not _alive(self.sandbox_host):
            return
        _clear(self.sandbox_box)
        base = self.state['default']
        card = Card('与默认策略对照')
        card.add(label('沙盒：' + _config_text(result['config']), 'muted', True))
        rows = [[name, a, b] for name, a, b in _compare_rows(base, result)]
        card.add(table(['指标', '默认策略', '沙盒参数'], rows))
        days, series = _align([('默认策略', '#8fa4b7', base['curve']['dates'], base['curve']['equity']),
                               ('沙盒参数', '#f6b72f', result['curve']['dates'], result['curve']['equity'])])
        chart = SeriesChart('沙盒净值对照', log=True, y_format='{:.2f}×')
        chart.set_data(series, (days[0], days[-1]))
        card.add(chart)
        card.add(label('净值为对数坐标，起点 = 1。参数改得越多，越可能只是在拟合这段历史——结果好看不等于以后有效。', 'muted', True))
        self.sandbox_box.addWidget(card)

    # ---- tab 4: forward tracking
    def build_forward(self):
        v = self.boxes['forward']
        _clear(v)
        fwd = self.state['forward']
        if fwd is None or fwd.get('error'):
            v.addWidget(label('前向记录读取失败：' + str((fwd or {}).get('error')), 'note', True))
            return
        ledger = fwd['settled']['ledger']
        records, summary = fwd['settled']['records'], fwd['settled']['summary']
        intro = Card('前向跟踪记录')
        intro.add(label('从现在起，每个出现开仓信号的交易日，把当天选出的股票冻结记下来（只能记最新一天，不能事后补记），'
                        '之后用真实后续行情按同一套成本结算。这是纸面记录，不下单。参数记下后冻结，改参数要先清空。', 'muted', True))
        if ledger.get('started_at'):
            intro.add(label(f"开始日 {ledger['start_date']}，参数哈希 {ledger['config_hash']}。", 'muted', True))
        v.addWidget(intro)
        v.addWidget(kpis([
            ('已记录信号', str(summary['n_records']), f"其中已结算 {summary['n_closed']} 条"),
            ('平均每次信号收益', _pct(summary['mean_signal_ret']), '计划内股票等权，扣成本，持有 20 日'),
            ('信号胜率', _pct(summary['signal_win_rate'], 0, False), f"个股胜率 {_pct(summary['pick_win_rate'], 0, False)}（{summary['n_picks']} 笔）"),
            ('回测同口径', _pct(self.state['default']['summary']['trades']['mean']), '回测里每笔平均净收益（供对照）')]))
        if summary['note']:
            v.addWidget(label(summary['note'], 'note', True))
        card = Card('逐条记录')
        status_names = {'waiting': '等待下一个交易日', 'open': '持有中', 'closed': '已结算'}
        rows = []
        for r in records:
            res = r.get('result') or {}
            shown = res.get('mean_ret') if res.get('mean_ret') is not None else res.get('mean_mtm')
            rows.append([r['signal_date'], _num(r.get('z')), status_names.get(r.get('status'), r.get('status')),
                         res.get('n_filled', 0), _pct(shown), r['recorded_at'][:16].replace('T', ' ')])
        card.add(table(['信号日', 'z', '状态', '买入只数', '收益（持有中为浮动）', '记录时间'], rows) if rows
                 else label('还没有记录。哪天闸门打开，在“今日信号”里点“记入前向跟踪”。', 'muted', True))
        v.addWidget(card)
        port = fwd.get('portfolio')
        if port:
            ptable = Card('按冻结参数从开始日起的组合净值')
            s = port['summary']['stats']
            if s:
                ptable.add(label(f"累计 {_pct(s['total'])}，最大回撤 {_pct(s['max_drawdown'], 0)}，共 {s['days']} 个交易日。", 'muted', True))
            chart = SeriesChart('前向净值', y_format='{:.3f}×')
            chart.set_data([{'name': '前向净值', 'color': '#f6b72f', 'values': port['equity']}], (port['dates'][0], port['dates'][-1]))
            ptable.add(chart)
            if port['mismatched']:
                ptable.add(label('提示：有 %d 个信号日，组合重算选出的股票不在当时的记录里（数据可能被修订）。' % len(port['mismatched']), 'note', True))
            v.addWidget(ptable)
        self.clear_armed = False
        if records:
            self.clear_button = button('清空记录', self.clear_ledger)
            self.clear_message = label('', 'muted', True)
            v.addWidget(row(self.clear_button, self.clear_message))
        v.addStretch(1)

    def clear_ledger(self):
        if not self.clear_armed:
            self.clear_armed = True
            self.clear_button.setText('再点一次确认清空')
            self.clear_message.setText('清空后不能恢复。')
            return
        tracker.clear_ledger(self.window.output)
        self.state['forward'] = _forward(self.window.output, self.state['panel'])
        self.build_forward()
        self.build_signal()

    # ---- tab 5: industry panic (signal only)
    def build_industry(self):
        v = self.boxes['industry']
        _clear(v)
        ind = self.state.get('industry')
        if not ind or ind.get('error'):
            v.addWidget(label('行业恐慌暂不可用：' + str((ind or {}).get('error') or '数据还没准备好'), 'note', True))
            v.addStretch(1)
            return
        cfg, cls, panel = industry.default_config(), ind['cls'], self.state['panel']
        sig = industry.latest_industry_signal(panel, cfg, cls, names=self.state['names'])
        self.ind_signal, self.ind_cfg = sig, cfg
        intro = Card('这是什么')
        intro.add(label('每天给 31 个申万一级行业各算一个“恐慌分”（行业内股票等权 20 日涨跌 ÷ 该行业平时的波动），低于 −1.5 就说明这个行业被集体砸得异常狠。'
                        '哪个行业触发，就在触发的行业里买 20 日跌得最多的股票（多个行业同时触发时按跌幅混排取前 20 只），'
                        f'次日开盘买、持有 {cfg.hold_days} 个交易日，默认 {cfg.leverage:g} 倍。和左边“大盘恐慌”是两套入场条件，不要求布林下轨收复。'
                        '注意：把行业标签随机打乱再跑同样的规则也有年化约 12%，所以行业信息本身的增量有限（详见下面的风险与口径）。这里只显示信号并做前向记录，不下单、不建议买卖。', 'muted', True))
        v.addWidget(intro)
        weakest = sig['industries'][0] if sig['industries'] else None
        v.addWidget(kpis([
            ('数据截至', sig['date'], f"分类文件 {sig['classification']['as_of']}（今天的分类）"),
            ('触发的行业', '、'.join(sig['triggered']) if sig['triggered'] else '无', f"阈值 {cfg.z_threshold:g}"),
            ('最弱行业', f"{weakest['name']} {_num(weakest['z'])}" if weakest and weakest['z'] is not None else '—', '行业分越低越恐慌'),
            ('大盘 z', _num(sig['market_z']), '参考，行业恐慌不要求大盘恐慌'),
            ('触发行业里的候选', f"{sig['n_e6']} 只", '可交易、非 ST、流动性够')]))
        table_card = Card('31 个行业的恐慌分（从最弱开始）')
        rows = [[r['name'], r['stocks'], r['members'], _pct(r['ret20']), _num(r['z']), '触发' if r['triggered'] else '']
                for r in sig['industries']]
        table_card.add(table(['行业', '股票数', '当日参与', '20日涨跌（等权）', '恐慌分', '状态'], rows))
        v.addWidget(table_card)
        pick_card = Card('触发时会选到的股票' if sig['gate_open'] else '今天没有行业触发（下面为空）')
        self.ind_record_button = button('把今天的信号记入行业前向跟踪', self.record_industry, True)
        self.ind_record_button.setEnabled(bool(sig['gate_open'] and sig['picks']))
        self.ind_record_message = label('', 'muted', True)
        pick_card.add(row(self.ind_record_button, self.ind_record_message))
        if sig['picks']:
            prow = [[p['rank'], p['code'], p['name'] or '—', p.get('industry') or '—', f"{p['close']:.2f}", _pct(p['ret20']),
                     '前 20（计划内）' if p['in_plan'] else '备选'] for p in sig['picks'][:MAX_ROWS]]
            pick_card.add(table(['排名', '代码', '名称', '行业', '收盘价', '20日涨跌', '位置'], prow))
        else:
            pick_card.add(label('没有行业触发，或触发行业里今天没有可买的股票。', 'muted', True))
        v.addWidget(pick_card)
        self.build_industry_forward(v, ind)
        run = ind['run']
        head = Card('行业恐慌的回测与风险')
        head.add(label(_config_text(run['config']) + f"　引擎 {run['engine_version']}　哈希 {run['content_hash']}", 'muted', True))
        head.add(label('口径：任一行业触发即开仓（不看大盘状态）；候选 = 触发行业里全部可交易股票，按 20 日跌幅混排；次日开盘一字涨停买不进的顺延。', 'muted', True))
        v.addWidget(head)
        v.addWidget(result_view(run, panel))
        v.addStretch(1)

    def record_industry(self):
        try:
            record = tracker.record_signal(self.window.output, self.ind_signal, self.ind_cfg, kind='industry')
        except ValueError as exc:
            self.ind_record_message.setText(str(exc))
            return
        self.ind_record_message.setText(f"已记录 {record['signal_date']} 的信号（{len(record['picks'])} 只），后续用真实行情结算。")
        self.ind_record_button.setEnabled(False)
        self.refresh_industry_forward()

    def refresh_industry_forward(self):
        ind = self.state.get('industry')
        if ind and not ind.get('error'):
            ind['forward'] = _industry_forward(self.window.output, self.state['panel'], ind['cls'])
        self.build_industry()

    def build_industry_forward(self, v, ind):
        fwd = ind.get('forward') or {}
        card = Card('行业恐慌的前向跟踪')
        if fwd.get('error'):
            card.add(label('前向记录读取失败：' + str(fwd['error']), 'note', True))
            v.addWidget(card)
            return
        records, summary, ledger = fwd['settled']['records'], fwd['settled']['summary'], fwd['settled']['ledger']
        card.add(label('规则同左边的前向跟踪：只能记最新一天、不能事后补记，参数冻结，用真实后续行情按同一套成本结算；纸面记录，不下单。'
                       + (f"开始日 {ledger['start_date']}，参数哈希 {ledger['config_hash']}。" if ledger.get('started_at') else ''), 'muted', True))
        card.add(kpis([
            ('已记录信号', str(summary['n_records']), f"其中已结算 {summary['n_closed']} 条"),
            ('平均每次信号收益', _pct(summary['mean_signal_ret']), '计划内股票等权，扣成本'),
            ('信号胜率', _pct(summary['signal_win_rate'], 0, False), f"个股胜率 {_pct(summary['pick_win_rate'], 0, False)}（{summary['n_picks']} 笔）"),
            ('回测同口径', _pct(ind['run']['summary']['trades']['mean']), '回测里每笔平均净收益（供对照）')]))
        if summary['note']:
            card.add(label(summary['note'], 'note', True))
        status_names = {'waiting': '等待下一个交易日', 'open': '持有中', 'closed': '已结算'}
        rows = []
        for r in records:
            res = r.get('result') or {}
            shown = res.get('mean_ret') if res.get('mean_ret') is not None else res.get('mean_mtm')
            rows.append([r['signal_date'], '、'.join(r.get('industries') or []) or '—', _num(r.get('z')),
                         status_names.get(r.get('status'), r.get('status')), res.get('n_filled', 0), _pct(shown)])
        card.add(table(['信号日', '触发行业', '最弱行业分', '状态', '买入只数', '收益（持有中为浮动）'], rows) if rows
                 else label('还没有记录。哪天有行业触发，在上面点“记入行业前向跟踪”。', 'muted', True))
        port = fwd.get('portfolio')
        if port:
            s = port['summary']['stats']
            if s:
                card.add(label(f"按冻结参数从开始日起的组合净值：累计 {_pct(s['total'])}，最大回撤 {_pct(s['max_drawdown'], 0)}，共 {s['days']} 个交易日。", 'muted', True))
            chart = SeriesChart('行业恐慌前向净值', y_format='{:.3f}×')
            chart.set_data([{'name': '前向净值', 'color': '#f6b72f', 'values': port['equity']}], (port['dates'][0], port['dates'][-1]))
            card.add(chart)
        self.ind_clear_armed = False
        if records:
            self.ind_clear_button = button('清空行业记录', self.clear_industry_ledger)
            self.ind_clear_message = label('', 'muted', True)
            card.add(row(self.ind_clear_button, self.ind_clear_message))
        v.addWidget(card)

    def clear_industry_ledger(self):
        if not self.ind_clear_armed:
            self.ind_clear_armed = True
            self.ind_clear_button.setText('再点一次确认清空')
            self.ind_clear_message.setText('清空后不能恢复。')
            return
        tracker.clear_ledger(self.window.output, 'industry')
        self.refresh_industry_forward()

    # ---- tab 6: strategy D (three panic layers sharing one account)
    def build_fusion(self):
        v = self.boxes['fusion']
        _clear(v)
        top = self.state.get('fusion')
        if not top or top.get('error'):
            v.addWidget(label('策略 D 暂不可用：' + str((top or {}).get('error') or '数据还没准备好'), 'note', True))
            v.addStretch(1)
            return
        variant, fus = self.fus_cur()
        name = fusion.VARIANT_NAMES[variant]
        v.addWidget(self.fusion_selector(variant))
        if fus.get('error'):
            v.addWidget(label(f'{name} 暂不可用：' + str(fus['error']), 'note', True))
            v.addStretch(1)
            return
        cfg, cls, panel = fus['cfg'], fus['cls'], self.state['panel']
        rank_text = ('买 20 日跌得最多的' if variant == 'D' else
                     f'先取 20 日跌得最多的前 {cfg.rank_k} 只，再买其中 60 日回撤（离近 60 日最高收盘价跌得最深）最大的')
        self.fus_cfg = cfg
        inp = fusion.build_inputs(panel, cfg, cls)
        sig = fusion.latest_fusion_signal(panel, inp, cfg, names=self.state['names'])
        self.fus_signal = sig
        w = cfg.weights
        intro = Card('这是什么')
        if variant == 'D1':
            intro.add(label('D1 = 策略 D 只换一件事：同一批触发的候选，D 直接买 20 日跌得最多的；D1 先留下 20 日跌得最多的前 40 只，再按 60 日回撤从深到浅买。'
                            '闸门、权重、仓位、持有期、成本都和 D 一样，单独一份回测和前向记录。注意：这个排序是看过全样本后挑出来的，属于样本内线索，'
                            '逐年看有的年份比 D 好很多、有的年份少赚，建议当可选增强，别当成 D 的替代品。', 'note', True))
        intro.add(label('三套恐慌信号共用一笔钱、不借钱：A 大盘恐慌（且个股布林下轨收复）、C 按近 60 日成交额分五档的某一档恐慌、B 申万一级某个行业恐慌。'
                        '恐慌分都是“一组股票的等权 20 日涨跌 ÷ 它平时的波动”，低于 −1.5 就触发。触发的层按 A → C → B 的顺序分钱，'
                        f"每只权重 A {w['A'] * 100:g}%、C {w['C'] * 100:g}%、B {w['B'] * 100:g}%（占净值），每层最多 {cfg.positions} 只，总仓位不超过 {cfg.gross_cap * 100:g}%，"
                        f'{rank_text}；次日开盘买、持有 {cfg.hold_days} 个交易日后收盘卖，同一只股票不会在两层里重复买。'
                        'A 触发的日子 C 一定触发，C 触发的日子 B 一定触发，所以 B 层最频繁、单笔质量最低，作用是把 A、C 空着的钱用起来。'
                        '这里只显示信号并做前向记录，不下单、不建议买卖。', 'muted', True))
        v.addWidget(intro)
        tiles = [('数据截至', sig['date'], f"分类文件 {sig['classification']['as_of']}（今天的分类）"),
                 ('触发的层', '、'.join(sig['fired']) if sig['fired'] else '无', f"阈值 {cfg.z_threshold:g}，任一层触发就买")]
        for s_ in fusion.ORDER:
            g = sig['sleeves'][s_]
            note = f"已触发，候选 {g['n_pool']} 只" if g['gate'] else ('未触发，还差 %.2f' % (g['z'] - cfg.z_threshold) if g['z'] is not None else '未触发')
            tiles.append((f"{s_} {g['name']}", _num(g['z']), f"{g['detail']}　{note}"))
        v.addWidget(kpis(tiles))
        recent = sig['recent']
        chart = SeriesChart('三层恐慌分', y_format='{:+.2f}', height=190)
        chart.set_data([{'name': 'A 大盘', 'color': '#4e96ff', 'values': [r['a'] for r in recent]},
                        {'name': 'C 最弱的成交额档', 'color': '#f6b72f', 'values': [r['c'] for r in recent]},
                        {'name': 'B 最弱的行业', 'color': '#22d787', 'values': [r['b'] for r in recent]}],
                       (recent[0]['date'], recent[-1]['date']), [(cfg.z_threshold, '#f35f62', f'触发线 {cfg.z_threshold:g}')])
        card = Card('三层恐慌分（最近 10 个交易日）')
        card.add(chart)
        v.addWidget(card)
        qcard = Card('成交额五档的恐慌分')
        qcard.add(table(['档', '当日参与', '20日涨跌（等权）', '恐慌分', '状态'],
                        [[r['name'], r['members'], _pct(r['ret20']), _num(r['z']), '触发' if r['triggered'] else ''] for r in sig['quintiles']]))
        v.addWidget(qcard)
        icard = Card('申万行业最弱的 10 个')
        icard.add(table(['行业', '股票数', '当日参与', '20日涨跌（等权）', '恐慌分', '状态'],
                        [[r['name'], r['stocks'], r['members'], _pct(r['ret20']), _num(r['z']), '触发' if r['triggered'] else '']
                         for r in sig['industries'][:10]]))
        v.addWidget(icard)
        plan = Card('明天的计划' if sig['gate_open'] else '今天不用买（三层闸门都没开）')
        self.fus_equity = QDoubleSpinBox()
        self.fus_equity.setAccessibleName('策略D账户本金')
        self.fus_equity.setRange(1, 100000)
        self.fus_equity.setDecimals(1)
        self.fus_equity.setValue(40)
        self.fus_equity.setSuffix(' 万元本金')
        self.fus_equity.valueChanged.connect(lambda _: self.fill_fusion_picks())
        self.fus_record_button = button(f'把今天的信号记入{name} 前向跟踪', self.record_fusion, True)
        self.fus_record_button.setEnabled(bool(sig['gate_open'] and sig['picks']))
        self.fus_record_message = label('', 'muted', True)
        plan.add(row(label('按'), self.fus_equity, label('本金估算每只金额（按账户空仓算，已有持仓要自己扣掉）：'), self.fus_record_button))
        plan.add(self.fus_record_message)
        self.fus_pick_host = QWidget()
        self.fus_pick_box = QVBoxLayout(self.fus_pick_host)
        self.fus_pick_box.setContentsMargins(0, 0, 0, 0)
        plan.add(self.fus_pick_host)
        plan.add(label('规则：明天开盘买入，A 先、C 次之、B 最后分钱，钱不够就少买；每只股票只出现在最先选中它的那一层；'
                       f'持有 {cfg.hold_days} 个交易日后收盘卖出；明天开盘一字涨停买不进的顺延到下一名。股数按今天收盘价估算，实际以明天开盘价为准。', 'muted', True))
        v.addWidget(plan)
        self.fill_fusion_picks()
        self.build_fusion_forward(v, fus)
        run = fus['run']
        head = Card(f'{name} 的回测与风险')
        head.add(label(_fusion_config_text(run['config']) + f"　引擎 {run['engine_version']}　哈希 {run['content_hash']}", 'muted', True))
        head.add(label('口径：一笔钱、不借钱，次日开盘买、持有到期收盘卖，同一套手续费和 1 个最小价位滑点；闲置资金按年化 2% 计息；'
                       '候选里次日开盘一字涨停的排除。', 'muted', True))
        v.addWidget(head)
        scard = Card('三层各自的成交')
        sl = run['summary']['sleeves']
        scard.add(table(['层', '触发天数', '成交笔数', '单笔平均净收益', '胜率', '未平仓'],
                        [[f"{k} {sl[k]['name']}", sl[k]['gate_days'], sl[k]['n'], _pct(sl[k]['mean']), _pct(sl[k]['win_rate'], 0, False), sl[k]['open']]
                         for k in fusion.ORDER]))
        v.addWidget(scard)
        v.addWidget(result_view(run, panel, levered=False))
        v.addStretch(1)

    def fill_fusion_picks(self):
        if getattr(self, 'fus_pick_host', None) is None or not _alive(self.fus_pick_host):
            return
        _clear(self.fus_pick_box)
        _, fus = self.fus_cur()
        panel = self.state['panel']
        inp = fusion.build_inputs(panel, fus['cfg'], fus['cls'])
        sig = fusion.latest_fusion_signal(panel, inp, fus['cfg'], equity=self.fus_equity.value() * 1e4, names=self.state['names'])
        self.fus_signal = sig
        if not sig['picks']:
            self.fus_pick_box.addWidget(label('今天没有层触发，或触发的层里没有可买的股票，没有计划。', 'muted', True))
            return
        d1 = sig.get('rank_mode') == 'dd60'
        rows = [[p['sleeve'], p['rank'], p['code'], p['name'] or '—', p['group'] or '—', f"{p['close']:.2f}", _pct(p['ret20'])]
                + ([_pct(p.get('dd60'))] if d1 else [])
                + ['计划内' if p['in_plan'] else '备选',
                   f"{p.get('plan_amount', 0):,.0f}" if p['in_plan'] else '—', f"{p.get('plan_shares', 0):,}" if p['in_plan'] else '—']
                for p in sig['picks'][:MAX_ROWS]]
        heads = ['层', '排名', '代码', '名称', '分组', '收盘价', '20日涨跌'] + (['60日回撤'] if d1 else []) + ['位置', '计划金额（元）', '估算股数']
        self.fus_pick_box.addWidget(table(heads, rows))

    def record_fusion(self):
        try:
            record = tracker.record_signal(self.window.output, self.fus_signal, self.fus_cfg, kind=_fusion_kind(self.fus_cfg.variant))
        except ValueError as exc:
            self.fus_record_message.setText(str(exc))
            return
        self.fus_record_message.setText(f"已记录 {record['signal_date']} 的信号（{len(record['picks'])} 只），后续用真实行情结算。")
        self.fus_record_button.setEnabled(False)
        self.refresh_fusion_forward()

    def refresh_fusion_forward(self):
        if (self.state.get('fusion') or {}).get('error'):
            return
        variant, fus = self.fus_cur()
        if fus and not fus.get('error'):
            fus['forward'] = _fusion_forward(self.window.output, self.state['panel'], fus['cls'], variant)
        self.build_fusion()

    def fus_cur(self):
        """当前选中的是 D 还是 D1，以及对应的那一份回测 / 前向包（D1 的包挂在 D 的包下面）。"""
        top = self.state.get('fusion') or {}
        if self.state.get('fusion_variant') == 'D1':
            return 'D1', top.get('d1') or {'error': '没有算出 D1'}
        return 'D', top

    def fusion_selector(self, variant):
        box = QComboBox()
        box.setAccessibleName('候选排序')
        box.addItem('D：买 20 日跌得最多的', 'D')
        box.addItem('D1：先取跌幅前 40，再买 60 日回撤最深的', 'D1')
        box.setCurrentIndex(1 if variant == 'D1' else 0)
        box.currentIndexChanged.connect(lambda _: self.set_fusion_variant(box.currentData()))
        return row(label('候选排序'), box)

    def set_fusion_variant(self, variant):
        if variant in ('D', 'D1') and variant != self.state.get('fusion_variant'):
            self.state['fusion_variant'] = variant
            self.build_fusion()

    def build_fusion_forward(self, v, fus):
        fwd = fus.get('forward') or {}
        name = fusion.VARIANT_NAMES[fus['cfg'].variant]
        card = Card(f'{name} 的前向跟踪')
        if fwd.get('error'):
            card.add(label('前向记录读取失败：' + str(fwd['error']), 'note', True))
            v.addWidget(card)
            return
        records, summary, ledger = fwd['settled']['records'], fwd['settled']['summary'], fwd['settled']['ledger']
        card.add(label('规则同其它前向跟踪：只能记最新一天、不能事后补记，参数冻结，用真实后续行情按同一套成本结算；纸面记录，不下单。'
                       '一条记录里各层各取前 20 只买得进的，收益按各层单只权重加权。'
                       + (f"开始日 {ledger['start_date']}，参数哈希 {ledger['config_hash']}。" if ledger.get('started_at') else ''), 'muted', True))
        card.add(kpis([
            ('已记录信号', str(summary['n_records']), f"其中已结算 {summary['n_closed']} 条"),
            ('平均每次信号收益', _pct(summary['mean_signal_ret']), '计划内股票按权重加权，扣成本'),
            ('信号胜率', _pct(summary['signal_win_rate'], 0, False), f"个股胜率 {_pct(summary['pick_win_rate'], 0, False)}（{summary['n_picks']} 笔）"),
            ('回测同口径', _pct(fus['run']['summary']['trades']['mean']), '回测里每笔平均净收益（供对照）')]))
        if summary['note']:
            card.add(label(summary['note'], 'note', True))
        status_names = {'waiting': '等待下一个交易日', 'open': '持有中', 'closed': '已结算'}
        rows = []
        for r in records:
            res = r.get('result') or {}
            shown = res.get('mean_ret') if res.get('mean_ret') is not None else res.get('mean_mtm')
            rows.append([r['signal_date'], '、'.join(r.get('fired') or []) or '—', _num(r.get('z')),
                         status_names.get(r.get('status'), r.get('status')), res.get('n_filled', 0), _pct(shown)])
        card.add(table(['信号日', '触发的层', '大盘 z', '状态', '买入只数', '收益（持有中为浮动）'], rows) if rows
                 else label(f'还没有记录。哪天有层触发，在上面点“记入{name} 前向跟踪”。', 'muted', True))
        port = fwd.get('portfolio')
        if port:
            s = port['summary']['stats']
            if s:
                card.add(label(f"按冻结参数从开始日起的组合净值：累计 {_pct(s['total'])}，最大回撤 {_pct(s['max_drawdown'], 0)}，共 {s['days']} 个交易日。", 'muted', True))
            chart = SeriesChart(f"{name.replace(' ', '')}前向净值", y_format='{:.3f}×')
            chart.set_data([{'name': '前向净值', 'color': '#f6b72f', 'values': port['equity']}], (port['dates'][0], port['dates'][-1]))
            card.add(chart)
            card.add(CalendarCard(port['dates'], port['equity'], title='前向收益日历'))
            if port['mismatched']:
                card.add(label('提示：有 %d 个信号日，组合重算选出的股票不在当时的记录里（数据可能被修订）。' % len(port['mismatched']), 'note', True))
        self.fus_clear_armed = False
        if records:
            self.fus_clear_button = button(f'清空{name} 记录', self.clear_fusion_ledger)
            self.fus_clear_message = label('', 'muted', True)
            card.add(row(self.fus_clear_button, self.fus_clear_message))
        v.addWidget(card)

    def clear_fusion_ledger(self):
        if not self.fus_clear_armed:
            self.fus_clear_armed = True
            self.fus_clear_button.setText('再点一次确认清空')
            self.fus_clear_message.setText('清空后不能恢复。')
            return
        tracker.clear_ledger(self.window.output, _fusion_kind(self.fus_cfg.variant))
        self.refresh_fusion_forward()


# ---------------------------------------------------------------------- pieces shared by tabs
def _forward(output, panel):
    try:
        settled = tracker.settle_ledger(output, panel)
        return {'settled': settled, 'portfolio': tracker.forward_portfolio(output, panel)}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _industry_forward(output, panel, cls):
    try:
        settled = tracker.settle_ledger(output, panel, kind='industry')
        return {'settled': settled, 'portfolio': tracker.forward_portfolio(
            output, panel, kind='industry', features=lambda cfg: industry.build_inputs(panel, cfg, cls)[:2])}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _fusion_kind(variant):
    return 'fusion1' if variant == 'D1' else 'fusion'


def _fusion_forward(output, panel, cls, variant='D'):
    try:
        kind = _fusion_kind(variant)
        settled = tracker.settle_ledger(output, panel, kind=kind)
        return {'settled': settled, 'portfolio': fusion.forward_portfolio(output, panel, cls, kind=kind)}
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _fusion_bundle(output, panel, ind, progress, stop):
    """策略 D / D1：需要行业分类（B 层）。回测、前向记录；任何一步失败只影响这个标签页。
    D1 = D 换一种候选排序，单独一份回测和前向记录；D1 失败不影响 D。"""
    try:
        if not ind or ind.get('error'):
            raise dpanel.DipDataError('B 层需要申万行业分类：' + str((ind or {}).get('error') or '行业数据还没准备好'))
        cls = ind['cls']
        out = None
        for variant in ('D', 'D1'):
            try:
                cfg = fusion.config_for(variant)
                run = fusion.run_backtest(panel, cfg, cls, progress=progress, stop=stop)
                bundle = {'cfg': cfg, 'cls': cls, 'run': run, 'forward': _fusion_forward(output, panel, cls, variant)}
            except dpanel.Cancelled:
                raise
            except Exception as exc:
                if variant == 'D':
                    raise
                bundle = {'error': f'{type(exc).__name__}: {exc}'}
            if variant == 'D':
                out = bundle
            else:
                out['d1'] = bundle
        return out
    except dpanel.Cancelled:
        raise
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _industry_bundle(output, panel, catalog, progress, stop):
    """行业分类、行业恐慌回测、前向记录；任何一步失败只影响这个标签页，其余照常。"""
    try:
        cls = industry.load_classification_for(panel, catalog)
        run = industry.run_backtest(panel, industry.default_config(), cls, progress=progress, stop=stop)
        return {'cls': cls, 'run': run, 'forward': _industry_forward(output, panel, cls)}
    except dpanel.Cancelled:
        raise
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


def _config_text(cfg):
    rate = '按年代' if cfg.get('financing_rate') is None else f"{cfg['financing_rate'] * 100:g}%"
    return (f"z≤{cfg['z_threshold']:g}　{cfg['positions']} 只等权　持有 {cfg['hold_days']} 日　{cfg['leverage']:g} 倍杠杆　"
            f"{engine.RANKS[cfg['rank']]}　融资利率 {rate}　闲置收益 {cfg['cash_yield'] * 100:g}%　冲击 {cfg['slippage_bp']:g} 基点/边　"
            f"成交额≥{cfg['min_amount'] / 1e4:g} 万　价≥{cfg['min_price']:g}　起点 {cfg['start']}")


def _fusion_config_text(cfg):
    return (f"z≤{cfg['z_threshold']:g}　每层最多 {cfg['positions']} 只　A {cfg['weight_a'] * 100:g}% · C {cfg['weight_c'] * 100:g}% · B {cfg['weight_b'] * 100:g}%　"
            f"总仓位≤{cfg['gross_cap'] * 100:g}%（不借钱）　持有 {cfg['hold_days']} 日　闲置收益 {cfg['cash_yield'] * 100:g}%　冲击 {cfg['slippage_bp']:g} 基点/边　"
            f"成交额≥{cfg['min_amount'] / 1e4:g} 万　价≥{cfg['min_price']:g}　起点 {cfg['start']}")


def _compare_rows(a, b):
    def get(r):
        s, t, i = r['summary']['stats'] or {}, r['summary']['trades'], r['summary']['info']
        return [_pct(s.get('cagr')), _num(s.get('sharpe')), _pct(s.get('max_drawdown'), 0), _pct(s.get('exposure'), 0, False),
                str(t['n']), _pct(t['win_rate'], 0, False), _pct(t['mean']), _pct(i['min_margin_ratio'], 0, False),
                str(i['n_liquidations']), _num(i['interest'], 2) + '（占初始本金倍数）', _num(r['summary']['final_equity']) + '×']
    names = ['年化收益', '夏普（日收益×√245）', '最大回撤', '平均仓位（占净值）', '交易笔数', '单笔胜率', '单笔平均净收益',
             '最低担保比例', '强平次数', '累计融资利息', '期末净值']
    return list(zip(names, get(a), get(b)))


def result_view(result, panel, *, levered=True):
    """一次回测的完整展示：指标、净值与回撤曲线、年度收益、分时期、风险说明。"""
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    s = result['summary']
    st, tr, info = s['stats'] or {}, s['trades'], s['info']
    lay.addWidget(kpis([
        ('年化收益', _pct(st.get('cagr')), f"等权大盘 {_pct((s['benchmark'] or {}).get('cagr'))}（不计成本）"),
        ('夏普', _num(st.get('sharpe')), '日收益 × √245'),
        ('最大回撤', _pct(st.get('max_drawdown'), 0), '净值从高点回落的最大幅度'),
        ('平均仓位', _pct(st.get('exposure'), 0, False), '持仓市值 / 净值，空仓时为 0')]))
    lay.addWidget(kpis([
        ('交易笔数', str(tr['n']), f"胜率 {_pct(tr['win_rate'], 0, False)}　赔率 {_num(tr['payoff'])}"),
        ('单笔平均净收益', _pct(tr['mean']), f"最差一笔 {_pct(tr['worst'], 0)}"),
        (('最低担保比例', _pct(info['min_margin_ratio'], 0, False), f"强平线 {result['config']['liquidation_line'] * 100:.0f}%，强平 {info['n_liquidations']} 次") if levered else
         ('闲置资金收益', _pct(result['config']['cash_yield'], 1, False) + '/年', '不借钱，没有利息和强平')),
        ('信号', f"{s['gate_days']} 天 / {s['episodes']} 段", '闸门打开的交易日与相隔 5 日以上的段数')]))
    cv = result['curve']
    chart = SeriesChart('净值曲线', log=True, y_format='{:.2f}×')
    chart.set_data([{'name': '策略净值', 'color': '#f6b72f', 'values': cv['equity']},
                    {'name': '等权大盘（不计成本）', 'color': '#5d7182', 'values': cv['benchmark']}], (cv['dates'][0], cv['dates'][-1]))
    card = Card('净值（对数坐标，起点 = 1）')
    card.add(chart)
    lay.addWidget(card)
    dd = result['drawdown']
    worst = min((x, i) for i, x in enumerate(dd) if x is not None)
    ddchart = SeriesChart('回撤曲线', y_format='{:.0%}')
    ddchart.set_data([{'name': '回撤', 'color': '#f35f62', 'values': dd}], (cv['dates'][0], cv['dates'][-1]))
    card = Card(f"回撤（最深 {_pct(worst[0], 0)}，出现在 {cv['dates'][worst[1]]}）")
    card.add(ddchart)
    lay.addWidget(card)
    bars = BarChart('年度收益')
    bars.set_items(list(s['years'].items()))
    card = Card('各年收益（%）')
    card.add(bars)
    lay.addWidget(card)
    lay.addWidget(CalendarCard(cv['dates'], cv['equity'], cv.get('benchmark')))
    eras = [[name, _pct(v and v['cagr']), _num(v and v['sharpe']), _pct(v and v['max_drawdown'], 0), _pct(v and v['exposure'], 0, False)]
            for name, v in s['eras'].items() if v]
    card = Card('分时期')
    card.add(table(['时期', '年化', '夏普', '最大回撤', '平均仓位'], eras))
    lay.addWidget(card)
    risk = Card('风险与口径')
    notes = [f"融资利息累计约为初始本金的 {info['interest']:.2f} 倍；预警线 {result['config']['warn_line'] * 100:.0f}% 以下 {info['n_warn_days']} 天。"] if levered else []
    notes += result['caveats']
    risk.add(label('\n'.join('· ' + n for n in notes), 'muted', True))
    lay.addWidget(risk)
    return host
