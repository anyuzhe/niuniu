"""每个交易日自动记录前向信号：牛牛开着、数据多了新的一天，就把当天的信号记进前向跟踪（纸面记录，不下单）。

  * 记四本：策略 D、D1、A（大盘恐慌）、B（行业恐慌），各记各的台账；闸门没开或没有候选就不记；
  * 规则和手动记录完全一样：只记面板最后一个交易日、参数冻结、同一天不重复；
  * 再加一条：数据必须还“新鲜”——过了下一个交易日 9:30，就不再自动记（那时已经知道开盘价，补记等于带着结果挑日子）；
    下一个交易日按“周一至周五，扣掉已知的休市日（见 KNOWN_CLOSURES）和每年 1 月 1 日”估算；
    不在清单里的节假日会被当成交易日——结果是把窗口算短，宁可少记也不补记；
  * 只在源数据指纹变化时才做一次（读指纹只 stat 文件），所以每天最多算一次；开关和上次结果存在 <output>/_home/dip_autorecord.json。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


from quantlab.dipbuy import engine, fusion, industry, panel as dpanel, tracker

STATE_FORMAT = 'niuniu-dip-autorecord-v1'
KINDS = ('fusion', 'fusion1', 'market', 'industry')
LABELS = {'fusion': '策略 D', 'fusion1': '策略 D1', 'market': '策略 A（大盘恐慌）', 'industry': '策略 B（行业恐慌）'}
SHANGHAI = timezone(timedelta(hours=8))
OPEN_TIME = time(9, 30)
# 已公告的休市日（只列周一至周五）。数据湖里的交易日历只到已采集的最后一天，没有未来的日期，所以未来的休市日要在这里补；
# 每次国务院公布新一年的放假安排后追加。来源：沪深北三大交易所 2026 年国庆休市公告（10 月 1 日至 7 日休市，10 月 8 日起开市）。
KNOWN_CLOSURES = frozenset(date(2026, 10, d) for d in (1, 2, 5, 6, 7))


def _path(output) -> Path:
    return Path(output).resolve() / '_home' / 'dip_autorecord.json'


def load_state(output) -> dict:
    empty = dict(format=STATE_FORMAT, enabled=True, last_signature=None, last=None)
    path = _path(output)
    if not path.is_file() or path.is_symlink():
        return empty
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty
    if not isinstance(value, dict) or value.get('format') != STATE_FORMAT:
        return empty
    return dict(empty, enabled=bool(value.get('enabled', True)), last_signature=value.get('last_signature'),
                last=value.get('last') if isinstance(value.get('last'), dict) else None)


def save_state(output, state: dict) -> None:
    path = _path(output)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('记录目录不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(dict(state, format=STATE_FORMAT), ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    tmp.replace(path)


def set_enabled(output, enabled: bool) -> dict:
    state = load_state(output)
    state['enabled'] = bool(enabled)
    save_state(output, state)
    return state


def next_open_day(last_date: str) -> date:
    """数据最后一天之后的第一个开市日：跳过周末、已知休市日和 1 月 1 日。"""
    d = date.fromisoformat(str(last_date)[:10])
    for _ in range(40):                 # 最长的假期也不到 40 天；防止清单写错时死循环
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in KNOWN_CLOSURES and (d.month, d.day) != (1, 1):
            return d
    return d


def is_fresh(last_date: str, now: datetime) -> bool:
    """数据最后一天 T 的信号，次日开盘买入；now 还没到 T 之后第一个开市日的 9:30 才算新鲜。"""
    return now.astimezone(SHANGHAI) < datetime.combine(next_open_day(last_date), OPEN_TIME, tzinfo=SHANGHAI)


def build_signal(kind: str, panel, cls, names):
    """返回 (信号, 配置)；和页面里手动记录用的是同一套配置与函数。"""
    if kind in ('fusion', 'fusion1'):
        if cls is None:
            raise ValueError('没有行业分类，算不了策略 D / D1')
        cfg = fusion.default_config() if kind == 'fusion' else fusion.d1_config()
        inp = fusion.build_inputs(panel, cfg, cls)
        return fusion.latest_fusion_signal(panel, inp, cfg, names=names), cfg
    if kind == 'market':
        cfg = engine.DipConfig()
        market, cand = engine.compute_features(panel, cfg.min_amount, cfg.min_price)
        return engine.latest_signal(panel, market, cand, cfg, names=names), cfg
    if kind == 'industry':
        if cls is None:
            raise ValueError('没有行业分类，算不了行业恐慌')
        cfg = industry.default_config()
        return industry.latest_industry_signal(panel, cfg, cls, names=names), cfg
    raise ValueError('记录类型不认识')


def _record_one(output, kind, sig, cfg, now) -> dict:
    if not sig.get('gate_open'):
        return dict(status='closed', message='闸门没开，没有开仓信号')
    if not sig.get('picks'):
        return dict(status='no_picks', message='闸门开了，但没有可买的股票')
    try:
        record = tracker.record_signal(output, sig, cfg, now=now.astimezone(timezone.utc), kind=kind)
    except ValueError as exc:
        text = str(exc)
        return dict(status='exists' if '已经记录过' in text else 'skipped', message=text)
    return dict(status='recorded', n_picks=len(record['picks']), message=f"已记录 {len(record['picks'])} 只")


def record_latest(output, panel, cls, names, *, kinds=KINDS, now: datetime | None = None) -> dict:
    """按面板最后一个交易日记录各本台账，返回 {kind: {status, message}}。status：recorded / closed / no_picks / exists / skipped / stale / error。"""
    now = now or datetime.now(SHANGHAI)
    if not is_fresh(panel.last_date, now):
        text = f'数据只到 {panel.last_date}，已经过了下一个交易日开盘，不再自动记录（补记等于带着结果挑日子）'
        return {k: dict(status='stale', message=text) for k in kinds}
    out = {}
    for kind in kinds:
        try:
            sig, cfg = build_signal(kind, panel, cls, names)
            out[kind] = _record_one(output, kind, sig, cfg, now)
        except Exception as exc:      # 一本算不出来不影响其它几本
            out[kind] = dict(status='error', message=f'{type(exc).__name__}: {exc}')
    return out


def run_if_new(output, catalog_path=None, *, force=False, now: datetime | None = None, progress=None, stop=None, kinds=KINDS):
    """开着且数据指纹变了才做：读面板（有缓存就读缓存）→ 记录 → 存状态。数据没开放、没变、开关关着都返回 None。"""
    state = load_state(output)
    if not state['enabled'] and not force:
        return None
    try:
        *_, signature = dpanel.current_sources(catalog_path)
    except dpanel.DipDataError:
        return None
    if not force and state.get('last_signature') == signature:
        return None
    panel = dpanel.load_panel(output, catalog_path, progress=progress, stop=stop)
    names = dpanel.load_names(catalog_path)
    try:
        cls = industry.load_classification_for(panel, catalog_path)
    except Exception:
        cls = None
    now = now or datetime.now(SHANGHAI)
    results = record_latest(output, panel, cls, names, kinds=kinds, now=now)
    last = dict(checked_at=now.isoformat(timespec='seconds'), data_date=panel.last_date, results=results)
    state['last'] = last
    if not any(r['status'] == 'error' for r in results.values()):      # 有算不出来的，下次还会再试
        state['last_signature'] = signature
    save_state(output, state)
    return last


def describe_last(last: dict | None) -> str:
    """给页面显示的一句话。"""
    if not last:
        return '还没有自动检查过。'
    parts = []
    for kind in KINDS:
        r = (last.get('results') or {}).get(kind)
        if not r:
            continue
        word = {'recorded': f"已记录 {r.get('n_picks', 0)} 只", 'closed': '闸门没开', 'no_picks': '没有候选', 'exists': '已记过',
                'skipped': '没记（' + str(r.get('message', '')) + '）', 'stale': '数据过期没记', 'error': '出错'}.get(r['status'], r['status'])
        parts.append(f'{LABELS[kind]}：{word}')
    return f"上次检查 {str(last.get('checked_at', ''))[:16].replace('T', ' ')}，数据截至 {last.get('data_date')}。" + '；'.join(parts)
