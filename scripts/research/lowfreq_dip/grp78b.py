import os, sys, json, pickle, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
z = inp.ind_state.z; breadth = np.nansum(z <= -1.5, axis=1)
mz = inp.market.z
R = json.load(open('grp71_indlevel.json')); T = json.load(open('grp69_D.json'))['trades']
dates = json.load(open('grp71_indlevel.json'))  # 只为占位
BAD = ['国防军工','环保','煤炭','基础化工','家用电器','美容护理','房地产']; GOOD = ['计算机','医药生物','有色金属','公用事业','食品饮料','农林牧渔','电子','银行']
traded = {(t['signal'], t['ind']) for t in T}
bk = [(3, '1-3个行业同时触发'), (8, '4-8个'), (15, '9-15个'), (99, '16个以上')]
def b(n):
    for hi, lab in bk:
        if n <= hi: return lab
print('每个行业触发日，按“同一天触发的行业数”分档：行业全成员后续20日收益；括号为其中账户买了的天数')
for lab, S in (('差7', BAD), ('好8', GOOD), ('其余', None), ('全部', 'ALL')):
    sel = [r for r in R if S == 'ALL' or (r['ind'] in S if S else r['ind'] not in BAD + GOOD)]
    d = collections.defaultdict(list); tr = collections.defaultdict(int)
    for r in sel:
        k = b(int(breadth[r['t']])); d[k].append(r['fwd']); tr[k] += (r['date'], r['ind']) in traded
    print(lab, ' | '.join(f"{k}: {len(d[k])}天 {np.mean(d[k])*100:+.1f}% (买{tr[k]})" for _, k in bk if d[k]))
