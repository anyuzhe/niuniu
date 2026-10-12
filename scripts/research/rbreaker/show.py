"""把 run_intraday 的 intraday.json 打成紧凑表。"""
import json
import sys

J = json.load(open((sys.argv[1] if len(sys.argv) > 1 else 'artifacts/research/rbreaker') + '/intraday.json'))
for g, d in J['drift'].items():
    print(g, '被动日内做多(开买收卖) 等权组合夏普 c0/c2/c5=', ' / '.join(f"{v:.2f}" for v in list(d['passive_port_sharpe'].values())[:3]), f"年化(未扣成本)={d['passive_ann_pct']:.1f}%")
for x in J['results']:
    if x.get('n', 0) == 0 or x['cost_bp'] not in (0, 2, 5) or x['label'].startswith('  └'):
        continue
    print(f"{x['group']:5s}{x['variant']:8s}{x['rule'][:9]:9s} c={x['cost_bp']} n={x['n']:5d} 触发日={x['n_dates']:4d} 胜率={x['win']*100:3.0f}% 毛={x['gross_bp']:+6.1f} 净={x['net_bp']:+6.1f}bp "
          f"组合夏普={x['port_sharpe']:+5.2f} 年化={x['port_ret_per_year_pct']:+5.1f}% 置换基线={x['null_mean_bp']:+6.1f}±{x['null_sd_bp']:.1f} p={x['p_vs_null']:.3f}")
