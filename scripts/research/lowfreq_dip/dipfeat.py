"""Dip candidates + ~28 factors + 20-day net label, saved to dipfeat.npz (research only).
Basic conditions: 20-day return < -10% & efficiency<0 (V1), not ST, tradable, listed >= 250 days, raw close >= 3, 20d avg amount >= 5e7,
next open not limit-up. Label: net return (next open buy, first good close on/after day 20 sell, 7.2bp + 1 tick each side)."""
import os, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']
exec(open('lowfreq.py').read().split("mon=np.array")[0])
T=np.arange(nd); jj=np.arange(nc)[None,:]
def run2(H):
    e_idx=np.minimum(T+H,nd-1); okx=(T+H)<nd
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    ei=np.tile(e_idx[:,None],(1,nc))
    for _ in range(3):
        bad=~(fin[np.minimum(ei,nd-1),jj])|limdn_close[np.minimum(ei,nd-1),jj]
        ei=np.where(bad&(ei<nd-1),ei+1,ei)
    e2=np.minimum(ei,nd-1); exC=C[e2,jj]; exR=R[e2,jj]
    enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]; enR=np.full((nd,nc),np.nan); enR[:-1]=Ro[1:]
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)
    net=(exC*(1-0.01/exR))/(enO*(1+0.01/enR))-1-FEE
    return valid,net,ei
valid,net,ei=run2(20)
listed250=np.cumsum(np.isfinite(C),0)>=250
cand=valid&base&listed250&(R>=3.0)&np.isfinite(net)
cd,cj=np.nonzero(cand); print('candidates',len(cd),flush=True)
FT={}
def add(name,arr):
    v=arr[cd,cj].astype(np.float64); FT[name]=v
def rext(a,n,fn):
    out=np.full(a.shape,np.nan,np.float32); a=a.astype(np.float32)
    for s in range(0,a.shape[1],400):
        w=np.lib.stride_tricks.sliding_window_view(a[:,s:s+400],n,axis=0)
        out[n-1:,s:s+400]=fn(w,axis=2)
    return out
Vn=np.nan_to_num(V)
# A. dip shape
add('20日跌幅',mom20); add('5日涨跌',ret5); add('3日涨跌',C/shift(C,3)-1); add('信号日涨跌',ret1); add('开盘跳空',O/shift(C,1)-1)
hi60=rext(Hh,60,np.max); add('距60日最高',C/hi60-1); del hi60
lo10=rext(L,10,np.min); add('距10日最低反弹幅度',C/lo10-1); del lo10
for nm,n in (('距20日最低天数',20),):
    a=rext(L,n,np.min)  # placeholder to keep memory small
    del a
# days since 20d low via argmin
out=np.full((nd,nc),np.nan,np.float32); Lf=L.astype(np.float32)
for s in range(0,nc,400):
    w=np.lib.stride_tricks.sliding_window_view(Lf[:,s:s+400],20,axis=0); out[19:,s:s+400]=19-np.argmin(w,axis=2)
add('距20日最低天数',out); del out
add('近10日下跌天数',roll(np.where(np.isfinite(ret1),(ret1<0).astype(float),np.nan),10))
# B. position vs longer trend
add('60日涨跌',C/shift(C,60)-1); add('120日涨跌',C/shift(C,120)-1); add('12减1动量',shift(C,20)/shift(C,250)-1)
mx=rext(C,250,np.max); mn=rext(C,250,np.min); add('250日区间位置',(C-mn)/np.where(mx>mn,mx-mn,np.nan)); del mx,mn
ma20=roll(C,20)/20; ma60=roll(C,60)/60; ma250=roll(C,250)/250
add('距60日均线',C/ma60-1); add('距250日均线',C/ma250-1); add('20日均线相对60日',ma20/ma60-1)
# C. volume
v5=roll(Vn,5)/5; v20=roll(Vn,20)/20; a60=roll(A,60)/60
add('5日量/20日量',v5/v20); add('信号日量/20日量',Vn/v20); add('20日额/60日额',amt20/a60)
add('近10日下跌日成交占比',roll(np.where(ret1<0,Vn,0.0),10)/roll(Vn,10))
# D. volatility / candle
add('20日波动率',vol20); tr=np.maximum(Hh-L,np.maximum(np.abs(Hh-shift(C,1)),np.abs(L-shift(C,1))))/C; add('20日平均真实波幅',roll(tr,20)/20)
add('收盘位置',cloc); add('下影线占比',np.where((Hh-L)>1e-9,(np.minimum(O,C)-L)/np.where((Hh-L)>1e-9,Hh-L,1),0.5))
# E. size / price level
add('成交额(对数)',np.log(np.maximum(amt20,1))); add('股价(对数)',np.log(np.maximum(R,0.01)))
FT['date_idx']=cd; FT['code_idx']=cj; FT['y']=net[cd,cj]; FT['exit_idx']=ei[cd,cj]
np.savez('dipfeat.npz',dates=dates,codes=codes,**FT)
print('saved',len(FT)-4,'factors',flush=True)
