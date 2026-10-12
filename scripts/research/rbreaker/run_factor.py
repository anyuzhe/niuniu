"""R-Breaker “区间位置”因子化验证（笔记 §18④）：RB_position = (price - Pivot) / (Bbreak - Sbreak)。

在 pivot 版里 Bbreak - Sbreak 恒等于 3(H-L)，所以 RB_position_t = (收盘_t - Pivot_{t-1}) / (3 (H-L)_{t-1})：
用“昨日振幅”做单位衡量今天收盘偏离昨日枢轴有多远。它和 1 日收益、按昨日振幅归一的 1 日收益高度同源——这里检验它有没有独立于这两者的预测力。
全 A 日线（前复权，2019 至今），收盘后算因子，次日开盘买（高开涨停的剔除）：
  F1 = 次日 开→收；  F5 = 持有到第 5 日收盘；  CC1 = 收→次日收（含隔夜，仅供参考）。
  python scripts/research/rbreaker/run_factor.py --out artifacts/research/rbreaker
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date

import numpy as np
import polars as pl

DIR = '/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_daily_v2/'
MIN_AMT = 1e8


def build():
    files = sorted(glob.glob(DIR + 's[hz]_*.parquet'))
    frames = []
    for f in files:
        code = os.path.basename(f)[:-8]
        if code[3:].startswith(('8', '4', '9')):
            continue
        d = pl.read_parquet(f, columns=['date', 'code', 'open', 'high', 'low', 'close', 'amount']).filter(pl.col('date') >= date(2018, 10, 1))
        if d.height > 80:
            frames.append(d)
    df = pl.concat(frames).sort(['code', 'date'])
    g = pl.col('code')
    df = df.with_columns(
        pl.col('date').shift(1).over(g).alias('pdate'), pl.col('high').shift(1).over(g).alias('H1'), pl.col('low').shift(1).over(g).alias('L1'),
        pl.col('close').shift(1).over(g).alias('C1'), pl.col('amount').shift(1).over(g).alias('A1'),
        pl.col('date').shift(-1).over(g).alias('ndate'), pl.col('open').shift(-1).over(g).alias('O_n'), pl.col('close').shift(-1).over(g).alias('C_n'),
        pl.col('close').shift(-5).over(g).alias('C_n5'), pl.col('date').shift(-5).over(g).alias('ndate5'))
    df = df.with_columns(
        ((pl.col('H1') + pl.col('L1') + pl.col('C1')) / 3).alias('P1'), (pl.col('H1') - pl.col('L1')).alias('R1'),
        (pl.col('date') - pl.col('pdate')).dt.total_days().alias('gap'), (pl.col('ndate') - pl.col('date')).dt.total_days().alias('ngap'),
        (pl.col('ndate5') - pl.col('date')).dt.total_days().alias('ngap5'))
    df = df.with_columns(
        ((pl.col('close') - pl.col('P1')) / (3 * pl.col('R1'))).alias('rbpos'),
        (pl.col('close') / pl.col('C1') - 1).alias('ret1'),
        ((pl.col('close') - pl.col('C1')) / pl.col('R1')).alias('ret1_norm'),
        (pl.col('C_n') / pl.col('O_n') - 1).alias('F1'),
        (pl.col('C_n5') / pl.col('O_n') - 1).alias('F5'),
        (pl.col('C_n') / pl.col('close') - 1).alias('CC1'))
    ok = ((pl.col('date') >= date(2019, 1, 1)) & (pl.col('gap') <= 5) & (pl.col('ngap') <= 5) & (pl.col('ngap5') <= 12) & (pl.col('R1') > 0)
          & (pl.col('A1') >= MIN_AMT) & (pl.col('amount') >= MIN_AMT) & (pl.col('O_n') < pl.col('close') * 1.095))
    return df.filter(ok).drop_nulls(['rbpos', 'ret1', 'ret1_norm', 'F1', 'F5', 'CC1'])


def rank_ic(df, fac, tgt):
    r = df.with_columns(pl.col(fac).rank().over('date').alias('_a'), pl.col(tgt).rank().over('date').alias('_b'))
    ic = r.group_by('date').agg(pl.corr('_a', '_b').alias('ic'), pl.len().alias('n')).filter(pl.col('n') >= 200).sort('date').drop_nulls('ic')
    x = ic['ic'].to_numpy()
    # 5 日持有的 IC 序列相邻重叠，t 值用 Newey-West 近似：按 5 步自相关修正
    n = len(x)
    lag = 5 if tgt == 'F5' else 1
    xc = x - x.mean()
    var = (xc @ xc) / n
    for L in range(1, lag):
        var += 2 * (1 - L / lag) * (xc[L:] @ xc[:-L]) / n
    t = x.mean() / np.sqrt(var / n)
    return dict(ic=float(x.mean()), icir=float(x.mean() / x.std(ddof=1)), t=float(t), pos_rate=float((x > 0).mean()), n_dates=int(n)), ic


def quintiles(df, fac, tgt):
    r = df.with_columns(((pl.col(fac).rank().over('date') - 1) / pl.len().over('date') * 5).floor().cast(pl.Int32).clip(0, 4).alias('q'))
    t = r.group_by(['date', 'q']).agg(pl.col(tgt).mean().alias('m')).group_by('q').agg(pl.col('m').mean()).sort('q')
    return [float(v) * 1e4 for v in t['m']]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='artifacts/research/rbreaker')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    df = build()
    print(f'样本 {df.height} 行，{df["code"].n_unique()} 只，{df["date"].n_unique()} 个交易日，{df["date"].min()} ~ {df["date"].max()}', flush=True)
    out = dict(rows=df.height)
    for tgt in ('F1', 'F5', 'CC1'):
        for fac in ('rbpos', 'ret1_norm', 'ret1'):
            s, series = rank_ic(df, fac, tgt)
            out[f'{fac}/{tgt}'] = s
            out[f'{fac}/{tgt}']['quintile_bp'] = quintiles(df, fac, tgt)
            yearly = series.with_columns(pl.col('date').dt.year().alias('y')).group_by('y').agg(pl.col('ic').mean()).sort('y')
            out[f'{fac}/{tgt}']['ic_by_year'] = {int(a): float(b) for a, b in zip(yearly['y'], yearly['ic'])}
    # 与对照因子的横截面相关，以及控制 ret1_norm 之后 rbpos 还剩什么：把 rbpos 对 ret1_norm 按日回归取残差
    r = df.with_columns(pl.col('rbpos').rank().over('date').alias('a'), pl.col('ret1_norm').rank().over('date').alias('b'), pl.col('ret1').rank().over('date').alias('c'))
    cc = r.group_by('date').agg(pl.corr('a', 'b').alias('r_norm'), pl.corr('a', 'c').alias('r_ret1')).drop_nulls()
    out['rank_corr_with'] = dict(ret1_norm=float(cc['r_norm'].mean()), ret1=float(cc['r_ret1'].mean()))
    r = r.with_columns(((pl.col('a') - pl.col('a').mean().over('date')) - (pl.corr('a', 'b').over('date') * pl.col('a').std().over('date') / pl.col('b').std().over('date')) * (pl.col('b') - pl.col('b').mean().over('date'))).alias('resid'))
    for tgt in ('F1', 'F5'):
        s, _ = rank_ic(r, 'resid', tgt)
        out[f'rbpos_resid_ret1_norm/{tgt}'] = s
    json.dump(out, open(os.path.join(args.out, 'factor.json'), 'w'), ensure_ascii=False, indent=1)
    print(f"rbpos 与 ret1_norm 的横截面秩相关 {out['rank_corr_with']['ret1_norm']:.3f}，与 ret1 {out['rank_corr_with']['ret1']:.3f}")
    for k, v in out.items():
        if isinstance(v, dict) and 'ic' in v:
            q = ' '.join(f'{x:+.0f}' for x in v.get('quintile_bp', []))
            print(f"{k:34s} IC={v['ic']:+.4f} ICIR={v['icir']:+.2f} t={v['t']:+.1f} 正比例={v['pos_rate']*100:.0f}% 五分位(bp, 低→高): {q}")
            if 'ic_by_year' in v:
                print('    分年IC: ' + ' '.join(f'{y}:{x:+.3f}' for y, x in v['ic_by_year'].items()))


if __name__ == '__main__':
    main()
