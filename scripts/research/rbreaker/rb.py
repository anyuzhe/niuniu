"""R-Breaker 人工验证（用户 2026-10-12 要求验证 R-Breaker 视频笔记；不是牛牛助手自主研究，只作验证复算用）。

线的公式有两个公开版本：
  pivot   笔记里的版本（和 BigQuant / 信易的枢轴点版一致）：P=(H+L+C)/3，Bbreak=H+2(P-L)，Ssetup=P+(H-L)，Senter=2P-L，
          Benter=2P-H，Bsetup=P-(H-L)，Sbreak=L-2(H-P)；
  classic 另一个常见版本（系数 0.35 / 0.07 / 0.25，未调优）：Ssetup=H+0.35(C-L)，Bsetup=L-0.35(H-C)，
          Senter=1.07/2(H+L)-0.07L，Benter=1.07/2(H+L)-0.07H，Bbreak=Ssetup+0.25(Ssetup-Bsetup)，Sbreak=Bsetup-0.25(Ssetup-Bsetup)。
无未来函数：前一交易日的 H/L/C 算线；盘中在某根 5 分钟线收盘后判断，下一根开盘价成交；收盘前最后一根按收盘价了结。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LINES = ('Bbreak', 'Ssetup', 'Senter', 'Benter', 'Bsetup', 'Sbreak')


def lines(h, l, c, variant='pivot'):
    """前一交易日 H/L/C（标量或数组）→ 六条线的 dict。"""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    if variant == 'pivot':
        p = (h + l + c) / 3
        return dict(Bbreak=h + 2 * (p - l), Ssetup=p + (h - l), Senter=2 * p - l,
                    Benter=2 * p - h, Bsetup=p - (h - l), Sbreak=l - 2 * (h - p))
    if variant == 'classic':
        ss = h + 0.35 * (c - l)
        bs = l - 0.35 * (h - c)
        return dict(Bbreak=ss + 0.25 * (ss - bs), Ssetup=ss, Senter=1.07 / 2 * (h + l) - 0.07 * l,
                    Benter=1.07 / 2 * (h + l) - 0.07 * h, Bsetup=bs, Sbreak=bs - 0.25 * (ss - bs))
    raise ValueError(variant)


@dataclass
class Trade:
    kind: str          # brk_long / brk_short / rev_long / rev_short（开仓那一刻的触发规则）
    entry_i: int
    exit_i: int
    entry: float
    exit: float
    side: int          # +1 多 / -1 空
    at_close: bool = False   # True：收盘前被动了结（按最后一根收盘价）；False：反转平仓（按下一根开盘价）

    @property
    def ret(self):
        return self.side * (self.exit / self.entry - 1.0)


def run_day(o, h, l, c, ln, *, allow_short=True, allow_rev=True, allow_brk=True, first_entry=1):
    """一天的原版状态机（日内，收盘前平掉）。o/h/l/c 是当天按时间排好的 5 分钟线；ln 是 lines() 的标量 dict。
    在第 i 根收盘后判断，第 i+1 根开盘价成交；最后一根只用来了结（收盘价）。first_entry：最早在第几根收盘后才允许判断（默认 1，即 09:40 起）。"""
    n = len(c)
    trades, pos, kind, ent_i, ent_px = [], 0, None, 0, 0.0
    dayhigh, daylow = -np.inf, np.inf
    for i in range(n - 1):
        dayhigh = max(dayhigh, h[i])
        daylow = min(daylow, l[i])
        if i < first_entry - 1:
            continue
        px = c[i]
        if pos == 0:
            if allow_brk and px > ln['Bbreak']:
                pos, kind, ent_i, ent_px = 1, 'brk_long', i + 1, o[i + 1]
            elif allow_brk and allow_short and px < ln['Sbreak']:
                pos, kind, ent_i, ent_px = -1, 'brk_short', i + 1, o[i + 1]
        elif allow_rev and pos > 0 and dayhigh > ln['Ssetup'] and px < ln['Senter']:
            trades.append(Trade(kind, ent_i, i + 1, ent_px, o[i + 1], 1))
            if allow_short:
                pos, kind, ent_i, ent_px = -1, 'rev_short', i + 1, o[i + 1]
            else:
                pos = 0
        elif allow_rev and pos < 0 and daylow < ln['Bsetup'] and px > ln['Benter']:
            trades.append(Trade(kind, ent_i, i + 1, ent_px, o[i + 1], -1))
            pos, kind, ent_i, ent_px = 1, 'rev_long', i + 1, o[i + 1]
    if pos != 0:
        trades.append(Trade(kind, ent_i, n - 1, ent_px, c[n - 1], pos, True))
    return trades


def first_rev_long(o, h, l, c, ln, first_entry=1):
    """只做“杀跌失败”的多头反转（空仓也算，用于只能做多的 A 股）：当天最低先跌破 Bsetup，之后收盘价升破 Benter。返回 (信号根, 成交价) 或 None。"""
    n = len(c)
    daylow = np.inf
    for i in range(n - 1):
        daylow = min(daylow, l[i])
        if i >= first_entry - 1 and daylow < ln['Bsetup'] and c[i] > ln['Benter']:
            return i, o[i + 1]
    return None


def first_brk_long(o, h, l, c, ln, first_entry=1):
    n = len(c)
    for i in range(first_entry - 1, n - 1):
        if c[i] > ln['Bbreak']:
            return i, o[i + 1]
    return None


def first_true(cond):
    """每行第一个 True 的列号，没有则 -1。"""
    return np.where(cond.any(1), cond.argmax(1), -1)


def first_brk_long_mat(c, bbreak):
    """矩阵版 first_brk_long：c 是 (天 × 根)，bbreak 是 (天,)；返回每天的信号根（-1 = 没有）。first_entry=1。"""
    return first_true(c[:, :-1] > np.asarray(bbreak)[:, None])


def first_rev_long_mat(l, c, bsetup, benter):
    """矩阵版 first_rev_long。"""
    daylow = np.minimum.accumulate(l, axis=1)[:, :-1]
    return first_true((daylow < np.asarray(bsetup)[:, None]) & (c[:, :-1] > np.asarray(benter)[:, None]))
