"""Panic-regime dip buying with a factor score: selection on 2020-22 only, holdout 2023-24 / 2025-26, path-based portfolio backtest."""
import os, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']
exec(open('lowfreq.py').read().split("mon=np.array")[0])
T=np.arange(nd); jj=np.arange(nc)[None,:]
def run2(H):
    e_idx=np.minimum(T+H,nd-1); okx=(T+H)<nd
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    ei=np.tile(e_idx[:,None],(1,nc))
    for _ in range(3):
        bad=~(fin[np.minimum(ei,nd-1),jj])|limdn_close[np.minimum(ei,nd-1),jj]; ei=np.where(bad&(ei<nd-1),ei+1,ei)
    e2=np.minimum(ei,nd-1); exC=C[e2,jj]; exR=R[e2,jj]
    enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]; enR=np.full((nd,nc),np.nan); enR[:-1]=Ro[1:]
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)
    return valid,(exC*(1-0.01/exR))/(enO*(1+0.01/enR))-1-FEE
valid,net=run2(20); univ_mean=np.nanmean(np.where(valid,net,np.nan),1)
mret=np.nanmean(np.where(uni,ret1,np.nan),1); mret[~np.isfinite(mret)]=0
idx=np.cumprod(1+mret); mk20=idx/np.r_[np.full(20,np.nan),idx[:-20]]-1
train=(dates>='2020-01-01')&(dates<='2022-12-31'); cut=np.nanpercentile(mk20[train&np.isfinite(mk20)],20); reg=mk20<=cut
print(f'恐慌日：全市场20日涨跌 ≤ {cut*100:.1f}%；共 {reg.sum()} 天')
Z=np.load('dipfeat.npz'); di=Z['date_idx']; dj=Z['code_idx']; y=Z['y']; xi=Z['exit_idx']
names=[k for k in Z.files if k not in ('dates','codes','date_idx','code_idx','y','exit_idx')]
cy=np.array([dates[i][:4] for i in di]); cmo=np.array([dates[i][:7] for i in di]); inreg=reg[di]
ymk=y-univ_mean[di]
def pct_rank(f,di):
    f=np.where(np.isfinite(f),f,np.nanmedian(f)); o=np.lexsort((f,di)); ds=di[o]
    st=np.r_[0,np.nonzero(np.diff(ds))[0]+1]; cnt=np.diff(np.r_[st,len(ds)])
    r=np.arange(len(ds))-np.repeat(st,cnt); out=np.empty(len(f)); out[o]=(r+0.5)/np.repeat(cnt,cnt); return out
def spread(px,m):
    q=np.minimum((px*5).astype(int),4); hi=m&(q==4); lo=m&(q==0); um=np.unique(cmo[m]); dd=[]
    for u in um:
        mh=hi&(cmo==u); ml=lo&(cmo==u)
        if mh.sum()>=10 and ml.sum()>=10: dd.append(ymk[mh].mean()-ymk[ml].mean())
    dd=np.array(dd); return (dd.mean()*1e4, dd.mean()/(dd.std(ddof=1)/np.sqrt(len(dd))+1e-12)) if len(dd)>2 else (np.nan,np.nan)
PX={n:pct_rank(Z[n],di) for n in names}
YEARS=['2020','2021','2022','2023','2024','2025','2026']
def spread_years(px,years):
    m=inreg&np.isin(cy,years); a,t=spread(px,m); ys=[spread(px,inreg&(cy==Y))[0] for Y in years]; return a,t,ys
score_wf=np.full(len(y),np.nan); chosen={}
for Y in YEARS[2:]:
    prior=[v for v in YEARS if v<Y]; sel=[]
    for n in names:
        a,t,ys=spread_years(PX[n],prior); ys=[v for v in ys if np.isfinite(v)]
        if np.isfinite(t) and abs(t)>=1.2 and len(ys)>=2 and np.mean(np.sign(ys)==np.sign(a))>=0.75: sel.append((n,np.sign(a)))
    chosen[Y]=sel; m=(cy==Y)
    if sel: score_wf[m]=np.mean([PX[n][m] if sg>0 else 1-PX[n][m] for n,sg in sel],axis=0)
print('\n滚动选因子（每年只用此前各年的恐慌日数据：分位差|t|≥1.2 且至少75%的年份同号）')
for Y,sel in chosen.items(): print(f'  {Y}: '+(', '.join(f'{n}({"+" if sg>0 else "-"})' for n,sg in sel) if sel else '（无因子入选）'))
have=np.isfinite(score_wf); psw=np.where(have,pct_rank(np.where(have,score_wf,0.5),di),np.nan)
print('\n滚动分数在恐慌日内的样本外分位差（最高20%-最低20%，超额bp）：')
for Y in YEARS[2:]:
    m=inreg&(cy==Y)&have
    if m.sum()<300: print(f'  {Y}: 无分数/样本不足'); continue
    q=np.minimum((psw*5).astype(int),4); hi=m&(q==4); lo=m&(q==0)
    print(f'  {Y}: {(ymk[hi].mean()-ymk[lo].mean())*1e4:+.0f}bp（最高组 {ymk[hi].mean()*1e4:+.0f} / 最低组 {ymk[lo].mean()*1e4:+.0f}）')
# hypothesis score: "how oversold" (deeper = higher score), decided from logic, not fitted
hyp=np.mean([1-PX['距60日最高'],1-PX['距60日均线'],1-PX['20日跌幅']],axis=0); psh=pct_rank(hyp,di)
print('\n假设型分数“超卖深度”（距60日最高、距60日均线、20日跌幅，越深分越高；逻辑先验，未做拟合，但我看过上面的分年表）：')
for pn,ys in {'2020-22':('2020','2021','2022'),'2023-24':('2023','2024'),'2025-26':('2025','2026')}.items():
    a,t=spread(psh,inreg&np.isin(cy,ys)); print(f'  {pn}: {a:+.0f}bp (t{t:+.1f})')
ps=psw
# ---------- path backtest ----------
def paths(sel_i):
    """daily P&L (units of total capital) for a set of selected candidate indices; equal slot weight."""
    e=di[sel_i]+1; x=xi[sel_i]; j=dj[sel_i]; n=len(sel_i)
    V=np.ones(n); pnl=np.zeros(nd); prev=np.ones(n); act=np.ones(n,bool); expo=np.zeros(nd)
    for k in range(0,40):
        d=e+k; live=act&(d<=x)&(d<nd)
        if not live.any(): break
        dd=np.minimum(d,nd-1)
        if k==0: newV=C[dd,j]/(O[e,j]*(1+0.01/Ro[e,j]))
        else:    newV=prev*(C[dd,j]/C[np.maximum(dd-1,0),j])
        atx=live&(d==x)
        newV=np.where(atx,newV*(1-0.01/R[dd,j])-FEE*prev*0-FEE,newV) if k>0 else newV
        newV=np.where(np.isfinite(newV),newV,prev)
        np.add.at(pnl,dd[live],(newV-prev)[live]); np.add.at(expo,dd[live],1.0)
        prev=np.where(live,newV,prev); act=live&~atx
    return pnl,expo
def pick(scoreV,K,Mday):
    """per regime day take top-K by score among candidates not currently held"""
    order=np.lexsort((-scoreV,di)); ds=di[order]; st=np.r_[0,np.nonzero(np.diff(ds))[0]+1]; en=np.r_[st[1:],len(ds)]
    free={}; out=[]
    for a,b in zip(st,en):
        d=ds[a]
        if not reg[d]: continue
        got=0
        for i in order[a:b]:
            if free.get(dj[i],-1)>d+1: continue
            out.append(i); free[dj[i]]=xi[i]; got+=1
            if got>=K: break
    return np.array(out)
def report(tag,sel_i,K):
    pnl,expo=paths(sel_i); M=K*20; pnl=pnl/M; out=[]
    for pn,(a,b) in {'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}.items():
        m=(dates>=a)&(dates<=b); p=pnl[m]; eq=np.cumsum(p); dd=(np.maximum.accumulate(eq)-eq).max()
        s=np.isin(cy[sel_i],pn.replace('2020-22','2020 2021 2022').replace('2023-24','2023 2024').replace('2025-26','2025 2026').split())
        tr=y[sel_i][s]; ex=ymk[sel_i][s]; yrs=(m.sum()/245)
        out.append(f'{pn}: {s.sum():4d}笔 每笔净{tr.mean()*1e4:+5.0f}bp 超额{ex.mean()*1e4:+5.0f} 胜率{(tr>0).mean()*100:.0f}% | 资金收益{eq[-1]*100:+5.1f}%（年化{eq[-1]/yrs*100:+.1f}%）最大回撤{dd*100:.1f}% 平均仓位{expo[m].mean()/M*100:.0f}%')
    print(f'{tag}\n    '+'\n    '.join(out))

def pick2(scoreV,K,ymask):
    order=np.lexsort((-np.where(np.isfinite(scoreV),scoreV,-1),di)); ds=di[order]; st=np.r_[0,np.nonzero(np.diff(ds))[0]+1]; en=np.r_[st[1:],len(ds)]
    free={}; out=[]
    for a_,b_ in zip(st,en):
        d=ds[a_]
        if not reg[d] or not ymask[order[a_]]: continue
        got=0
        for i in order[a_:b_]:
            if not np.isfinite(scoreV[i]): continue
            if free.get(dj[i],-1)>d+1: continue
            out.append(i); free[dj[i]]=xi[i]; got+=1
            if got>=K: break
    return np.array(out)
def report2(tag,sel_i,K,periods):
    pnl,expo=paths(sel_i); M=K*20; pnl=pnl/M; out=[]
    for pn,(a_,b_) in periods.items():
        m=(dates>=a_)&(dates<=b_); p=pnl[m]; eq=np.cumsum(p); dd=(np.maximum.accumulate(eq)-eq).max(); yrs=m.sum()/245
        s_=(dates[di[sel_i]]>=a_)&(dates[di[sel_i]]<=b_); tr=y[sel_i][s_]; ex=ymk[sel_i][s_]
        out.append(f'{pn}: {s_.sum():4d}笔 每笔净{tr.mean()*1e4:+5.0f}bp 超额{ex.mean()*1e4:+5.0f} 胜率{(tr>0).mean()*100:.0f}% | 资金收益{eq[-1]*100:+5.1f}%（年化{eq[-1]/yrs*100:+.1f}%）最大回撤{dd*100:.1f}% 平均仓位{expo[m].mean()/M*100:.0f}%')
    print(f'{tag}\n    '+'\n    '.join(out))
PER2={'2022-24':('2022-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
PER3={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
rng_=np.random.default_rng(1); allm=np.ones(len(y),bool); m22=np.isin(cy,YEARS[2:])
print('\n=== 组合回测（恐慌日，每天买分数最高的K只，同一只股票持仓期间不重复，持有20个交易日，每个仓位1/(20K)资金，扣成本）===')
for K in (3,5,10):
    print(f'\n--- K={K} ---')
    report2(f'A 滚动选因子打分（2022年起样本外）前{K}',pick2(psw,K,m22),K,PER2)
    rs=[]
    for sd in range(8): rs.append(pick2(rng_.random(len(y)),K,m22))
    report2(f'随机选{K}只（示例1次，2022年起）',rs[0],K,PER2); ex=[ymk[r].mean()*1e4 for r in rs]; print(f'    随机选{K}只 8次平均每笔超额 {np.mean(ex):+.0f}bp（{min(ex):+.0f}~{max(ex):+.0f}）')
    report2(f'B 假设型“超卖深度”打分 前{K}（全期，含我看过的年份）',pick2(psh,K,allm),K,PER3)
