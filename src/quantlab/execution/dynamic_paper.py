"""Event-sourced long-horizon paper account with an append-only dynamic universe.

Unlike ``PaperAccount`` this account may add symbols on later dates.  Sparse
portfolio target events are canonicalized into complete target snapshots over
all symbols ever observed; symbols that did not exist in an earlier target are
assigned zero weight.  Every update replays the deterministic execution engine
and requires the previously committed NAV/fill/rejection prefix to remain
byte-for-byte equivalent after canonical JSON encoding.

There is no broker connectivity and no live order submission in this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import fcntl
import math
import re

import polars as pl

from quantlab.execution.backtest import ExecutionConfig, OpenExecutionBacktester
from quantlab.execution.paper import engine_hash, frame
from quantlab.execution.rules import MarketRules
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest, encode

FORMAT = 'dynamic-paper-v1'
SYMBOL = re.compile(r'^(?:sh|sz|bj)\.\d{6}$')
MAX_BARS = 1_000_000
MAX_TARGET_EVENTS = 100_000


class DynamicPaperError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _aware(value, name='time'):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DynamicPaperError('INVALID_CLOCK', name + ' 必须是带时区 datetime。')
    return value


def _canonical_rows(value):
    return __import__('json').loads(encode(value))


def _engine_identity():
    return digest({'paper_engine': engine_hash(), 'dynamic_paper_source': Path(__file__).read_text(encoding='utf-8')})


def _target(weights, at, source_ref):
    at = _aware(at, 'target_at')
    if not isinstance(weights, dict) or len(weights) > 5000:
        raise DynamicPaperError('INVALID_TARGET', 'target_weights 必须是不超过5000项的对象。')
    normalized = {}
    for raw_symbol, raw_weight in weights.items():
        symbol = raw_symbol.lower() if isinstance(raw_symbol, str) else ''
        if not SYMBOL.fullmatch(symbol):
            raise DynamicPaperError('INVALID_TARGET', 'target_weights 证券代码无效。')
        if type(raw_weight) not in (int, float) or not math.isfinite(raw_weight) or not 0 <= raw_weight <= 1:
            raise DynamicPaperError('INVALID_TARGET', '目标权重必须为 [0,1] 有限数。')
        if raw_weight > 0:
            normalized[symbol] = float(raw_weight)
    if sum(normalized.values()) > 1 + 1e-12:
        raise DynamicPaperError('INVALID_TARGET', '目标权重合计不能超过1。')
    if not isinstance(source_ref, str) or not source_ref.strip() or len(source_ref) > 500:
        raise DynamicPaperError('INVALID_TARGET', 'target_source_ref 必须是1–500字文本。')
    core = {'available_at': at.astimezone(timezone.utc).isoformat(), 'weights': normalized,
        'source_ref': source_ref.strip()}
    return {**core, 'target_id': str(uuid5(NAMESPACE_URL, 'niuniu-dynamic-paper-target:' + digest(core)))}


class DynamicPaperAccount:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise DynamicPaperError('INVALID_WORKSPACE', '动态 Paper 路径不能是符号链接。')
        lock = self.path.with_suffix(self.path.suffix + '.lock')
        if lock.is_symlink():
            raise DynamicPaperError('INVALID_WORKSPACE', '动态 Paper lock 不能是符号链接。')
        with lock.open('a+b') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DynamicPaperError('BUSY', '动态 PaperAccount 正在处理。') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _read_unlocked(self):
        if not self.path.exists():
            raise DynamicPaperError('NOT_FOUND', '动态 PaperAccount 不存在。')
        try:
            value = read_checked(self.path)
        except (OSError, ValueError) as exc:
            raise DynamicPaperError('CORRUPT_ACCOUNT', str(exc)) from None
        if value.get('format') != FORMAT:
            raise DynamicPaperError('CORRUPT_ACCOUNT', '动态 PaperAccount 格式无效。')
        return value

    def read(self):
        with self.locked():
            return self._read_unlocked()

    @staticmethod
    def _merge_bars(previous, incoming):
        raw = _canonical_rows(incoming.to_dicts())
        old = previous.get('bars', []) if previous else []
        known = {(r['symbol'], r['datetime'], r['available_at']): r for r in old}
        watermark = datetime.fromisoformat(previous['watermark']) if previous else None
        added = 0
        for row in raw:
            key = (row['symbol'], row['datetime'], row['available_at'])
            if key in known:
                if known[key] != row:
                    raise DynamicPaperError('BAR_REVISION', '已经提交的动态 Paper bar 被修改。')
                continue
            moment = datetime.fromisoformat(row['datetime'])
            if watermark is not None and moment <= watermark:
                raise DynamicPaperError('LATE_BAR', '新增 bar 不能早于或等于已提交 watermark。')
            known[key] = row
            added += 1
        merged = sorted(known.values(), key=lambda r: (r['datetime'], r['symbol']))
        if len(merged) > MAX_BARS:
            raise DynamicPaperError('BUDGET_EXCEEDED', '动态 Paper bar 超过上限。')
        return merged, added

    @staticmethod
    def _merge_rules(previous, rules):
        old = previous.get('rules', []) if previous else []
        incoming = _canonical_rows(rules.records)
        known = {(r['symbol'], r['effective_at'], r['available_at']): r for r in old}
        added = 0
        for row in incoming:
            key = (row['symbol'], row['effective_at'], row['available_at'])
            if key in known:
                if known[key] != row:
                    raise DynamicPaperError('RULE_REVISION', '已经提交的 MarketRule 被修改。')
                continue
            known[key] = row
            added += 1
        return sorted(known.values(), key=lambda r: (r['effective_at'], r['symbol'], r['available_at'])), added

    @staticmethod
    def _merge_target(previous, target, old_watermark):
        events = list(previous.get('target_events', [])) if previous else []
        if target is None:
            return events, 0
        same_time = [row for row in events if row['available_at'] == target['available_at']]
        if same_time:
            if len(same_time) == 1 and same_time[0] == target:
                return events, 0
            raise DynamicPaperError('TARGET_CONFLICT', '同一时点已经冻结另一份组合目标。')
        target_at = datetime.fromisoformat(target['available_at'])
        if old_watermark is not None and target_at < old_watermark:
            raise DynamicPaperError('LATE_TARGET', '新的组合目标不能插入已处理行情之前。')
        if events and target_at <= datetime.fromisoformat(events[-1]['available_at']):
            raise DynamicPaperError('LATE_TARGET', '组合目标必须按可用时间单调追加。')
        events.append(target)
        if len(events) > MAX_TARGET_EVENTS:
            raise DynamicPaperError('BUDGET_EXCEEDED', '动态 Paper target event 超过上限。')
        return events, 1

    @staticmethod
    def _materialize_targets(events, universe):
        rows = []
        for event in events:
            at = datetime.fromisoformat(event['available_at'])
            weights = event['weights']
            rows.extend({'symbol': symbol, 'datetime': at, 'available_at': at,
                'weight': float(weights.get(symbol, 0.0))} for symbol in universe)
        if not rows:
            raise DynamicPaperError('TARGET_REQUIRED', '动态 Paper 至少需要一个组合目标。')
        return pl.DataFrame(rows).sort('available_at', 'symbol')

    @staticmethod
    def _assert_prefix(previous, nav, fills, rejections):
        if previous is None:
            return
        for name, current in (('nav', nav), ('fills', fills), ('rejections', rejections)):
            old = previous.get(name, [])
            if current[:len(old)] != old:
                raise DynamicPaperError('HISTORY_REWRITE', '动态 universe 重放改变了已提交的 ' + name + ' 前缀。')

    def current_target_weights(self):
        state = self.read()
        events = state.get('target_events', [])
        return dict(events[-1]['weights']) if events else {}

    def advance(self, bars, rules, config=None, backend='open', *, as_of=None,
            target_at=None, target_weights=None, target_source_ref=''):
        if not isinstance(bars, pl.DataFrame) or bars.is_empty():
            raise DynamicPaperError('INVALID_MARKET_INPUT', 'bars 必须是非空 Polars DataFrame。')
        if not isinstance(rules, MarketRules):
            raise DynamicPaperError('INVALID_MARKET_INPUT', 'rules 必须是 MarketRules。')
        if backend not in ('open', 'vnpy_rules'):
            raise DynamicPaperError('INVALID_ARGUMENT', 'backend 仅支持 open/vnpy_rules。')
        stamp = _aware(as_of or datetime.now(timezone.utc), 'as_of')
        if bars['available_at'].max() > stamp:
            raise DynamicPaperError('FUTURE_MARKET_INPUT', 'bars 包含尚未可用的数据。')
        cfg = config or ExecutionConfig(price_mode='account')
        if cfg.price_mode != 'account':
            raise DynamicPaperError('ACCOUNT_PRICE_MODE_REQUIRED', '长期 Paper 必须使用 price_mode=account。')
        cfg.validate_price_inputs(rules)
        target = None
        if target_at is not None or target_weights is not None or target_source_ref:
            if target_at is None or target_weights is None:
                raise DynamicPaperError('INVALID_TARGET', '新增目标必须同时提供 target_at 与 target_weights。')
            if _aware(target_at, 'target_at') > stamp:
                raise DynamicPaperError('FUTURE_TARGET', 'target_at 不能晚于交付时钟。')
            target = _target(target_weights, target_at, target_source_ref)

        with self.locked():
            previous = self._read_unlocked() if self.path.exists() else None
            identity = _canonical_rows({'config': asdict(cfg), 'backend': backend, 'engine_hash': _engine_identity()})
            if previous and previous['identity'] != identity:
                raise DynamicPaperError('ACCOUNT_IDENTITY_CHANGED', '账户配置、后端或执行代码变化；请新建账户。')
            old_watermark = datetime.fromisoformat(previous['watermark']) if previous else None
            if target is not None:
                prior_weights=dict(previous.get('target_events',[])[-1]['weights']) if previous and previous.get('target_events') else {}
                changed={symbol for symbol in set(prior_weights)|set(target['weights'])
                    if abs(prior_weights.get(symbol,0.0)-target['weights'].get(symbol,0.0))>1e-12}
                delivered=set(bars['symbol'].to_list())
                missing=sorted(changed-delivered)
                if missing:raise DynamicPaperError('TARGET_DELIVERY_INCOMPLETE','权重变化证券缺少本次完成 bar：'+','.join(missing[:20]))
            merged_bars, new_bars = self._merge_bars(previous, bars)
            merged_rules, new_rules = self._merge_rules(previous, rules)
            events, new_targets = self._merge_target(previous, target, old_watermark)
            if previous and not new_bars and not new_rules and not new_targets:
                return previous

            market = frame(merged_bars)
            universe = sorted(set(market['symbol'].to_list()))
            if events:
                target_symbols = set().union(*(set(row['weights']) for row in events))
                missing = sorted(target_symbols - set(universe))
                if missing:
                    raise DynamicPaperError('TARGET_SYMBOL_WITHOUT_BAR', '目标证券没有已交付 bar：' + ','.join(missing[:20]))
            targets = self._materialize_targets(events, universe)
            merged_market_rules = MarketRules(merged_rules)
            cfg.validate_price_inputs(merged_market_rules)
            engine = OpenExecutionBacktester(cfg, merged_market_rules)
            if backend == 'vnpy_rules':
                from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
                engine = VnpyRulesBacktester(cfg, merged_market_rules)
            curve, fills, rejections, summary = engine.run(targets, market)
            nav = _canonical_rows(curve.to_dicts())
            fill_rows = _canonical_rows(fills)
            rejection_rows = _canonical_rows(rejections)
            self._assert_prefix(previous, nav, fill_rows, rejection_rows)
            orders = [{'order_id': digest({'account': str(self.path), 'fill': row}), 'status': 'filled', **row}
                for row in fill_rows]
            orders += [{'order_id': digest({'account': str(self.path), 'rejection': row}), 'status': 'remainder_rejected', **row}
                for row in rejection_rows]
            state = {'format': FORMAT, 'identity': identity, 'revision': previous['revision'] + 1 if previous else 1,
                'delivered_at': stamp.astimezone(timezone.utc).isoformat(), 'watermark': market['available_at'].max().isoformat(),
                'bars': merged_bars, 'target_events': events, 'rules': merged_rules, 'universe_symbols': universe,
                'nav': nav, 'fills': fill_rows, 'rejections': rejection_rows, 'orders': orders,
                'summary': _canonical_rows(summary), 'execution_audit': _canonical_rows(engine.execution_audit),
                'backend_details': _canonical_rows(getattr(engine, 'diagnostics', {})),
                'mode': 'paper_dynamic_universe',
                'limitations': ('Completed-bar deterministic replay; new symbols are backfilled as zero weight in older target snapshots. '
                    'Committed NAV/fill/rejection prefixes must remain unchanged. No broker gateway, live order queue or real capacity guarantee.')}
            write_checked(self.path, state)
            return state


__all__ = ['FORMAT', 'DynamicPaperError', 'DynamicPaperAccount']
