import sys; sys.argv=['x','core']
exec(open('states2.py').read().split("P=run(")[0])
g=zv<=-1.5
run('恐慌 E6 1x',g,e6,L=1.0); run('恐慌 最弱10% 1x',g,loser,L=1.0)
run('恐慌 E6 2x',g,e6,L=2.0); run('恐慌 最弱10% 2x',g,loser,L=2.0)
p5=np.nanpercentile(np.where(valid,ret20,np.nan),5,axis=1); l5=valid&(ret20<=p5[:,None])
run('恐慌 最弱5% 2x',g,l5,L=2.0)
run('恐慌 最弱10% 2x 随机取20只',g,loser,L=2.0,rank=None)
# overlap of pools on panic days
m=g[:,None]&valid
print('恐慌日 候选池平均只数 全部%.0f E6 %.0f 最弱10%% %.0f  E6∩最弱10%% %.0f'%(valid[g].sum(1).mean(),e6[g].sum(1).mean(),loser[g].sum(1).mean(),(e6&loser)[g].sum(1).mean()))
