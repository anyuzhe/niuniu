"""手机版首页「市场概览」：把策略自己的数据整理成四个问题的答案。

  1. 现在情绪怎样？      → 大盘（全市场等权）20 日涨跌的标准化值 z，落在哪一档、比历史上多少天更悲观；
  2. 有没有信号？        → 7 本账今天有没有触发、有几只候选、持仓有没有该卖的；
  3. 后面会怎样？        → 离触发线还差多少；大盘再连跌几天、每天跌多少才会触发（按同一套公式推演）；历史上触发后的类比；
  4. 需要关注什么？      → 按规则生成的关注清单（最近的层、最近的行业、过滤器、休市、数据新鲜度）。

这里的“情绪”指策略看的下跌恐慌程度（z），不是涨停板情绪；涨停板情绪库（trading/market_sentiment）目前没有每天更新，所以不用。
所有“后面会怎样”都是规则推演或历史类比，不是预测。
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from quantlab.dipbuy.engine import Z_WINDOW

# (z 上限, 键, 档名, 色调, 一句话)；z 从低到高，第一个满足 z < 上限 的档
LEVELS = (
    (-1.5, 'panic', '恐慌', 'hot', '大盘 20 日跌幅已超出历史最差的约 5%，策略的"大盘恐慌"层已进入触发区。'),
    (-1.0, 'tense', '紧张', 'warn', '跌得不轻，离触发线不远，值得每天看一眼。'),
    (-0.4, 'weak', '偏弱', 'warn', '偏弱但没到恐慌，策略还在等。'),
    (0.6, 'calm', '平稳', 'calm', '没有恐慌，也没有明显的单边行情，策略没有动作。'),
    (1.5, 'strong', '偏强', 'ok', '大盘偏强，抄底策略在这种环境里本来就不出手。'),
    (math.inf, 'hot', '过热', 'ok', '大盘 20 日涨幅处在历史最高的约 10%，抄底策略不会有信号；要留意的是追高风险而不是抄底机会。'),
)
SCENARIO_DAYS = (1, 3, 5)
SCENARIO_FLOOR = -0.10          # 单日跌幅超过这个按“基本不可能”处理（A 股主板涨跌停 ±10%，全市场等权更不可能）
SCENARIO_STEP = 0.0005
HORIZON = 20                    # 历史类比看触发后 20 个交易日


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def level_of(z) -> dict:
    z = _num(z)
    if z is None:
        return dict(key='unknown', label='未知', tone='calm', text='数据不足，算不出。')
    for upper, key, label, tone, text in LEVELS:
        if z < upper:
            return dict(key=key, label=label, tone=tone, text=text)
    raise AssertionError('unreachable')


def percentile_of(series, value) -> float | None:
    """value 在历史 series 里的位置：历史上有多大比例的交易日 z 不高于 value（越小越悲观）。"""
    value = _num(value)
    s = np.asarray(series, dtype=float)
    s = s[np.isfinite(s)]
    if value is None or s.size == 0:
        return None
    return float((s <= value).mean())


def _z_after(mret: np.ndarray, extra: list[float]) -> float | None:
    ext = np.concatenate([mret, np.asarray(extra, dtype=float)])
    if ext.size < Z_WINDOW or ext.size < 20:
        return None
    mk20 = float(np.prod(1.0 + ext[-20:]) - 1.0)
    sd = float(ext[-Z_WINDOW:].std(ddof=1))
    if sd <= 0:
        return None
    return mk20 / (sd * math.sqrt(20))


def scenarios(mret: np.ndarray, threshold: float, days=SCENARIO_DAYS) -> list[dict]:
    """大盘接下来连续 k 天每天同样下跌 r，从 0 往下扫，第一个让 z ≤ 阈值的 r 就是“最少要每天跌多少”。
    用的是和策略同一套公式（20 日涨跌 ÷ (60 日日波动 × √20)），所以窗口滚动、波动变大这些都算进去了。"""
    mret = np.asarray(mret, dtype=float)
    out = []
    for k in days:
        hit = None
        r = 0.0
        while r > SCENARIO_FLOOR:
            r -= SCENARIO_STEP
            z = _z_after(mret, [r] * k)
            if z is not None and z <= threshold:
                hit = r
                break
        if hit is None:
            out.append(dict(days=k, daily=None, cum=None))
        else:
            out.append(dict(days=k, daily=hit, cum=(1 + hit) ** k - 1))
    return out


def history_of_gate(dates, z, mret, threshold: float, horizon: int = HORIZON) -> dict:
    """“大盘恐慌”层历史上的触发频率，和每一段触发的第一天之后 horizon 个交易日大盘的涨跌（历史类比）。"""
    z = np.asarray(z, dtype=float)
    ok = np.isfinite(z)
    gate = ok & (z <= threshold)
    starts = np.flatnonzero(gate & ~np.r_[False, gate[:-1]])
    idx = np.cumprod(1.0 + np.where(np.isfinite(mret), mret, 0.0))
    fwd = [float(idx[t + horizon] / idx[t] - 1) for t in starts if t + horizon < len(idx)]
    base = [float(idx[t + horizon] / idx[t] - 1) for t in range(len(idx) - horizon) if ok[t]]
    last = int(np.flatnonzero(gate)[-1]) if gate.any() else None
    years = max(ok.sum() / 242.0, 1e-9)
    out = dict(days=int(gate.sum()), share=float(gate.sum() / max(ok.sum(), 1)), episodes=int(starts.size),
               per_year=float(starts.size / years), horizon=horizon,
               last_date=str(dates[last]) if last is not None else None,
               since_last=int(len(dates) - 1 - last) if last is not None else None,
               fwd_n=len(fwd))
    if fwd:
        out.update(fwd_median=float(np.median(fwd)), fwd_mean=float(np.mean(fwd)), fwd_win=float(np.mean(np.asarray(fwd) > 0)),
                   fwd_worst=float(np.min(fwd)))
    if base:
        out.update(base_median=float(np.median(base)), base_win=float(np.mean(np.asarray(base) > 0)))
    return out


def breadth_today(panel, inp) -> dict:
    """今天全市场的广度：上涨家数占比、20 日跌超 10% 的占比（候选池口径：可交易、非 ST、上市满一年、够流动）。"""
    t = len(panel.dates) - 1
    uni = inp.cand.uni[t]
    c = panel.c[t].astype(float)
    p = panel.c[t - 1].astype(float)
    with np.errstate(invalid='ignore'):
        ok = uni & np.isfinite(c) & np.isfinite(p)
        up = float(((c > p) & ok).sum() / max(ok.sum(), 1))
        dn = float(((c < p) & ok).sum() / max(ok.sum(), 1))
        r20 = inp.cand.ret20[t].astype(float)
        okr = uni & np.isfinite(r20)
        weak = float(((r20 <= -0.10) & okr).sum() / max(okr.sum(), 1))
        neg = float(((r20 < 0) & okr).sum() / max(okr.sum(), 1))
    return dict(n=int(ok.sum()), up_share=up, down_share=dn, r20_below_10_share=weak, r20_negative_share=neg)


def _pct(x, digits=1, sign=False):
    return None if x is None else format(x * 100, ('+' if sign else '') + f'.{digits}f') + '%'


def _layer_rows(sig: dict, thr: float) -> list[dict]:
    rows = []
    recent = sig.get('recent') or []
    for key, rk in (('A', 'a'), ('C', 'c'), ('B', 'b')):
        s = (sig.get('sleeves') or {}).get(key) or {}
        z = _num(s.get('z'))
        past = _num(recent[-4][rk]) if len(recent) >= 4 else None
        change = None if z is None or past is None else z - past
        gap = None if z is None else z - thr
        state = 'open' if s.get('gate') else ('near' if gap is not None and gap <= 0.5 else 'far')
        rows.append(dict(key=key, name=s.get('name'), detail=s.get('detail'), z=z, threshold=thr, gap=gap, change3=change, state=state))
    return rows


def _watch(ov: dict, sig: dict, signals: dict, holdings: dict | None, fresh: bool) -> list[dict]:
    items = []
    fired_books = [b for b in ov['signal']['books'] if b['gate_open']]
    if fired_books:
        names = '、'.join(b['label'] for b in fired_books[:4]) + ('…' if len(fired_books) > 4 else '')
        items.append(dict(tone='hot', title='有触发', text=f'{len(fired_books)} 本账今天出了信号（{names}）。到「信号」页看候选和计划金额；按规则下一个开盘日开盘买、持有 20 个交易日。'))
    sells = ov['signal'].get('sells_due') or 0
    if sells:
        items.append(dict(tone='warn', title='有持仓到期', text=f'{sells} 只持仓按规则到了该卖出的日子，在「持仓」页看明细。'))
    layers = [l for l in ov['layers'] if l['gap'] is not None]
    if layers and not fired_books:
        near = min(layers, key=lambda l: l['gap'])
        ch = near['change3']
        trend = '' if ch is None else ('，近 3 天在走近' if ch <= -0.3 else ('，近 3 天在走远' if ch >= 0.3 else '，近 3 天变化不大'))
        who = f'（{near["detail"]}最弱）' if near['key'] != 'A' and near['detail'] else ''
        text = f'最接近触发的是「{near["name"]}」层{who}：z = {near["z"]:.2f}，离 {near["threshold"]:.1f} 还差 {near["gap"]:.2f}{trend}。'
        if near['key'] == 'A':
            sc = next((s for s in ov['scenarios'] if s['days'] == 3 and s['daily'] is not None), None)
            if sc:
                text += f'大盘要连跌 3 天、每天约 {_pct(sc["daily"])} 才会触发。'
        items.append(dict(tone='info', title='离触发最近的层', text=text))
    blacklist = set(sig.get('blacklist') or [])
    inds = [i for i in (sig.get('industries') or []) if i.get('z') is not None]
    if inds:
        top = [i for i in inds[:3]]
        bits = []
        for i in top:
            tag = '（D4 黑名单，不买）' if i['name'] in blacklist else ''
            bits.append(f'{i["name"]} z={i["z"]:.2f}{tag}')
        items.append(dict(tone='info', title='最弱的行业', text='；'.join(bits) + f'。行业层 z ≤ {ov["threshold"]:.1f} 才算该行业恐慌。'))
    mp = sig.get('market_position') or {}
    if mp.get('on') and mp.get('gap') is not None:
        if mp.get('would_block'):
            items.append(dict(tone='warn', title='近高点过滤会拦', text=f'大盘离近 {mp["window"]} 日高点只有 {_pct(mp["gap"])}，不到 {mp["pct"] * 100:.0f}%——此时即使 z 触发，D2/D3/D4 也不开仓。'))
        else:
            items.append(dict(tone='ok', title='近高点过滤不会拦', text=f'大盘离近 {mp["window"]} 日高点 {_pct(mp["gap"])}，离 {mp["pct"] * 100:.0f}% 的拦截线还远；真触发了不会被它挡掉。'))
    gap_days = ov.get('calendar_gap_days')
    if gap_days and gap_days > 3:
        items.append(dict(tone='warn', title='下一个开盘日隔着休市', text=f'数据日 {ov["as_of"]} → 下一个开盘日 {ov["plan_day"]}，中间休市 {gap_days - 1} 天；休市期间消息多，复牌那天开盘价可能跳空。'))
    if not fresh:
        items.append(dict(tone='warn', title='数据还没更新', text='页面上的数据不是最新交易日的收盘数据，今晚电脑更新后会自动刷新；结论先别当真。'))
    items.append(dict(tone='info', title='怎么用这页', text='每个交易日收盘后电脑会自动更新；盘中看到的是上一个收盘日的结论。没有触发就不用做任何事。'))
    return items


def build_overview(panel, inp, sig: dict, signals: dict, holdings: dict | None, *, as_of: str, plan_day: str, fresh: bool,
                   labels: dict, threshold: float) -> dict:
    """panel/inp：策略 D 的输入（只用大盘部分）；sig：D4 信号；signals：7 本账的信号；holdings：手机快照里的持仓部分。"""
    mk = inp.market
    t = len(panel.dates) - 1
    z = _num(mk.z[t])
    lvl = level_of(z)
    pct = percentile_of(mk.z, z)
    recent_mret = [float(x) for x in mk.mret[-5:]]
    books = []
    for kind, s in signals.items():
        if not isinstance(s, dict) or s.get('error'):
            continue
        picks = s.get('picks') or []
        books.append(dict(kind=kind, label=labels.get(kind, kind), gate_open=bool(s.get('gate_open')), n_picks=len(picks) if s.get('gate_open') else 0,
                          n_plan=sum(1 for p in picks if p.get('in_plan')) if s.get('gate_open') else 0))
    sells_due = 0
    n_hold = 0
    if isinstance(holdings, dict) and not holdings.get('error'):
        n_hold = int(holdings.get('n_holdings') or 0)
        plan = (holdings.get('plans') or {}).get('D4') or {}
        sells_due = len(plan.get('sells') or [])
    d_as, d_plan = date.fromisoformat(as_of), date.fromisoformat(plan_day)
    ov = dict(
        as_of=as_of, plan_day=plan_day, threshold=threshold, calendar_gap_days=(d_plan - d_as).days,
        level=dict(**lvl, z=z, pct=pct, mk20=_num(mk.mk20[t]), edges=[-1.5, -1.0, -0.4, 0.6, 1.5]),
        market=dict(today=_num(mk.mret[t]), last5=float(np.prod(1 + np.asarray(recent_mret)) - 1), mk20=_num(mk.mk20[t]),
                    count=int(mk.count[t]), breadth=breadth_today(panel, inp)),
        layers=_layer_rows(sig, threshold),
        scenarios=scenarios(mk.mret, threshold),
        history=history_of_gate(panel.dates, mk.z, mk.mret, threshold),
        signal=dict(books=books, any=any(b['gate_open'] for b in books), n_books=len(books), n_hold=n_hold, sells_due=sells_due),
        trend=(sig.get('recent') or [])[-10:],
        caveat='“情绪”指策略看的下跌恐慌程度（z），不是涨停板情绪；下面的推演和历史类比都不是预测。',
    )
    ov['watch'] = _watch(ov, sig, signals, holdings, fresh)
    return ov
