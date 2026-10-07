"""策略 D：大盘恐慌（A）、成交额分档恐慌（C）、申万行业恐慌（B）三层信号共用一笔钱。纯函数，不读文件、不联网。

研究依据：docs/archive/testing/20260930-低频抄底扣成本重测与ETF.md。三层用同一个恐慌分：
  z = 一组股票的等权 20 日涨跌 / (该组近 60 日日收益波动 x sqrt(20))，z <= 阈值（默认 -1.5）就算这一组“恐慌”。
  A 大盘      组 = 全市场流动性股票；候选 = 满足布林下轨收复（E6）的票，沿用 engine 的大盘闸门与候选。
  C 成交额    组 = 按近 60 日平均成交额分五档（每天重新分档）；任一档触发，候选 = 触发档里全部可交易股票。
  B 行业      组 = 申万一级行业（至少 8 只有收益）；任一行业触发，候选 = 触发行业里全部可交易股票。
触发范围嵌套：A 触发的日子 C 一定触发，C 触发的日子 B 一定触发；所以越往后信号越频繁、质量越低。
账户：一笔钱、不借钱（总仓位上限 1 倍）。优先级 A > C > B，钱不够时先给前面的层。每层最多 positions 只，每只的权重各层不同
（A 与 C 各 8% 净值、B 2.5% 净值），候选按 20 日跌幅从大到小排（D）。同一只股票不会在两层里重复买。
D1 = D 只换一件事：候选先取 20 日跌幅最大的前 rank_k（默认 40）只，再按 60 日回撤从深到浅排（rank_mode='dd60'）；其余与 D 完全一样。
D2 = D1 再加一件事：大盘（等权指数）离近 120 日高点不足 5% 的日子，三层闸门全部关掉，不开新仓（near_high_on）；其余与 D1 完全一样。
次日开盘买、持有 hold_days 个交易日后收盘卖，成本与 engine 一致；闲置资金按 cash_yield 计息。
结果是历史回测，参数在同一份样本上调过；面板只含现存股票（幸存者偏差）。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields, replace

import numpy as np

from quantlab.dipbuy import industry as ind_mod
from quantlab.dipbuy import tracker
from quantlab.dipbuy.engine import (DipConfig, Candidates, Market, _exit_index, _fee_by_day, _open_row, _trade_row,
                                    compute_features, curve, drawdown_series, summarize)
from quantlab.dipbuy.panel import Cancelled, DipDataError, Panel, survivorship_caveats

FUSION_VERSION = 'dipbuy-fusion-1'
RANK_MODES = ('ret20', 'dd60')
DD_WINDOW = 60
DD_MIN = 40
VARIANT_NAMES = {'D': '策略 D', 'D1': '策略 D1', 'D2': '策略 D2'}
ORDER = ('A', 'C', 'B')
SLEEVE_NAMES = {'A': '大盘恐慌', 'C': '成交额分档恐慌', 'B': '行业恐慌'}
QUINTILE_NAMES = ('成交额最小档', '较小档', '中间档', '较大档', '成交额最大档')
N_QUINTILES = 5
AMOUNT_WINDOW = 60
MIN_MEMBERS = 8
RET_WINDOW = 20
STD_WINDOW = 60
STD_MIN = 40

DELISTED_DETAIL = '研究里同口径对比（2008 起，扣成本）：D 含退市股 +15.9% / 回撤 −42%，不含 +18.0% / −36%；D1 含 +18.3% / −36%，不含 +19.6% / −35%。；D2（D1 + 近高点过滤）含退市股 +21.3% / 回撤 −36%（样本内）。'

CAVEATS = (
    '历史回测：参数（权重、阈值、持有天数）是在同一份数据上试过很多组后定的，没有做多重检验修正，更像局部最优，不是样本外验证过的结论。',
    '面板只含现存股票（幸存者偏差）：D 买的恰恰是跌得最多的票，后来退市的那批不在数据里，回测收益偏高。研究里补进 290 只退市股后（2008 起，扣成本）：D 年化约 +15.9%（面板里不含退市股时 +18.0%）、最大回撤约 −42%（−36%）；D1 +18.3%（+19.6%）、−36%（−35%）。',
    '持有 20 天比 19 天明显好，卖出日换成第 21 天结果也会变；行业分类用的是今天的申万一级分类（轻微前视）。',
    '回测用次日开盘买、第 20 个交易日收盘卖，不计整手、最低佣金和冲击成本；40 万本金按 9:35 买、21 日 9:30 卖的测算，实盘预期年化约 +18% 到 +25%，最大回撤约 −31% 到 −37%。',
    'A 触发的日子 C 一定触发，C 触发的日子 B 一定触发，三层不是三份独立证据；B 层单笔收益最低，作用是把 A、C 空着的钱填起来。',
    'D1 的“60 日回撤”排序是看过全样本后挑的，属于样本内线索：逐年看，它在 2008、2012、2015、2022 比 D 好很多，在 2024、2025 反而少赚 15 到 20 个点，建议当可选增强，不是替代 D。',
    'D2 = D1 + 近高点过滤：过滤的窗口和距离是看过 129 个组合的网格后选的（样本内，没做多重检验修正）；安慰剂检验里挑出来的最好一格不比运气好多少，增益几乎全来自 2013、2021–2023 年，2008–2019 年多数年份没有差别。回测里 D2 比 D1 多约 3 个点年化是样本内数字，真实预期只有每年多 1.5 到 3 个点；最大回撤不变。',
)


# ---------------------------------------------------------------- 参数
@dataclass(frozen=True)
class FusionConfig:
    z_threshold: float = -1.5
    positions: int = 20                # 每层最多同时持有几只
    hold_days: int = 20
    weight_a: float = 0.08             # 每只占净值的比例
    weight_c: float = 0.08
    weight_b: float = 0.025
    gross_cap: float = 1.0             # 总仓位上限（占净值），D 不借钱，最大 1 倍
    cash_yield: float = 0.02           # 闲置资金年化收益
    min_amount: float = 5e7
    min_price: float = 3.0
    slippage_bp: float = 0.0
    start: str = '2008-01-01'
    end: str | None = None
    rank_mode: str = 'ret20'           # 'ret20' = D（20 日跌幅最大优先）；'dd60' = D1（先取跌幅前 rank_k，再按 60 日回撤最深优先）
    rank_k: int = 40
    near_high_on: bool = False         # 可选过滤：大盘离近 window 日高点不足 pct 时，三层信号一律不开（默认关；研究 §101/§102）
    near_high_window: int = 120
    near_high_pct: float = 0.05

    def __post_init__(self):
        checks = (
            (-4.0 <= self.z_threshold <= 0.0, 'z 阈值应在 -4 到 0 之间'),
            (1 <= self.positions <= 100, '每层持仓只数应在 1 到 100 之间'),
            (1 <= self.hold_days <= 60, '持有天数应在 1 到 60 之间'),
            (all(0.0 < w <= 0.5 for w in (self.weight_a, self.weight_c, self.weight_b)), '单只权重应在 0 到 50% 之间'),
            (0.1 <= self.gross_cap <= 1.0, '总仓位上限应在 10% 到 100% 之间（不借钱）'),
            (0.0 <= self.cash_yield <= 0.1, '闲置资金收益应在 0 到 10% 之间'),
            (0.0 <= self.min_amount <= 1e10, '成交额下限不合理'),
            (0.0 <= self.min_price <= 1000.0, '价格下限不合理'),
            (0.0 <= self.slippage_bp <= 200.0, '冲击成本应在 0 到 200 基点之间'),
            (self.rank_mode in RANK_MODES, '候选排序只支持 ret20 或 dd60'),
            (5 <= self.rank_k <= 200, '二段排序的候选数应在 5 到 200 之间'),
            (20 <= self.near_high_window <= 1000, '近高点过滤的窗口应在 20 到 1000 日之间'),
            (0.01 <= self.near_high_pct <= 0.20, '近高点过滤的距离应在 1% 到 20% 之间'),
        )
        for ok, message in checks:
            if not ok:
                raise ValueError(message)

    @property
    def weights(self) -> dict:
        return {'A': self.weight_a, 'C': self.weight_c, 'B': self.weight_b}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict | None) -> 'FusionConfig':
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (value or {}).items() if k in known})

    @property
    def variant(self) -> str:
        if self.rank_mode == 'dd60':
            return 'D2' if self.near_high_on else 'D1'
        return 'D'

    def hash(self) -> str:
        payload = self.to_dict()
        if self.rank_mode == 'ret20':       # D 的哈希保持和加排序选项之前一样，已有的前向记录和缓存不受影响
            payload.pop('rank_mode'), payload.pop('rank_k')
        if not self.near_high_on:           # 过滤关着时哈希与加这个选项之前完全一样，已有的前向记录和缓存不受影响
            for k in ('near_high_on', 'near_high_window', 'near_high_pct'):
                payload.pop(k)
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256((FUSION_VERSION + blob).encode()).hexdigest()[:12]

    def dip_config(self) -> DipConfig:
        """借用 engine / industry 里按 DipConfig 取参数的函数。"""
        return DipConfig(z_threshold=self.z_threshold, positions=self.positions, hold_days=self.hold_days, leverage=1.0,
                         cash_yield=self.cash_yield, min_amount=self.min_amount, min_price=self.min_price,
                         slippage_bp=self.slippage_bp, start=self.start, end=self.end)


def default_config() -> FusionConfig:
    return FusionConfig()


def d1_config() -> FusionConfig:
    return FusionConfig(rank_mode='dd60')


def d2_config() -> FusionConfig:
    """D2 = D1 + 近高点过滤：大盘离近 120 日高点不足 5% 的日子，三层闸门全关（研究 §102、§103）。"""
    return FusionConfig(rank_mode='dd60', near_high_on=True)


def config_for(variant: str) -> FusionConfig:
    return d2_config() if variant == 'D2' else d1_config() if variant == 'D1' else default_config()


# ---------------------------------------------------------------- 成交额分档与分档恐慌分
def amount_labels(panel: Panel, cand: Candidates, *, stop=None) -> np.ndarray:
    """每天把候选池里的股票按近 60 日平均成交额从小到大分五档（0 最小 … 4 最大）；不在池里或没有成交额为 -1。"""
    import pandas as pd
    nd, nc = panel.shape
    a = np.nan_to_num(panel.a, nan=0.0).astype(np.float64)
    cs = np.cumsum(a, 0)
    del a
    amt = np.full((nd, nc), np.nan, np.float32)
    if nd > AMOUNT_WINDOW:
        amt[AMOUNT_WINDOW:] = ((cs[AMOUNT_WINDOW:] - cs[:-AMOUNT_WINDOW]) / AMOUNT_WINDOW).astype(np.float32)
    del cs
    labels = np.full((nd, nc), -1, np.int8)
    for s0 in range(0, nd, 400):
        if stop is not None and stop.is_set():
            raise Cancelled()
        b = min(nd, s0 + 400)
        v = np.where(cand.uni[s0:b] & np.isfinite(amt[s0:b]), amt[s0:b], np.nan)
        pct = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
        labels[s0:b] = np.where(np.isfinite(pct), np.minimum(np.nan_to_num(pct * N_QUINTILES).astype(np.int16), N_QUINTILES - 1), -1).astype(np.int8)
    return labels


def group_state(panel: Panel, cand: Candidates, labels: np.ndarray, *, stop=None):
    """按“前一天收盘后已知”的每日分档，算各档的恐慌分 z、等权 20 日涨跌、当天参与的股票数，形状都是 [nd, 档数]。"""
    import pandas as pd
    nd, nc = panel.shape
    uni_prev = np.vstack([np.zeros((1, nc), bool), cand.uni[:-1]])
    lab_prev = np.vstack([np.full((1, nc), -1, labels.dtype), labels[:-1]])
    c = panel.c.astype(np.float32)
    ret1 = np.full((nd, nc), np.nan, np.float32)
    ret1[1:] = c[1:] / c[:-1] - 1
    del c
    ok_all = uni_prev & np.isfinite(ret1)
    ret1 = np.where(ok_all, ret1, 0.0).astype(np.float32)
    z = np.full((nd, N_QUINTILES), np.nan)
    r20 = np.full((nd, N_QUINTILES), np.nan)
    cnt = np.zeros((nd, N_QUINTILES), np.int32)
    for g in range(N_QUINTILES):
        if stop is not None and stop.is_set():
            raise Cancelled()
        member = (lab_prev == g) & ok_all
        n = member.sum(1)
        s = (ret1 * member).sum(1, dtype=np.float64)
        mean = np.where(n >= MIN_MEMBERS, s / np.maximum(n, 1), np.nan)
        ser = pd.Series(mean)
        c20 = np.exp(np.log1p(ser).rolling(RET_WINDOW, min_periods=RET_WINDOW).sum()) - 1
        sd = ser.rolling(STD_WINDOW, min_periods=STD_MIN).std()
        with np.errstate(invalid='ignore', divide='ignore'):
            z[:, g] = (c20 / (sd * np.sqrt(RET_WINDOW))).to_numpy()
        r20[:, g] = c20.to_numpy()
        cnt[:, g] = n
    return z, r20, cnt


# ---------------------------------------------------------------- 候选排序（D：20 日跌幅；D1：跌幅前 K 再按 60 日回撤）
def drawdown60(panel: Panel) -> np.ndarray:
    """收盘价相对近 60 个交易日（至少 40 个有价）最高收盘价的回撤，<= 0；缓存在面板上。"""
    key = ('fusion-dd60',)
    if key in panel.cache:
        return panel.cache[key]
    c = panel.c
    nd, nc = c.shape
    out = np.full((nd, nc), np.nan, np.float32)
    pad = np.full((DD_WINDOW - 1, 1), np.nan, np.float32)
    for b0 in range(0, nc, 256):
        blk = c[:, b0:b0 + 256].astype(np.float32)
        ext = np.concatenate([np.repeat(pad, blk.shape[1], axis=1), blk], axis=0)
        win = np.lib.stride_tricks.sliding_window_view(ext, DD_WINDOW, axis=0)      # [nd, w, 60]
        mx = np.fmax.reduce(win, axis=-1)
        n_ok = np.isfinite(win).sum(axis=-1)
        with np.errstate(invalid='ignore', divide='ignore'):
            out[:, b0:b0 + 256] = np.where(n_ok >= DD_MIN, blk / mx - 1.0, np.nan)
    panel.cache[key] = out
    return out


def order_candidates(panel: Panel, inp, cfg: FusionConfig, t: int, base: np.ndarray, pool: np.ndarray) -> np.ndarray:
    """pool（已去掉持仓的候选下标）按买入先后排序。base 是该层当日全部候选（去持仓之前）。
    D：20 日涨跌从小到大。D1：先在 base 里取 20 日涨跌最小的 rank_k 只，再按 60 日回撤从深到浅；没入选的排在后面（保持下标顺序）。"""
    if cfg.rank_mode != 'dd60' or not len(pool):
        return pool[np.argsort(inp.rank[t, pool], kind='stable')]
    v = inp.rank[t, base]
    ok = np.isfinite(v)
    top = base[ok][np.argsort(v[ok], kind='stable')[:cfg.rank_k]]
    dd = drawdown60(panel)[t, top].astype(np.float64)
    key = np.full(panel.shape[1], np.inf)
    key[top] = np.where(np.isfinite(dd), dd, np.inf)
    return pool[np.argsort(key[pool], kind='stable')]


# ---------------------------------------------------------------- 三层闸门与候选
@dataclass
class FusionInputs:
    market: Market
    cand: Candidates
    gates: dict                 # 'A'/'C'/'B' -> bool[nd]
    pools: dict                 # 'A'/'C'/'B' -> bool[nd, nc]
    rank: np.ndarray            # float32 [nd, nc]，20 日涨跌，越小越先买
    buyok: np.ndarray
    labels: np.ndarray          # int8 [nd, nc] 成交额分档
    z_c: np.ndarray             # [nd, 5]
    r20_c: np.ndarray
    n_c: np.ndarray
    ind_state: object           # industry.IndustryState
    cls: object                 # industry.Classification
    any_gate: np.ndarray
    raw_any_gate: np.ndarray | None = None     # 近高点过滤打开时，过滤之前的“有信号”日（用来告诉你过滤挡掉了什么）


def market_index(market: Market) -> np.ndarray:
    """等权大盘指数（从 1 起累乘，缺失的日收益当 0）。"""
    return np.cumprod(1.0 + np.where(np.isfinite(market.mret), market.mret, 0.0))


def near_high_gap(market: Market, window: int) -> np.ndarray:
    """大盘指数相对近 window 日（含当天）最高点的涨跌，≤0；前 window−1 天没有足够历史，给 NaN。"""
    idx = market_index(market)
    out = np.full(idx.shape, np.nan)
    if len(idx) >= window:
        peak = np.lib.stride_tricks.sliding_window_view(idx, window).max(axis=1)
        out[window - 1:] = idx[window - 1:] / peak - 1.0
    return out


def with_near_high_filter(inp: FusionInputs, cfg: FusionConfig) -> FusionInputs:
    """过滤关着原样返回；打开时，大盘离近 window 日高点不足 pct 的日子，三层闸门全部关掉（历史不足的日子不过滤）。"""
    if not cfg.near_high_on:
        return inp
    gap = near_high_gap(inp.market, cfg.near_high_window)
    with np.errstate(invalid='ignore'):
        keep = ~(np.isfinite(gap) & (gap > -cfg.near_high_pct))
    gates = {k: v & keep for k, v in inp.gates.items()}
    return replace(inp, gates=gates, any_gate=gates['A'] | gates['C'] | gates['B'], raw_any_gate=inp.any_gate)


def build_inputs(panel: Panel, cfg: FusionConfig, cls, *, progress=None, stop=None) -> FusionInputs:
    return with_near_high_filter(_build_inputs(panel, cfg, cls, progress=progress, stop=stop), cfg)


def _build_inputs(panel: Panel, cfg: FusionConfig, cls, *, progress=None, stop=None) -> FusionInputs:
    key = ('fusion-inputs', cls.as_of, float(cfg.z_threshold), float(cfg.min_amount), float(cfg.min_price))
    if key in panel.cache:
        return panel.cache[key]
    thr = cfg.z_threshold
    market, cand = compute_features(panel, cfg.min_amount, cfg.min_price, progress=progress, stop=stop)
    b_market, b_cand, ind_state = ind_mod.build_inputs(panel, cfg.dip_config(), cls, progress=progress, stop=stop)
    labels = amount_labels(panel, cand, stop=stop)
    z_c, r20_c, n_c = group_state(panel, cand, labels, stop=stop)
    trig = np.isfinite(z_c) & (z_c <= thr)
    in_trig = np.zeros(cand.uni.shape, bool)
    for g in range(N_QUINTILES):
        in_trig |= (labels == g) & trig[:, g:g + 1]
    pool_c = cand.uni & in_trig & np.isfinite(cand.ret20)
    zmin = np.where(np.isfinite(z_c), z_c, np.inf).min(axis=1)
    zmin = np.where(np.isfinite(zmin), zmin, np.nan)
    with np.errstate(invalid='ignore'):
        gates = {'A': np.isfinite(market.z) & (market.z <= thr), 'C': np.isfinite(zmin) & (zmin <= thr),
                 'B': np.isfinite(b_market.z) & (b_market.z <= thr)}
    out = FusionInputs(market=market, cand=cand, gates=gates, pools={'A': cand.e6, 'C': pool_c, 'B': b_cand.e6},
                       rank=cand.ret20, buyok=cand.buyok, labels=labels, z_c=z_c, r20_c=r20_c, n_c=n_c,
                       ind_state=ind_state, cls=cls, any_gate=gates['A'] | gates['C'] | gates['B'])
    panel.cache[key] = out
    return out


# ---------------------------------------------------------------- 共享资金回测
def simulate_fused(panel: Panel, inp: FusionInputs, cfg: FusionConfig, *, progress=None, stop=None) -> dict:
    nd, nc = panel.shape
    dates, c, o, f = panel.dates, panel.c, panel.o, panel.f
    H, N, G, W = cfg.hold_days, cfg.positions, cfg.gross_cap, cfg.weights
    t0 = int(np.searchsorted(dates, cfg.start))
    tend = nd - 1 if cfg.end is None else min(int(np.searchsorted(dates, cfg.end, side='right')) - 1, nd - 1)
    if t0 >= tend:
        raise DipDataError('回测区间内没有数据')
    fee = _fee_by_day(dates)
    slip = cfg.slippage_bp / 1e4
    cash = 1.0
    active: list[dict] = []
    trades: list[dict] = []
    eq = np.full(nd, np.nan)
    expo = np.zeros(nd)
    earned = 0.0
    for t in range(t0, tend + 1):
        if stop is not None and stop.is_set():
            raise Cancelled()
        if progress and t % 250 == 0:
            progress(t - t0, tend - t0, '回测')
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net'])
            trades.append(dict(_trade_row(panel, p, closed='exit'), sleeve=p['s']))
            active.remove(p)
        if t + 1 <= min(tend, nd - 1):
            held = {p['j'] for p in active}
            for s in ORDER:
                if not inp.gates[s][t]:
                    continue
                n_s = sum(1 for p in active if p['s'] == s)
                if n_s >= N:
                    continue
                base = np.nonzero(inp.pools[s][t] & inp.buyok[t])[0]
                pool = np.array([j for j in base if j not in held], dtype=int)
                if not len(pool):
                    continue
                pool = order_candidates(panel, inp, cfg, t, base, pool)
                invested = sum(p['v'] for p in active)
                equity = cash + invested
                for j in pool[:N - n_s]:
                    size = min(W[s] * equity, G * equity - invested)
                    if size <= 1e-9:
                        break
                    cash -= size
                    invested += size
                    e = t + 1
                    o0 = float(o[e, j])
                    raw_e = o0 / float(f[e, j])
                    ex = _exit_index(c, j, t + H, nd)
                    pos = dict(j=int(j), s=s, sig=t, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None,
                               px_x=None, last=o0)
                    if ex is not None:
                        xi, px = ex
                        fx, k = float(f[xi, j]), xi
                        while not np.isfinite(fx) and k > 0:      # 退市 / 长期停牌：退出价是最后一个有价的收盘价，复权因子也沿用最近一个已知值
                            k -= 1
                            fx = float(f[k, j])
                        raw_x = px / fx
                        pos['net'] = (px * (1 - 0.01 / raw_x - slip)) / (o0 * (1 + 0.01 / raw_e + slip)) - 1 - fee[xi]
                        pos['px_x'] = px
                        pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2 + slip
                    else:
                        pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2 + slip
                    active.append(pos)
                    held.add(int(j))
        if cash > 0 and cfg.cash_yield > 0:
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
        eq[t] = tot
        expo[t] = vs / max(tot, 1e-9)
    open_positions = [dict(_open_row(panel, p, tend), sleeve=p['s']) for p in active]
    info = dict(interest=0.0, cash_earned=earned, n_liquidations=0, liquidation_days=[], min_margin_ratio=None,
                n_warn_days=0, peak_debt_ratio=0.0, ruined=False)
    return dict(eq=eq, expo=expo, trades=trades, open_positions=open_positions, info=info, gate=inp.any_gate,
                gates=inp.gates, t0=t0, tend=tend)


def sleeve_stats(raw: dict) -> dict:
    t0, tend = raw['t0'], raw['tend']
    out = {}
    for s in ORDER:
        rets = np.array([t['ret'] for t in raw['trades'] if t.get('sleeve') == s])
        out[s] = dict(name=SLEEVE_NAMES[s], gate_days=int(raw['gates'][s][t0:tend + 1].sum()), n=int(len(rets)),
                      mean=float(rets.mean()) if len(rets) else None,
                      win_rate=float((rets > 0).mean()) if len(rets) else None,
                      open=int(sum(1 for p in raw['open_positions'] if p.get('sleeve') == s)))
    return out


def run_backtest(panel: Panel, cfg: FusionConfig, cls, *, progress=None, stop=None) -> dict:
    from quantlab.dipbuy.backtest import RUN_FORMAT, content_hash
    inp = build_inputs(panel, cfg, cls, progress=progress, stop=stop)
    raw = simulate_fused(panel, inp, cfg, progress=progress, stop=stop)
    summary = summarize(panel, inp.market, raw, cfg.dip_config())
    summary['sleeves'] = sleeve_stats(raw)
    cv = curve(panel, inp.market, raw)
    meta = panel.meta or {}
    result = dict(
        format=RUN_FORMAT, kind='fusion', engine_version=FUSION_VERSION, config=cfg.to_dict(), config_hash=cfg.hash(),
        classification=dict(as_of=cls.as_of, n_mapped=cls.n_mapped, n_industries=len(cls.codes)),
        panel={k: meta.get(k) for k in ('signature', 'first_date', 'last_date', 'n_stocks', 'n_days')} | {
            'last_date': panel.last_date, 'n_stocks': int(panel.shape[1]), 'n_days': int(panel.shape[0])},
        summary=summary, curve=cv, drawdown=drawdown_series(cv['equity']), trades=raw['trades'],
        caveats=survivorship_caveats(CAVEATS, panel, DELISTED_DETAIL))
    result['content_hash'] = content_hash(result)
    return result


# ---------------------------------------------------------------- 当日信号
def _num(x):
    return None if x is None or not np.isfinite(x) else float(x)


def latest_fusion_signal(panel: Panel, inp: FusionInputs, cfg: FusionConfig, *, equity: float | None = None,
                         day: str | None = None, names: dict | None = None, top: int | None = None) -> dict:
    """某个交易日收盘后三层的状态，以及触发的层按优先级分到的候选。equity 给了就按“空仓、一笔新钱”估算每只金额和股数。"""
    t = panel.index_of(day) if day else len(panel.dates) - 1
    thr = cfg.z_threshold
    cls = inp.cls
    quint = []
    for g in range(N_QUINTILES):
        zg = _num(inp.z_c[t, g])
        quint.append(dict(q=g, name=QUINTILE_NAMES[g], z=zg, ret20=_num(inp.r20_c[t, g]), members=int(inp.n_c[t, g]),
                          triggered=bool(zg is not None and zg <= thr)))
    inds = []
    for g in range(len(cls.codes)):
        zg = _num(inp.ind_state.z[t, g])
        inds.append(dict(code=cls.codes[g], name=cls.names[g], stocks=cls.sizes[g], members=int(inp.ind_state.n[t, g]),
                         ret20=_num(inp.ind_state.ret20[t, g]), z=zg, triggered=bool(zg is not None and zg <= thr)))
    inds.sort(key=lambda r: (r['z'] is None, r['z'] if r['z'] is not None else 0.0))
    weakest_q = min((r for r in quint if r['z'] is not None), key=lambda r: r['z'], default=None)
    weakest_i = next((r for r in inds if r['z'] is not None), None)
    z_a = _num(inp.market.z[t])
    sleeves = {
        'A': dict(name=SLEEVE_NAMES['A'], gate=bool(inp.gates['A'][t]), z=z_a, detail='全市场等权', n_pool=int(inp.pools['A'][t].sum())),
        'C': dict(name=SLEEVE_NAMES['C'], gate=bool(inp.gates['C'][t]), z=weakest_q and weakest_q['z'],
                  detail=weakest_q['name'] if weakest_q else '—', n_pool=int(inp.pools['C'][t].sum())),
        'B': dict(name=SLEEVE_NAMES['B'], gate=bool(inp.gates['B'][t]), z=weakest_i and weakest_i['z'],
                  detail=weakest_i['name'] if weakest_i else '—', n_pool=int(inp.pools['B'][t].sum())),
    }
    limit = top if top is not None else cfg.positions * 2
    invested, taken, picks = 0.0, set(), []
    code_of = [str(c) for c in panel.codes]
    for s in ORDER:
        if not inp.gates[s][t]:
            continue
        pool = np.nonzero(inp.pools[s][t])[0]
        pool = order_candidates(panel, inp, cfg, t, pool, pool)
        rank = 0
        for j in pool:
            code = code_of[j]
            if code in taken:
                continue
            rank += 1
            if rank > limit:
                break
            taken.add(code)
            raw = float(panel.c[t, j]) / float(panel.f[t, j])
            in_plan = rank <= cfg.positions
            row = dict(sleeve=s, rank=rank, code=code, name=(names or {}).get(code, ''), close=round(raw, 3),
                       ret20=_num(inp.rank[t, j]), dd60=_num(drawdown60(panel)[t, j]) if cfg.rank_mode == 'dd60' else None,
                       in_plan=in_plan, weight=cfg.weights[s],
                       group=(QUINTILE_NAMES[int(inp.labels[t, j])] if s == 'C' and inp.labels[t, j] >= 0 else
                              cls.name_of(int(j)) if s == 'B' else ''))
            if equity is not None and in_plan and raw > 0:
                size = min(cfg.weights[s] * equity, cfg.gross_cap * equity - invested)
                size = max(size, 0.0)
                invested += size
                row['plan_amount'] = round(size, 2)
                row['plan_shares'] = int(size / raw // 100 * 100)
            picks.append(row)
    z_all = [r for r in (z_a, sleeves['C']['z'], sleeves['B']['z']) if r is not None]
    recent = []
    for i in range(max(0, t - 9), t + 1):
        zc_i = _num(np.nanmin(inp.z_c[i])) if np.isfinite(inp.z_c[i]).any() else None
        zb_i = _num(np.nanmin(inp.ind_state.z[i])) if np.isfinite(inp.ind_state.z[i]).any() else None
        recent.append(dict(date=str(panel.dates[i]), a=_num(inp.market.z[i]), c=zc_i, b=zb_i))
    plan_size = sum(1 for p in picks if p['in_plan'])
    gap_now = _num(near_high_gap(inp.market, cfg.near_high_window)[t])
    blocked = bool(inp.raw_any_gate is not None and inp.raw_any_gate[t] and not inp.any_gate[t])
    market_position = dict(window=cfg.near_high_window, pct=cfg.near_high_pct, gap=gap_now, on=cfg.near_high_on,
                           would_block=bool(gap_now is not None and gap_now > -cfg.near_high_pct), blocked=blocked)
    return dict(date=str(panel.dates[t]), index=int(t), is_last_day=bool(t == len(panel.dates) - 1),
                gate_open=bool(inp.any_gate[t]), fired=[s for s in ORDER if sleeves[s]['gate']], z=z_a,
                mk20=_num(inp.market.mk20[t]), n_e6=int(sum(sl['n_pool'] for s, sl in sleeves.items() if sl['gate'])),
                z_threshold=thr, sleeves=sleeves, quintiles=quint, industries=inds, picks=picks, plan_size=plan_size,
                recent=recent, config_hash=cfg.hash(), variant=cfg.variant, rank_mode=cfg.rank_mode, nearest=min(z_all) if z_all else None, fusion=True, market_position=market_position,
                classification=dict(as_of=cls.as_of, n_mapped=cls.n_mapped))


# ---------------------------------------------------------------- 前向跟踪的组合净值
def forward_portfolio(output, panel: Panel, cls, kind: str = 'fusion') -> dict | None:
    """用冻结的参数，从记录开始日起在真实数据上跑一遍共享资金组合，给出前向净值。没有记录返回 None。"""
    ledger = tracker.load_ledger(output, kind)
    if not ledger.get('config') or not ledger.get('start_date'):
        return None
    if int(panel.index_of(ledger['start_date'])) >= len(panel.dates) - 1:
        return None
    cfg = replace(FusionConfig.from_dict(ledger['config']), start=ledger['start_date'], end=None)
    inp = build_inputs(panel, cfg, cls)
    raw = simulate_fused(panel, inp, cfg)
    summary = summarize(panel, inp.market, raw, cfg.dip_config())
    by_day: dict[str, set] = {}
    for t in raw['trades']:
        by_day.setdefault(t['signal'], set()).add(t['code'])
    for p in raw['open_positions']:
        by_day.setdefault(p['signal'], set()).add(p['code'])
    mismatched = []
    for record in ledger['records']:
        recorded = {p['code'] for p in record['picks']}
        extra = sorted(by_day.get(record['signal_date'], set()) - recorded)
        if extra:
            mismatched.append(dict(date=record['signal_date'], extra=extra))
    eq = [None if not math.isfinite(v) else round(float(v), 5) for v in raw['eq'][raw['t0']:raw['tend'] + 1]]
    return dict(start_date=ledger['start_date'], dates=[str(d) for d in panel.dates[raw['t0']:raw['tend'] + 1]], equity=eq,
                summary=summary, mismatched=mismatched, trades=raw['trades'], open_positions=raw['open_positions'])
