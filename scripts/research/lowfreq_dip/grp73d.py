import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np, collections
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
gB = inp.gates['B']; gA = inp.gates['A']
R = json.load(open('grp71_indlevel.json'))
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理']; GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
def grp(n): return '差6' if n in BAD else '房地产' if n == '房地产' else '好8' if n in GOOD else '其余'
acc = collections.defaultdict(list)
for r in R:
    g = grp(r['ind']); b = 'B闸开' if gB[r['t']] else 'B闸关'
    acc[(g, b)].append(r['fwd'])
for g in ('差6', '房地产', '其余', '好8'):
    print(g, ' | '.join(f"{b}: 触发日{len(acc[(g,b)])} 行业20日均值{np.mean(acc[(g,b)])*100:+.1f}%" for b in ('B闸开', 'B闸关') if acc[(g, b)]))
print('B闸开的天数占全部交易日', float(np.mean(gB)), ' A闸开', float(np.mean(gA)))
