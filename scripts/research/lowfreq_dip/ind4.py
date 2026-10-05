import sys
src=open('ind2.py').read().split("allg=np.isfinite(zv)\n# episodes")[0]
exec(src)
allg=np.isfinite(zv); uni_all=valid&(zind<=-1.5)
sizes={g:(ind==g).sum() for g in u}; ug=np.array(u)
big=ug[[sizes[g]>=60 for g in u]]; bigm=np.isin(ind,big)[None,:]
print('大行业(>=60只)',len(big),'个；小行业',len(u)-len(big),'个')
run('统一闸门 1x 只大行业',allg,uni_all&bigm); run('统一闸门 1x 只大行业 每边冲击20bp',allg,uni_all&bigm,slip=0.002)
run('统一闸门 1.5x 只大行业',allg,uni_all&bigm,L=1.5)
rng=np.random.default_rng(5)
for s in range(3):
    perm=rng.permutation(len(u)); A=ug[perm[:len(u)//2]]; Bq=ug[perm[len(u)//2:]]
    run(f'随机拆分{s}: 一半行业 1x',allg,uni_all&np.isin(ind,A)[None,:]); run(f'随机拆分{s}: 另一半行业 1x',allg,uni_all&np.isin(ind,Bq)[None,:])
