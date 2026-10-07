"""Annual financial table (code, year, revenue, net profit, equity, notice date) from eastmoney (listed) + baostock (delisted, fin_del.json). Research only."""
import glob, os, json, numpy as np, pandas as pd, pyarrow.parquet as pq
E = os.path.expanduser('~/mnt/lake/bronze/provider=eastmoney/'); rows = []
def code(sec): return sec.str.slice(7, 9).str.lower() + '.' + sec.str.slice(0, 6)
for f in sorted(glob.glob(E + 'financial_cpd/report_date=*-12-31.parquet')):
    y = int(os.path.basename(f)[12:16]); t = pq.read_table(f, columns=[c for c in ('SECUCODE', 'TOTAL_OPERATE_INCOME', 'PARENT_NETPROFIT', 'NOTICE_DATE') if c in pq.read_schema(f).names]).to_pandas()
    t['code'] = code(t['SECUCODE']); t['year'] = y; t['notice'] = t['NOTICE_DATE'].astype(str).str.slice(0, 10)
    b = None; fb = E + f'financial_balance/report_date={y}-12-31.parquet'
    if os.path.exists(fb):
        b = pq.read_table(fb, columns=['SECUCODE', 'TOTAL_EQUITY']).to_pandas(); b['code'] = code(b['SECUCODE']); b = b.drop_duplicates('code').set_index('code')['TOTAL_EQUITY']
    t['equity'] = t['code'].map(b) if b is not None else np.nan
    rows.append(t.rename(columns={'TOTAL_OPERATE_INCOME': 'rev', 'PARENT_NETPROFIT': 'np'})[['code', 'year', 'rev', 'np', 'equity', 'notice']])
X = pd.concat(rows, ignore_index=True); X['src'] = 'em'; print('eastmoney rows', len(X), 'codes', X.code.nunique())
if os.path.exists('fin_del.json'):
    D = json.load(open('fin_del.json')); r2 = []
    for c, ys in D.items():
        for y, d in ys.items():
            fl = lambda k: float(d[k]) if d.get(k) not in (None, '') else np.nan
            la = fl('liabilityToAsset')
            r2.append(dict(code=c, year=int(y), rev=fl('MBRevenue'), np=fl('netProfit'), equity=(-1.0 if la > 1 else 1.0) if np.isfinite(la) else np.nan, notice=d.get('pubDate', '')[:10], src='bs'))
    Y = pd.DataFrame(r2); print('baostock rows', len(Y), 'codes', Y.code.nunique()); X = pd.concat([X, Y], ignore_index=True)
X = X[X.notice.str.len() == 10].drop_duplicates(['code', 'year', 'src']); X.to_csv('fin_tab.csv', index=False); print(X.groupby('src').size().to_dict())
