"""Shared synthetic Baostock fixtures for limit-board research tests (not a test module)."""
from datetime import date, timedelta

from quantlab.data.retro_daily import BASIC_FIELDS, CALENDAR_FIELDS, FIELDS


class Resp:
    def __init__(self, fields, rows, error_code='0'):
        self.fields = list(fields); self.rows = [list(r) for r in rows]; self.i = -1; self.error_code = error_code; self.error_msg = ''
    def next(self):
        self.i += 1; return self.i < len(self.rows)
    def get_row_data(self):
        return list(self.rows[self.i])


START = date(2026, 8, 3)
CAL = []
day = START
while len(CAL) < 40:
    CAL.append(day); day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
CAL_ROWS = []
d = START
while d <= CAL[-1]:
    CAL_ROWS.append((d.isoformat(), '1' if d in CAL else '0')); d += timedelta(days=1)


def T(i):
    return CAL[i - 1]


def row(i, code, o, h, l, c, pre, status='1', st='0'):
    if status == '0':
        return (T(i).isoformat(), code, str(pre), str(pre), str(pre), str(pre), str(pre), '0', '', '3', '', '0', '0', st)
    return (T(i).isoformat(), code, str(o), str(h), str(l), str(c), str(pre), '1000', str(1000 * c), '3', '1.2', '1',
            str(round((c / pre - 1) * 100, 4)), st)


def flat_path(code, days, price, overrides):
    rows, pre = [], price
    for i in days:
        if i in overrides:
            spec = overrides[i]
            if spec == 'suspend':
                rows.append(row(i, code, 0, 0, 0, 0, pre, status='0')); continue
            o, h, l, c = spec
            rows.append(row(i, code, o, h, l, c, pre)); pre = c
        else:
            rows.append(row(i, code, pre, pre, pre, pre, pre))
    return rows


def bars():
    b = {}
    b['sh.600001'] = flat_path('sh.600001', range(1, 41), 10.0, {
        26: (10.2, 11.0, 10.1, 11.0), 27: (12.1, 12.1, 12.1, 12.1), 28: (12.2, 13.31, 12.0, 12.5), 29: (12.5, 12.8, 12.4, 12.7)})
    b['sz.300001'] = flat_path('sz.300001', range(1, 41), 10.0, {10: (10.5, 12.0, 10.4, 12.0), 11: 'suspend'})
    star = flat_path('sh.688001', range(5, 41), 10.0, {5: (15.0, 25.0, 14.0, 20.0), 6: (21.0, 30.0, 20.0, 28.0), 10: (28.5, 33.6, 28.0, 33.6)})
    b['sh.688001'] = star
    b['sz.000002'] = flat_path('sz.000002', range(1, 38), 5.0, {20: (5.1, 5.5, 5.0, 5.5)})
    b['sh.600003'] = flat_path('sh.600003', range(1, 41), 10.0, {15: (9.8, 9.9, 9.0, 9.0)})
    b['sh.600004'] = flat_path('sh.600004', range(1, 41), 10.0, {12: (10.2, 11.5, 10.1, 10.8)})
    return b


BASIC = [('sh.600001', 'A', '2000-01-01', '', '1', '1'), ('sz.300001', 'B', '2010-01-01', '', '1', '1'),
         ('sh.688001', 'C', T(5).isoformat(), '', '1', '1'), ('sz.000002', 'D', '2001-01-01', T(38).isoformat(), '1', '0'),
         ('sh.600003', 'E', '2002-01-01', '', '1', '1'), ('sh.600004', 'F', '2003-01-01', '', '1', '1')]


class FakeSDK:
    __version__ = '0.9.3'
    def __init__(self, bars_=None, basic=None):
        self.b = bars() if bars_ is None else bars_; self.basic = BASIC if basic is None else basic
    def login(self):
        return Resp((), [])
    def logout(self):
        pass
    def query_stock_basic(self):
        return Resp(BASIC_FIELDS, self.basic)
    def query_trade_dates(self, start_date, end_date):
        return Resp(CALENDAR_FIELDS, [r for r in CAL_ROWS if start_date <= r[0] <= end_date])
    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        return Resp(FIELDS, [r for r in self.b.get(code, []) if start_date <= r[0] <= end_date])
