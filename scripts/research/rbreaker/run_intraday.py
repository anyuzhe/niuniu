"""原版 R-Breaker（日内、可做空）在指数与 ETF 的 5 分钟线上的验证（假设可 T+0、可做空——相当于股指期货的理想化版本；A 股股票做不到）。

  python scripts/research/rbreaker/run_intraday.py --out artifacts/research/rbreaker

数据：TDX 5 分钟线（bronze/provider=tdx/index_kline_min5、etf_kline_min5），约 2024-09 至今。只用每天恰好 48 根（09:35–15:00）的完整交易日。
成本按每次成交单边 c（基点）扣，每笔交易两次成交；反手算两笔。
对照：①同一标的“每天开盘买、收盘卖”；②时点匹配的随机日置换——每笔交易把成交日换成同一标的的随机另一天、同样的进出场时刻与方向，
重复 500 次，看真实平均收益排在置换分布的哪里（p 值）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

import numpy as np
import polars as pl

sys.path.insert(0, os.path.dirname(__file__))
import rb

BRONZE = '/Volumes/Lexar/niuniu-data/lake/bronze/provider=tdx/'
NBAR = 48
COSTS_BP = (0, 2, 5, 10)
REPS = 500


def load(path):
    """→ dates(list[str])、o/h/l/c 矩阵 (days × 48)，只保留完整交易日。"""
    d = pl.read_parquet(path, columns=['date', 'time', 'open', 'high', 'low', 'close']).with_columns(
        pl.col('time').str.slice(8, 4).cast(pl.Int32).alias('hm')).filter((pl.col('hm') >= 935) & (pl.col('hm') <= 1500))
    d = d.sort(['date', 'hm'])
    g = d.group_by('date', maintain_order=True).agg(pl.len().alias('n'), pl.col('open'), pl.col('high'), pl.col('low'), pl.col('close'))
    g = g.filter(pl.col('n') == NBAR)
    if g.height < 30:
        return None
    dates = [str(x) for x in g['date']]
    mats = [np.array(g[k].to_list(), float) for k in ('open', 'high', 'low', 'close')]
    return dates, mats


def previous_day_ok(dates):
    """第 k 天的“前一交易日”必须就是序列里的第 k-1 天，且间隔不超过 5 个自然日（节假日以内）。"""
    from datetime import date
    ds = [date.fromisoformat(x) for x in dates]
    return np.array([False] + [(ds[k] - ds[k - 1]).days <= 5 for k in range(1, len(ds))])


def run_symbol(code, dates, mats, variant, **kw):
    o, h, l, c = mats
    ok = previous_day_ok(dates)
    out = []
    # 前一日的 H/L/C 用 5 分钟线聚合（全天最高/最低/最后一根收盘）
    H, L, C = h.max(1), l.min(1), c[:, -1]
    for k in range(1, len(dates)):
        if not ok[k]:
            continue
        ln = {n: float(v) for n, v in rb.lines(H[k - 1], L[k - 1], C[k - 1], variant).items()}
        for t in rb.run_day(o[k], h[k], l[k], c[k], ln, **kw):
            out.append((code, k, t))
    return out


def null_means(trades_by_code, data, rng):
    """时点匹配的随机日置换（保留标的之间同一天的相关性）：每次重复，把每个日历日整体换成另一个随机日历日，
    同一标的、同样的进出场时刻与方向；某标的在被换到的那天没数据就不计。返回每次重复的“平均每笔收益”。"""
    G = sorted({d for _, (dates, _) in data.items() for d in dates})
    gi = {d: i for i, d in enumerate(G)}
    M = rng.integers(0, len(G), size=(REPS, len(G)))
    lookup = {}
    for code, (dates, _) in data.items():
        arr = np.full(len(G), -1)
        for k, d in enumerate(dates):
            arr[gi[d]] = k
        lookup[code] = arr
    sums, cnt = np.zeros(REPS), np.zeros(REPS)
    for code, items in trades_by_code.items():
        dates, (o, h, l, c) = data[code]
        for k, t in items:
            r = lookup[code][M[:, gi[dates[k]]]]
            ok = (r >= 0) & (r != k)
            rr = np.where(ok, r, 0)
            exit_px = c[rr, NBAR - 1] if t.at_close else o[rr, t.exit_i]
            val = t.side * (exit_px / o[rr, t.entry_i] - 1.0)
            sums += np.where(ok, val, 0.0)
            cnt += ok
    return sums / np.maximum(cnt, 1)


def summarize(trades, data, cost_bp, rng, label):
    """trades: [(code, day_index, Trade)]。"""
    rets = np.array([t.ret for _, _, t in trades])
    if len(rets) == 0:
        return dict(label=label, n=0)
    net = rets - 2 * cost_bp / 1e4
    by_code = defaultdict(list)
    by_date = defaultdict(list)
    for (code, k, t), x in zip(trades, net):
        by_code[code].append((k, t))
        by_date[data[code][0][k]].append(x)
    dm = np.array([np.mean(v) for v in by_date.values()])
    row = dict(label=label, cost_bp=cost_bp, n=int(len(rets)), n_dates=int(len(dm)), win=float((rets > 0).mean()), gross_bp=float(rets.mean() * 1e4),
               net_bp=float(net.mean() * 1e4),
               t_trade=float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 2 else None,
               t_date=float(dm.mean() / (dm.std(ddof=1) / np.sqrt(len(dm)))) if len(dm) > 2 else None)
    # 等权组合的日度收益（每个标的当天的合计收益，没触发就是 0；某天没数据的标的不计入当天分母）
    G = sorted({d for c_ in data for d in data[c_][0]})
    gi = {d: i for i, d in enumerate(G)}
    tot, cnt = np.zeros(len(G)), np.zeros(len(G))
    for code, (dates, _) in data.items():
        idx = np.array([gi[d] for d in dates])
        cnt[idx] += 1
    for code, items in by_code.items():
        dates = data[code][0]
        for k, t in items:
            tot[gi[dates[k]]] += t.ret - 2 * cost_bp / 1e4
    port = tot[cnt > 0] / cnt[cnt > 0]
    row['port_sharpe'] = float(port.mean() / port.std() * np.sqrt(242)) if port.std() > 0 else None
    row['port_ret_per_year_pct'] = float(port.mean() * 242 * 100)
    nm = null_means(by_code, data, rng) - 2 * cost_bp / 1e4
    row['null_mean_bp'] = float(nm.mean() * 1e4)
    row['null_sd_bp'] = float(nm.std() * 1e4)
    row['p_vs_null'] = float((nm >= net.mean()).mean())
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='artifacts/research/rbreaker')
    ap.add_argument('--max-etf', type=int, default=0)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(20261012)
    groups = {'index': sorted(glob.glob(BRONZE + 'index_kline_min5/*.parquet')), 'etf': sorted(glob.glob(BRONZE + 'etf_kline_min5/*.parquet'))}
    if args.max_etf:
        groups['etf'] = groups['etf'][:args.max_etf]
    results = []
    drift = {}
    for gname, files in groups.items():
        data = {}
        for f in files:
            if gname == 'etf' and os.path.basename(f).startswith(('sh_511', 'sz_1599')) and os.path.basename(f)[3:6] == '511':
                continue          # 债券 / 货币 ETF：日内波动只有几个基点，固定成本会把结果吃光，也不是 R-Breaker 的目标品种
            got = load(f)
            if got:
                data[os.path.basename(f)[:-8]] = got
        # 对照：每天开盘买收盘卖
        bh = []
        for code, (dates, (o, h, l, c)) in data.items():
            r = c[:, -1] / o[:, 0] - 1
            bh.append((r.mean() * 1e4, r.mean() / r.std() * np.sqrt(242)))
        Gd = sorted({d for c_ in data for d in data[c_][0]})
        gix = {d: i for i, d in enumerate(Gd)}
        tot, cnt = np.zeros(len(Gd)), np.zeros(len(Gd))
        for code, (dates, (o, h, l, c)) in data.items():
            ii = np.array([gix[d] for d in dates])
            tot[ii] += c[:, -1] / o[:, 0] - 1
            cnt[ii] += 1
        passive = tot / cnt
        passive_port = {f'c{cb}': float((passive - 2 * cb / 1e4).mean() / passive.std() * np.sqrt(242)) for cb in COSTS_BP}
        drift[gname] = dict(passive_port_sharpe=passive_port, passive_ann_pct=float(passive.mean() * 242 * 100), n_symbols=len(data), intraday_long_bp=float(np.mean([a for a, _ in bh])), intraday_long_sharpe=float(np.mean([b for _, b in bh])),
                            days_per_symbol=float(np.mean([len(v[0]) for v in data.values()])))
        for variant in ('pivot', 'classic'):
            configs = [('原版（多空、突破+反转）', dict())] if gname == 'index' else []
            configs += [('只做多（突破+反转）', dict(allow_short=False)), ('只做多·仅突破', dict(allow_short=False, allow_rev=False))]
            for name, kw in configs:
                trades = []
                for code, (dates, mats) in data.items():
                    trades += run_symbol(code, dates, mats, variant, **kw)
                with open(os.path.join(args.out, f'trades_{gname}_{variant}_{len(kw)}{sorted(kw)}.csv'.replace(' ', '').replace("'", '').replace('[', '_').replace(']', '')), 'w') as fh:
                    fh.write('code,date,kind,side,entry_i,exit_i,ret\n')
                    for code, k, t in trades:
                        fh.write(f'{code},{data[code][0][k]},{t.kind},{t.side},{t.entry_i},{t.exit_i},{t.ret:.6f}\n')
                for cost in COSTS_BP:
                    results.append(dict(group=gname, variant=variant, rule=name, **summarize(trades, data, cost, rng, name)))
                kinds = sorted({t.kind for _, _, t in trades})
                if kw == {} or kw == dict(allow_short=False):
                    for kind in kinds:
                        sub = [x for x in trades if x[2].kind == kind]
                        for cost in (0, 5):
                            results.append(dict(group=gname, variant=variant, rule=name, **summarize(sub, data, cost, rng, '  └ ' + kind)))
    json.dump(dict(results=results, drift=drift), open(os.path.join(args.out, 'intraday.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(drift, ensure_ascii=False, indent=1))
    for r in results:
        if r.get('n', 0) == 0:
            continue
        print(f"{r['group']:5s} {r['variant']:7s} {r['rule'][:14]:14s} {r['label'][:16]:16s} c={r['cost_bp']:>2}bp n={r['n']:6d} win={r['win']*100:5.1f}% gross={r['gross_bp']:+7.1f}bp "
              f"net={r['net_bp']:+7.1f}bp tT={r['t_trade'] if r['t_trade'] is None else round(r['t_trade'], 1)} tD={r['t_date'] if r['t_date'] is None else round(r['t_date'], 1)} sharpe={r['port_sharpe'] if r['port_sharpe'] is None else round(r['port_sharpe'], 2)} ann={r['port_ret_per_year_pct']:+.1f}% "
              f"null={r['null_mean_bp']:+6.1f}±{r['null_sd_bp']:.1f}bp p={r['p_vs_null']:.3f} nd={r['n_dates']}")


if __name__ == '__main__':
    main()
