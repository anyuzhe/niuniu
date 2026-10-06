"""前向跟踪记录：从现在起，每个出现闸门信号的交易日把“当天挑出的股票”冻结记下来，之后用真实后续行情结算。

  * 记录只能记面板最后一个交易日的信号，不能事后补记（补记等于带着结果挑日子）；
  * 记录里冻结了参数和哈希，已经有记录时不允许悄悄改参数，要改先清空；
  * 结算只用面板里的真实价格（次日开盘买、第 hold_days 日收盘卖，同一套成本）；已经结算完成的记录把结果写回，
    以后数据口径变了也不会改写历史；
  * 这是纸面记录，不下单、不连券商。
存放在 <output>/_home/dip_forward.json，先写 .tmp 再替换，拒绝符号链接。
"""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from quantlab.dipbuy.engine import DipConfig, settle_picks, simulate, summarize, compute_features
from quantlab.dipbuy.panel import Panel

FORMAT = 'niuniu-dip-forward-v1'
LEDGER_FILES = {'market': 'dip_forward.json', 'industry': 'dip_industry_forward.json', 'fusion': 'dip_fusion_forward.json'}   # 大盘恐慌 / 行业恐慌 / 策略 D，各记各的
MAX_RECORDS = 500
MIN_STATS = 5     # 少于这么多条已结算信号，只给数字，不下结论


def _path(output, kind: str = 'market') -> Path:
    if kind not in LEDGER_FILES:
        raise ValueError('记录类型不认识')
    return Path(output).resolve() / '_home' / LEDGER_FILES[kind]


def load_ledger(output, kind: str = 'market') -> dict:
    path = _path(output, kind)
    empty = dict(format=FORMAT, config=None, config_hash=None, started_at=None, start_date=None, records=[])
    if not path.is_file() or path.is_symlink():
        return empty
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        return empty
    value['records'] = [r for r in value.get('records', []) if isinstance(r, dict) and r.get('id') and r.get('signal_date')]
    return value | {k: value.get(k) for k in ('config', 'config_hash', 'started_at', 'start_date')}


def _save(output, ledger: dict, kind: str = 'market') -> None:
    path = _path(output, kind)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('记录目录不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    tmp.replace(path)


def clear_ledger(output, kind: str = 'market') -> None:
    path = _path(output, kind)
    if path.is_file() and not path.is_symlink():
        path.unlink()


def record_signal(output, signal: dict, cfg: DipConfig, *, now: datetime | None = None, kind: str = 'market') -> dict:
    """signal 是 engine.latest_signal（行业恐慌用 industry.latest_industry_signal）的结果。成功返回记录；不满足条件抛 ValueError（给页面直接显示）。"""
    if not signal.get('is_last_day'):
        raise ValueError('只能记录数据里最后一个交易日的信号，不能事后补记')
    industry = kind == 'industry'
    fusion = kind == 'fusion'
    if not signal.get('gate_open'):
        raise ValueError('今天三层闸门都没开，没有可记录的开仓信号' if fusion else
                         '今天没有行业触发恐慌线，没有可记录的开仓信号' if industry else '今天闸门没开（z 没低于阈值），没有可记录的开仓信号')
    if not signal.get('picks'):
        raise ValueError('有闸门开了，但今天没有可买的股票' if fusion else
                         '有行业触发了，但触发行业里今天没有可买的股票' if industry else '闸门开了，但今天没有符合“布林下轨收复”的股票')
    ledger = load_ledger(output, kind)
    if ledger['records'] and ledger.get('config_hash') != cfg.hash():
        raise ValueError('已有前向记录，参数已冻结；要换参数请先清空记录')
    if any(r['signal_date'] == signal['date'] for r in ledger['records']):
        raise ValueError(f'{signal["date"]} 的信号已经记录过了')
    if len(ledger['records']) >= MAX_RECORDS:
        raise ValueError('记录条数已到上限')
    when = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    if not ledger.get('config_hash'):
        ledger.update(config=cfg.to_dict(), config_hash=cfg.hash(), started_at=when, start_date=signal['date'])
    keys = ('rank', 'code', 'name', 'close', 'ret20') + (('industry',) if industry else ()) + (('sleeve', 'weight', 'group') if fusion else ())
    record = dict(id=uuid.uuid4().hex[:10], signal_date=signal['date'], recorded_at=when, data_last_date=signal['date'],
                  z=signal['z'], mk20=signal['mk20'], n_e6=signal['n_e6'], status='waiting', result=None,
                  picks=[{k: p.get(k) for k in keys} for p in signal['picks']])
    if industry:
        record['industries'] = list(signal.get('triggered') or [])
    if fusion:
        record['fired'] = list(signal.get('fired') or [])
    ledger['records'].append(record)
    _save(output, ledger, kind)
    return record


def _evaluate(panel: Panel, record: dict, cfg: DipConfig) -> dict:
    """取前 N 个“买得进”的，算每只的结果和合计。"""
    rows = settle_picks(panel, record['picks'], record['signal_date'], cfg)
    filled, taken = [], {}
    for r in rows:        # 策略 D 的记录里每层各取前 positions 只买得进的；其它记录没有 sleeve 字段，等于整体取前 positions 只
        if r['not_filled'] or taken.get(r.get('sleeve'), 0) >= cfg.positions:
            continue
        taken[r.get('sleeve')] = taken.get(r.get('sleeve'), 0) + 1
        filled.append(r)
    closed = [r for r in filled if r['status'] == 'closed']
    done = bool(filled) and len(closed) == len(filled)
    rets = [r['ret'] for r in closed]
    weight = lambda r: r.get('weight') or 1.0
    mtm_rows = [r for r in filled if r['status'] == 'closed' or r['mtm'] is not None]
    mtm = [r['ret'] if r['status'] == 'closed' else r['mtm'] for r in mtm_rows]
    status = 'closed' if done else ('open' if filled and any(r['status'] != 'waiting' for r in filled) else 'waiting')
    plan_codes = {r['code'] for r in filled}
    for r in rows:
        r['in_plan'] = r['code'] in plan_codes
    return dict(status=status, rows=rows, n_filled=len(filled), n_closed=len(closed),
                mean_ret=(sum(weight(r) * r['ret'] for r in closed) / sum(weight(r) for r in closed)) if rets else None,
                mean_mtm=(sum(weight(r) * m for r, m in zip(mtm_rows, mtm)) / sum(weight(r) for r in mtm_rows)) if mtm else None,
                win_rate=(sum(1 for x in rets if x > 0) / len(rets)) if rets else None)


def settle_ledger(output, panel: Panel, cfg: DipConfig | None = None, kind: str = 'market') -> dict:
    """按最新面板结算所有记录；完成的记录写回。返回 {ledger, records(含明细), summary}。"""
    ledger = load_ledger(output, kind)
    cfg = DipConfig.from_dict(ledger['config']) if ledger.get('config') else (cfg or DipConfig())
    out = []
    changed = False
    for record in ledger['records']:
        if record.get('status') == 'closed' and record.get('result'):
            out.append(dict(record))
            continue
        ev = _evaluate(panel, record, cfg)
        shown = dict(record, status=ev['status'], result=ev)
        if ev['status'] == 'closed':
            record['status'] = 'closed'
            record['result'] = ev
            changed = True
        out.append(shown)
    if changed:
        _save(output, ledger, kind)
    return dict(ledger=ledger, records=out, summary=summarize_records(out))


def summarize_records(records: list[dict]) -> dict:
    done = [r for r in records if r.get('status') == 'closed' and r.get('result')]
    means = [r['result']['mean_ret'] for r in done if r['result'].get('mean_ret') is not None]
    all_rets = [x['ret'] for r in done for x in r['result']['rows'] if x.get('in_plan') and x.get('ret') is not None]
    cum = 1.0
    for m in means:
        cum *= 1 + m
    return dict(n_records=len(records), n_closed=len(done), enough=len(done) >= MIN_STATS,
                mean_signal_ret=(sum(means) / len(means)) if means else None,
                signal_win_rate=(sum(1 for m in means if m > 0) / len(means)) if means else None,
                pick_win_rate=(sum(1 for x in all_rets if x > 0) / len(all_rets)) if all_rets else None,
                n_picks=len(all_rets), compounded=(cum - 1) if means else None,
                note=None if len(done) >= MIN_STATS else f'已结算的信号只有 {len(done)} 条（至少 {MIN_STATS} 条才有参考意义），数字只当记录看')


def forward_portfolio(output, panel: Panel, kind: str = 'market', features=None) -> dict | None:
    """用冻结的参数，从记录开始日起在真实数据上跑一遍组合（含杠杆和借款利息），给出前向净值。没有记录返回 None。
    features(cfg) -> (Market, Candidates)：行业恐慌传入自己的闸门与候选；缺省走大盘恐慌的特征。"""
    ledger = load_ledger(output, kind)
    if not ledger.get('config') or not ledger.get('start_date'):
        return None
    if int(panel.index_of(ledger['start_date'])) >= len(panel.dates) - 1:
        return None          # 记录日就是最新一天，还没有后续行情
    cfg = replace(DipConfig.from_dict(ledger['config']), start=ledger['start_date'], end=None)
    market, cand = features(cfg) if features else compute_features(panel, cfg.min_amount, cfg.min_price)
    raw = simulate(panel, market, cand, cfg)
    summary = summarize(panel, market, raw, cfg)
    codes_by_day: dict[str, set] = {}
    for t in raw['trades']:
        codes_by_day.setdefault(t['signal'], set()).add(t['code'])
    for p in raw['open_positions']:
        codes_by_day.setdefault(p['signal'], set()).add(p['code'])
    mismatched = []
    for record in ledger['records']:
        recorded = {p['code'] for p in record['picks']}
        extra = sorted(codes_by_day.get(record['signal_date'], set()) - recorded)
        if extra:
            mismatched.append(dict(date=record['signal_date'], extra=extra))
    eq = [None if not math.isfinite(v) else round(float(v), 5) for v in raw['eq'][raw['t0']:raw['tend'] + 1]]
    return dict(start_date=ledger['start_date'], dates=[str(d) for d in panel.dates[raw['t0']:raw['tend'] + 1]], equity=eq,
                summary=summary, mismatched=mismatched, trades=raw['trades'], open_positions=raw['open_positions'])
