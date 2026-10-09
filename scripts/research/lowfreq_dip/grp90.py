"""grp90: 分行业设 B 层触发阈值（预先登记见档案 §134）。python grp90.py run | report"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np, pandas as pd
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
HERE = os.path.dirname(os.path.abspath(__file__))
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array([str(d) for d in panel.dates]); nd, nc = panel.shape; i18 = int(np.searchsorted(dates, '2018-01-01'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
ng = len(cls.codes); names = list(cls.names); mapped = np.nonzero(cls.labels >= 0)[0]
st = raw_inp.ind_state; Z = np.asarray(st.z, float); R20 = np.asarray(st.ret20, float)
BASE_T = -1.5

def with_B(T):
    """按 T[t,g] 重算 B 闸门与候选池（和 industry.build_inputs 同一套逻辑），再接近高点过滤（D2 才开）。"""
    trig = np.isfinite(Z) & (Z <= T)
    in_trig = np.zeros((nd, nc), bool); in_trig[:, mapped] = trig[:, cls.labels[mapped]]
    pool = raw_inp.cand.uni & in_trig & np.isfinite(raw_inp.cand.ret20)
    gB = trig.any(axis=1)
    gates = {**raw_inp.gates, 'B': gB}
    return replace(raw_inp, gates=gates, pools={**raw_inp.pools, 'B': pool}, any_gate=gates['A'] | gates['C'] | gB), trig

def const(v=BASE_T): return np.full((nd, ng), float(v))
def idx(*nm): return [names.index(n) for n in nm]
def with_cols(cols, v):
    T = const(); T[:, cols] = v; return T

# ---- S1：行业自身波动三档（扩展标准差，至少 250 个观测，只用到 t 为止的数据）
V = pd.DataFrame(R20).expanding(250).std().values
TIER = np.full((nd, ng), -1, int)          # 0 低 1 中 2 高
for t in range(nd):
    ok = np.nonzero(np.isfinite(V[t]))[0]
    if len(ok) >= 6:
        order = ok[np.argsort(V[t, ok], kind='stable')]; n = len(order)
        TIER[t, order[: n // 3]] = 0; TIER[t, order[n // 3: n - n // 3]] = 1; TIER[t, order[n - n // 3:]] = 2
def s1(tier, v):
    T = const(); T[TIER == tier] = v; return T
# ---- S2：行业自己的历史分位（t−1 之前，至少 250 个观测），夹在 [−2.5, −1.0]
def s2(p):
    q = pd.DataFrame(Z).expanding(250).quantile(p).shift(1).values
    return np.clip(np.where(np.isfinite(q), q, BASE_T), -2.5, -1.0)
# ---- S3：软黑名单
WORST5 = idx('国防军工', '环保', '煤炭', '基础化工', '房地产'); TWO = idx('房地产', '国防军工')
DESIGNS = {'BASE': lambda: const(),
           'L-': lambda: s1(0, -2.0), 'M-': lambda: s1(1, -2.0), 'H-': lambda: s1(2, -2.0),
           'L+': lambda: s1(0, -1.0), 'M+': lambda: s1(1, -1.0), 'H+': lambda: s1(2, -1.0),
           'Q3': lambda: s2(0.03), 'Q5': lambda: s2(0.05), 'Q8': lambda: s2(0.08),
           'Y2': lambda: with_cols(TWO, -2.0), 'Y25': lambda: with_cols(TWO, -2.5), 'F2': lambda: with_cols(WORST5, -2.0)}
MIRROR = {'L-': 'L+', 'M-': 'M+', 'H-': 'H+', 'L+': 'L-', 'M+': 'M-', 'H+': 'H-'}

def mdd_seg(e): return float((e / np.maximum.accumulate(e) - 1).min()) if len(e) > 2 else float('nan')
CACHE = os.path.join(HERE, 'grp90_cache.json'); cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def run_sim(key, Vn, T, hard_bl=False):
    if key in cache: return cache[key]
    cfg = fusion.config_for(Vn)
    inp, trig = with_B(T)
    inp = fusion.with_near_high_filter(inp, cfg)
    if hard_bl: inp = fusion.with_industry_blacklist(inp, replace(cfg, industry_blacklist=('国防军工', '房地产')), cls)
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); ii = np.nonzero(ok)[0]; e = eq[ii]; r = e[1:] / e[:-1] - 1
    n0 = int((ii < i18).sum()); n1 = int((ii >= i18).sum()); pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    tr = raw['trades']; nb = sum(1 for x in tr if x.get('sleeve') == 'B')
    o = dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=mdd_seg(e), final=float(e[-1] / e[0]),
             pre=float(pre ** (245 / n0) - 1), post=float(post ** (245 / n1) - 1), n=len(tr), n_b=nb, gate_b=float(inp.gates['B'][ii[0]:].mean()), trig_cells=float(trig[ii[0]:].mean()))
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False); return o

def check_baseline():
    inp, _ = with_B(const())
    assert np.array_equal(inp.gates['B'], raw_inp.gates['B']), 'B 闸门与产品不一致'
    assert np.array_equal(inp.pools['B'], raw_inp.pools['B']), 'B 候选池与产品不一致'
    assert np.array_equal(inp.any_gate, raw_inp.any_gate), 'any_gate 不一致'
    print('基线重算与产品输入逐位一致')

PLACEBO_N = 60
def placebo(kind, k, base_cagr):
    rng = np.random.default_rng({'s1': 134, 'two': 135, 'five': 136}[kind]); out = []
    for i in range(PLACEBO_N):
        cols = sorted(rng.choice(ng, size=k, replace=False).tolist())
        out.append(run_sim(f'D|PL_{kind}|{i}', 'D', with_cols(cols, -2.0))['cagr'] - base_cagr)
    return np.array(out)

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if mode == 'run':
        check_baseline()
        for Vn in ('D', 'D2'):
            for k, f in DESIGNS.items(): run_sim(f'{Vn}|{k}', Vn, f())
            run_sim(f'{Vn}|HB', Vn, const(), hard_bl=True)
        b = cache['D|BASE']['cagr']
        for kind, k in (('s1', 10), ('two', 2), ('five', 5)): placebo(kind, k, b)
        print('done', len(cache))
    # ---- 报告
    out = []
    P = lambda x: f'{x * 100:+.1f}%'
    pl = {kind: np.array([cache[f'D|PL_{kind}|{i}']['cagr'] for i in range(PLACEBO_N)]) - cache['D|BASE']['cagr'] for kind in ('s1', 'two', 'five') if f'D|PL_{kind}|{PLACEBO_N - 1}' in cache}
    for kind, a in pl.items(): out.append(f'安慰剂 {kind}：年化变化 均值 {a.mean() * 100:+.2f} 点，标准差 {a.std() * 100:.2f}，95 分位 {np.percentile(a, 95) * 100:+.2f}，最大 {a.max() * 100:+.2f}（{len(a)} 次）')
    PLK = {'L-': 's1', 'M-': 's1', 'H-': 's1', 'Y2': 'two', 'Y25': 'two', 'F2': 'five'}
    verdict = {}
    for Vn in ('D', 'D2'):
        b = cache[f'{Vn}|BASE']
        out.append(f"\n== {Vn} 基线 年化 {P(b['cagr'])} 夏普 {b['sharpe']:.2f} 回撤 {b['mdd'] * 100:.1f}% 终值 {b['final']:.1f}x 前 {P(b['pre'])} 后 {P(b['post'])} B 闸门天数占比 {b['gate_b'] * 100:.1f}% 触发格占比 {b['trig_cells'] * 100:.2f}% 成交 {b['n']}（B {b['n_b']}）")
        for k in list(DESIGNS)[1:] + ['HB']:
            o = cache[f'{Vn}|{k}']
            out.append(f"{k:>4}: 年化 {P(o['cagr'])} ({(o['cagr'] - b['cagr']) * 100:+.2f}) 夏普 {o['sharpe']:.2f} 回撤 {o['mdd'] * 100:.1f}% 前 {P(o['pre'])} ({(o['pre'] - b['pre']) * 100:+.2f}) 后 {P(o['post'])} ({(o['post'] - b['post']) * 100:+.2f}) 成交 {o['n']}（B {o['n_b']}）B 闸门 {o['gate_b'] * 100:.1f}% 触发格 {o['trig_cells'] * 100:.2f}%")
    out.append('\n== 采用标准逐条（D / D2）')
    for k in list(DESIGNS)[1:]:
        res = {}
        for Vn in ('D', 'D2'):
            b, o = cache[f'{Vn}|BASE'], cache[f'{Vn}|{k}']
            res[Vn] = (o['cagr'] - b['cagr'] >= 0.01, o['sharpe'] >= b['sharpe'], o['pre'] - b['pre'] >= -0.003 and o['post'] - b['post'] >= -0.003, o['mdd'] - b['mdd'] >= -0.02)
        c5 = None
        if k in PLK and PLK[k] in pl: c5 = (cache[f'D|{k}']['cagr'] - cache['D|BASE']['cagr']) > np.percentile(pl[PLK[k]], 95)
        c6 = None
        if k in MIRROR:
            m = {Vn: cache[f'{Vn}|{MIRROR[k]}']['cagr'] - cache[f'{Vn}|BASE']['cagr'] for Vn in ('D', 'D2')}; c6 = not all(v >= 0.01 for v in m.values())
        ok = all(all(v) for v in res.values()) and (c5 is not False) and (c6 is not False)
        verdict[k] = ok
        out.append(f"{k:>4}: D ①{'√' if res['D'][0] else '×'}②{'√' if res['D'][1] else '×'}③{'√' if res['D'][2] else '×'}④{'√' if res['D'][3] else '×'}  D2 ①{'√' if res['D2'][0] else '×'}②{'√' if res['D2'][1] else '×'}③{'√' if res['D2'][2] else '×'}④{'√' if res['D2'][3] else '×'}  ⑤{'-' if c5 is None else ('√' if c5 else '×')} ⑥{'-' if c6 is None else ('√' if c6 else '×')}  => {'候选' if ok else '不通过'}")
    out.append('\n候选：' + ('、'.join(k for k, v in verdict.items() if v) or '无'))
    text = '\n'.join(out); print(text); open(os.path.join(HERE, 'grp90.txt'), 'w', encoding='utf-8').write(text + '\n')
