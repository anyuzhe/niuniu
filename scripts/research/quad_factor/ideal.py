"""Native re-computation of docs/reference/quad-factor-composite-v1.json (no tuning)."""
import sys, json, pickle, datetime as dt, math
from pathlib import Path
import numpy as np
import polars as pl

REPO = Path(sys.argv[1]); LAKE = Path(sys.argv[2]); OUT = Path(sys.argv[3])
PHASE = int(sys.argv[4]) if len(sys.argv) > 4 else 0
sys.path.insert(0, str(REPO / 'src'))

from quantlab.factors.registry import FactorRegistry
from quantlab.factors.builtin import base_quant_pack
from quantlab.factors.alpha import alpha_packs
from quantlab.factors.combinations import combination_pack
from quantlab.factors.engine import compute_factor
from quantlab.data.validation import PUBLISHED_RESEARCH_CONTRACT, ordered_bars
from quantlab.execution.backtest import OpenExecutionBacktester, ExecutionConfig
from datetime import time

START, END = dt.date(2018, 1, 1), dt.date(2026, 9, 4)
QFQ = LAKE / 'silver/qfq_kline_daily_v2'
STATUS = LAKE / 'bronze/provider=baostock/daily_status_v2'

cov = pl.read_parquet(QFQ / '_meta/coverage.parquet')
pool = cov.filter((~pl.col('history_truncated')) & (pl.col('valid_from') <= '2018-01-01'))['code'].to_list()
def board(c):
    n = c[3:]
    if c.startswith('sh.') and n[:3] in ('600', '601', '603', '605'): return 'SH'
    if c.startswith('sz.') and n[:3] in ('000', '001', '002', '003'): return 'SZ'
    if c.startswith('sz.') and n[:3] in ('300', '301'): return 'CY'
    return None
pool = [c for c in sorted(pool) if board(c)]

def clean(code):
    b = pl.read_parquet(QFQ / (code.replace('.', '_') + '.parquet')).filter(pl.col('date').is_between(START, END))
    s = pl.read_parquet(STATUS / (code.replace('.', '_') + '.parquet')).with_columns(pl.col('date').str.to_date()).filter(pl.col('date').is_between(START, END))
    if b.height == 0: return None
    if b.select(pl.any_horizontal(pl.col('open', 'high', 'low', 'close', 'volume', 'factor').is_null())).to_series().any(): return None
    if s.filter(pl.col('tradestatus') != '1').height: return None
    return b.join(s.select('date', 'tradestatus', 'isST'), on='date', how='left')

eligible = {}
for c in pool:
    r = clean(c)
    if r is not None: eligible[c] = r
sess = pl.concat([f.select('date') for f in eligible.values()]).unique().sort('date')['date'].to_list()
eligible = {c: f for c, f in eligible.items() if f.height == len(sess)}
by_board = {k: [c for c in eligible if board(c) == k] for k in ('SH', 'SZ', 'CY')}
quota = {'SH': 34, 'SZ': 33, 'CY': 33}
def draw(codes, n, phase):
    step = (len(codes) - 1) / (n - 1)
    if phase == 0:
        idx = [int(round(i * step)) for i in range(n)]
    else:
        idx = [min(len(codes) - 1, int(i * len(codes) / n) + phase) for i in range(n)]
    return [codes[i] for i in idx]
symbols = []
for k in ('SH', 'SZ', 'CY'):
    sel = draw(by_board[k], quota[k], PHASE)
    assert len(set(sel)) == quota[k], (k, len(set(sel)))
    symbols += sel
print('pool sizes', {k: len(v) for k, v in by_board.items()}, 'n_symbols', len(symbols), 'sessions', len(sess), flush=True)

frames = []
for c in sorted(symbols):
    f = eligible[c]
    stamp = pl.col('date').dt.combine(time(15)).dt.replace_time_zone('Asia/Shanghai')
    frames.append(f.select(pl.lit(c).alias('symbol'), pl.lit(c[:2]).alias('exchange'), stamp.alias('datetime'), stamp.alias('available_at'),
        pl.lit('1d').alias('timeframe'), *[pl.col(k).cast(pl.Float64) for k in ('open', 'high', 'low', 'close', 'volume')],
        pl.col('amount').cast(pl.Float64).alias('turnover'), pl.col('factor').cast(pl.Float64).alias('adj_factor'),
        ))
bars = ordered_bars(pl.concat(frames))

reg = FactorRegistry(); reg.register_pack(base_quant_pack())
for _p in alpha_packs(): reg.register_pack(_p)
reg.register_pack(combination_pack(reg))
comb = reg.get('COMB.SCORE', '1.0.0')
params = {'inputs': {
    'a28': {'factor_id': 'ALPHA101.ALPHA28'},
    'qtld': {'factor_id': 'ALPHA158.QTLD_5'},
    'sumd': {'factor_id': 'ALPHA158.SUMD_30'},
    'atr': {'factor_id': 'BASE.ATR', 'parameters': {'lookback': 60}}},
    'weights': {'a28': 1.0, 'qtld': 1.0, 'sumd': 1.0, 'atr': 1.0}}
obs = compute_factor(comb, bars, params)
print('factor rows', obs.height, 'non-null', obs['value'].drop_nulls().len(), flush=True)

TOP_N, HOLD = 20, 40
days = sorted(bars['datetime'].unique().to_list())
syms = sorted(symbols)
score = {}
for k, g in obs.group_by('datetime'):
    score[k[0]] = {r['symbol']: r['value'] for r in g.iter_rows(named=True) if r['value'] is not None and math.isfinite(r['value'])}
cohorts = {}
for d in days:
    s = score.get(d, {})
    cohorts[d] = sorted(s, key=lambda x: (s[x], x))[:TOP_N] if len(s) >= TOP_N else []

import numpy as np, json
pos={d:i for i,d in enumerate(days)}
px=bars.sort('symbol','datetime')
O=px.pivot(on='symbol',index='datetime',values='open').sort('datetime'); C=px.pivot(on='symbol',index='datetime',values='close').sort('datetime')
cols=O.drop('datetime').columns; ci={s:i for i,s in enumerate(cols)}
O=O.drop('datetime').to_numpy(); C=C.drop('datetime').to_numpy(); n=len(days)
COST=float(sys.argv[5]) if len(sys.argv)>5 else 12e-4   # round-trip, bp-equivalent, split half/half
act=np.zeros(n); ret=np.zeros(n); cnt=np.zeros(n)
for i,d in enumerate(days):
    names=cohorts[d]
    if not names or i+41>=n: continue
    idx=[ci[x] for x in names]
    for k in range(1,42):
        t=i+k
        if k==1: r=C[t,idx]/O[t,idx]-1
        elif k==41: r=O[t,idx]/C[t-1,idx]-1
        else: r=C[t,idx]/C[t-1,idx]-1
        ret[t]+=r.mean(); cnt[t]+=1
        if k==1: ret[t]-=COST/2
        if k==41: ret[t]-=COST/2
inv=cnt>0
# normalise by 40 slots (exposure ramps)
port=ret/40.0
full=np.where(cnt>=40)[0]
def st(r):
    nav=np.cumprod(1+r); return dict(sharpe=float(r.mean()/r.std(ddof=1)*np.sqrt(252)),ann=float(nav[-1]**(252/len(r))-1),mdd=float((nav/np.maximum.accumulate(nav)-1).min()))
i0=full[0]
res={'phase':PHASE,'symbols':symbols,'full':st(port[i0:n-41]) ,'since2023':st(port[[i for i,d in enumerate(days) if d.year>=2023 and i<n-41][0]:n-41])}
json.dump(res,open('/tmp/q/ideal_%d.json'%PHASE,'w'))
print(PHASE,res['full'],res['since2023'])
