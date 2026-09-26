"""Group reversal outcomes by features (research only)."""
import numpy as np, os, glob
H=os.environ['HOME']
Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/rev_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
d=Z['date']; P={'20-22':d<'2023','23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
ud,inv=np.unique(d,return_inverse=True)
def dq(x,q=10):
    """per-date decile of x (0..q-1), nan stays -1"""
    out=np.full(len(x),-1)
    order=np.lexsort((x,inv)); xs=x[order]; iv=inv[order]
    cnt=np.bincount(inv[np.isfinite(x)],minlength=len(ud))
    fin=np.isfinite(xs); pos=np.zeros(len(x),int)
    # rank within date among finite
    start=np.r_[0,np.cumsum(np.bincount(iv,minlength=len(ud)))[:-1]]
    rk=np.arange(len(x))-start[iv]
    out[order[fin]]=(rk[fin]*q//np.maximum(cnt[iv[fin]],1)).clip(0,q-1)
    return out
def tstat(y,mask):
    y=y[mask]; dd=inv[mask]; m=y.mean(); r=np.bincount(dd,y-m); return m/(np.sqrt((r**2).sum())/len(y))
def show(title,y,groups,labels):
    print(f'\n{title}')
    for g,lab in zip(groups,labels):
        s=f'  {lab:22s}'
        for p,pm in P.items():
            mk=g&pm&np.isfinite(y)
            if mk.sum()<50: s+=f' | {p} —'; continue
            w=y[mk]>0
            s+=f' | {p} {y[mk].mean():+6.1f}bp 胜{w.mean()*100:3.0f}% 赔{y[mk][w].mean()/-y[mk][~w].mean():.2f} t{tstat(y,mk):+4.1f} n{mk.sum()}'
        print(s)
y=Z['rev_open']
show('基准：每天开盘先卖、收盘买回（全部 500 只）',y,[np.ones(len(y),bool)],['全部'])
for f,nm in (('gap','高开幅度'),('r1','昨日涨跌'),('r5','近5日涨跌'),('vr','昨日量比'),('loc','昨收在昨日区间位置')):
    q=dq(Z[f]); show(f'开盘先卖，按{nm}分十组（0=最低）',y,[q==i for i in (0,1,4,5,8,9)],[f'{nm} 第{i}组' for i in (0,1,4,5,8,9)])
g=Z['gap']
show('开盘先卖，按高开绝对幅度',y,[g<-0.02,(g>=-0.02)&(g<0),(g>=0)&(g<0.02),(g>=0.02)&(g<0.04),(g>=0.04)&(g<0.07),g>=0.07],['低开>2%','低开0-2%','高开0-2%','高开2-4%','高开4-7%','高开≥7%'])
lu=Z['plu']>0
show('昨日涨停的股票，开盘先卖',y,[lu&(g<0),lu&(g>=0)&(g<0.03),lu&(g>=0.03)&(g<0.07),lu&(g>=0.07),lu],['低开','高开0-3%','高开3-7%','高开≥7%','全部'])
for tag in ('1000','1030'):
    q=dq(Z[f'rel{tag}'])
    show(f'{tag[:2]}:{tag[2:]} 相对大盘最弱的买入（正T）',Z[f'long{tag}'],[q==0,q==1,q==9],['最弱10%','次弱10%','最强10%'])
    show(f'{tag[:2]}:{tag[2:]} 相对大盘最强的先卖（反T）',Z[f'short{tag}'],[q==9,q==8,q==0],['最强10%','次强10%','最弱10%'])
