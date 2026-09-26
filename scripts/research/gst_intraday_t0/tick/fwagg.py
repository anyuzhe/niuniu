import pickle, glob, os, numpy as np
acc={}
for f in glob.glob(os.path.expanduser('~/research/tick/fw_*.pkl')):
    for k,v in pickle.load(open(f,'rb')).items(): acc.setdefault(k,[]).extend(v)
for k,v in sorted(acc.items()):
    v=[x for x in v if np.all(np.isfinite(x[1])) and np.isfinite(x[2])]
    N=sum(x[0] for x in v); w=lambda j: sum(x[0]*x[1][j] for x in v)/N
    print(f"{k[0]} {k[1]} n{N} | 信号后中间价(价位) 3秒{w(0):+.2f} 15秒{w(1):+.2f} 30秒{w(2):+.2f} 1分{w(3):+.2f} 5分{w(4):+.2f}"
          f" | 买入后 1分{w(8):+.2f} 5分{w(9):+.2f} | 买入时价差{sum(x[0]*x[4] for x in v)/N:.2f}价位"
          f" | 5分钟内买一曾≥买入价+1价位 {sum(x[0]*x[2] for x in v)/N*100:.0f}%，≥买入价 {sum(x[0]*x[3] for x in v)/N*100:.0f}%")
