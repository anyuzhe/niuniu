"""恐慌日抄底：信号定义、组合回测引擎（含融资杠杆）、统计。纯函数，不读文件、不联网。

策略（全部出自 docs/archive/testing/20260930-低频抄底扣成本重测与ETF.md）：
  闸门  等权大盘 20 日涨跌 mk20 除以 (近 60 日大盘日波动 x sqrt(20)) = z，z <= 阈值（默认 -1.5）才允许开仓。
  选股  个股布林下轨收复 E6：昨收 < 昨日下轨(MA20-2σ)，今收 > 今日下轨且收阳；候选须非 ST、可交易、上市满 250 日、
        20 日均成交额 >= 5000 万、原始价 >= 3 元。
  排序  20 日跌幅最大的在前（研究里排序大部分是贝塔，不是选股能力）。
  仓位  N 只等权，单只 = 杠杆 x 净值 / N；信号日收盘后决定，次日开盘买，持有 hold_days 个交易日后收盘卖。
  成本  印花税/佣金按年代，每边再加 1 个最小价位 0.01 元；可另加冲击成本。
  杠杆  借款按年代融资利率日计息；担保比例 = 持仓市值 / 负债，低于平仓线全部卖出。
结果是历史回测，不保证未来；面板只含现存股票（幸存者偏差），见文档。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields

import numpy as np

from quantlab.dipbuy.panel import Cancelled, DipDataError, Panel

ENGINE_VERSION = 'dipbuy-engine-1'
DAYS_PER_YEAR = 245
MARKET_MIN_AMOUNT = 5e7        # 大盘等权指数的流动性股票池，固定，不随沙盒参数变化
MARKET_MIN_LISTED = 80
CANDIDATE_MIN_LISTED = 250
Z_WINDOW = 60
BOLL_WINDOW = 20
BLOCK = 600
RANKS = {'drop20': '20 日跌幅最大优先', 'random': '随机（对照）'}
ERAS = (('2008-11', '2008-01-01', '2011-12-31'), ('2012-16', '2012-01-01', '2016-12-31'),
        ('2017-19', '2017-01-01', '2019-12-31'), ('2020-26', '2020-01-01', '2026-12-31'))


@dataclass(frozen=True)
class DipConfig:
    z_threshold: float = -1.5
    positions: int = 20
    hold_days: int = 20
    leverage: float = 2.0
    rank: str = 'drop20'
    seed: int = 7
    cash_yield: float = 0.0            # 闲置资金年化收益（货基/逆回购），0 = 不计
    financing_rate: float | None = None    # None = 按年代：2020 前 8.5%，2020-22 7%，2023 起 6%
    liquidation_line: float = 1.3
    warn_line: float = 1.5
    min_amount: float = 5e7            # 候选股 20 日均成交额下限（元）
    min_price: float = 3.0             # 候选股原始价下限（元）
    slippage_bp: float = 0.0           # 每边额外冲击成本（基点）
    start: str = '2008-01-01'
    end: str | None = None
    require_exit: bool = False         # 研究脚本只挑“20 天后一定有收盘价”的票（带一点前视）；产品默认关

    def __post_init__(self):
        checks = (
            (-4.0 <= self.z_threshold <= 0.0, 'z 阈值应在 -4 到 0 之间'),
            (1 <= self.positions <= 100, '持仓只数应在 1 到 100 之间'),
            (1 <= self.hold_days <= 60, '持有天数应在 1 到 60 之间'),
            (0.5 <= self.leverage <= 3.0, '杠杆应在 0.5 到 3 倍之间'),
            (self.rank in RANKS, '排序方式不认识'),
            (0.0 <= self.cash_yield <= 0.1, '闲置资金收益应在 0 到 10% 之间'),
            (self.financing_rate is None or 0.0 <= self.financing_rate <= 0.3, '融资利率应在 0 到 30% 之间'),
            (1.0 <= self.liquidation_line <= 2.0, '平仓线应在 100% 到 200% 之间'),
            (self.liquidation_line <= self.warn_line, '预警线不能低于平仓线'),
            (0.0 <= self.min_amount <= 1e10, '成交额下限不合理'),
            (0.0 <= self.min_price <= 1000.0, '价格下限不合理'),
            (0.0 <= self.slippage_bp <= 200.0, '冲击成本应在 0 到 200 基点之间'),
        )
        for ok, message in checks:
            if not ok:
                raise ValueError(message)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> 'DipConfig':
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (value or {}).items() if k in known})

    def hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256((ENGINE_VERSION + blob).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- 特征
@dataclass
class Market:
    mret: np.ndarray       # 等权大盘日收益
    mk20: np.ndarray       # 大盘 20 日涨跌
    z: np.ndarray          # 标准化后的 20 日涨跌
    count: np.ndarray      # 当天进入大盘指数的股票数


@dataclass
class Candidates:
    uni: np.ndarray        # bool 候选池（可交易、非 ST、上市满 250 日、流动性、价格）
    e6: np.ndarray         # bool 布林下轨收复
    buyok: np.ndarray      # bool 次日开盘不是涨停、次日可交易
    ret20: np.ndarray      # float32 20 日涨跌（排序用，越小跌得越多）


def _rollsum(x: np.ndarray, n: int) -> np.ndarray:
    z = np.where(np.isfinite(x), x, 0.0).astype(np.float64)
    cs = np.cumsum(z, 0)
    out = np.full(x.shape, np.nan)
    out[n - 1] = cs[n - 1]
    out[n:] = cs[n:] - cs[:-n]
    return out


def _limit_rates(panel: Panel, cols: slice) -> np.ndarray:
    codes = panel.codes[cols]
    lim = np.full((len(panel.dates), len(codes)), 0.1, np.float32)
    is30 = np.char.startswith(codes, 'sz.30')
    is688 = np.char.startswith(codes, 'sh.688')
    lim[np.ix_(panel.dates >= '2020-08-24', is30)] = 0.2
    lim[:, is688] = 0.2
    return lim


def compute_features(panel: Panel, min_amount: float = 5e7, min_price: float = 3.0, *, progress=None, stop=None):
    """返回 (Market, Candidates)。按列分块算，内存只多出几个布尔矩阵。同一个面板同样参数只算一次。"""
    key = ('features', float(min_amount), float(min_price))
    if key in panel.cache:
        return panel.cache[key]
    nd, nc = panel.shape
    sum_r = np.zeros(nd)
    cnt = np.zeros(nd)
    uni = np.zeros((nd, nc), bool)
    e6 = np.zeros((nd, nc), bool)
    buyok = np.zeros((nd, nc), bool)
    ret20 = np.full((nd, nc), np.nan, np.float32)
    for b0 in range(0, nc, BLOCK):
        if stop is not None and stop.is_set():
            raise Cancelled()
        if progress:
            progress(b0, nc, '计算信号')
        s = slice(b0, min(nc, b0 + BLOCK))
        c = panel.c[:, s].astype(np.float64)
        o = panel.o[:, s].astype(np.float64)
        f = panel.f[:, s].astype(np.float64)
        a = panel.a[:, s]
        st = panel.st[:, s]
        ts = panel.ts[:, s]
        finite_c = np.isfinite(c)
        n_listed = np.cumsum(finite_c, 0)
        amt20 = _rollsum(a, 20) / 20
        # 大盘等权指数的股票池
        r = np.full(c.shape, np.nan)
        r[1:] = c[1:] / c[:-1] - 1
        um = finite_c & (ts == 1) & ~st & (n_listed >= MARKET_MIN_LISTED) & (amt20 >= MARKET_MIN_AMOUNT) & np.isfinite(r)
        sum_r += np.where(um, r, 0.0).sum(1)
        cnt += um.sum(1)
        # 候选池
        fin = finite_c & np.isfinite(o) & (ts == 1)
        raw = c / f
        u = fin & ~st & (n_listed >= CANDIDATE_MIN_LISTED) & (amt20 >= min_amount) & (raw >= min_price)
        s1 = _rollsum(c, BOLL_WINDOW)
        s2 = _rollsum(c ** 2, BOLL_WINDOW)
        ma = s1 / BOLL_WINDOW
        sd = np.sqrt(np.maximum(s2 / BOLL_WINDOW - ma * ma, 0) * BOLL_WINDOW / (BOLL_WINDOW - 1))
        blo = ma - 2 * sd
        prev_c = np.full(c.shape, np.nan)
        prev_c[1:] = c[:-1]
        prev_blo = np.full(c.shape, np.nan)
        prev_blo[1:] = blo[:-1]
        with np.errstate(invalid='ignore'):
            e = (prev_c < prev_blo) & (c > blo) & (c > o) & u
        uni[:, s] = u
        e6[:, s] = e
        gap = np.full(c.shape, np.nan)
        gap[:-1] = o[1:] / c[:-1] - 1
        lim = _limit_rates(panel, s)
        ok = np.zeros(c.shape, bool)
        with np.errstate(invalid='ignore'):
            ok[:-1] = fin[1:] & ~(gap[:-1] >= lim[:-1] - 0.0025)
        buyok[:, s] = ok
        rr = np.full(c.shape, np.nan)
        rr[20:] = c[20:] / c[:-20] - 1
        ret20[:, s] = rr
    mret = np.where(cnt > 0, sum_r / np.maximum(cnt, 1), 0.0)
    idx = np.cumprod(1 + mret)
    mk20 = np.full(nd, np.nan)
    mk20[20:] = idx[20:] / idx[:-20] - 1
    sd60 = np.full(nd, np.nan)
    if nd >= Z_WINDOW:
        win = np.lib.stride_tricks.sliding_window_view(mret, Z_WINDOW)
        sd60[Z_WINDOW - 1:] = win.std(axis=1, ddof=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        z = mk20 / (sd60 * np.sqrt(20))
    out = (Market(mret=mret, mk20=mk20, z=z, count=cnt), Candidates(uni=uni, e6=e6, buyok=buyok, ret20=ret20))
    panel.cache[key] = out
    if progress:
        progress(nc, nc, '信号完成')
    return out


# ---------------------------------------------------------------- 成本与利率
def _fee_by_day(dates: np.ndarray) -> np.ndarray:
    stamp = np.where(dates < '2008-09-19', 0.003, np.where(dates < '2023-08-28', 0.001, 0.0005))
    comm = np.where(dates < '2015-01-01', 0.0006, np.where(dates < '2020-01-01', 0.0004, 0.00022))
    return stamp + comm


def _rate_by_day(dates: np.ndarray, override) -> np.ndarray:
    if override is not None:
        return np.full(len(dates), float(override))
    return np.where(dates < '2020-01-01', 0.085, np.where(dates < '2023-01-01', 0.07, 0.06))


def _exit_index(c: np.ndarray, j: int, x0: int, nd: int):
    """第 x0 天收盘价缺失就顺延最多 3 天；仍没有就用此前最后一个收盘价（视作停牌卡住，按原价平仓）。"""
    for k in range(4):
        i = x0 + k
        if i >= nd:
            return None
        if np.isfinite(c[i, j]):
            return i, float(c[i, j])
    for i in range(x0 - 1, -1, -1):
        if np.isfinite(c[i, j]):
            return x0, float(c[i, j])
    return None


# ---------------------------------------------------------------- 回测
def simulate(panel: Panel, market: Market, cand: Candidates, cfg: DipConfig, *, progress=None, stop=None) -> dict:
    nd, nc = panel.shape
    dates, c, o, f = panel.dates, panel.c, panel.o, panel.f
    H, N, L = cfg.hold_days, cfg.positions, cfg.leverage
    z = market.z
    gate = np.isfinite(z) & (z <= cfg.z_threshold)
    t0 = int(np.searchsorted(dates, cfg.start))
    tend = nd - 1 if cfg.end is None else int(np.searchsorted(dates, cfg.end, side='right')) - 1
    tend = min(tend, nd - 1)
    if t0 >= tend:
        raise DipDataError('回测区间内没有数据')
    fee = _fee_by_day(dates)
    rate = _rate_by_day(dates, cfg.financing_rate)
    rng = np.random.default_rng(cfg.seed)
    slip = cfg.slippage_bp / 1e4
    cash = 1.0
    active: list[dict] = []
    trades: list[dict] = []
    eq = np.full(nd, np.nan)
    expo = np.zeros(nd)
    interest = earned = 0.0
    liq_days: list[str] = []
    n_warn = 0
    min_ratio = 9.0
    peak_debt = 0.0
    frozen = False
    ret20 = cand.ret20
    for t in range(t0, tend + 1):
        if stop is not None and stop.is_set():
            raise Cancelled()
        if progress and t % 250 == 0:
            progress(t - t0, tend - t0, '回测')
        if frozen:
            eq[t] = eq[t - 1]
            continue
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net'])
            trades.append(_trade_row(panel, p, closed='exit'))
            active.remove(p)
        slots = N - len(active)
        if slots > 0 and gate[t] and t + 1 <= min(tend, nd - 1):
            pool = np.nonzero(cand.e6[t] & cand.buyok[t])[0]
            if len(pool):
                held = {p['j'] for p in active}
                pool = np.array([j for j in pool if j not in held], dtype=int)
                if cfg.require_exit and len(pool):
                    pool = np.array([j for j in pool if t + H < nd and np.isfinite(c[t + H:t + H + 4, j]).any()], dtype=int)
                if len(pool):
                    if cfg.rank == 'random':
                        rng.shuffle(pool)
                    else:
                        pool = pool[np.argsort(ret20[t, pool], kind='stable')]
                    invested = sum(p['v'] for p in active)
                    equity = cash + invested
                    for j in pool[:slots]:
                        size = min(L * equity / N, L * equity - invested)
                        if size <= 1e-9:
                            break
                        cash -= size
                        invested += size
                        e = t + 1
                        o0 = float(o[e, j])
                        raw_e = o0 / float(f[e, j])
                        ex = _exit_index(c, j, t + H, nd)
                        pos = dict(j=int(j), sig=t, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None,
                                   px_x=None, last=o0)
                        if ex is not None:
                            xi, px = ex
                            raw_x = px / float(f[xi, j])
                            pos['net'] = (px * (1 - 0.01 / raw_x - slip)) / (o0 * (1 + 0.01 / raw_e + slip)) - 1 - fee[xi]
                            pos['px_x'] = px
                            pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2 + slip
                        else:
                            pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2 + slip
                        active.append(pos)
        if cash < 0:
            ic = -cash * rate[t] / 242.0
            cash -= ic
            interest += ic
        elif cash > 0 and cfg.cash_yield > 0:
            ey = cash * cfg.cash_yield / 242.0
            cash += ey
            earned += ey
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = c[t, p['j']]
                if np.isfinite(ct):
                    p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        tot = cash + vs
        debt = max(-cash, 0.0)
        if debt > 1e-9:
            peak_debt = max(peak_debt, debt / max(tot, 1e-9))
            ratio = (vs + max(cash, 0.0)) / debt
            min_ratio = min(min_ratio, ratio)
            if ratio < cfg.warn_line:
                n_warn += 1
            if ratio < cfg.liquidation_line:
                cash = cash + vs * (1 - 0.003)
                liq_days.append(str(dates[t]))
                for p in active:
                    trades.append(_trade_row(panel, p, closed='liquidated', day=t))
                active = []
                tot, vs = cash, 0.0
        eq[t] = tot
        expo[t] = vs / max(tot, 1e-9)
        if tot <= 0.02:
            frozen = True
    open_positions = [_open_row(panel, p, tend) for p in active]
    info = dict(interest=interest, cash_earned=earned, n_liquidations=len(liq_days), liquidation_days=liq_days,
                min_margin_ratio=None if min_ratio == 9.0 else min_ratio, n_warn_days=n_warn, peak_debt_ratio=peak_debt,
                ruined=frozen)
    return dict(eq=eq, expo=expo, trades=trades, open_positions=open_positions, info=info, gate=gate,
                t0=t0, tend=tend)


def _trade_row(panel: Panel, p: dict, *, closed: str, day: int | None = None) -> dict:
    j = p['j']
    if closed == 'exit':
        ret = p['net']
        exit_day = str(panel.dates[p['x']])
    else:
        ret = p['v'] / p['inv'] - 1
        exit_day = str(panel.dates[day])
    return dict(code=str(panel.codes[j]), signal=str(panel.dates[p['sig']]), entry=str(panel.dates[p['e']]),
                exit=exit_day, weight=p['inv'], ret=float(ret), closed=closed,
                entry_px=float(p['o0'] / panel.f[p['e'], j]))


def _open_row(panel: Panel, p: dict, t: int) -> dict:
    j = p['j']
    return dict(code=str(panel.codes[j]), signal=str(panel.dates[p['sig']]), entry=str(panel.dates[p['e']]),
                weight=p['inv'], mtm=float(p['v'] / p['inv'] - 1), days_held=int(max(0, t - p['e'] + 1)))


# ---------------------------------------------------------------- 统计
def period_stats(dates, eq, expo, a, b):
    m = (dates >= a) & (dates <= b) & np.isfinite(eq)
    idx = np.nonzero(m)[0]
    if len(idx) < 50:
        return None
    e = eq[idx]
    r = e[1:] / e[:-1] - 1
    years = len(r) / DAYS_PER_YEAR
    cagr = (e[-1] / e[0]) ** (1 / years) - 1 if e[-1] > 0 else -1.0
    dd = float((e / np.maximum.accumulate(e) - 1).min())
    sharpe = float(r.mean() / (r.std() + 1e-12) * np.sqrt(DAYS_PER_YEAR))
    return dict(cagr=float(cagr), sharpe=sharpe, max_drawdown=dd, exposure=float(expo[idx].mean()),
                total=float(e[-1] / e[0] - 1), days=int(len(idx)))


def episodes(gate_days: np.ndarray, gap: int = 5) -> list[tuple[int, int]]:
    idx = np.nonzero(gate_days)[0]
    out: list[tuple[int, int]] = []
    for i in idx:
        if out and i - out[-1][1] <= gap:
            out[-1] = (out[-1][0], int(i))
        else:
            out.append((int(i), int(i)))
    return out


def summarize(panel: Panel, market: Market, result: dict, cfg: DipConfig) -> dict:
    dates, eq, expo = panel.dates, result['eq'], result['expo']
    t0, tend = result['t0'], result['tend']
    whole = period_stats(dates, eq, expo, str(dates[t0]), str(dates[tend]))
    eras = {name: period_stats(dates, eq, expo, a, b) for name, a, b in ERAS}
    years = {}
    for y in sorted({d[:4] for d in dates[t0:tend + 1]}):
        ii = np.nonzero((np.char.startswith(dates, y)) & np.isfinite(eq))[0]
        if len(ii) >= 20:
            years[y] = float(eq[ii[-1]] / eq[ii[0]] - 1)
    trades = result['trades']
    rets = np.array([t['ret'] for t in trades]) if trades else np.zeros(0)
    pos = rets[rets > 0]
    neg = rets[rets <= 0]
    gate = result['gate'][t0:tend + 1]
    eps = episodes(result['gate'][t0:tend + 1])
    bench = np.cumprod(1 + market.mret)
    bench_stats = period_stats(dates, bench, np.ones(len(dates)), str(dates[t0]), str(dates[tend]))
    final = float(eq[tend]) if np.isfinite(eq[tend]) else None
    return dict(
        stats=whole, eras=eras, years=years, benchmark=bench_stats,
        trades=dict(n=int(len(rets)), mean=float(rets.mean()) if len(rets) else None,
                    win_rate=float((rets > 0).mean()) if len(rets) else None,
                    payoff=float(pos.mean() / -neg.mean()) if len(pos) and len(neg) and neg.mean() < 0 else None,
                    worst=float(rets.min()) if len(rets) else None),
        gate_days=int(gate.sum()), episodes=len(eps), final_equity=final,
        open_positions=result['open_positions'], info=result['info'])


def curve(panel: Panel, market: Market, result: dict, every: int = 1) -> dict:
    t0, tend = result['t0'], result['tend']
    sl = slice(t0, tend + 1, every)
    bench = np.cumprod(1 + market.mret)
    eq = result['eq']
    return dict(dates=[str(d) for d in panel.dates[sl]],
                equity=[None if not np.isfinite(v) else round(float(v), 5) for v in eq[sl]],
                benchmark=[round(float(v / bench[t0]), 5) for v in bench[sl]],
                exposure=[round(float(v), 4) for v in result['expo'][sl]],
                z=[None if not np.isfinite(v) else round(float(v), 3) for v in market.z[sl]])


def drawdown_series(equity) -> list:
    e = np.array([np.nan if v is None else v for v in equity], float)
    peak = np.fmax.accumulate(np.where(np.isfinite(e), e, 0))
    with np.errstate(invalid='ignore', divide='ignore'):
        dd = np.where(peak > 0, e / peak - 1, np.nan)
    return [None if not np.isfinite(v) else round(float(v), 4) for v in dd]


# ---------------------------------------------------------------- 当日信号
def latest_signal(panel: Panel, market: Market, cand: Candidates, cfg: DipConfig, *, equity: float | None = None,
                  day: str | None = None, names: dict | None = None, top: int | None = None) -> dict:
    """某个交易日收盘后的信号。day 缺省为面板最后一天。equity 给了就换算成每只的计划金额和股数。"""
    t = panel.index_of(day) if day else len(panel.dates) - 1
    zt = float(market.z[t]) if np.isfinite(market.z[t]) else None
    gate_open = zt is not None and zt <= cfg.z_threshold
    pool = np.nonzero(cand.e6[t])[0]
    if cfg.rank == 'random':
        order = pool
    else:
        order = pool[np.argsort(cand.ret20[t, pool], kind='stable')]
    limit = top if top is not None else max(cfg.positions * 2, 40)
    per = None if equity is None else cfg.leverage * equity / cfg.positions
    picks = []
    for rank, j in enumerate(order[:limit], 1):
        close_q = float(panel.c[t, j])
        raw = close_q / float(panel.f[t, j])
        row = dict(rank=rank, code=str(panel.codes[j]), name=(names or {}).get(str(panel.codes[j]), ''),
                   close=round(raw, 3), ret20=None if not np.isfinite(cand.ret20[t, j]) else float(cand.ret20[t, j]),
                   in_plan=rank <= cfg.positions)
        if per is not None and raw > 0:
            row['plan_amount'] = round(per, 2)
            row['plan_shares'] = int(per / raw // 100 * 100)
        picks.append(row)
    recent = [dict(date=str(panel.dates[i]), mk20=None if not np.isfinite(market.mk20[i]) else float(market.mk20[i]),
                   z=None if not np.isfinite(market.z[i]) else float(market.z[i]))
              for i in range(max(0, t - 9), t + 1)]
    return dict(date=str(panel.dates[t]), index=int(t), mk20=None if not np.isfinite(market.mk20[t]) else float(market.mk20[t]),
                z=zt, gate_open=bool(gate_open), z_threshold=cfg.z_threshold, n_e6=int(len(pool)),
                n_market=int(market.count[t]), picks=picks, recent=recent, is_last_day=bool(t == len(panel.dates) - 1),
                config_hash=cfg.hash(), positions=cfg.positions)


def settle_picks(panel: Panel, picks: list[dict], signal_day: str, cfg: DipConfig) -> list[dict]:
    """用面板里已有的数据，给一组信号日挑出的股票算：次日开盘买入价、第 hold_days 日收盘卖出价、扣成本后的收益。
    还没到的价格留空；次日开盘一字涨停买不进的标记 not_filled，按研究口径由后面的备选顺延。"""
    nd = len(panel.dates)
    t = panel.index_of(signal_day)
    fee = _fee_by_day(panel.dates)
    slip = cfg.slippage_bp / 1e4
    lim_cols = {}
    out = []
    code_index = {str(c): i for i, c in enumerate(panel.codes)}
    for pick in picks:
        j = code_index.get(pick['code'])
        row = dict(pick, entry_date=None, entry_px=None, exit_date=None, exit_px=None, ret=None, mtm=None,
                   status='waiting', not_filled=False)
        if j is None or t + 1 >= nd:
            out.append(row)
            continue
        e = t + 1
        o0 = float(panel.o[e, j])
        if not np.isfinite(o0) or panel.ts[e, j] != 1:
            row.update(status='not_filled', not_filled=True, note='次日停牌或无开盘价')
            out.append(row)
            continue
        if j not in lim_cols:
            lim_cols[j] = _limit_rates(panel, slice(j, j + 1))[:, 0]
        gap = o0 / float(panel.c[t, j]) - 1
        if gap >= lim_cols[j][t] - 0.0025:
            row.update(status='not_filled', not_filled=True, note='次日开盘涨停，买不进')
            out.append(row)
            continue
        raw_e = o0 / float(panel.f[e, j])
        row.update(entry_date=str(panel.dates[e]), entry_px=round(raw_e, 3), status='held')
        ex = _exit_index(panel.c, j, t + cfg.hold_days, nd)
        if ex is not None and t + cfg.hold_days < nd:
            xi, px = ex
            raw_x = px / float(panel.f[xi, j])
            net = (px * (1 - 0.01 / raw_x - slip)) / (o0 * (1 + 0.01 / raw_e + slip)) - 1 - fee[xi]
            row.update(exit_date=str(panel.dates[xi]), exit_px=round(raw_x, 3), ret=float(net), status='closed')
        else:
            last = nd - 1
            ct = float(panel.c[last, j])
            if np.isfinite(ct):
                row['mtm'] = float(ct / o0 - 1)
        out.append(row)
    return out
