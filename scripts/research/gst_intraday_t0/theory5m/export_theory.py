"""Export 5-minute bars for a sample of the yearly universe (every 8th stock by prior-year turnover rank, ~63 per year),
including ~30 trading days of the previous year as warm-up, for running the repo's theory factors elsewhere. Research only."""
import numpy as np, json, os, duckdb
H=os.environ['HOME']; U=json.load(open(f'{H}/research/mkt/universe.json'))
rows=[]
import pandas as pd
out=[]
for yr in range(2020,2027):
    z=np.load(f'{H}/research/brk/g{yr}.npz'); codes=set(U[str(yr)][::8])
    code=z['code'];date=z['date'];slots=[str(s) for s in z['slots']]; m=np.isin(code,list(codes))
    O,Hh,L,C,V,A=(z[k][m] for k in 'O H L C V A'.split()); cd=code[m]; dt=date[m]
    r,c=np.nonzero(np.isfinite(C)&(V>0))
    df=pd.DataFrame({'year':yr,'symbol':cd[r],'date':dt[r],'hm':np.array(slots)[c],'open':O[r,c],'high':Hh[r,c],'low':L[r,c],'close':C[r,c],'volume':V[r,c],'turnover':A[r,c]})
    out.append(df); print(yr,len(codes),len(df))
df=pd.concat(out); df.
con=duckdb.connect(); con.register('df',df); con.execute(f"copy df to '{H}/research/theory5m.parquet' (format parquet, compression zstd)")
print(os.path.getsize(f'{H}/research/theory5m.parquet')/1e6,'MB')
