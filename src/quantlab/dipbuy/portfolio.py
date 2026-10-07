"""我的持仓与明天的操作清单（纸面辅助，不下单、不连券商）。

用户自己录入真实持仓，按策略 D / D1 的规则算“明天该做什么”：

  * 持仓只存在本机 <output>/_home/dip_holdings.json，先写 .tmp 再替换，拒绝符号链接；
  * 到期判断和回测一致：买入当天算第 1 个持有日，第 hold_days 个持有日收盘卖出；
    数据最后一天已经是第 hold_days 个持有日或更晚的，算“已到期”，明天开盘就该卖；
  * 买入计划照搬 simulate_fused 的选股流程（A → C → B 的顺序、每层名额扣掉这一层已持有的、已持有的股票不重复买、
    总仓位不超过 gross_cap），区别只有两点：不用“次日开盘是否涨停”过滤（那是明天才知道的），
    以及金额按用户填的账户总资产（权益）和已有持仓市值扣除后算；
  * 数据不是最新（已经过了下一个交易日）就不出买入计划，只给持仓估值，避免按旧信号下单。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from quantlab.dipbuy import autorecord, fusion
from quantlab.dipbuy.fusion import ORDER, order_candidates
from quantlab.dipbuy.panel import Panel

FORMAT = 'niuniu-dip-holdings-v1'
MAX_HOLDINGS = 200
SLEEVES = ('', 'A', 'C', 'B')
LOT = 100


def _path(output) -> Path:
    return Path(output).resolve() / '_home' / 'dip_holdings.json'


def load(output) -> dict:
    empty = dict(format=FORMAT, equity_wan=40.0, holdings=[])
    path = _path(output)
    if not path.is_file() or path.is_symlink():
        return empty
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        return empty
    rows = [h for h in value.get('holdings', []) if isinstance(h, dict) and h.get('id') and h.get('code')
            and isinstance(h.get('shares'), int) and h.get('entry_date')]
    eq = value.get('equity_wan')
    return dict(format=FORMAT, equity_wan=float(eq) if isinstance(eq, (int, float)) and eq > 0 else 40.0, holdings=rows)


def _save(output, data: dict) -> None:
    path = _path(output)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('记录目录不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(dict(data, format=FORMAT, updated_at=datetime.now(timezone.utc).isoformat()),
                              ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    tmp.replace(path)


def normalize_code(text: str) -> str:
    """'600000'、'sh600000'、'SH.600000'、'600000.SH' 都变成 'sh.600000'；认不出就报错。"""
    s = str(text or '').strip().lower().replace(' ', '')
    m = re.fullmatch(r'(?:(sh|sz|bj)\.?)?(\d{6})(?:\.(sh|sz|bj))?', s)
    if not m:
        raise ValueError('股票代码要 6 位数字，例如 600000 或 sh.600000')
    market, num = m.group(1) or m.group(3), m.group(2)
    if market is None:
        market = 'sh' if num[0] in '69' else 'sz' if num[0] in '03' else 'bj' if num[0] in '48' else None
        if market is None:
            raise ValueError('认不出这是沪市还是深市的代码，请写成 sh.xxxxxx 或 sz.xxxxxx')
    return f'{market}.{num}'


def _check_day(value: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError('买入日要写成 2026-10-08 这样的格式') from None


def add_holding(output, *, code, shares, entry_date, cost=None, sleeve='', note='') -> dict:
    data = load(output)
    code = normalize_code(code)
    if not isinstance(shares, int) or isinstance(shares, bool) or shares <= 0:
        raise ValueError('股数要是正整数')
    if sleeve not in SLEEVES:
        raise ValueError('层只能是 A、C、B 或留空')
    if cost is not None and not (isinstance(cost, (int, float)) and cost > 0):
        raise ValueError('成本价要大于 0，不知道可以留空')
    if any(h['code'] == code for h in data['holdings']):
        raise ValueError(f'已经有 {code} 的持仓，请先删除再重新录入')
    if len(data['holdings']) >= MAX_HOLDINGS:
        raise ValueError('持仓太多了')
    h = dict(id=uuid.uuid4().hex[:12], code=code, shares=shares, entry_date=_check_day(entry_date),
             cost=float(cost) if cost else None, sleeve=sleeve, note=str(note or '')[:60])
    data['holdings'].append(h)
    _save(output, data)
    return h


def remove_holding(output, hid: str) -> bool:
    data = load(output)
    keep = [h for h in data['holdings'] if h['id'] != hid]
    if len(keep) == len(data['holdings']):
        return False
    data['holdings'] = keep
    _save(output, data)
    return True


def set_equity(output, equity_wan: float) -> None:
    if not (isinstance(equity_wan, (int, float)) and equity_wan > 0):
        raise ValueError('账户总资产要大于 0')
    data = load(output)
    data['equity_wan'] = float(equity_wan)
    _save(output, data)


def clear_expired(output, panel: Panel, hold_days: int) -> int:
    """卖完之后清掉已到期的持仓（数据最后一天已经是第 hold_days 个持有日或更晚）。返回清掉几条。"""
    data = load(output)
    ds = np.array([str(d) for d in panel.dates])
    t = len(ds) - 1
    keep, n = [], 0
    for h in data['holdings']:
        d = _days_held(ds, t, h['entry_date'])
        if d is not None and d >= hold_days:
            n += 1
        else:
            keep.append(h)
    if n:
        data['holdings'] = keep
        _save(output, data)
    return n


def _days_held(ds: np.ndarray, t: int, entry: str):
    """数据最后一天（下标 t）是买入后的第几个持有日（买入当天算第 1 天）；买入日晚于数据最后一天返回 None。"""
    if entry > ds[t]:
        return None
    e = int(np.searchsorted(ds, entry))
    return t - e + 1


def _last_close(panel: Panel, t: int, j: int):
    """最近一个有价的未复权收盘价和它的日期下标；停牌太久返回 (None, None)。"""
    for i in range(t, max(-1, t - 10), -1):
        c, f = panel.c[i, j], panel.f[i, j]
        if np.isfinite(c) and np.isfinite(f) and f > 0:
            return float(c) / float(f), i
    return None, None


def plan_operations(panel: Panel, inp, cfg, holdings: list[dict], *, equity: float, names: dict | None = None,
                    today: date | None = None, spare: int = 5) -> dict:
    """数据最后一天收盘后，明天（下一个开市日）该卖什么、该买什么。"""
    names = names or {}
    ds = np.array([str(d) for d in panel.dates])
    t = len(ds) - 1
    H, N, W, G = cfg.hold_days, cfg.positions, cfg.weights, cfg.gross_cap
    last = ds[t]
    plan_day = autorecord.next_open_day(last)
    stale = bool(today is not None and today > plan_day)
    code_ix = {str(c): j for j, c in enumerate(panel.codes)}
    notes: list[str] = []
    if stale:
        notes.append(f'数据只到 {last}，已经过了下一个开市日 {plan_day.isoformat()}：先更新数据再看买入计划；下面的持仓天数也只算到 {last}。')

    held_rows, active, held_idx = [], [], set()
    for h in holdings:
        j = code_ix.get(h['code'])
        d = _days_held(ds, t, h['entry_date'])
        px, _ = _last_close(panel, t, j) if j is not None else (None, None)
        cost_basis = h.get('cost')
        value = h['shares'] * px if px else (h['shares'] * cost_basis if cost_basis else None)
        row = dict(id=h['id'], code=h['code'], name=names.get(h['code'], ''), shares=h['shares'], entry_date=h['entry_date'],
                   cost=cost_basis, sleeve=h.get('sleeve', ''), close=px, value=value,
                   pnl=(px / cost_basis - 1) if px and cost_basis else None, days_held=d)
        if j is None:
            row['status'], row['sell_in'] = 'unknown', None
            row['advice'] = '面板里没有这只股票，无法估值和判断到期'
        elif d is None:
            row['status'], row['sell_in'] = 'pending', None
            row['advice'] = f"买入日 {h['entry_date']} 晚于数据最后一天，数据更新后再算"
        else:
            sell_in = H - d
            row['sell_in'] = sell_in
            if sell_in <= 0:
                row['status'] = 'overdue'
                row['advice'] = '已到期：明天开盘卖出' + ('（已过期 %d 天）' % (-sell_in) if sell_in < 0 else '')
            elif sell_in == 1:
                row['status'] = 'due'
                row['advice'] = f'明天（{plan_day.isoformat()}）收盘前卖出'
            else:
                row['status'] = 'hold'
                row['advice'] = f'继续持有，还有 {sell_in} 个交易日到期'
        if row['status'] in ('hold', 'due', 'pending', 'unknown'):
            active.append(row)
            if j is not None:
                held_idx.add(j)
        held_rows.append(row)
    invested = sum(r['value'] or 0.0 for r in active)
    if equity <= 0:
        notes.append('账户总资产要大于 0。')
    elif invested > equity * G + 1:
        notes.append(f'持仓市值 {invested:,.0f} 元已超过账户总资产 × {G:g}，请核对账户总资产。')
    if any(r['status'] == 'unknown' for r in held_rows):
        notes.append('有持仓不在面板里（代码写错、北交所或已退市很久），无法算到期，请自己核对。')
    n_unlabeled = sum(1 for r in active if not r['sleeve'])
    if n_unlabeled:
        notes.append(f'{n_unlabeled} 只持仓没有标注是哪一层买的，它们不占 A / C / B 的名额，只占资金和“不重复买”。')

    sells = [r for r in held_rows if r['status'] in ('overdue', 'due')]
    buys, spares = [], []
    sleeves = {}
    small: dict[str, int] = {}
    cap_note = False
    if not stale and equity > 0:
        for s in ORDER:
            n_s = sum(1 for r in active if r['sleeve'] == s)
            gate = bool(inp.gates[s][t])
            sleeves[s] = dict(gate=gate, held=n_s, slots=max(0, N - n_s))
            if not gate or n_s >= N:
                continue
            base = np.nonzero(inp.pools[s][t])[0]
            pool = np.array([j for j in base if j not in held_idx], dtype=int)
            if not len(pool):
                continue
            pool = order_candidates(panel, inp, cfg, t, base, pool)
            take = N - n_s
            for rank, j in enumerate(pool[:take + spare], 1):
                px, _ = _last_close(panel, t, int(j))
                if px is None or px <= 0:
                    continue
                code = str(panel.codes[j])
                if rank > take:
                    spares.append(dict(sleeve=s, rank=rank, code=code, name=names.get(code, ''), close=px))
                    continue
                cap_left = G * equity - invested
                if cap_left < px * LOT:
                    if not cap_note:
                        notes.append(f'总仓位上限（账户总资产的 {G * 100:g}%）已用完，排在后面的候选不买。')
                        cap_note = True
                    break
                size = max(0.0, min(W[s] * equity, cap_left))
                shares = int(size / px // LOT * LOT)
                if shares <= 0:
                    small[s] = small.get(s, 0) + 1
                    continue
                invested += shares * px
                held_idx.add(int(j))
                buys.append(dict(sleeve=s, rank=rank, code=code, name=names.get(code, ''), close=px, weight=W[s],
                                 amount=shares * px, shares=shares))
        for s, n in small.items():
            notes.append(f'{s} 层每只计划金额约 {W[s] * equity:,.0f} 元，买不起一手，已略过 {n} 只。')
    else:
        for s in ORDER:
            sleeves[s] = dict(gate=bool(inp.gates[s][t]), held=sum(1 for r in active if r['sleeve'] == s), slots=None)
    proceeds = sum(r['value'] or 0.0 for r in sells)
    new_money = sum(b['amount'] for b in buys)
    return dict(data_date=last, plan_day=plan_day.isoformat(), stale=stale, variant=cfg.variant, equity=float(equity),
                holdings=held_rows, sells=sells, buys=buys, spares=spares, sleeves=sleeves, notes=notes,
                invested_after=invested, proceeds=proceeds, new_money=new_money,
                gate_open=bool(inp.any_gate[t]), fired=[s for s in ORDER if inp.gates[s][t]],
                hold_days=H, config_hash=cfg.hash())
