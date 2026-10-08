"""grp86: 公告类风险过滤（预先登记见档案 §126）。规则 S/B × 窗口 60/120，在 D / D1（主）与 D2 / D3 / D4（参考）上重跑。
python grp86.py prep            # 事件表 + 命中矩阵（存 grp86_flags.npz）+ 覆盖诊断
python grp86.py run [V ...]     # 逐变体跑基线与 4 个规则（有缓存，可分多次）
python grp86.py report          # 汇总表
"""
import os, sys, re, json, glob, time, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np, pandas as pd
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
LAKE = os.path.expanduser('~/mnt/lake/bronze/provider=cninfo/announcements_history')
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array([str(d) for d in panel.dates]); nd, nc = panel.shape
plain = np.array([str(c).split('.')[-1] for c in panel.codes]); col_of = {c: j for j, c in enumerate(plain)}
i20 = int(np.searchsorted(dates, '2020-01-01'))
RULES = {  # 类别：(必含, 必不含)  —— 与档案 §126 登记一致
    'R1': (['立案', '调查通知', '处罚事先告知', '处罚决定'], ['结案', '终止调查', '撤销']),
    'R2': (['风险警示', '退市风险', '终止上市', '暂停上市', '退市整理'], ['撤销', '摘帽']),
    'R3': (['保留意见', '否定意见', '无法表示意见'], ['消除', '撤销']),
    'R4': (['问询函', '关注函', '监管函', '警示函'], ['回函', '复函', '回复', '答复', '核查意见']),
    'R5': (['诉讼', '仲裁'], ['律师', '法律意见', '撤诉']),
}
def classify(title):
    out = []
    for k, (inc, exc) in RULES.items():
        if any(w in title for w in inc) and not any(w in title for w in exc): out.append(k)
    return out
def visible_idx(df):
    h = ((df.announcement_time_ms.values / 1000 + 8 * 3600) % 86400) / 3600
    d = df.date.astype(str).values
    right = np.searchsorted(dates, d, 'right'); left = np.searchsorted(dates, d, 'left')
    return np.where((h == 0) | (h >= 15), right, left)
if mode == 'prep':
    df = pd.concat([pd.read_parquet(f) for f in glob.glob(f'{LAKE}/scope=keyword/*/year=*.parquet')], ignore_index=True)
    df = df.drop_duplicates(['announcement_id', 'code']).reset_index(drop=True)
    cl = df.title.map(classify); df['cats'] = cl
    print('事件', len(df), '命中任一类别', int((cl.map(len) > 0).sum()), {k: int(cl.map(lambda x, k=k: k in x).sum()) for k in RULES})
    df['vis'] = visible_idx(df); df['col'] = df.code.map(col_of)
    ok = df.col.notna() & (df.vis < nd)
    print('能对上面板股票且可见日在面板内的事件', int(ok.sum()), '面板外股票事件', int(df.col.isna().sum()))
    ev = {k: np.zeros((nd, nc), np.int16) for k in RULES}
    for k in RULES:
        m = ok & cl.map(lambda x, k=k: k in x)
        np.add.at(ev[k], (df.vis[m].astype(int).values, df.col[m].astype(int).values), 1)
    np.savez_compressed(os.path.join(HERE, 'grp86_flags.npz'), **ev)
    # 覆盖诊断：退市股在 scope=delisted 全量公告里的 R1~R3 事件，关键词数据抓到多少
    dl = pd.concat([pd.read_parquet(f) for f in glob.glob(f'{LAKE}/scope=delisted/*.parquet') if os.path.getsize(f) > 0], ignore_index=True)
    dl = dl.drop_duplicates(['announcement_id', 'code']); dl['cats'] = dl.title.map(classify)
    dl_s = dl[dl.cats.map(lambda x: bool({'R1', 'R2', 'R3'} & set(x)))]
    kw_ids = set(zip(df.announcement_id, df.code))
    cov = np.mean([(a, c) in kw_ids for a, c in zip(dl_s.announcement_id, dl_s.code)])
    print(f'退市股全量公告 {len(dl)} 条，其中 R1~R3 类 {len(dl_s)} 条，{len(set(dl_s.code))} 只股票有；关键词数据抓到其中 {cov*100:.1f}%')
    last = dl.groupby('code').date.max()
    json.dump(dict(n_events=len(df), cover=float(cov), n_delisted_with_R123=len(set(dl_s.code))), open(os.path.join(HERE, 'grp86_prep.json'), 'w'))
    sys.exit()
ev = np.load(os.path.join(HERE, 'grp86_flags.npz'))
def flag_matrix(rule, N):
    cats = ['R1', 'R2', 'R3'] if rule == 'S' else ['R1', 'R2', 'R3', 'R4', 'R5']
    tot = sum(ev[k].astype(np.int32) for k in cats); cs = np.cumsum(tot, 0)
    f = np.zeros((nd, nc), bool); f[N:] = (cs[N:] - cs[:-N]) > 0; f[:N] = cs[:N] > 0     # (t-N, t]
    return f
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
delisted_plain = {os.path.basename(f)[:-8] for f in glob.glob(f'{LAKE}/scope=delisted/*.parquet')}
is_del = np.array([c in delisted_plain for c in plain])
CACHE = os.path.join(HERE, 'grp86_cache.json'); cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
years = np.array([int(d[:4]) for d in dates])
def sim(V, rule=None, N=None):
    key = f'{V}|{rule}|{N}'
    if key in cache: return cache[key]
    cfg = fusion.config_for(V)
    inp = fusion.with_industry_blacklist(fusion.with_near_high_filter(replace(raw_inp), cfg), cfg, cls)
    flag = None
    if rule:
        flag = flag_matrix(rule, N); inp = replace(inp, buyok=inp.buyok & ~flag)
    raw = fusion.simulate_fused(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    r = e[1:] / e[:-1] - 1
    n0 = int((idx < i20).sum()); n1 = int((idx >= i20).sum())
    pre = eq[i20 - 1] / e[0]; post = e[-1] / eq[i20 - 1]
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            base = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]; yr[y] = float(eq[ii[-1]] / base - 1)
    o = dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=float((e / np.maximum.accumulate(e) - 1).min()),
             final=float(e[-1] / e[0]), pre=float(pre ** (245 / n0) - 1), post=float(post ** (245 / n1) - 1), years=yr, n=len(raw['trades']))
    if rule is None:       # 基线成交里，各规则会剔除多少
        T = raw['trades']
        sig = np.array([np.searchsorted(dates, str(t['signal'])) for t in T]); col = np.array([col_of[str(t['code']).split('.')[-1]] for t in T])
        ret = np.array([t['ret'] for t in T]); o['trades_n'] = len(T); o['trades_mean'] = float(ret.mean()); o['trades_del_n'] = int(is_del[col].sum())
        o['trades_del_mean'] = float(ret[is_del[col]].mean()) if is_del[col].any() else None
        for rl in ('S', 'B'):
            for NN in (60, 120):
                fl = flag_matrix(rl, NN)[sig, col]; ex = {}
                ex['n'] = int(fl.sum()); ex['share'] = float(fl.mean()); ex['del_share'] = float(is_del[col][fl].mean()) if fl.any() else None
                ex['mean_out'] = float(ret[fl].mean()) if fl.any() else None; ex['mean_keep'] = float(ret[~fl].mean())
                ex['del_covered'] = float(fl[is_del[col]].mean()) if is_del[col].any() else None      # 买到的退市股里被命中的比例
                o[f'ex_{rl}{NN}'] = ex
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False); return o
CFG = [(None, None), ('S', 60), ('S', 120), ('B', 60), ('B', 120)]
if mode == 'run':
    t0 = time.time()
    for V in (sys.argv[2:] or ['D', 'D1']):
        for rule, N in CFG:
            if time.time() - t0 > 95: print('time budget hit; rerun'); sys.exit()
            sim(V, rule, N)
    print('done')
elif mode == 'report':
    for V in ('D', 'D1', 'D2', 'D3', 'D4'):
        b = cache.get(f'{V}|None|None')
        if not b: continue
        print(f"\n== {V} 基线 年化 {b['cagr']*100:.1f}% 夏普 {b['sharpe']:.2f} 回撤 {b['mdd']*100:.1f}% 终值 {b['final']:.1f}x  2020前 {b['pre']*100:.1f}% 后 {b['post']*100:.1f}%  成交 {b['n']}（退市股 {b['trades_del_n']} 笔，均值 {b['trades_del_mean']*100:+.1f}%，在市 {(b['trades_mean']*b['trades_n']-b['trades_del_mean']*b['trades_del_n'])/(b['trades_n']-b['trades_del_n'])*100:+.1f}%）")
        for rule, N in CFG[1:]:
            o = cache.get(f'{V}|{rule}|{N}')
            if not o: continue
            ex = b[f'ex_{rule}{N}']
            print(f"  {rule}{N:<3d} 年化 {o['cagr']*100:5.1f}% ({(o['cagr']-b['cagr'])*100:+.1f}) 夏普 {o['sharpe']:.2f} 回撤 {o['mdd']*100:6.1f}% 终值 {o['final']:5.1f}x  2020前 {o['pre']*100:5.1f}% ({(o['pre']-b['pre'])*100:+.1f}) 后 {o['post']*100:5.1f}% ({(o['post']-b['post'])*100:+.1f})  "
                  f"基线成交被剔 {ex['n']} 笔 {ex['share']*100:.1f}%，其中退市股占 {(ex['del_share'] or 0)*100:.0f}%，被剔均值 {(ex['mean_out'] or 0)*100:+.1f}% 保留 {ex['mean_keep']*100:+.1f}%；买到的退市股被命中 {(ex['del_covered'] or 0)*100:.0f}%")
