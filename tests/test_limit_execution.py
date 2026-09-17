from datetime import date, timedelta
import math
import random
import unittest

import polars as pl

from quantlab.trading.limit_execution import (ENTRY_MODES, EXIT_MODES, SCENARIOS, TRADE_SCHEMA, ExecutionSpec, fill_summary,
                                              simulate_trades, stamp_tax_bps, transfer_fee_bps)

START = date(2024, 3, 4)


def day(i):
    d = START
    for _ in range(i):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d


def bar(code, i, pre, o, h, l, c, status='NORMAL'):
    up, down = round(pre * 1.1 + 1e-9, 2), round(pre * 0.9 + 1e-9, 2)
    normal = status == 'NORMAL'
    return {'code': code, 'date': day(i), '_pos': i, 'tradable': True, 'open': o, 'high': h, 'low': l, 'close': c, 'preclose': pre,
            'limit_up_price': up if normal else None, 'limit_down_price': down if normal else None, 'limit_rule_status': status,
            'is_one_word_limit_up': (o == h == l == c == up) if normal else None,
            'touched_limit_up': (round(h * 100) >= round(up * 100)) if normal else None,
            'is_limit_up_close': (round(c * 100) == round(up * 100)) if normal else None}


def halted(code, i, pre):
    return {'code': code, 'date': day(i), '_pos': i, 'tradable': False, 'open': None, 'high': None, 'low': None, 'close': None,
            'preclose': pre, 'limit_up_price': None, 'limit_down_price': None, 'limit_rule_status': 'NORMAL',
            'is_one_word_limit_up': None, 'touched_limit_up': None, 'is_limit_up_close': None}


def rows(code, spec, first=0):
    """spec: (open, high, low, close) tuples, 'S' for suspension, or {'preclose': x, 'bar': (...)} for ex-rights days."""
    out, pre = [], 10.0
    for k, item in enumerate(spec):
        i = first + k
        if item == 'S':
            out.append(halted(code, i, pre))
            continue
        if isinstance(item, dict):
            pre, item = item['preclose'], item['bar']
        out.append(bar(code, i, pre, *item))
        pre = item[3]
    return out


def states(*groups):
    return pl.DataFrame([r for g in groups for r in g], schema_overrides={'_pos': pl.Int64})


def events(*pairs):
    return pl.DataFrame({'date': [day(i) for _c, i in pairs], 'code': [c for c, _i in pairs]})


def _cents(x):
    return int(round(x * 100))


def reference_trades(evts, panel, spec, last_pos=None):
    """Plain-Python statement of the execution rules, used as an oracle for the vectorized model."""
    by_code = {}
    for r in panel.to_dicts():
        by_code.setdefault(r['code'], {})[r['_pos']] = r
    last = max(panel['_pos'].to_list()) if last_pos is None else last_pos
    slip = spec.slippage_bps / 10000
    out = []
    for d, code in evts.select('date', 'code').iter_rows():
        pos = next(p for p, r in by_code[code].items() if r['date'] == d)
        rec = dict.fromkeys(TRADE_SCHEMA)
        rec.update(date=d, code=code)
        e_pos = pos + (1 if spec.entry.startswith('t1_') else 0)
        row = by_code[code].get(e_pos)
        price = None
        if e_pos > last:
            status = 'PENDING_ENTRY_DATA'
        elif row is None:
            status = 'NO_FILL_NOT_LISTED'
        elif not row['tradable']:
            status = 'NO_FILL_SUSPENDED'
        elif row['limit_rule_status'] != 'NORMAL' or row['limit_up_price'] is None:
            status = 'NO_FILL_UNMODELED'
        elif spec.entry == 't1_open':
            status = 'NO_FILL_OPEN_AT_LIMIT_UP' if _cents(row['open']) >= _cents(row['limit_up_price']) else 'FILLED'
            price = min(row['open'] * (1 + slip), row['limit_up_price'])
        elif spec.entry == 't1_close':
            status = 'NO_FILL_CLOSE_AT_LIMIT_UP' if _cents(row['close']) >= _cents(row['limit_up_price']) else 'FILLED'
            price = min(row['close'] * (1 + slip), row['limit_up_price'])
        else:
            if not row['touched_limit_up']:
                status = 'NO_FILL_NOT_TOUCHED'
            elif row['is_one_word_limit_up']:
                status = 'NO_FILL_ONE_WORD'
            elif row['is_limit_up_close'] and spec.scenario == 'conservative':
                status = 'NO_FILL_SEALED_QUEUE_UNKNOWN'
            else:
                status = 'FILLED'
            price = row['limit_up_price']
        rec['fill_status'] = status
        if status != 'FILLED':
            out.append(rec)
            continue
        rec.update(entry_date=row['date'], entry_price=price)
        factor, prev_close, found, mark, mark_factor = 1.0, row['close'], None, None, None
        for p in range(e_pos + 1, e_pos + spec.max_hold_sessions + 1):
            r = by_code[code].get(p)
            if r is None or not r['tradable'] or r['preclose'] is None:
                continue
            factor *= prev_close / r['preclose']
            key = r['open'] if spec.exit == 'next_open' else r['close']
            if r['limit_down_price'] is None or _cents(key) > _cents(r['limit_down_price']):
                found = (r, key, factor)
                break
            prev_close, mark, mark_factor = r['close'], r, factor

        def floor(value, down):
            return value if down is None else max(value, down)

        if found:
            r, key, f = found
            rec.update(fill_status='FILLED', exit_price=floor(key * (1 - slip), r['limit_down_price']), exit_date=r['date'],
                       hold_sessions=r['_pos'] - e_pos, exit_delayed=r['_pos'] > e_pos + 1)
        elif e_pos + spec.max_hold_sessions > last and max(by_code[code]) >= last:
            rec['fill_status'] = 'PENDING_EXIT_DATA'
            out.append(rec)
            continue
        elif mark is not None:
            f = mark_factor
            rec.update(fill_status='UNRESOLVED_EXIT', exit_price=floor(mark['close'] * (1 - slip), mark['limit_down_price']),
                       exit_date=mark['date'], hold_sessions=mark['_pos'] - e_pos, exit_delayed=True)
        else:
            f = 1.0
            rec.update(fill_status='UNRESOLVED_EXIT', exit_price=floor(row['close'] * (1 - slip), row['limit_down_price']), exit_delayed=True)
        gross = rec['exit_price'] / price * f - 1
        sell_day = rec['exit_date'] or row['date']
        buy = (spec.commission_bps + transfer_fee_bps(row['date'])) / 10000
        sell = (spec.commission_bps + transfer_fee_bps(sell_day) + stamp_tax_bps(sell_day)) / 10000
        rec.update(gross_return=gross, net_return=(1 + gross) * (1 - sell) / (1 + buy) - 1)
        out.append(rec)
    return out


def random_panel(seed, codes=8, length=36):
    rng = random.Random(seed)
    out = []
    for k in range(codes):
        code = f'sz.0003{k:02d}'
        first = rng.choice([0, 0, 2])
        last = length - rng.choice([0, 0, 0, 3, 7])
        pre = round(rng.uniform(4, 30), 2)
        for i in range(first, last):
            if rng.random() < 0.08:
                out.append(halted(code, i, pre))
                continue
            if rng.random() < 0.06:
                pre = round(pre * rng.uniform(0.9, 0.99), 2)
            up, down = round(pre * 1.1 + 1e-9, 2), round(pre * 0.9 + 1e-9, 2)
            u = lambda: round(rng.uniform(down, up), 2)
            kind = rng.random()
            if kind < 0.1:
                o = h = l = c = up
            elif kind < 0.25:
                o = h = l = c = down
            elif kind < 0.35:
                o = u(); h = up; c = up; l = min(o, u())
            elif kind < 0.5:
                o = u(); h = up; c = min(u(), round(up - 0.01, 2)); l = min(o, c)
            elif kind < 0.55:
                o = up; h = up; c = u(); l = min(o, c)
            else:
                o, c = u(), u(); h, l = max(o, c), min(o, c)
            out.append(bar(code, i, pre, o, h, l, c, 'NORMAL' if rng.random() > 0.04 else 'UNMODELED'))
            pre = c
    return pl.DataFrame(out, schema_overrides={'_pos': pl.Int64})


class ExecutionTests(unittest.TestCase):
    def trade(self, panel, code, i, **spec):
        return simulate_trades(events((code, i)), panel, ExecutionSpec(**spec)).row(0, named=True)

    def test_next_open_entry_exit_and_costs(self):
        panel = states(rows('sh.600001', [(10, 11, 10, 11), (11.5, 12.0, 11.2, 11.8), (12.0, 12.5, 11.9, 12.2)]))
        t = self.trade(panel, 'sh.600001', 0, max_hold_sessions=1)
        self.assertEqual(t['fill_status'], 'FILLED'); self.assertAlmostEqual(t['entry_price'], 11.5 * 1.0005)
        self.assertEqual((t['entry_date'], t['exit_date'], t['hold_sessions'], t['exit_delayed']), (day(1), day(2), 1, False))
        gross = 12.0 * 0.9995 / (11.5 * 1.0005) - 1
        self.assertAlmostEqual(t['gross_return'], gross, places=12)
        net = (1 + gross) * (1 - (2.5 + 0.1 + 5.0) / 10000) / (1 + (2.5 + 0.1) / 10000) - 1  # 2024 年卖出印花税 0.05%
        self.assertAlmostEqual(t['net_return'], net, places=12)
        close_exit = self.trade(panel, 'sh.600001', 0, exit='next_close', slippage_bps=0.0, max_hold_sessions=1)
        self.assertAlmostEqual(close_exit['gross_return'], 12.2 / 11.5 - 1, places=12)

    def test_entry_blocks_and_unknown_event(self):
        opened_up = states(rows('sz.000001', [(10, 11, 10, 11), (12.1, 12.1, 12.1, 12.1), (12.0, 12.5, 11.9, 12.2)]))
        self.assertEqual(self.trade(opened_up, 'sz.000001', 0)['fill_status'], 'NO_FILL_OPEN_AT_LIMIT_UP')
        suspended = states(rows('sz.000002', [(10, 11, 10, 11), 'S', (11, 11.5, 10.8, 11.2)]))
        self.assertEqual(self.trade(suspended, 'sz.000002', 0)['fill_status'], 'NO_FILL_SUSPENDED')
        closed_up = states(rows('sz.000003', [(10, 11, 10, 11), (11.5, 12.1, 11.2, 12.1), (12.0, 12.5, 11.9, 12.2)]))
        self.assertEqual(self.trade(closed_up, 'sz.000003', 0, entry='t1_close')['fill_status'], 'NO_FILL_CLOSE_AT_LIMIT_UP')
        with self.assertRaises(ValueError):
            simulate_trades(events(('sz.009999', 0)), closed_up, ExecutionSpec())
        delisted = states(rows('sz.000004', [(10, 11, 10, 11)]), rows('sz.000005', [(10, 10.5, 9.9, 10.2)] * 3))
        self.assertEqual(self.trade(delisted, 'sz.000004', 0)['fill_status'], 'NO_FILL_NOT_LISTED')

    def test_queue_scenarios_for_limit_price_entries(self):
        panel = states(rows('sh.600010', [(11, 11, 11, 11), (11.5, 11.5, 11.5, 11.5)]),
                       rows('sh.600011', [(10.2, 11.0, 10.1, 10.6), (10.7, 10.9, 10.4, 10.8)]),
                       rows('sh.600012', [(10.2, 11.0, 10.1, 11.0), (11.2, 11.6, 11.0, 11.3)]),
                       rows('sh.600013', [(10.2, 10.6, 10.1, 10.5), (10.6, 10.9, 10.4, 10.8)]))
        self.assertEqual(self.trade(panel, 'sh.600010', 0, entry='t0_limit_price')['fill_status'], 'NO_FILL_ONE_WORD')
        broken = self.trade(panel, 'sh.600011', 0, entry='t0_limit_price', max_hold_sessions=1)
        self.assertEqual((broken['fill_status'], broken['entry_price']), ('FILLED', 11.0))
        self.assertEqual(self.trade(panel, 'sh.600012', 0, entry='t0_limit_price')['fill_status'], 'NO_FILL_SEALED_QUEUE_UNKNOWN')
        self.assertEqual(self.trade(panel, 'sh.600012', 0, entry='t0_limit_price', scenario='optimistic', max_hold_sessions=1)['fill_status'], 'FILLED')
        self.assertEqual(self.trade(panel, 'sh.600013', 0, entry='t0_limit_price')['fill_status'], 'NO_FILL_NOT_TOUCHED')

    def test_limit_down_delays_exit_dividend_adjustment_and_marked_unresolved(self):
        delayed = states(rows('sz.300001', [(10, 11, 10, 11), (11.2, 11.5, 11.0, 11.0), (9.9, 9.9, 9.9, 9.9), (9.5, 10.0, 9.2, 9.8)]))
        t = self.trade(delayed, 'sz.300001', 0, slippage_bps=0.0, max_hold_sessions=2)
        self.assertEqual((t['exit_date'], t['hold_sessions'], t['exit_delayed']), (day(3), 2, True))
        self.assertAlmostEqual(t['gross_return'], 9.5 / 11.2 - 1, places=12)
        dividend = states(rows('sh.600020', [(10, 10.5, 9.9, 10.2), (10.0, 10.3, 9.9, 10.0), {'preclose': 9.8, 'bar': (9.9, 10.1, 9.7, 10.0)}]))
        d = self.trade(dividend, 'sh.600020', 0, slippage_bps=0.0, max_hold_sessions=1)
        self.assertAlmostEqual(d['gross_return'], 9.9 / 10.0 * (10.0 / 9.8) - 1, places=12)
        # 持有窗口内一直跌停：不丢弃，按窗口内最后收盘价计价，收益留在样本里。
        pinned = rows('sz.000030', [(10, 11, 10, 11), (11.2, 11.5, 11.0, 11.0), (9.9, 9.9, 9.9, 9.9), (8.91, 8.91, 8.91, 8.91), (8.5, 9.0, 8.4, 8.8)])
        panel = states(pinned, rows('sz.000031', [(10, 10.2, 9.9, 10.0)] * 6))
        unresolved = self.trade(panel, 'sz.000030', 0, max_hold_sessions=2, slippage_bps=0.0)
        self.assertEqual((unresolved['fill_status'], unresolved['exit_date'], unresolved['hold_sessions']), ('UNRESOLVED_EXIT', day(3), 2))
        self.assertAlmostEqual(unresolved['gross_return'], 8.91 / 11.2 - 1, places=12)
        summary = fill_summary(simulate_trades(events(('sz.000030', 0), ('sz.000031', 0)), panel, ExecutionSpec(max_hold_sessions=2)))
        self.assertEqual((summary['entered'], summary['unresolved_exits'], summary['pending'], summary['fill_rate']), (2, 1, 0, 1.0))
        self.assertLess(summary['mean_net_return'], 0)

    def test_end_of_data_is_pending_not_no_fill(self):
        panel = states(rows('sh.600040', [(10, 10.5, 9.9, 10.2), (10.3, 10.6, 10.1, 10.4), (10.4, 10.5, 10.2, 10.3)]))
        self.assertEqual(self.trade(panel, 'sh.600040', 2)['fill_status'], 'PENDING_ENTRY_DATA')
        self.assertEqual(self.trade(panel, 'sh.600040', 1, max_hold_sessions=3)['fill_status'], 'PENDING_EXIT_DATA')
        self.assertEqual(self.trade(panel, 'sh.600040', 0, max_hold_sessions=3)['fill_status'], 'FILLED')
        pending = simulate_trades(events(('sh.600040', 2), ('sh.600040', 0)), panel, ExecutionSpec(max_hold_sessions=3))
        summary = fill_summary(pending)
        self.assertEqual((summary['events'], summary['pending'], summary['resolved'], summary['fill_rate']), (2, 1, 1, 1.0))
        # 日历终点晚于该证券最后一行（证券已不再交易）：不是等待数据，而是按买入日收盘价计价的未能卖出。
        gone = simulate_trades(events(('sh.600040', 1)), panel, ExecutionSpec(max_hold_sessions=3, slippage_bps=0.0), last_pos=5).row(0, named=True)
        self.assertEqual((gone['fill_status'], gone['exit_date'], gone['hold_sessions']), ('UNRESOLVED_EXIT', None, None))
        self.assertAlmostEqual(gone['gross_return'], 10.3 / 10.4 - 1, places=12)

    def test_vectorized_model_matches_reference_rules_on_random_panels(self):
        for seed in range(6):
            panel = random_panel(seed)
            rng = random.Random(100 + seed)
            picks = rng.sample(panel.select('code', '_pos').rows(), 60)
            evts = pl.DataFrame({'date': [day(p) for _c, p in picks], 'code': [c for c, _p in picks]})
            for entry in ENTRY_MODES:
                for exit_mode in EXIT_MODES:
                    for scenario in SCENARIOS:
                        spec = ExecutionSpec(entry=entry, exit=exit_mode, scenario=scenario, max_hold_sessions=rng.choice([1, 3, 8]),
                                             slippage_bps=rng.choice([0.0, 5.0]))
                        got = simulate_trades(evts, panel, spec, last_pos=35).to_dicts()
                        want = reference_trades(evts, panel, spec, last_pos=35)
                        self.assertEqual(len(got), len(want))
                        for g, w in zip(got, want):
                            for key in TRADE_SCHEMA:
                                if isinstance(w[key], float):
                                    self.assertTrue(math.isclose(g[key], w[key], rel_tol=1e-12, abs_tol=1e-12), (seed, spec, key, g, w))
                                else:
                                    self.assertEqual(g[key], w[key], (seed, spec, key, g, w))

    def test_dated_fees_and_spec_validation(self):
        self.assertEqual((stamp_tax_bps(date(2023, 8, 25)), stamp_tax_bps(date(2023, 8, 28))), (10.0, 5.0))
        self.assertEqual((transfer_fee_bps(date(2022, 4, 28)), transfer_fee_bps(date(2022, 4, 29))), (0.2, 0.1))
        for bad in ({'entry': 'market'}, {'commission_bps': -1}, {'max_hold_sessions': 0}, {'scenario': 'best'}):
            with self.assertRaises(ValueError):
                ExecutionSpec(**bad)
        with self.assertRaises(ValueError):
            ExecutionSpec.from_dict({'unknown': 1})
        self.assertEqual(simulate_trades(events(('sh.600001', 0)).head(0), states(rows('sh.600001', [(10, 11, 10, 11)])), ExecutionSpec()).schema,
                         pl.Schema(TRADE_SCHEMA))


if __name__ == '__main__':
    unittest.main()
