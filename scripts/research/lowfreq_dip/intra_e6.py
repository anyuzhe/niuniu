"""Research only (2020-2026): intraday entry for stock Bollinger-lower-band reclaim (E6) x dynamic market oversold z.
Uses panel.npz (daily) + snap_YYYY.parquet (5-min snapshots from bars_min5_baostock_raw, READY, raw prices)."""
import numpy as np, pandas as pd, gc, os, warnings; warnings.filterwarnings('ignore')
H0=os.environ['HOME']; L=f'{H0}/research/lowfreq/'
P=np.load(L+'panel.npz'); dates=P['dates'].astype(str); codes=P['codes']; nd=len(dates); nc=len(codes)
c=P['c'].astype(np.float64); o=P['o'].astype(np.float64); f=P['f'].astype(np.float64); a=P['a']; st=P['st']; ts=P['ts']
t0=int(np.searchsorted(dates,'2020-01-02')); H=20
SN=['0945','1000','1030','1100','1330','1400','1430','1450']
# ---- snapshots
cidx={cd:i for i,cd in enumerate(codes)}; didx={d:i for i,d in enumerate(dates)}
SIG=np.full((len(SN),nd,nc),np.nan,np.float32); EXE=np.full((len(SN),nd,nc),np.nan,np.float32); DOP=np.full((nd,nc),np.nan,np.float32)
for y in range(2020,2027):
    fp=f'{H0}/research/intra/snap_{y}.parquet'
    if not os.path.exists(fp): continue
    df=pd.read_parquet(fp); df['d']=df['date'].astype(str).map(didx); df['j']=df['code'].map(cidx); df=df.dropna(subset=['d','j']); di=df['d'].astype(int).values; ji=df['j'].astype(int).values
    DOP[di,ji]=df['dopen'].values
    for k,s in enumerate(SN): SIG[k,di,ji]=df['c'+s].values; EXE[k,di,ji]=df['x'+s].values
    del df; gc.collect()
print('snap loaded; coverage 2020-26: dopen finite share',np.isfinite(DOP[t0:]).mean().round(3),flush=True)
# ---- universes (as stockdyn / mkreg)
fin=np.isfinite(c)&np.isfinite(o)&(ts==1)
def rollsum(x,n):
    z=np.where(np.isfinite(x),x,0).astype(np.float64); cs=np.vstack([np.zeros((1,nc)),np.cumsum(z,0)]); out=np.full((nd,nc),np.nan); out[n-1:]=(cs[n:]-cs[:-n]); return out
amt20=rollsum(a,20)/20
raw=c/f
PE=np.load(L+'panel_ext.npz'); assert (PE['codes']==codes).all(); _ced=np.cumsum(np.isfinite(PE['c']),0); _ix=np.searchsorted(PE['dates'].astype(str),dates); assert (PE['dates'].astype(str)[_ix]==dates).all()
listed250=_ced[_ix]>=250; listed80=_ced[_ix]>=80; del PE,_ced
uni=fin&~st&listed250&(amt20>=5e7)&(raw>=3)
uniL=fin&~st&listed80&(amt20>=5e7)
def sh(x,k):
    out=np.full_like(x,np.nan) if x.dtype!=bool else np.zeros_like(x); out[k:]=x[:-k]; return out
uniP=sh(uni,1); uniLP=sh(uniL,1)
cf=np.where(np.isfinite(c),c,np.nan)
s1=rollsum(cf,20); s2=rollsum(cf**2,20); cnt=rollsum(np.isfinite(cf).astype(float),20)
ma=s1/20; sd=np.sqrt(np.maximum(s2/20-ma*ma,0)*20/19); blo=ma-2*sd
E6=(sh(c,1)<sh(blo,1))&(c>blo)&(c>o)&uni        # daily close-confirmed (baseline)
# prior-19 sums (days t-19..t-1) for intraday band
s1p=sh(rollsum(cf,19),1); s2p=sh(rollsum(cf**2,19),1); cntp=sh(rollsum(np.isfinite(cf).astype(float),19),1)
del s1,s2,ma,sd,cnt,amt20,a,raw,listed250,listed80
prevBloOK=(sh(c,1)<sh(blo,1))   # previous close below previous lower band
del blo; gc.collect()
# ---- market z
M=np.load(L+'mkreg_ext_liq.npz'); Md={d:i for i,d in enumerate(M['dates'].astype(str))}
mr=np.full(nd,np.nan); mk20s=np.full(nd,np.nan)
for i,d in enumerate(dates):
    if d in Md: mr[i]=M['mret'][Md[d]]; mk20s[i]=M['mk20'][Md[d]]
sd60i=np.full(nd,np.nan); sd60p=np.full(nd,np.nan)
for i in range(61,nd):
    sd60i[i]=np.nanstd(mr[i-59:i+1],ddof=1); sd60p[i]=np.nanstd(mr[i-60:i],ddof=1)
zv=mk20s/(sd60i*np.sqrt(20))                # baseline close z (stored mk20)
c20=sh(c,20)
def mk20_from(pa):                           # pa: adjusted price [nd,nc]
    r=pa/c20-1; m=uniLP&np.isfinite(r); return np.where(m.sum(1)>200,np.nansum(np.where(m,r,0),1)/np.maximum(m.sum(1),1),np.nan)
mk_own_c=mk20_from(c)
print('sanity: corr own close mk20 vs stored (2020+):',np.corrcoef(mk_own_c[t0:][np.isfinite(mk_own_c[t0:])&np.isfinite(mk20s[t0:])],mk20s[t0:][np.isfinite(mk_own_c[t0:])&np.isfinite(mk20s[t0:])])[0,1].round(4),flush=True)
# ---- limits, fees
lim=np.full(nc,0.1); is30=np.char.startswith(codes,'sz.30'); is688=np.char.startswith(codes,'sh.688')
limm=np.repeat(lim[None,:],nd,0); limm[(dates>='2020-08-24')[:,None]&is30[None,:]]=0.2; limm[:,is688]=0.2
prevraw=sh(c/f,1)
stamp=np.where(dates<'2023-08-28',0.001,0.0005); comm=np.where(dates<'2020-01-01',0.0004,0.00022); feeD=(stamp+comm)
rawX=np.full((nd,nc),np.nan); rawX[:-H]=c[H:]/f[H:]
exA=np.full((nd,nc),np.nan); exA[:-H]=c[H:]
for k in (1,2,3):
    miss=~np.isfinite(exA)
    alt=np.full((nd,nc),np.nan); alt[:-(H+k)]=c[H+k:]; altr=np.full((nd,nc),np.nan); altr[:-(H+k)]=c[H+k:]/f[H+k:]
    exA=np.where(miss,alt,exA); rawX=np.where(miss,altr,rawX)
valid_day=np.arange(nd)<nd-H-4
def net_from(entry_raw, fday):               # entry_raw [nd,nc] raw price; entry day = signal day t
    ea=entry_raw*f                           # adjusted at day t
    return (exA*(1-0.01/rawX))/(ea*(1+0.01/entry_raw))-1-fday[:,None]
# baseline close-confirmed: entry next open, exit c[t+H]  (hold 20d)
entB=np.full((nd,nc),np.nan); entB[:-1]=o[1:]; rawEB=np.full((nd,nc),np.nan); rawEB[:-1]=o[1:]/f[1:]
gapB=np.full((nd,nc),np.nan); gapB[:-1]=o[1:]/c[:-1]-1
okB=np.zeros((nd,nc),bool); okB[:-1]=fin[1:]&~(gapB[:-1]>=limm[:-1]-0.0025)
netB=(exA*(1-0.01/rawX))/(entB*(1+0.01/rawEB))-1-feeD[:,None]
netB=netB.astype(np.float32)
# ---- intraday per snapshot
dayidx=np.arange(nd)[:,None]
E6s=[]; Zs=[]; NETs=[]; OKs=[]
for k in range(len(SN)):
    pa=(SIG[k]*f.astype(np.float32)).astype(np.float64)
    n20=cntp+1; m1=(s1p+pa)/20; m2=(s2p+pa**2)/20; sdx=np.sqrt(np.maximum(m2-m1*m1,0)*20/19); bl=m1-2*sdx
    dopa=DOP*f
    e6=prevBloOK&(pa>bl)&(pa>dopa)&uniP&(cntp>=19)&np.isfinite(pa)
    mk=mk20_from(pa); z=mk/(sd60p*np.sqrt(20))
    ex_raw=EXE[k].astype(np.float64)
    ok=np.isfinite(ex_raw)&~((ex_raw/prevraw-1)>=limm-0.0025)
    nt=net_from(ex_raw,feeD).astype(np.float32)
    E6s.append(e6); Zs.append(z); NETs.append(nt); OKs.append(ok)
    del pa,m1,m2,sdx,bl,dopa,ex_raw,nt; gc.collect()
print('intraday arrays built',flush=True)
np.savez(f'{H0}/research/intra/intra_cache.npz',Zs=np.array(Zs),zv=zv,dates=dates)
# ---- episode-cluster helper
def episodes(day_list):
    ep=[];last=-99;cur=-1
    for t in day_list:
        if t-last>5: cur+=1
        ep.append(cur); last=t
    return np.array(ep)
def summarize(tag,evnet,evday,gate_days_all=None):
    # evnet: array of net returns for events; evday: day index per event
    if len(evnet)==0: print(f'{tag:34s}| 无'); return
    days=np.unique(evday); dm=np.array([evnet[evday==d].mean() for d in days]); ep=episodes(days)
    em=np.array([dm[ep==e].mean() for e in np.unique(ep)]); ne=len(em)
    t=em.mean()/(em.std(ddof=1)/np.sqrt(ne)) if ne>2 and em.std()>0 else np.nan
    print(f'{tag:34s}| 事件{len(evnet):5d} 天{len(days):3d} 段{ne:3d} | 均净{evnet.mean()*1e4:+5.0f}bp 中位{np.median(evnet)*1e4:+5.0f} 胜率{(evnet>0).mean()*100:3.0f}% | 按天均{dm.mean()*1e4:+5.0f} 按段均{em.mean()*1e4:+5.0f} t={t:+.1f}',flush=True)
def evs(mask,net): 
    ti,ji=np.nonzero(mask); return net[ti,ji], ti
tm=np.zeros(nd,bool); tm[t0:]=True; tm&=valid_day
ZB=-1.5
print('\n=== A. 事件研究(2020-01~2026,z闸门≤-1.5)：买点不同，同一天同一退出日(第t+20日收盘)，净收益(已扣成本)')
base=E6&okB&(zv<=ZB)[:,None]&tm[:,None]&np.isfinite(netB)
x,d=evs(base,netB); summarize('基线: 收盘确认,次日开盘买',x,d)
first=np.zeros((nd,nc),bool); firstK=np.full((nd,nc),-1,int); firstNet=np.full((nd,nc),np.nan,np.float32)
for k in range(len(SN)):
    g=(Zs[k]<=ZB)[:,None]
    m=E6s[k]&OKs[k]&g&tm[:,None]&np.isfinite(NETs[k])
    x,d=evs(m,NETs[k]); summarize(f'固定{SN[k][:2]}:{SN[k][2:]} 触发即买(次根开盘)',x,d)
    new=m&~first; firstK[new]=k; firstNet[new]=NETs[k][new]; first|=m
x,d=evs(first,firstNet); summarize('首次触发(9:45~14:50 任意时刻)',x,d)
# of first-trigger events: share confirmed at close
conf=first&E6
x1,d1=evs(conf,firstNet); x0,d0=evs(first&~E6,firstNet)
print(f'   其中收盘仍确认{conf.sum()}/{first.sum()}={conf.sum()/max(first.sum(),1)*100:.0f}%: 均净{x1.mean()*1e4:+.0f}bp;  收盘没守住{(first&~E6).sum()}: 均净{x0.mean()*1e4:+.0f}bp')
for k in range(len(SN)):
    m=first&(firstK==k)
    if m.sum()>0: print(f'   首次触发在{SN[k][:2]}:{SN[k][2:]}: {m.sum():5d}只 均净{firstNet[m].mean()*1e4:+5.0f}bp 胜率{(firstNet[m]>0).mean()*100:3.0f}%  收盘确认{(m&E6).sum()/m.sum()*100:3.0f}%')
print('\n=== B. 同一批“收盘确认”的信号股：价格路径 (昨收→各时点→收盘→次日开盘→次日收盘)，看盘中已反弹多少 (含前视，仅用于看路径)')
cs=base
pc=sh(c,1)
def ad(x): return x*f
r_prev_c=c/pc-1
print(f'  昨收→当日收盘: 均{np.nanmean(r_prev_c[cs])*1e4:+.0f}bp')
nxt=np.full((nd,nc),np.nan); nxt[:-1]=o[1:]/c[:-1]-1; nxo=np.full((nd,nc),np.nan); nxo[:-1]=c[1:]/o[1:]-1
print(f'  收盘→次日开盘(隔夜跳空): 均{np.nanmean(nxt[cs])*1e4:+.0f}bp  次日开盘→次日收盘: 均{np.nanmean(nxo[cs])*1e4:+.0f}bp')
for k in range(len(SN)):
    p=SIG[k]*f.astype(np.float32); ex=EXE[k]*f.astype(np.float32)
    a1=np.nanmean((p/pc-1)[cs]); a2=np.nanmean((ex/(c[:]) -1)[cs]); a3=np.nanmean((np.where(np.isfinite(entB),entB,np.nan)*0+ (np.concatenate([o[1:]/1,np.full((1,nc),np.nan)])/ex-1))[cs])
    print(f'  {SN[k][:2]}:{SN[k][2:]} 时昨收→价 {a1*1e4:+5.0f}bp ; 买入价(次根开盘)→收盘 {a2*-1e4:+5.0f}bp(若此价买到收盘) ; 买入价→次日开盘 {a3*1e4:+5.0f}bp')
np.savez(f'{H0}/research/intra/intra_events.npz',first=first,firstK=firstK,firstNet=firstNet,base=base)
# ---- save events for portfolio test
S={}
def put(name,m,net,k=None,entry_raw=None,offset=0):
    ti,ji=np.nonzero(m); S[name+'_t']=ti; S[name+'_j']=ji; S[name+'_net']=net[ti,ji]
    S[name+'_raw']=entry_raw[ti,ji] if entry_raw is not None else np.zeros(len(ti))
    S[name+'_o0']=(entry_raw[ti,ji]*f[ti,ji]) if entry_raw is not None else np.zeros(len(ti))
    S[name+'_off']=np.array([offset])
for k in range(len(SN)):
    g=(Zs[k]<=ZB)[:,None]
    m=E6s[k]&OKs[k]&g&tm[:,None]&np.isfinite(NETs[k]); put(f'fx{k}',m,NETs[k],entry_raw=EXE[k].astype(np.float64))
    cm=uniP&OKs[k]&g&tm[:,None]&np.isfinite(NETs[k]); put(f'cc{k}',cm,NETs[k],entry_raw=EXE[k].astype(np.float64))
# first-trigger: need the entry raw by chosen k
frawE=np.full((nd,nc),np.nan)
for k in range(len(SN)):
    mk=(firstK==k); frawE[mk]=EXE[k][mk]
put('first',first,firstNet,entry_raw=frawE); S['first_k']=firstK[first]
put('base',base,netB,entry_raw=rawEB,offset=1); S['base_o0']=entB[np.nonzero(base)]
np.savez(f'{H0}/research/intra/intra_events.npz',dates=dates,**S)
print('events saved',flush=True)
