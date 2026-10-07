"""策略工作台的收益日历：像同花顺“两融资产分析”那样，年历看每个月赚赔多少，月历看每个交易日赚赔多少。

输入只是一条净值曲线（日期 + 净值，可以带一条对照曲线，如等权大盘），所以回测结果和前向跟踪的组合净值都能用。
红色是赚、蓝色是赔（同花顺的配色），颜色越深幅度越大；非交易日只显示日期。显示的是收益率，不是金额。
"""
import calendar
import math

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QComboBox, QWidget

from .widgets import Card, button, label, row

RED, BLUE, GREY, BG = QColor('#f35f62'), QColor('#4e96ff'), QColor('#8fa4b7'), QColor('#0b1a24')
MONTH_NAMES = ('一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月')
WEEK_HEAD = ('日', '一', '二', '三', '四', '五', '六')


def _finite(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def calendar_stats(dates, values):
    """净值曲线 -> 日 / 月 / 年收益率。

    daily {'YYYY-MM-DD': r}（第一天没有前值，不给）；monthly {(y, m): r}；yearly {y: r}。
    月（年）收益 = 当月（年）最后一个有净值的日子 / 上月（上年）最后一个有净值的日子 - 1，第一个月（年）以曲线第一个值为底。
    缺失（None / NaN）的日子跳过，用前一个有效值接续。
    """
    daily, month_end, year_end = {}, {}, {}
    prev, first = None, None
    for d, v in zip(dates, values):
        if not _finite(v) or v <= 0:
            continue
        if first is None:
            first = float(v)
        if prev is not None:
            daily[d] = v / prev - 1
        prev = float(v)
        y, m = int(d[:4]), int(d[5:7])
        month_end[(y, m)] = prev
        year_end[y] = prev
    monthly, yearly = {}, {}
    last = first
    for k in sorted(month_end):
        monthly[k] = month_end[k] / last - 1 if last else None
        last = month_end[k]
    last = first
    for k in sorted(year_end):
        yearly[k] = year_end[k] / last - 1 if last else None
        last = year_end[k]
    return {'daily': daily, 'monthly': monthly, 'yearly': yearly}


def _pct(x, digits=1):
    return '—' if not _finite(x) else f'{x * 100:+.{digits}f}%'


class CalendarChart(QWidget):
    """画年历（4 × 3 个月份格）或月历（周日到周六）。点年历里的月份格会跳到那个月的月历（通过 on_pick_month 回调）。"""

    def __init__(self, name='收益日历', height=380):
        super().__init__()
        self.setAccessibleName(name)
        self.setMinimumHeight(height)
        self.view, self.year, self.month = 'year', None, None
        self.stats = {'daily': {}, 'monthly': {}, 'yearly': {}}
        self.on_pick_month = None
        self._cells = []

    def set_state(self, stats, view, year, month):
        self.stats, self.view, self.year, self.month = stats, view, year, month
        self.update()

    @staticmethod
    def _fill(r, scale):
        if not _finite(r):
            return None
        c = QColor(RED if r >= 0 else BLUE)
        c.setAlphaF(0.30 + 0.70 * min(abs(r) / scale, 1.0) if scale else 0.5)
        return c

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        self._cells = []
        if self.year is None:
            p.setPen(GREY)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '暂无数据')
            return
        (self._paint_year if self.view == 'year' else self._paint_month)(p)

    def _tile(self, p, rect, top, bottom, fill, strong=True):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill if fill is not None else QColor('#112533'))
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QColor('#e8f0f6') if fill is not None else GREY)
        f = QFont(p.font())
        f.setPointSizeF(10)
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(rect.left(), rect.top() + 6, rect.width(), rect.height() * 0.45),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, top)
        if bottom:
            f.setBold(strong)
            p.setFont(f)
            p.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.45, rect.width(), rect.height() * 0.45),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, bottom)

    def _paint_year(self, p):
        gap, cols, rows = 4, 4, 3
        w, h = (self.width() - 16 - gap * (cols - 1)) / cols, (self.height() - 16 - gap * (rows - 1)) / rows
        vals = [self.stats['monthly'].get((self.year, m)) for m in range(1, 13)]
        scale = max([abs(v) for v in vals if _finite(v)] or [0.0])
        for i in range(12):
            r, c = divmod(i, cols)
            rect = QRectF(8 + c * (w + gap), 8 + r * (h + gap), w, h)
            v = vals[i]
            self._tile(p, rect, MONTH_NAMES[i], _pct(v) if _finite(v) else '-', self._fill(v, scale))
            self._cells.append((rect, i + 1))

    def _paint_month(self, p):
        gap = 3
        weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(self.year, self.month)
        head = 22
        w = (self.width() - 16 - gap * 6) / 7
        h = (self.height() - 16 - head - gap * len(weeks)) / len(weeks)
        p.setPen(GREY)
        for c, name in enumerate(WEEK_HEAD):
            p.drawText(QRectF(8 + c * (w + gap), 6, w, head), Qt.AlignmentFlag.AlignCenter, name)
        prefix = f'{self.year:04d}-{self.month:02d}'
        days = {k: v for k, v in self.stats['daily'].items() if k[:7] == prefix}
        scale = max([abs(v) for v in days.values()] or [0.0])
        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if not day:
                    continue
                rect = QRectF(8 + c * (w + gap), 8 + head + r * (h + gap), w, h)
                v = days.get(f'{prefix}-{day:02d}')
                self._tile(p, rect, f'{day:02d}', _pct(v, 2) if _finite(v) else '', self._fill(v, scale), strong=False)

    def mousePressEvent(self, event):
        if self.view != 'year' or self.on_pick_month is None:
            return
        pos = event.position()
        for rect, month in self._cells:
            if rect.contains(pos):
                self.on_pick_month(month)
                return


class CalendarCard(Card):
    """带控件的收益日历卡片：年历 / 月历切换、上一期 / 下一期、期末汇总（可带一条对照曲线）。"""

    def __init__(self, dates, equity, benchmark=None, bench_name='等权大盘（不计成本）', title='收益日历'):
        super().__init__(title)
        self.stats = calendar_stats(dates, equity)
        self.bench = calendar_stats(dates, benchmark) if benchmark else None
        self.bench_name = bench_name
        self.months = sorted(self.stats['monthly'])
        self.chart = CalendarChart()
        self.chart.on_pick_month = self.pick_month
        self.view_box = QComboBox()
        self.view_box.setAccessibleName('日历视图')
        self.view_box.addItem('年历（看每月）', 'year')
        self.view_box.addItem('月历（看每天）', 'month')
        self.view_box.currentIndexChanged.connect(lambda _: self.set_view(self.view_box.currentData()))
        self.prev_button = button('‹', lambda: self.step(-1))
        self.next_button = button('›', lambda: self.step(1))
        self.prev_button.setFixedWidth(40)
        self.next_button.setFixedWidth(40)
        self.prev_button.setAccessibleName('上一期')
        self.next_button.setAccessibleName('下一期')
        self.period = label('', 'panelTitle')
        self.period.setAccessibleName('日历期间')
        self.summary = label('', 'muted', True)
        self.summary.setAccessibleName('日历汇总')
        self.view = 'year'
        self.year, self.month = self.months[-1] if self.months else (None, None)
        bar = row(self.view_box, self.prev_button, self.period, self.next_button)
        bar.layout().addStretch(1)
        self.add(bar)
        self.add(self.chart)
        self.add(self.summary)
        self.add(label('红色赚、蓝色赔，颜色越深幅度越大；显示的是收益率（月 / 年按期末净值相对上期末），不是金额。'
                       '年历里点一个月可以直接看那个月的每日收益。', 'muted', True))
        self.refresh()

    def set_view(self, view):
        if view in ('year', 'month') and view != self.view:
            self.view = view
            self.view_box.blockSignals(True)
            self.view_box.setCurrentIndex(0 if view == 'year' else 1)
            self.view_box.blockSignals(False)
            self.refresh()

    def pick_month(self, month):
        if (self.year, month) in self.stats['monthly']:
            self.month = month
            self.set_view('month')

    def step(self, delta):
        if self.year is None:
            return
        if self.view == 'year':
            years = sorted({y for y, _ in self.months})
            self.year = min(max(self.year + delta, years[0]), years[-1])
        else:
            i = self.months.index((self.year, self.month)) if (self.year, self.month) in self.months else len(self.months) - 1
            self.year, self.month = self.months[min(max(i + delta, 0), len(self.months) - 1)]
        self.refresh()

    def refresh(self):
        if self.year is None:
            self.period.setText('暂无数据')
            self.summary.setText('')
            self.chart.set_state(self.stats, self.view, None, None)
            return
        if self.view == 'year':
            self.period.setText(f'{self.year} 年')
            own = self.stats['yearly'].get(self.year)
            other = self.bench['yearly'].get(self.year) if self.bench else None
            text = f'{self.year} 年收益：{_pct(own)}'
        else:
            self.period.setText(f'{self.year} 年 {self.month} 月')
            own = self.stats['monthly'].get((self.year, self.month))
            other = self.bench['monthly'].get((self.year, self.month)) if self.bench else None
            text = f'{self.month} 月累计收益：{_pct(own)}'
        if self.bench:
            text += f'　　{self.bench_name}：{_pct(other)}'
        self.summary.setText(text)
        self.chart.set_state(self.stats, self.view, self.year, self.month)
