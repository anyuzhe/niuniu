"""配对做T (yearly top-500, 5-minute bars). Monthly, pair each stock with its most correlated peer by 5-minute returns
over the previous 20 trading days (mutual best, corr >= c0). Intraday, at 10:00/10:30/11:30/13:30/14:00, when one leg is
ahead of the other by >= k (return since previous close), sell the leader's base and buy the laggard at the next bar
open; at the close (or when the gap has halved) buy the leader back and sell the laggard's base. Two round trips of
7.2 bp + 1 tick per side. Result in bp of one leg's notional, summed over both legs. Research only."""
import sys, os, numpy as np, pickle
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,H,L,C,pc,up,V,code,date=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code'],D['date']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
days=np.unique(date); codes=np.unique(code); ci={c:i for i,c in enumerate(codes)}; di={d:i for i,d in enumerate(days)}
row=np.full((len(days),len(codes)),-1); row[[di[d] for d in date],[ci[c] for c in code]]=np.arange(len(code))
r5=np.c_[np.zeros(len(C)),np.diff(np.log(C),axis=1)]
CK=(5,11,23,29,35)
out={}
months=sorted(set(d[:7] for d in days))
pairs_by_month={}
for m in months:
    first=[i for i,d in enumerate(days) if d[:7]==m][0]
    if first<20: continue
    win=range(first-20,first)
    M=np.zeros((len(codes),20*48)); ok=np.zeros(len(codes),int)
    for k,i in enumerate(win):
        rr=row[i]; has=rr>=0; M[has,k*48:(k+1)*48]=np.nan_to_num(r5[rr[has]]); ok+=has
    good=ok>=18; X=M[good]; X=X-X.mean(1,keepdims=True); X/=np.maximum(np.linalg.norm(X,axis=1,keepdims=True),1e-12)
    Cm=X@X.T; np.fill_diagonal(Cm,-1); idx=np.flatnonzero(good); best=Cm.argmax(1)
    pairs_by_month[m]=[(idx[a],idx[b],Cm[a,b]) for a,b in enumerate(best) if best[b]==a and a<b]
for c0 in (0.5,0.65):
  for k in (0.01,0.02,0.03):
    for ex in ('close','half'):
      res=[]
      for m,pl in pairs_by_month.items():
        for i,d in enumerate(days):
          if d[:7]!=m: continue
          for a,b,cor in pl:
            if cor<c0: continue
            ra,rb=row[i,a],row[i,b]
            if ra<0 or rb<0 or np.isnan(pc[ra]) or np.isnan(pc[rb]): continue
            sa=C[ra]/pc[ra]-1; sb=C[rb]/pc[rb]-1
            for j in CK:
              gap=sa[j]-sb[j]
              if abs(gap)>=k:
                lead,lag=(ra,rb) if gap>0 else (rb,ra); e=j+1
                sell=O[lead,e]-T; buy=O[lag,e]+T
                if sell<=dn[lead]+0.005 or buy>=up[lag]-0.005 or V[lead,e]<=0 or V[lag,e]<=0: break
                x=47
                if ex=='half':
                  g=np.abs((C[lead]/pc[lead])-(C[lag]/pc[lag]))
                  hit=np.flatnonzero(g[e:47]<=abs(gap)/2)
                  if len(hit): x=e+hit[0]
                if x<47: bb=O[lead,x+1]+T if x+1<48 else C[lead,-1]+T; ss=O[lag,x+1]-T if x+1<48 else C[lag,-1]-T
                else: bb=C[lead,-1]+T; ss=C[lag,-1]-T
                if C[lead,-1]>=up[lead]-0.001 and x>=46: bb=nO[lead]+T
                if C[lag,-1]<=dn[lag]+0.001 and x>=46: ss=nO[lag]-T
                v=(sell/bb-1)*1e4+(ss/buy-1)*1e4-2*FEE
                if np.isfinite(v) and abs(v)<3000: res.append((d,v,cor))
                break
      out[(c0,k,ex)]=res
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/pairs_{yr}.pkl','wb'))
print(yr,{k:len(v) for k,v in out.items() if k[2]=='close'},round(np.mean([len(p) for p in pairs_by_month.values()]),1),'pairs/month')
