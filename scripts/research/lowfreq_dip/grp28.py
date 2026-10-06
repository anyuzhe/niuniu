"""D with a finer B-sleeve classification (SW L1 / L2 / L3 and a coarse variant): everything else identical to D. Research only."""
import grp11 as g
from grp11 import *
D_ = pd.read_parquet(f'{LAKE}/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet')
D_ = D_.sort_values(['code', 'start_date']).groupby('code').tail(1).set_index('code')
def lab_from(m):
    raw = np.array([m.get(s, '') for s in sym]); u = sorted(set(raw) - {''}); ix = {k: i for i, k in enumerate(u)}
    return np.array([ix.get(x, -1) for x in raw], np.int16), len(u)
W = {'A': .08, 'C': .08, 'B': .025}
def runD(label, lab, nlab):
    R2, _ = ind_series(lab); Z2 = zscore(R2); trig = np.isfinite(Z2) & (Z2 <= -1.5)
    fm, fc = build(trig, lab)
    g.SL['B'] = ((fm.z <= -1.5), fc.e6, fc.ret20)
    ndays = int((fm.z <= -1.5).sum()); nact = int(np.isfinite(Z2).any(0).sum())
    print(f'--- {label}（{nlab} 组，有效 {nact}；B 触发 {ndays} 天）', flush=True)
    return show(f'D：B 用{label}', order='ACB', w=W, G=1.0, caps={}, cash_yield=0.02)
if __name__ == '__main__':
    l1_, n1 = lab_from(D_['l1_code'].to_dict()); l2_, n2 = lab_from(D_['l2_code'].to_dict()); l3_, n3 = lab_from(D_['industry_code'].astype(str).to_dict())
    runD('申万一级', l1_, n1); runD('申万二级', l2_, n2); runD('申万三级', l3_, n3)
    show('D：只有 A+C（无 B）', order='AC', w={'A': .08, 'C': .08, 'B': 1e-9}, G=1.0, caps={}, cash_yield=0.02)
