import json, numpy as np, collections
R = json.load(open('grp71_indlevel.json'))
BAD = ['国防军工','环保','煤炭','基础化工','家用电器','美容护理','房地产']; GOOD = ['计算机','医药生物','有色金属','公用事业','食品饮料','农林牧渔','电子','银行']
bk = [(-1.75, '-1.5~-1.75'), (-2.0, '-1.75~-2.0'), (-2.5, '-2.0~-2.5'), (-99, '< -2.5')]
def b(z):
    for hi, lab in bk:
        if z > hi: return lab
print('行业触发日按行业 z 分档的后续 20 日收益（行业全成员）')
for lab, S in (('差7', BAD), ('好8', GOOD), ('其余', None)):
    sel = [r for r in R if (r['ind'] in S if S else r['ind'] not in BAD + GOOD)]; d = collections.defaultdict(list)
    for r in sel: d[b(r['z'])].append(r['fwd'])
    print(lab, ' | '.join(f"{k}: {len(d[k])}个 {np.mean(d[k])*100:+.1f}%" for _, k in bk if d[k]))
