"""Research only: capped MTM portfolio (N slots, equity/N each), intraday vs next-open entry, 2020-2026."""
import numpy as np, os, warnings; warnings.filterwarnings('ignore')
H0=os.environ['HOME']; L=f'{H0}/research/lowfreq/'
EVz=np.load(f'{H0}/research/intra/intra_events.npz'); dates=EVz['dates'].astype(str); nd=len(dates)
P=np.load(L+'panel.npz'); c=P['c'].astype(np.float64); del P
H=20; rng=np.random.default_rng(11)
stamp=np.where(dates<'2023-08-28',0.001,0.0005); comm=np.where(dates<'2020-01-01',0.0004,0.00022); feeD=stamp+comm
M=np.load(L+'mkreg_ext_liq.npz'); Md={d:i for i,d in enumerate(M['dates'].astype(str))}
mr=np.array([M['mret'][Md[d]] if d in Md else np.nan for d in dates])
def events(name,rank=None):
    t=EVz[name+'_t']; j=EVz[name+'_j']; net=EVz[name+'_net']; raw=EVz[name+'_raw']; o0=EVz[name+'_o0']; off=int(EVz[name+'_off'][0])
    ev={}
    for i in range(len(t)):
        ev.setdefault(int(t[i]),[]).append((int(j[i]),float(net[i]),float(o0[i]),float(raw[i]),off,(int(EVz['first_k'][i]) if name=='first' else 0)))
    return ev
def portfolio(ev,N,start='2020-01-02'):
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); trades=[]
    for t in range(t0,nd-H-1):
        for p in [p for p in act if p['x']==t]:
            cash+=p['inv']*(1+p['net']); trades.append(p['net']); act.remove(p)
        slots=N-len(act)
        if slots>0 and t in ev:
            held={p['j'] for p in act}; cs=[e for e in ev[t] if e[0] not in held]
            idx=rng.permutation(len(cs)); cs=sorted([cs[i] for i in idx],key=lambda e:e[5])   # earlier trigger first, random within
            E=cash+sum(p['v'] for p in act)
            for (j,net,o0,raw,off,k) in cs[:slots]:
                size=min(E/N,cash)
                if size<=1e-9: break
                cash-=size; act.append(dict(j=j,e=t+off,x=t+H,inv=size,v=size,net=net,o0=o0,costE=0.01/raw+feeD[t]/2))
        tot=cash
        for p in act:
            if p['e']<=t:
                cj=c[t,p['j']]; p['v']=p['inv']*(cj/p['o0'] if np.isfinite(cj) else 1.0)*(1-p['costE'])
            tot+=p['v']
        eq[t]=tot; expo[t]=(tot-cash)/tot
    return eq,expo,np.array(trades)
ERA={'2020-21':('2020-01-01','2021-12-31'),'2022-23':('2022-01-01','2023-12-31'),'2024-26':('2024-01-01','2026-12-31'),'2020-26':('2020-01-01','2026-12-31')}
def stats(eq,expo,a,b):
    m=(dates>=a)&(dates<=b)&np.isfinite(eq); idx=np.nonzero(m)[0]
    if len(idx)<50: return None
    e=eq[idx]; r=e[1:]/e[:-1]-1; yrs=len(r)/245; return (e[-1]/e[0])**(1/yrs)-1, r.mean()/(r.std()+1e-12)*np.sqrt(245), (e/np.maximum.accumulate(e)-1).min(), expo[idx].mean()
def line(tag,eq,expo,tr):
    cells=[]
    for pn,(a,b) in ERA.items():
        s=stats(eq,expo,a,b); cells.append('无' if s is None else f'{s[0]*100:+5.1f}%/{s[1]:+.2f}/{s[2]*100:4.0f}%/{s[3]*100:2.0f}%')
    print(f'{tag:30s}| '+' | '.join(cells)+f' | 笔{len(tr)} 均{tr.mean()*1e4:+.0f}bp 胜{(tr>0).mean()*100:.0f}%',flush=True)
print('格式：年化/夏普/最大回撤/平均仓位；列='+' | '.join(ERA)); 
cells=[]
for pn,(a,b) in ERA.items():
    m=(dates>=a)&(dates<=b); x=mr[m]; cum=np.cumprod(1+x); yrs=m.sum()/245
    cells.append(f'{(cum[-1]**(1/yrs)-1)*100:+5.1f}%/{x.mean()/x.std()*np.sqrt(245):+.2f}/{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}%/100%')
print(f'{"基准 等权大盘(不计成本)":30s}| '+' | '.join(cells))
SN=['09:45','10:00','10:30','11:00','13:30','14:00','14:30','14:50']
R={}
for nm,key in [('基线:收盘确认 次日开盘买','base'),('盘中首次触发即买','first')]+[(f'固定{SN[k]}触发即买',f'fx{k}') for k in range(8)]+[(f'随机候选(对照) {SN[k]}',f'cc{k}') for k in (1,7)]:
    ev=events(key)
    for N in (20,):
        eq,ex_,tr=portfolio(ev,N); R[(key,N)]=(eq,ex_); line(f'{nm} N={N}',eq,ex_,tr)
bench=np.cumprod(1+np.nan_to_num(mr))
print('\n逐年 年收益：基线 / 盘中首次触发 / 固定10:00 / 固定14:50 / 基准  (括号=平均仓位)')
for y in range(2020,2027):
    cells=[]
    for key in ('base','first','fx1','fx7'):
        eq,ex_=R[(key,20)]; ii=np.nonzero(np.char.startswith(dates,str(y))&np.isfinite(eq))[0]
        cells.append('   -   ' if len(ii)<20 else f'{(eq[ii[-1]]/eq[ii[0]]-1)*100:+6.1f}%({ex_[ii].mean()*100:2.0f})')
    ii=np.nonzero(np.char.startswith(dates,str(y)))[0]; b=bench[ii[-1]]/bench[ii[0]]-1
    print(f'  {y}: '+' / '.join(cells)+f' / {b*100:+6.1f}%')
