"""回测一次，结果存成 JSON：<output>/_dipbuy/runs/<时间>-<6位>.json。含参数、面板指纹、引擎版本和内容哈希，
所以同一份数据同一组参数可以复算并对上；先写 .tmp 再替换，拒绝符号链接目录。"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from quantlab.dipbuy.engine import (ENGINE_VERSION, DipConfig, compute_features, curve, drawdown_series, simulate,
                                    summarize)
from quantlab.dipbuy.panel import Panel

RUN_FORMAT = 'niuniu-dipbuy-run-v1'
MAX_LIST = 30
RUN_ID = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{6}$')
CAVEATS = (
    '历史回测，不保证未来；样本只有约 45 段恐慌期（240 个信号日），参数是看过数据后选的。',
    '面板只含现存股票（幸存者偏差），2020 年以前退市的股票没有数据，收益可能被高估。',
    '没有模拟冲击成本与跌停卖不出；融资买入需要券商开通两融资格。',
    '融资利率按年代近似，闲置资金收益默认不计。',
)


def run_backtest(panel: Panel, cfg: DipConfig, *, progress=None, stop=None) -> dict:
    market, cand = compute_features(panel, cfg.min_amount, cfg.min_price, progress=progress, stop=stop)
    raw = simulate(panel, market, cand, cfg, progress=progress, stop=stop)
    summary = summarize(panel, market, raw, cfg)
    cv = curve(panel, market, raw)
    meta = panel.meta or {}
    result = dict(
        format=RUN_FORMAT, engine_version=ENGINE_VERSION, config=cfg.to_dict(), config_hash=cfg.hash(),
        panel={k: meta.get(k) for k in ('signature', 'first_date', 'last_date', 'n_stocks', 'n_days')} | {
            'last_date': panel.last_date, 'n_stocks': int(panel.shape[1]), 'n_days': int(panel.shape[0])},
        summary=summary, curve=cv, drawdown=drawdown_series(cv['equity']),
        trades=raw['trades'], caveats=list(CAVEATS))
    result['content_hash'] = content_hash(result)
    return result


def content_hash(result: dict) -> str:
    body = {k: result[k] for k in ('engine_version', 'config', 'panel', 'summary', 'trades') if k in result}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, default=float)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _runs_dir(output) -> Path:
    return Path(output).resolve() / '_dipbuy' / 'runs'


def save_run(output, result: dict) -> str:
    directory = _runs_dir(output)
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError('回测目录不能是符号链接')
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    run_id = f'{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
    body = dict(result, run_id=run_id, created_at=now.isoformat(timespec='seconds'))
    tmp = directory / f'{run_id}.json.tmp'
    tmp.write_text(json.dumps(body, ensure_ascii=False, default=float), encoding='utf-8')
    tmp.replace(directory / f'{run_id}.json')
    return run_id


def list_runs(output, limit: int = MAX_LIST) -> list[dict]:
    directory = _runs_dir(output)
    if not directory.is_dir() or directory.is_symlink():
        return []
    rows = []
    for path in sorted(directory.glob('*.json'), reverse=True)[:limit]:
        if path.is_symlink():
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            stats = value['summary']['stats'] or {}
            rows.append(dict(run_id=value['run_id'], created_at=value.get('created_at'), config=value['config'],
                             config_hash=value.get('config_hash'), cagr=stats.get('cagr'), sharpe=stats.get('sharpe'),
                             max_drawdown=stats.get('max_drawdown'), last_date=value['panel'].get('last_date')))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return rows


def load_run(output, run_id: str) -> dict:
    if not RUN_ID.match(str(run_id)):
        raise ValueError('回测编号格式不对')
    path = _runs_dir(output) / f'{run_id}.json'
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(run_id)
    return json.loads(path.read_text(encoding='utf-8'))
