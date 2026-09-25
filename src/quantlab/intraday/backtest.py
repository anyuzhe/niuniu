"""Run a 底仓做T strategy over the gst_intraday stocks and keep the result."""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from quantlab.intraday.strategies import STRATEGIES, STRATEGY_CONFIG
from quantlab.intraday.t0 import T0Config, run_day, summarize, verdict

DEFAULT_SPLIT = '2022-12-31'  # 2019-05 .. 2022 to look at, 2023 .. 2024-10 to check
FORMAT = 'niuniu-intraday-t0-run-v1'


def config_for(strategy_key: str, config: T0Config | None = None) -> T0Config:
    config = config or T0Config()
    override = STRATEGY_CONFIG.get(strategy_key)
    if override:
        value = config.to_dict()
        value.update({k: ([list(w) for w in v] if k == 'windows' else v) for k, v in override.items()})
        config = T0Config.from_dict(value)
    return config


def run_backtest(reader, strategy_key: str, *, params=None, config: T0Config | None = None, symbols=None,
                 start=None, end=None, split=DEFAULT_SPLIT, progress=None, stop=None) -> dict:
    if strategy_key not in STRATEGIES:
        raise ValueError(f'未知策略 {strategy_key}')
    strategy = STRATEGIES[strategy_key]
    params = {**strategy.params, **(params or {})}
    config = config_for(strategy_key, config)
    stocks = reader.stocks()
    wanted = [s['symbol'] for s in stocks if not symbols or s['symbol'] in symbols]
    days, trips = [], []
    started = time.monotonic()
    for index, symbol in enumerate(wanted):
        if stop is not None and stop.is_set():
            raise RuntimeError('已停止')
        for day in reader.days(symbol, start, end):
            record, day_trips = run_day(day, strategy, params, config)
            days.append(record)
            trips.extend(day_trips)
        if progress:
            progress(index + 1, len(wanted), symbol)
    split = split or DEFAULT_SPLIT
    parts = {
        'all': (days, trips),
        'train': ([d for d in days if d['date'] <= split], [t for t in trips if t['date'] <= split]),
        'test': ([d for d in days if d['date'] > split], [t for t in trips if t['date'] > split]),
    }
    summary = {}
    for key, (d, t) in parts.items():
        stats = summarize(d, t)
        stats['verdict'] = verdict(stats)
        summary[key] = stats
    per_symbol = []
    names = {s['symbol']: s['name'] for s in stocks}
    for symbol in wanted:
        stats = summarize([d for d in days if d['symbol'] == symbol], [t for t in trips if t['symbol'] == symbol])
        stats.pop('curve', None)
        per_symbol.append({'symbol': symbol, 'name': names.get(symbol, symbol), **stats})
    per_year = []
    for year in sorted({d['date'][:4] for d in days}):
        stats = summarize([d for d in days if d['date'][:4] == year], [t for t in trips if t['date'][:4] == year])
        stats.pop('curve', None)
        per_year.append({'year': year, **stats})
    return {
        'format': FORMAT, 'strategy': strategy_key, 'strategy_name': strategy.name, 'params': params,
        'config': config.to_dict(), 'symbols': wanted, 'start': start and str(start), 'end': end and str(end),
        'split': split, 'created_at': datetime.now(timezone.utc).isoformat(),
        'seconds': round(time.monotonic() - started, 1),
        'summary': summary, 'per_symbol': per_symbol, 'per_year': per_year, 'days': days, 'trips': trips,
    }


def runs_root(output) -> Path:
    return Path(output).resolve() / '_intraday' / 'runs'


def save_run(output, result: dict) -> str:
    root = runs_root(output)
    if root.parent.is_symlink() or root.is_symlink():
        raise ValueError('输出目录不能是符号链接')
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    result = {**result, 'run_id': run_id}
    path = root / f'{run_id}.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return run_id


def list_runs(output, limit=30) -> list[dict]:
    root = runs_root(output)
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob('*.json'), reverse=True)[:limit]:
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        rows.append({'run_id': value.get('run_id', path.stem), 'strategy_name': value.get('strategy_name'),
                     'created_at': value.get('created_at'), 'params': value.get('params'),
                     'summary': {k: {x: v.get(x) for x in ('portfolio_mean_bps', 't_stat', 'trips', 'verdict')}
                                 for k, v in value.get('summary', {}).items()}})
    return rows


def load_run(output, run_id: str) -> dict:
    if not run_id or '/' in run_id or '..' in run_id:
        raise ValueError('run_id 无效')
    return json.loads((runs_root(output) / f'{run_id}.json').read_text(encoding='utf-8'))


__all__ = ['run_backtest', 'save_run', 'list_runs', 'load_run', 'config_for', 'DEFAULT_SPLIT']
