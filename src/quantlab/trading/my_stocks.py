"""我的股票: a small local watchlist/holdings list and its daily check.

Stored in <output>/_home/my_stocks.json. Position weights and costs are optional
and only used for concentration and P&L hints; nothing is sent anywhere.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from quantlab.trading.market_overview import latest_stocks
from quantlab.trading.stock_report import _events, _flags, normalize_code

FORMAT = 'niuniu-my-stocks-v1'
MAX_STOCKS = 50


def _path(output) -> Path:
    return Path(output).resolve() / '_home' / 'my_stocks.json'


def load_my_stocks(output) -> list[dict]:
    path = _path(output)
    if not path.is_file() or path.is_symlink():
        return []
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    items = value.get('stocks', []) if isinstance(value, dict) else []
    return [i for i in items if isinstance(i, dict) and normalize_code(i.get('code', ''))]


def _save(output, items):
    path = _path(output)
    if path.parent.is_symlink():
        raise ValueError('_home 不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'format': FORMAT, 'stocks': items}, ensure_ascii=False, indent=1),
                         encoding='utf-8')
    temporary.replace(path)


def add_stock(output, code, *, weight=None, cost=None, note=''):
    code = normalize_code(code)
    if code is None:
        raise ValueError('股票代码无效')
    if weight is not None and not (isinstance(weight, (int, float)) and 0 <= weight <= 1):
        raise ValueError('仓位比例须在 0–100% 之间')
    if cost is not None and not (isinstance(cost, (int, float)) and cost > 0):
        raise ValueError('成本价须为正数')
    items = [i for i in load_my_stocks(output) if i['code'] != code]
    if len(items) >= MAX_STOCKS:
        raise ValueError(f'最多 {MAX_STOCKS} 只')
    total = sum(i.get('weight') or 0 for i in items) + (weight or 0)
    if total > 1 + 1e-9:
        raise ValueError('仓位合计超过 100%')
    items.append({'code': code, 'weight': weight, 'cost': cost, 'note': note[:200],
                  'added_at': datetime.now(timezone.utc).isoformat()})
    _save(output, items)
    return items


def remove_stock(output, code):
    code = normalize_code(code)
    items = [i for i in load_my_stocks(output) if i['code'] != code]
    _save(output, items)
    return items


def inspect_my_stocks(output, catalog_path=None) -> dict:
    items = load_my_stocks(output)
    overview, stocks = latest_stocks(output)
    if not items:
        return {'trading_day': overview['trading_day'] if overview else None, 'rows': [], 'industries': [],
                'notes': []}
    if overview is None or stocks is None:
        raise ValueError('还没有今日市场数据，请先打开“今日市场”生成一次。')
    from datetime import date
    day = date.fromisoformat(overview['trading_day'])
    facts = {r['code']: r for r in stocks.filter(pl.col('code').is_in([i['code'] for i in items])).iter_rows(named=True)}
    rows, exposure = [], defaultdict(float)
    for item in items:
        row = facts.get(item['code'])
        if row is None:
            rows.append({**item, 'name': None, 'missing': True, 'flags': ['不在当天的在市A股数据里（可能已退市或代码有误）。']})
            continue
        flags = _flags(row, _events(catalog_path, item['code'], day))
        pnl = row['close'] / item['cost'] - 1 if item.get('cost') else None
        rows.append({**item, 'name': row['name'], 'industry': row['industry'], 'close': row['close'],
                     'pct': row['pct'], 'ret5': row['ret5'], 'ret20': row['ret20'], 'rank20': row['rank20'],
                     'ma20_gap': row['ma20_gap'], 'pnl': pnl, 'flags': flags, 'missing': False})
        if item.get('weight'):
            exposure[row['industry'] or '未分类'] += item['weight']
    total = sum(exposure.values())
    industries = sorted(({'industry': k, 'weight': v} for k, v in exposure.items()), key=lambda x: -x['weight'])
    notes = []
    if total:
        notes.append(f'已填仓位合计 {total * 100:.0f}%，其余视为现金。')
        if industries and industries[0]['weight'] / total >= 0.5:
            notes.append(f"一半以上仓位集中在“{industries[0]['industry']}”。")
    flagged = sum(bool(r['flags']) for r in rows)
    if flagged:
        notes.append(f'{flagged} 只股票有需要留意的情况。')
    return {'trading_day': overview['trading_day'], 'rows': rows, 'industries': industries, 'notes': notes}


def my_stocks_prompt(result: dict) -> str:
    lines = [f"请帮我巡检我的股票（数据截至 {result['trading_day']} 收盘）："]
    for r in result['rows']:
        if r.get('missing'):
            continue
        weight = f"，仓位 {r['weight'] * 100:.0f}%" if r.get('weight') else ''
        lines.append(f"- {r['name']}（{r['code']}）{r['industry'] or ''}：今日 {(r['pct'] or 0) * 100:+.1f}%，"
                     f"近20日 {(r['ret20'] or 0) * 100:+.1f}%{weight}。" + (' 留意：' + ' '.join(r['flags']) if r['flags'] else ''))
    lines.extend(result['notes'])
    lines.append('请逐只给出状态、需要观察的条件和失效条件，再说整体的集中度和风险；不要给出确定的买卖指令。')
    return '\n'.join(lines)


__all__ = ['load_my_stocks', 'add_stock', 'remove_stock', 'inspect_my_stocks', 'my_stocks_prompt']
