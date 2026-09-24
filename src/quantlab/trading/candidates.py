"""今日候选: a few plain-language screens, each shown with its own historical check.

Every rule is fixed in code (not tuned on the result). For each rule the same
features are evaluated on every past session in the loaded window (about one year):
buy the selected stocks at the next session's open (skipping one-word limit-up
opens, which cannot be bought) and sell at the close five sessions after the signal,
equal weight; compare with the same trade on all tradable stocks that day.

Stats use non-overlapping signal days (every 5th session) so the five-day holding
windows do not overlap. The verdict is deliberately conservative. Known limits,
shown to the user: only currently listed stocks (survivorship bias), about one year
of one market regime, adjusted prices, no capacity or slippage beyond a flat cost.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

HOLD_SESSIONS = 5
ROUND_TRIP_COST = 0.002  # commission both sides + stamp duty + slippage, rounded up
MIN_SELECTED = 3
MIN_SAMPLES = 20
MAX_TODAY = 30


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    description: str
    condition: pl.Expr
    order: str
    descending: bool = True


NOT_ST = ~pl.col('is_st').fill_null(False)
TRADABLE = pl.col('tradable').fill_null(False)

RULES = (
    Rule('strong_trend', '强势趋势',
         '近20日涨幅排在全市场前10%，收盘在20日线和60日线上方，非ST。',
         (pl.col('rank20') >= 0.9) & (pl.col('ma20_gap') > 0) & (pl.col('ma60_gap') > 0), 'ret20'),
    Rule('volume_breakout', '放量创新高',
         '今天涨幅超过3%，成交额是20日均值2倍以上，收盘接近或创出60日新高，非ST。',
         (pl.col('pct') >= 0.03) & (pl.col('amount_ratio') >= 2) & (pl.col('high60_gap') >= -0.01), 'amount_ratio'),
    Rule('first_board', '首板',
         '今天首次涨停（此前一个交易日没有涨停），非ST。',
         pl.col('streak') == 1, 'amount_ratio'),
    Rule('pullback', '强势股回调',
         '近60日涨幅超过20%，但近5日回落超过5%，收盘仍在60日线上方，非ST。',
         (pl.col('ret60') >= 0.2) & (pl.col('ret5') <= -0.05) & (pl.col('ma60_gap') > 0), 'ret60'),
    Rule('oversold', '超跌',
         '近20日涨幅排在全市场后5%，收盘低于20日线10%以上，非ST。',
         (pl.col('rank20') <= 0.05) & (pl.col('ma20_gap') <= -0.1), 'ret20', False),
)


def _selected(features: pl.DataFrame, rule: Rule) -> pl.DataFrame:
    return features.filter(TRADABLE & NOT_ST & rule.condition.fill_null(False))


def _validate(features: pl.DataFrame, rule: Rule, sessions: list[date]) -> dict:
    tested_days = sessions[FEATURE_START:-HOLD_SESSIONS] if len(sessions) > FEATURE_START + HOLD_SESSIONS else []
    signal_days = tested_days[::HOLD_SESSIONS]  # non-overlapping five-session windows
    buyable = (pl.col('fwd5').is_not_null() & pl.col('next_tradable') & ~pl.col('next_one_word'))
    universe = features.filter(pl.col('date').is_in(signal_days) & TRADABLE & buyable)
    market = universe.group_by('date').agg(pl.col('fwd5').mean().alias('market'))
    picks = (universe.filter(NOT_ST & rule.condition.fill_null(False))
             .group_by('date').agg(pl.col('fwd5').mean().alias('picked'), pl.len().alias('count')))
    daily = picks.join(market, on='date').filter(pl.col('count') >= MIN_SELECTED).sort('date')
    excess = (daily['picked'] - daily['market']).to_list()
    n = len(excess)
    result = {'hold_sessions': HOLD_SESSIONS, 'cost': ROUND_TRIP_COST, 'samples': n,
              'first_day': daily['date'][0].isoformat() if n else None,
              'last_day': daily['date'][-1].isoformat() if n else None,
              'avg_selected': round(float(daily['count'].mean()), 1) if n else None}
    if n < MIN_SAMPLES:
        return {**result, 'verdict': 'insufficient',
                'text': f'历史样本不足（{n} 个有效日，至少需要 {MIN_SAMPLES} 个），暂不能判断。'}
    mean = sum(excess) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in excess) / (n - 1)) if n > 1 else 0.0
    net = mean - ROUND_TRIP_COST
    t = net / sd * math.sqrt(n) if sd > 0 else (math.copysign(math.inf, net) if net else 0.0)
    hit = sum(x > ROUND_TRIP_COST for x in excess) / n
    verdict = 'positive' if net > 0 and t >= 2 else 'negative' if net < 0 and t <= -2 else 'unclear'
    headline = {
        'positive': '过去一年扣成本后平均跑赢全市场，统计上较稳定',
        'negative': '过去一年扣成本后平均跑输全市场',
        'unclear': '过去一年没有显示出稳定的优势',
    }[verdict]
    text = (f"{headline}：入选后持有{HOLD_SESSIONS}天，平均比全市场多 {mean * 100:+.2f}%，"
            f"扣约{ROUND_TRIP_COST * 100:.1f}%往返成本后 {net * 100:+.2f}%；{hit * 100:.0f}% 的时候跑赢；"
            f"平均每天选出 {result['avg_selected']} 只，{n} 个不重叠样本" + (f"（t={t:.1f}）。" if math.isfinite(t) else '。'))
    return {**result, 'verdict': verdict, 'mean_excess': round(mean, 5), 'net_excess': round(net, 5),
            'hit_rate': round(hit, 3), 't_stat': round(t, 2) if math.isfinite(t) else None, 'text': text}


def _reason(rule: Rule, row: dict) -> str:
    def p(v):
        return '—' if v is None else f'{v * 100:+.1f}%'
    if rule.key == 'strong_trend':
        return f"近20日 {p(row['ret20'])}，强于全市场 {row['rank20'] * 100:.0f}%"
    if rule.key == 'volume_breakout':
        return f"今日 {p(row['pct'])}，成交额 {row['amount_ratio']:.1f} 倍，距60日高点 {p(row['high60_gap'])}"
    if rule.key == 'first_board':
        return f"首板，成交额 {row['amount_ratio']:.1f} 倍" if row.get('amount_ratio') else '首板'
    if rule.key == 'pullback':
        return f"近60日 {p(row['ret60'])}，近5日 {p(row['ret5'])}"
    return f"近20日 {p(row['ret20'])}，低于20日线 {p(row['ma20_gap'])}"


def screen_candidates(features: pl.DataFrame, day: date, sessions: list[date]) -> list[dict]:
    today = features.filter(pl.col('date') == day)
    result = []
    for rule in RULES:
        picked = _selected(today, rule).sort(rule.order, descending=rule.descending, nulls_last=True)
        rows = picked.head(MAX_TODAY).to_dicts()
        result.append({
            'key': rule.key, 'name': rule.name, 'description': rule.description,
            'count': picked.height,
            'stocks': [{'code': r['code'], 'name': r['name'], 'industry': r['industry'], 'pct': r['pct'],
                        'ret20': r['ret20'], 'amount_ratio': r['amount_ratio'], 'streak': r['streak'],
                        'reason': _reason(rule, r)} for r in rows],
            'validation': _validate(features, rule, sessions),
        })
    return result


# Features need 60 sessions of history before they are defined.
FEATURE_START = 60

CAVEATS = [
    '验证只用当前在市的股票，已退市的股票不在里面，结果会偏乐观（幸存者偏差）。',
    '只看最近约一年，换一种市场环境结果可能不同。',
    '按次日开盘买、第5个交易日收盘卖、等权计算；次日一字涨停买不进的已剔除；成本按往返约0.2%估计。',
    '这些是研究候选，不是买卖建议。',
]

__all__ = ['RULES', 'screen_candidates', 'CAVEATS', 'HOLD_SESSIONS', 'ROUND_TRIP_COST']
