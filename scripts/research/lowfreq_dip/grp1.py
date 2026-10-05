"""Static groupings: SW L1/L2/L3, CSRC sector/division, board, random partitions (control). Research only."""
import json, time
from grp_lib import *
T0 = time.time()
panel = load_panel(); print('panel', panel.shape, panel.dates[0], panel.dates[-1], round(time.time() - T0), 's', flush=True)
nc = panel.shape[1]; codes = panel.codes; sym = np.array([str(c).split('.')[-1] for c in codes])
D = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D = D.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')
def lab_from(series_by_sym):
    raw = np.array([series_by_sym.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
    return np.array([ix.get(x, -1) for x in raw], np.int16), len(u)
out = []
sets = []
l1, n1 = lab_from(D['l1_code'].to_dict()); sets.append(('申万一级', l1))
l2, n2 = lab_from(D['l2_code'].to_dict()); sets.append(('申万二级', l2))
l3, n3 = lab_from(D['industry_code'].astype(str).to_dict()); sets.append(('申万三级', l3))
B = pd.read_parquet(f'{LAKE}/bronze/provider=baostock/industry/industry.parquet')
B = B[B['industry'].astype(str).str.len() > 0].drop_duplicates('code', keep='last').set_index('code')['industry'].astype(str)
bm = dict(zip([c.split('.')[-1] for c in B.index], B.values))
cs1, _ = lab_from({k: v[0] for k, v in bm.items()}); sets.append(('证监会门类', cs1))
cs2, _ = lab_from({k: v[:3] for k, v in bm.items()}); sets.append(('证监会大类', cs2))
board = np.array([0 if str(c).startswith('sh.688') else 1 if str(c).startswith('sz.30') else 2 if str(c).startswith('sh.6') else 3 if str(c).startswith('sz.0') else -1 for c in codes], np.int16)
sets.append(('板块(科创/创业/沪主/深主)', board))
rng = np.random.default_rng(11)
for k, ng in ((31, 'a'), (31, 'b'), (5, 'c')):
    sets.append((f'随机分{k}组({ng})', rng.integers(0, k, nc).astype(np.int16)))
for name, lab in sets:
    print(f'--- {name}: 组数{int(lab.max()) + 1}, 已分类{int((lab >= 0).sum())}/{nc}', flush=True)
    out.append(run(panel, name + ' 任一组触发', lab, 'any'))
    out.append(run(panel, name + ' 仅大盘未恐慌日', lab, 'idio'))
json.dump(out, open('grp1.json', 'w'), ensure_ascii=False, indent=1)
print('done', round(time.time() - T0), 's')
