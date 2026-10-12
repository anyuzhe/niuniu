"""R-Breaker 的 A 股可交易版（T+1、只能做多）验证：个股 5 分钟线，2020 年至今，随机抽样。

事件：①突破买入（盘中某根 5 分钟收盘价 > Bbreak）；②杀跌失败（当天最低先跌破 Bsetup，之后某根收盘价 > Benter）。每股每天各取第一次触发，
下一根开盘价买入（涨停封死买不进的剔除），次日开盘价或次日收盘价卖出（T+1）。
对照：同一天、同一根 5 分钟线开盘买、次日同一时点卖的全样本平均（控制当天大盘与时段漂移）→ 超额收益。
股票池：随机 N 只（固定种子），剔除北交所、ST（按 9-23 名称快照）、上市不足 10 个交易日、前一日成交额 < 5000 万、前一交易日不连续（停牌复牌）。

  python scripts/research/rbreaker/run_stocks.py --n 400 --out artifacts/research/rbreaker
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import date

import numpy as np
import polars as pl

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'src'))
import rb

DIR = '/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_min5_v2/'
NBAR = 48
START = date(2020, 1, 1)
MIN_AMT = 5e7


def limit_pct(code):
    n = code.split('.')[-1] if '.' in code else code[3:]
    if n.startswith(('688', '689', '300', '301')):
        return 0.20
    if n.startswith(('8', '4', '9')):
        return None
    return 0.10


def load(path):
    d = pl.read_parquet(path, columns=['date', 'time', 'code', 'open', 'high', 'low', 'close', 'amount']).filter(pl.col('date') >= START)
    d = d.with_columns(pl.col('time').str.slice(8, 4).cast(pl.Int32).alias('hm')).filter((pl.col('hm') >= 935) & (pl.col('hm') <= 1500)).sort(['date', 'hm'])
    g = d.group_by('date', maintain_order=True).agg(pl.len().alias('n'), pl.col('open'), pl.col('high'), pl.col('low'), pl.col('close'), pl.col('amount').sum().alias('amt'))
    g = g.filter(pl.col('n') == NBAR)
    if g.height < 60:
        return None
    dates = [x for x in g['date']]
    o, h, l, c = (np.array(g[k].to_list(), float) for k in ('open', 'high', 'low', 'close'))
    return d['code'][0], dates, o, h, l, c, g['amt'].to_numpy()


def stock_names():
    try:
        from quantlab.dipbuy import panel as dpanel
        return dpanel.load_names()
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=400)
    ap.add_argument('--seed', type=int, default=20261012)
    ap.add_argument('--out', default='artifacts/research/rbreaker')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    names = stock_names()
    files = sorted(glob.glob(DIR + 's[hz]_*.parquet'))
    rng = np.random.default_rng(args.seed)
    rng.shuffle(files)
    # 全局交易日历：取一只老股票的完整日
    ref = load(DIR + 'sh_600000.parquet')
    G = [d for d in ref[1]]
    gi = {d: i for i, d in enumerate(G)}
    D, K = len(G), NBAR - 1
    base_o, base_c, base_n = np.zeros((D, K)), np.zeros((D, K)), np.zeros((D, K))
    events = []          # (date_idx, k, code, variant, kind, ret_open, ret_close)
    used = 0
    for f in files:
        if used >= args.n:
            break
        code0 = os.path.basename(f)[:-8].replace('_', '.')
        pct = limit_pct(code0)
        nm = names.get(code0, '')
        if pct is None or 'ST' in nm.upper():
            continue
        got = load(f)
        if not got:
            continue
        used += 1
        code, dates, o, h, l, c, amt = got
        n = len(dates)
        di = np.array([gi.get(d, -1) for d in dates])
        gap = np.array([0] + [(dates[k] - dates[k - 1]).days for k in range(1, n)])
        H, L, C = h.max(1), l.min(1), c[:, -1]
        prevc = np.concatenate([[np.nan], C[:-1]])
        valid = (np.arange(n) >= 10) & (gap <= 5) & (di >= 0) & (np.concatenate([[0], amt[:-1]]) >= MIN_AMT)
        nxt = np.arange(n) + 1
        has_next = (nxt < n)
        nxt_c = np.minimum(nxt, n - 1)
        has_next &= (gap[nxt_c] <= 5) & (di[nxt_c] >= 0) & (np.arange(n) < n - 1)
        # 次日开盘、次日收盘
        o_next = np.where(has_next, o[nxt_c, 0], np.nan)
        c_next = np.where(has_next, c[nxt_c, -1], np.nan)
        # 基线：任一根 5 分钟线（k+1 根开盘）买入的同一天同一时点平均收益
        ent = o[:, 1:]                                                     # 第 k+1 根开盘，k=0..46
        ok_b = valid & has_next
        with np.errstate(invalid='ignore', divide='ignore'):
            ro = o_next[:, None] / ent - 1.0
            rc = c_next[:, None] / ent - 1.0
        fin = np.isfinite(ro) & np.isfinite(rc) & (ent > 0)              # 坏数据（开盘价为 0 等）既不进基线也不进事件
        ro, rc = np.where(fin, ro, 0.0), np.where(fin, rc, 0.0)
        for dd in np.where(ok_b)[0]:
            base_o[di[dd]] += ro[dd]
            base_c[di[dd]] += rc[dd]
            base_n[di[dd]] += fin[dd]
        limit_px = prevc * (1 + pct)
        for variant in ('pivot', 'classic'):
            ln = rb.lines(np.concatenate([[np.nan], H[:-1]]), np.concatenate([[np.nan], L[:-1]]), prevc, variant)
            sig = {'brk': rb.first_brk_long_mat(c, ln['Bbreak']), 'rev': rb.first_rev_long_mat(l, c, ln['Bsetup'], ln['Benter'])}
            for kind, idx in sig.items():
                for dd in np.where((idx >= 0) & ok_b)[0]:
                    i = idx[dd]
                    px = o[dd, i + 1]
                    if not fin[dd, i]:
                        continue
                    if px >= limit_px[dd] * 0.995 or c[dd, i] >= limit_px[dd] * 0.995:        # 封死涨停：买不进
                        continue
                    events.append((int(di[dd]), int(i), code, variant, kind, float(o_next[dd] / px - 1.0), float(c_next[dd] / px - 1.0)))
    print(f'股票 {used} 只，事件 {len(events)} 个', flush=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        bo = base_o / base_n
        bc = base_c / base_n
    out = {}
    for variant in ('pivot', 'classic'):
        for kind in ('brk', 'rev'):
            ev = [e for e in events if e[3] == variant and e[4] == kind]
            if not ev:
                continue
            d = np.array([e[0] for e in ev]); k = np.array([e[1] for e in ev])
            ro_ = np.array([e[5] for e in ev]); rc_ = np.array([e[6] for e in ev])
            res = {}
            for hname, r, b in (('次日开盘卖', ro_, bo), ('次日收盘卖', rc_, bc)):
                base = b[d, k]
                good = np.isfinite(base)
                ex = (r - base)[good]
                dd = d[good]
                # 按日聚类：每个日历日内的平均超额收益，再做 t 检验
                uniq = np.unique(dd)
                dm = np.array([ex[dd == u].mean() for u in uniq])
                yr = np.array([G[u].year for u in dd])
                res[hname] = dict(n=int(good.sum()), n_dates=int(len(uniq)), raw_bp=float(r[good].mean() * 1e4), base_bp=float(base[good].mean() * 1e4),
                                  excess_bp=float(ex.mean() * 1e4), t_date=float(dm.mean() / (dm.std(ddof=1) / np.sqrt(len(dm)))) if len(dm) > 2 else None,
                                  win_raw=float((r[good] > 0).mean()), by_year={int(y): dict(n=int((yr == y).sum()), excess_bp=float(ex[yr == y].mean() * 1e4)) for y in np.unique(yr)})
            res['events_per_stock_year'] = len(ev) / used / ((G[-1] - G[0]).days / 365.25)
            out[f'{variant}/{kind}'] = res
    json.dump(dict(n_stocks=used, n_events=len(events), results=out), open(os.path.join(args.out, 'stocks.json'), 'w'), ensure_ascii=False, indent=1)
    for key, res in out.items():
        print(f"== {key}  每股每年触发 {res['events_per_stock_year']:.2f} 次")
        for hname in ('次日开盘卖', '次日收盘卖'):
            r = res[hname]
            print(f"  {hname}: n={r['n']} 日期数={r['n_dates']} 原始={r['raw_bp']:+.1f}bp 基线={r['base_bp']:+.1f}bp 超额={r['excess_bp']:+.1f}bp t(按日)={r['t_date']:+.2f} 胜率={r['win_raw']*100:.1f}%")
            print('    分年超额(bp): ' + ' '.join(f"{y}:{v['excess_bp']:+.0f}(n={v['n']})" for y, v in r['by_year'].items()))


if __name__ == '__main__':
    main()
