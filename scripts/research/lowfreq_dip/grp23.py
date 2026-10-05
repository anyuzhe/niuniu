"""Win rate / payoff / expectancy / return on deployed capital for A, B, C (fixed 20d hold, 1x, 2008+). Research only."""
from grp11 import *
didx = {d: i for i, d in enumerate(panel.dates)}
rows = []
for nm, fm, fc in (('A 大盘z+E6', market, cand), ('B 行业恐慌', fmB, fcB), ('C 成交额五分位', fmC, fcC), ('D 大盘z<=-1.0最弱20', fmD, fcD)):
    r = simulate(panel, fm, fc, DipConfig(leverage=1.0)); tr = [t for t in r['trades']]; eq, ex = r['eq'], r['expo']
    ret = np.array([t['ret'] for t in tr]); w = np.array([t['weight'] for t in tr]); hd = np.array([didx[t['exit']] - didx[t['entry']] for t in tr], float)
    hd = np.maximum(hd, 1)
    win = ret > 0; p = win.mean(); aw = ret[win].mean(); al = -ret[~win].mean(); b = aw / al
    exp_ = ret.mean(); pf = ret[win].sum() / -ret[~win].sum(); kelly = p - (1 - p) / b
    # capital-weighted: money made per money deployed
    pnl = (w * ret).sum(); dep = w.sum(); roic_trade = pnl / dep                    # weighted avg return per trade (per unit of capital deployed)
    cap_days = (w * hd).sum()                                                       # capital-days deployed (initial-capital-weighted)
    roic_ann = (w * ret).sum() / (w * hd).sum() * 245                              # simple annualised return on deployed capital
    m = np.isfinite(eq); n = m.sum(); x = np.diff(eq[m]) / eq[m][:-1]; cagr = (eq[m][-1] / eq[m][0]) ** (245 / n) - 1
    expo = np.nanmean(ex[m])
    half = {}
    mid = len(tr) // 2
    for lab, sl in (('前半', slice(0, mid)), ('后半', slice(mid, None))):
        rr = ret[sl]; half[lab] = f'{(rr>0).mean()*100:.0f}%/{(rr[rr>0].mean()/-rr[rr<=0].mean()):.2f}/{rr.mean()*1e4:+.0f}bp'
    # worst clusters: share of total P&L from top 10% trades
    srt = np.sort(w * ret)[::-1]; top10 = srt[:max(1, len(srt) // 10)].sum() / srt.sum()
    print(f'--- {nm}: 笔数 {len(tr)}，平均持有 {hd.mean():.1f} 个交易日，平均仓位占用 {expo*100:.0f}%（实际资金利用率）', flush=True)
    print(f'    胜率 {p*100:.1f}%  平均盈利 {aw*1e4:+.0f}bp  平均亏损 {-al*1e4:+.0f}bp  赔率(盈/亏) {b:.2f}  盈亏比(利润合计/亏损合计) {pf:.2f}', flush=True)
    print(f'    每笔期望 {exp_*1e4:+.0f}bp  中位 {np.median(ret)*1e4:+.0f}bp  凯利比例 {kelly*100:.0f}%  前10%盈利笔贡献总利润 {top10*100:.0f}%', flush=True)
    print(f'    每投入 1 元(按仓位加权)平均每笔赚 {roic_trade*100:.2f}%；年化占用资金回报率 {roic_ann*100:.1f}%（只看投下去的钱）；账户年化 {cagr*100:.1f}%（= 占用回报 × 利用率 {expo*100:.0f}% 附近）', flush=True)
    print(f'    前/后半 胜率/赔率/每笔期望: {half["前半"]} | {half["后半"]}', flush=True)
