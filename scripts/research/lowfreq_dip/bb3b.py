import sys; sys.argv=['x']
src=open('bb3.py').read(); pre,post=src.split("#SCAN")
exec(pre)
# extra entries / gates
def feat2(s):
    C=pd.DataFrame(c[:,s].astype(np.float64)); A=pd.DataFrame(P['a'][:,s].astype(np.float64))
    return dict(a20=A.rolling(20,min_periods=15).mean().values.astype(np.float32), dd20=(C/C.rolling(20,min_periods=20).max()-1).values.astype(np.float32),
                r5=(C/C.shift(5)-1).values.astype(np.float32))
F2=blk(feat2)
a=np.where(valid,F2['a20'],np.nan); hi=np.nanpercentile(a,70,axis=1)[:,None]; lo=np.nanpercentile(a,30,axis=1)[:,None]
up=S['上轨突破首日']; nh=S['一年新高突破']; n60=S['60日新高突破']
T={}
T['大成交额(前30%) 上轨突破']=up&(a>=hi); T['小成交额(后30%) 上轨突破']=up&(a<=lo)
T['大成交额(前30%) 60日新高']=n60&(a>=hi); T['小成交额(后30%) 60日新高']=n60&(a<=lo)
T['大成交额 一年新高']=nh&(a>=hi)
T['深回踩(距20日高-10%~-20%,MA60上)']=cool(valid&(F2['dd20']<=-0.10)&(F2['dd20']>=-0.20)&(ma20>=ma60)&(c>ma60))
T['强势股急跌(5日跌>8%,MA60上,MA20>MA60)']=cool(valid&(F2['r5']<=-0.08)&(c>ma60)&(ma20>ma60))
S=T
abv=(valid&(c>ma20)).sum(1)/np.maximum(valid.sum(1),1)
GR={'广度>70%(多数股在MA20上)':abv>0.7,'广度>85%':abv>0.85,'z>0.5且广度>70%':(zz>0.5)&(abv>0.7),'z>0.5':zz>0.5,'任何日子':np.isfinite(zz)}
EXITS={k:EXITS[k] for k in ('跌破MA20(1日)','跌破MA60','距最高收盘回落20%','涨25%止盈或跌破MA20','固定持有20天','固定持有40天')}
EXITS['固定持有10天']=dict(fix=10)
print('extra set',{k:int(v.sum()) for k,v in S.items()},flush=True)
exec(post.replace("bb3.json","bb3b.json"))
