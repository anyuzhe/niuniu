"""复盘验证: save a judgment about a stock, then check it against later daily bars.

A judgment is what the user (or the AI, recorded by the user) concluded after a
session's close: 看多 / 观望 / 看空, a horizon of 5/10/20 sessions, and optionally a
失效价 (the close that would prove it wrong) and a 目标价. Stored in
<output>/_home/judgments.json; nothing is sent anywhere.

Checking uses only DATA-READY adjusted daily bars (qfq_published_f24):
- returns run from the close of the judgment day to the close N sessions later
  (adjusted prices, so dividends and splits are not counted as moves);
- 失效价 / 目标价 are compared with the actual (unadjusted) close of each session,
  so they mean the same numbers the user saw; the first one reached ends the check;
- the benchmark is the equal-weight average of all tradable stocks, from the market
  overview's per-session series.
A finished check is written back into the record, so later data changes or a
shorter overview window cannot rewrite history.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from quantlab.trading.stock_report import _optional_path, normalize_code

FORMAT = 'niuniu-judgments-v1'
STANCES = {'bullish': '看多', 'neutral': '观望', 'bearish': '看空'}
SOURCES = {'me': '我的判断', 'ai': 'AI 的判断', 'kol': '大V观点'}
HORIZONS = (1, 3, 5, 10, 20)
MARKET = 'market'    # a view on the whole market: checked against the equal-weight market series
FLAT = 0.01          # an aligned move smaller than ±1% counts as 持平
MAX_JUDGMENTS = 2000
MIN_STATS = 10       # fewer finished judgments than this: say the rate means little
VERDICTS = {'right': '判断正确', 'wrong': '判断错误', 'flat': '基本持平', 'none': '观望不计对错'}


def _path(output) -> Path:
    return Path(output).resolve() / '_home' / 'judgments.json'


def load_judgments(output) -> list[dict]:
    path = _path(output)
    if not path.is_file() or path.is_symlink():
        return []
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    items = value.get('judgments', []) if isinstance(value, dict) else []
    return [i for i in items if isinstance(i, dict) and i.get('id')
            and (i.get('code') == MARKET or normalize_code(i.get('code', '')))
            and i.get('stance') in STANCES and i.get('horizon') in HORIZONS]


def _save(output, items):
    path = _path(output)
    if path.parent.is_symlink():
        raise ValueError('_home 不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'format': FORMAT, 'judgments': items}, ensure_ascii=False, indent=1),
                         encoding='utf-8')
    temporary.replace(path)


def _positive(value, name):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name}须为正数')
    return float(value)


def make_judgment(*, code, made_on, close, stance, horizon, name='', source='me', stop=None, target=None,
                  reason='', author='', post_id=None, now=None) -> dict:
    """Validate one judgment. `close` is the actual close on `made_on` that the user saw."""
    code = MARKET if code == MARKET else normalize_code(code or '')
    if code is None:
        raise ValueError('股票代码无效')
    day = date.fromisoformat(made_on).isoformat()
    if stance not in STANCES:
        raise ValueError('判断须为 看多 / 观望 / 看空')
    if horizon not in HORIZONS:
        raise ValueError('核对周期须为 ' + '、'.join(map(str, HORIZONS)) + ' 个交易日之一')
    if source not in SOURCES:
        raise ValueError('来源须为 ' + ' / '.join(SOURCES.values()))
    stop, target = _positive(stop, '失效价'), _positive(target, '目标价')
    if code == MARKET:
        if stop or target:
            raise ValueError('大盘判断不设失效价和目标价')
        close = None
    else:
        close = _positive(close, '收盘价')
        if close is None:
            raise ValueError('缺少判断日收盘价')
    if stance == 'bullish' and ((stop and stop >= close) or (target and target <= close)):
        raise ValueError('看多时失效价应低于、目标价应高于当前收盘价')
    if stance == 'bearish' and ((stop and stop <= close) or (target and target >= close)):
        raise ValueError('看空时失效价应高于、目标价应低于当前收盘价')
    if stance == 'neutral' and (stop or target):
        raise ValueError('观望不设失效价和目标价')
    return {'id': f"{day}-{code.replace('.', '')}-{uuid.uuid4().hex[:6]}", 'code': code,
            'name': '大盘' if code == MARKET else (name or ''), 'made_on': day,
            'close': None if close is None else round(close, 4), 'stance': stance, 'horizon': horizon,
            'source': source, 'stop': stop, 'target': target, 'reason': (reason or '').strip()[:500],
            'author': (author or '').strip()[:60], 'post_id': post_id,
            'created_at': (now or datetime.now(timezone.utc)).isoformat(), 'result': None}


def add_judgments(output, records, *, replace_post=None) -> list[dict]:
    """Append validated records; `replace_post` first drops that post's earlier judgments."""
    items = [i for i in load_judgments(output) if replace_post is None or i.get('post_id') != replace_post]
    if len(items) + len(records) > MAX_JUDGMENTS:
        raise ValueError(f'最多保存 {MAX_JUDGMENTS} 条判断')
    items.extend(records)
    _save(output, items)
    return records


def save_judgment(output, **kwargs) -> dict:
    return add_judgments(output, [make_judgment(**kwargs)])[0]


def delete_judgment(output, judgment_id) -> bool:
    items = load_judgments(output)
    kept = [i for i in items if i['id'] != judgment_id]
    if len(kept) == len(items):
        return False
    _save(output, kept)
    return True


def _aligned(stance, value):
    if value is None or stance == 'neutral':
        return None
    return value if stance == 'bullish' else -value


def evaluate(judgment: dict, bars: list[dict], market: dict | None, last_day: date) -> dict:
    """Check one judgment against bars (dicts with date, close [adjusted], close_raw).

    `market` maps session date -> equal-weight average return, or None when unknown.
    Only sessions up to `last_day` are used.
    """
    made_on = date.fromisoformat(judgment['made_on'])
    stance, horizon = judgment['stance'], judgment['horizon']
    bars = [b for b in bars if b['date'] <= last_day]
    base = [b for b in bars if b['date'] <= made_on]
    if not base:
        return {'status': 'unavailable', 'text': '没有判断日及之前的日线，无法核对。'}
    base = base[-1]
    if market:
        sessions = sorted(d for d in market if made_on < d <= last_day)
    else:
        sessions = [b['date'] for b in bars if b['date'] > made_on]
    window = sessions[:horizon]
    if not window:
        return {'status': 'waiting', 'sessions_done': 0, 'horizon': horizon,
                'text': f'判断日之后还没有新的交易日数据（数据截至 {last_day}）。'}
    by_day = {b['date']: b for b in bars}
    trigger, final = None, window[-1]
    for day in window:
        bar = by_day.get(day)
        if bar is None:
            continue  # suspended that session
        raw = bar['close_raw']
        stop, target = judgment.get('stop'), judgment.get('target')
        if stance == 'bullish':
            hit = 'stop' if stop and raw <= stop else 'target' if target and raw >= target else None
        elif stance == 'bearish':
            hit = 'stop' if stop and raw >= stop else 'target' if target and raw <= target else None
        else:
            hit = None
        if hit:
            trigger, final = {'kind': hit, 'date': day.isoformat(), 'close': round(raw, 4)}, day
            break
    held = [d for d in window if d <= final]
    last_bar = [b for b in bars if b['date'] <= final][-1]
    ret = last_bar['close'] / base['close'] - 1
    closes = [by_day[d]['close'] for d in held if d in by_day]
    worst = min((_aligned(stance, c / base['close'] - 1) for c in closes), default=None) if stance != 'neutral' else None
    mkt = None
    if market and all(market.get(d) is not None for d in held):
        mkt = math.prod(1 + market[d] for d in held) - 1
    done = trigger is not None or len(window) == horizon
    result = {
        'status': 'done' if done else 'running', 'sessions_done': len(held), 'horizon': horizon,
        'end_day': final.isoformat(), 'return': round(ret, 5), 'market': None if mkt is None else round(mkt, 5),
        'excess': None if mkt is None else round(ret - mkt, 5),
        'aligned': None if _aligned(stance, ret) is None else round(_aligned(stance, ret), 5),
        'aligned_excess': None if mkt is None or stance == 'neutral' else round(_aligned(stance, ret - mkt), 5),
        'worst': None if worst is None else round(worst, 5), 'trigger': trigger, 'verdict': None,
    }
    if done:
        if stance == 'neutral':
            verdict = 'none'
        elif trigger:
            verdict = 'right' if trigger['kind'] == 'target' else 'wrong'
        else:
            verdict = 'right' if result['aligned'] > FLAT else 'wrong' if result['aligned'] < -FLAT else 'flat'
        result['verdict'] = verdict
    result['text'] = _text(judgment, result)
    return result


def _p(value):
    return '—' if value is None else f'{value * 100:+.1f}%'


def _text(judgment, r):
    parts = [f"{r['sessions_done']}/{r['horizon']} 个交易日，截至 {r['end_day']} 涨跌 {_p(r['return'])}"]
    if r['market'] is not None:
        parts.append(f"同期全市场平均 {_p(r['market'])}")
    if r['trigger']:
        kind = '失效价' if r['trigger']['kind'] == 'stop' else '目标价'
        parts.append(f"{r['trigger']['date']} 收盘 {r['trigger']['close']:.2f} 触及{kind}")
    text = '，'.join(parts) + '。'
    if r['verdict']:
        text = VERDICTS[r['verdict']] + '：' + text
    return text


def _bars(folder: Path | None, code: str, start: date) -> list[dict]:
    if folder is None:
        return []
    path = folder / f"{code.replace('.', '_')}.parquet"
    if not path.is_file():
        return []
    frame = (pl.read_parquet(path, columns=['date', 'close', 'factor']).filter(pl.col('date') >= start)
             .sort('date').with_columns((pl.col('close') / pl.col('factor')).alias('close_raw')))
    return frame.select('date', 'close', 'close_raw').to_dicts()


def _market_bars(market: dict | None) -> list[dict]:
    """The equal-weight market series as an index, so market views use the same checks."""
    level, bars = 1.0, []
    for day in sorted(market or {}):
        level *= 1 + (market[day] or 0.0)
        bars.append({'date': day, 'close': level, 'close_raw': level})
    return bars


def _stats(rows: list[dict]) -> dict:
    finished = [r for r in rows if (r['result'] or {}).get('verdict') in ('right', 'wrong', 'flat')]
    n = len(finished)
    right = sum(r['result']['verdict'] == 'right' for r in finished)
    wrong = sum(r['result']['verdict'] == 'wrong' for r in finished)

    def mean(key):
        values = [r['result'][key] for r in finished if r['result'].get(key) is not None]
        return round(sum(values) / len(values), 5) if values else None

    return {'finished': n, 'right': right, 'wrong': wrong, 'flat': n - right - wrong,
            'hit_rate': round(right / n, 3) if n else None, 'avg_aligned': mean('aligned'),
            'avg_aligned_excess': mean('aligned_excess')}


def summarize(rows: list[dict]) -> dict:
    groups = {}
    authors = {r.get('author'): r.get('author') for r in rows if r.get('author')}
    for key, labels in (('source', SOURCES), ('stance', STANCES), ('horizon', {h: f'{h}日' for h in HORIZONS}),
                        ('author', authors)):
        groups[key] = [{'key': k, 'label': v, **_stats([r for r in rows if r.get(key) == k])}
                       for k, v in labels.items() if any(r.get(key) == k for r in rows)]
    overall = _stats(rows)
    status = {s: sum((r['result'] or {}).get('status') == s for r in rows) for s in ('running', 'waiting', 'unavailable')}
    notes = []
    if overall['finished'] < MIN_STATS:
        notes.append(f"已完成核对的看多/看空判断只有 {overall['finished']} 条，准确率参考意义有限（至少积累 {MIN_STATS} 条再看）。")
    notes.append('“顺向收益”：看多按涨跌计，看空按涨跌取反；“顺向超额”再减去同期全市场等权平均。')
    return {'overall': overall, 'groups': groups, 'pending': status, 'total': len(rows), 'notes': notes}


def review_judgments(output, catalog_path=None) -> dict:
    """Check every saved judgment; finished checks are frozen into the store."""
    from quantlab.trading.market_overview import latest_overview
    items = load_judgments(output)
    overview = latest_overview(output)
    market = None
    if overview and overview.get('market_returns'):
        market = {date.fromisoformat(r['date']): r['mean_pct'] for r in overview['market_returns']}
    folder = _optional_path(catalog_path, 'qfq_published_f24')
    last_day = date.fromisoformat(overview['trading_day']) if overview else None
    cache, changed, rows = {}, False, []
    for item in items:
        result = item.get('result')
        if not (isinstance(result, dict) and result.get('status') == 'done'):
            code, made_on = item['code'], date.fromisoformat(item['made_on'])
            if code not in cache:
                starts = [date.fromisoformat(i['made_on']) for i in items if i['code'] == code]
                cache[code] = (_market_bars(market) if code == MARKET
                               else _bars(folder, code, min(starts) - timedelta(days=30)))
            bars = cache[code]
            end = last_day or (bars[-1]['date'] if bars else made_on)
            if code == MARKET:
                # The market is its own benchmark: no excess.
                result = (evaluate(item, bars, None, end) if market and min(market) <= made_on else
                          {'status': 'unavailable', 'text': '市场总览里没有覆盖判断日的全市场序列，无法核对大盘判断。'})
                if result['status'] == 'done':
                    item['result'] = {**result, 'checked_at': datetime.now(timezone.utc).isoformat()}
                    changed = True
            elif folder is None:
                result = {'status': 'unavailable', 'text': '数据清单里没有可用的前复权日线，无法核对。'}
            else:
                # The benchmark only counts when the series covers the whole window.
                usable = market if market and min(market) <= made_on else None
                result = evaluate(item, bars, usable, end)
                if result['status'] == 'done':
                    item['result'] = {**result, 'checked_at': datetime.now(timezone.utc).isoformat()}
                    changed = True
        rows.append({**item, 'result': result})
    if changed:
        _save(output, items)
    rows.sort(key=lambda r: (r['made_on'], r.get('created_at', '')), reverse=True)
    return {'trading_day': overview['trading_day'] if overview else None, 'rows': rows, 'stats': summarize(rows)}


def judgments_prompt(review: dict) -> str:
    s = review['stats']['overall']
    lines = [f"请帮我复盘我保存过的判断（数据截至 {review['trading_day']} 收盘）。"]
    if s['finished']:
        lines.append(f"已完成核对 {s['finished']} 条：正确 {s['right']}、错误 {s['wrong']}、持平 {s['flat']}，"
                     f"准确率 {s['hit_rate'] * 100:.0f}%，平均顺向收益 {_p(s['avg_aligned'])}，平均顺向超额 {_p(s['avg_aligned_excess'])}。")
    for g in review['stats']['groups']['source']:
        if g['finished']:
            lines.append(f"{g['label']}：{g['finished']} 条，准确率 {g['hit_rate'] * 100:.0f}%，平均顺向超额 {_p(g['avg_aligned_excess'])}。")
    for r in review['rows'][:15]:
        who = f"{r['author']}，" if r.get('author') else ''
        lines.append(f"- {r['made_on']} {r['name'] or r['code']} {STANCES[r['stance']]}（{who}{SOURCES[r['source']]}，{r['horizon']}日）"
                     + (f"理由：{r['reason']}；" if r['reason'] else '') + (r['result'] or {}).get('text', ''))
    lines.append('请指出我的判断在哪类情况下更准、哪类情况下常错，失效价设置是否合理，以及样本量是否足以下结论。')
    return '\n'.join(lines)


__all__ = ['STANCES', 'SOURCES', 'HORIZONS', 'VERDICTS', 'MARKET', 'load_judgments', 'make_judgment', 'add_judgments',
           'save_judgment', 'delete_judgment',
           'evaluate', 'summarize', 'review_judgments', 'judgments_prompt']
