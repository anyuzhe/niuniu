from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import random
import unittest

import polars as pl

from quantlab.agent.event_study_cli import main as cli_main
from quantlab.trading.event_study import EventStudyError, EventStudyRegistry, compile_condition, sample_stats
from quantlab.trading.market_sentiment import METRICS

DAYS = []
d = date(2024, 1, 1)
while len(DAYS) < 160:
    if d.weekday() < 5:
        DAYS.append(d)
    d += timedelta(days=1)


def synthetic_events(seed=7):
    rng = random.Random(seed); rows = []
    for i, day in enumerate(DAYS):
        for k in range(4):
            streak = 1 + (k % 3)
            effect = 0.02 if streak >= 2 else 0.0
            rows.append({'date': day, 'code': f'sh.60{i:02d}{k:02d}'[:9].ljust(9, '0'), 'board': 'MAIN' if k % 2 else 'CHINEXT',
                         'is_st': k == 3, 'limit_up_streak': streak, 'is_limit_up_close': True, 'touched_limit_up': True,
                         'turn': 10.0 + k, 't1_open_ret': effect + rng.gauss(0, 0.02), 't1_is_limit_up_close': rng.random() < (0.4 if streak >= 2 else 0.2)})
    return pl.DataFrame(rows)


class FakeEvents:
    def __init__(self, frame):
        self.frame = frame
    def get(self, build_id):
        if build_id != '11111111-1111-1111-1111-111111111111':
            raise ValueError('missing build')
        return {'build_id': build_id}
    def read_events(self, build_id):
        self.get(build_id); return self.frame, {'events_sha256': 'a' * 64}


class FakeSentiment:
    def get(self, build_id):
        return {'build_id': build_id}
    def read(self, build_id):
        rows = []
        for i, day in enumerate(DAYS):
            row = {'date': day, **{m: float((i * 7 + len(m)) % 100) for m in METRICS}}
            rows.append(row)
        return pl.DataFrame(rows), {}


class ConditionTests(unittest.TestCase):
    def test_whitelisted_language(self):
        frame = pl.DataFrame({'limit_up_streak': [1, 2, 3, None], 'board': ['MAIN', 'CHINEXT', 'MAIN', 'STAR'], 'is_st': [False, False, True, None]})
        expr, used = compile_condition('1 < limit_up_streak <= 3 and board in ["MAIN", "CHINEXT"] and not is_st')
        self.assertEqual(frame.filter(expr).height, 1); self.assertEqual(used, ['board', 'is_st', 'limit_up_streak'])
        expr, _ = compile_condition('limit_up_streak >= -1 or board not in ["STAR"]')
        # SQL-like null logic: (null >= -1) or False is null, and null conditions are treated as not matched.
        self.assertEqual(frame.filter(expr).height, 3)
        with self.assertRaises(EventStudyError) as ctx:
            compile_condition('t1_open_ret > 0')
        self.assertEqual(ctx.exception.code, 'LABEL_IN_CONDITION')
        for bad in ('__import__("os")', 'turn + 1 > 2', 'board.upper() == "MAIN"', 'unknown_col > 1', 'turn > float("nan")', '', 'x' * 501):
            with self.assertRaises(EventStudyError):
                compile_condition(bad)


class StatsTests(unittest.TestCase):
    def test_daily_clustering_and_insufficient_samples(self):
        frame = pl.DataFrame({'date': [DAYS[0], DAYS[0], DAYS[1]], 'v': [0.1, 0.3, -0.2]})
        stats = sample_stats(frame, 'v', DAYS[:2], seed=1, min_events=10)
        self.assertEqual((stats['events'], stats['days']), (3, 2)); self.assertAlmostEqual(stats['daily_mean'], 0.0)
        self.assertEqual(stats['test']['reason'], 'insufficient_events'); self.assertAlmostEqual(stats['top5_day_event_share'], 1.0)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.registry = EventStudyRegistry(self.output, now_fn=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc),
                                           event_library=FakeEvents(synthetic_events()), sentiment_library=FakeSentiment())
        self.base = {'family': 'limit-events-test', 'hypothesis': '连板股次日开盘收益高于首板', 'expected_sign': 'positive',
                     'library_build_id': '11111111-1111-1111-1111-111111111111', 'condition': 'limit_up_streak >= 2',
                     'baseline_condition': 'limit_up_streak == 1', 'outcome': 't1_open_ret', 'start': '2024-01-01', 'end': '2024-08-30',
                     'split_date': '2024-05-01', 'group_by': 'board', 'min_events': 30}
    def tearDown(self):
        self.tmp.cleanup()

    def test_register_is_idempotent_and_validates(self):
        first = self.registry.register(self.base); again = self.registry.register(dict(self.base))
        self.assertTrue(first['created']); self.assertFalse(again['created']); self.assertEqual(first['study_id'], again['study_id'])
        bad_cases = [{**self.base, 'extra': 1}, {**self.base, 'outcome': 'close'}, {**self.base, 'condition': 't2_open_ret_day > 0'},
                     {**self.base, 'condition': 'mkt_limit_up_count > 10'}, {**self.base, 'split_date': '2025-01-01'},
                     {**self.base, 'library_build_id': '22222222-2222-2222-2222-222222222222'}, {**self.base, 'family': 'Bad Family'},
                     {**self.base, 'group_by': 'code'}, {**self.base, 'min_events': 5}]
        for spec in bad_cases:
            with self.assertRaises((EventStudyError, ValueError)):
                self.registry.register(spec)

    def test_run_detects_planted_effect_and_is_immutable(self):
        study = self.registry.register(self.base)
        result = self.registry.run('limit-events-test', study['study_id'])['result']
        self.assertEqual(result['primary_sample'], 'out_of_sample')
        oos = result['samples']['out_of_sample']
        self.assertGreater(oos['events'], 100); self.assertAlmostEqual(oos['mean_daily_difference'], 0.02, delta=0.006)
        self.assertLess(result['primary_p_value'], 0.01)
        self.assertEqual({g['board'] for g in result['by_group']}, {'MAIN', 'CHINEXT'})
        self.assertEqual(result['by_year'][0]['year'], '2024')
        again = self.registry.run('limit-events-test', study['study_id'])
        self.assertFalse(again['created']); self.assertEqual(again['result'], result)
        null = self.registry.register({**self.base, 'hypothesis': '首板内部 MAIN 与全体首板无差异', 'condition': 'limit_up_streak == 1 and board == "MAIN"'})
        null_result = self.registry.run('limit-events-test', null['study_id'])['result']
        self.assertGreater(null_result['primary_p_value'], 0.01)

    def test_family_holm_reserves_unrun_studies_and_context_columns(self):
        run = self.registry.register(self.base); self.registry.run('limit-events-test', run['study_id'])
        self.registry.register({**self.base, 'hypothesis': '布尔标签：连板次日继续涨停率更高', 'outcome': 't1_is_limit_up_close', 'group_by': None})
        report = self.registry.family_report('limit-events-test')
        completed = next(r for r in report['studies'] if r['status'] == 'completed')
        self.assertEqual(report['registered'], 2); self.assertEqual(completed['p_holm'], min(1.0, 2 * completed['p_value']))
        context = self.registry.register({**self.base, 'family': 'context-test', 'hypothesis': '市场涨停多时连板更强',
                                          'sentiment_build_id': '33333333-3333-3333-3333-333333333333',
                                          'condition': 'limit_up_streak >= 2 and mkt_limit_up_count >= 0', 'group_by': 'mkt_phase'})
        result = self.registry.run('context-test', context['study_id'])['result']
        self.assertTrue(result['by_group'])


class ExecutionStudyTests(unittest.TestCase):
    def test_execution_outcome_uses_conservative_fills(self):
        days = DAYS[:60]; rows = []; events = []
        for code_index, code in enumerate(('sh.600100', 'sz.000200')):
            pre = 10.0
            for i, day in enumerate(days):
                up, down = round(pre * 1.1 + 1e-9, 2), round(pre * 0.9 + 1e-9, 2)
                opened_at_limit = (i % 5 == 1)
                o = up if opened_at_limit else round(pre * 1.01, 2)
                c = round(pre * (1.02 if i % 2 else 0.99), 2)
                h, l = max(o, c), min(o, c)
                rows.append({'code': code, 'date': day, '_pos': i, 'tradable': True, 'open': o, 'high': h, 'low': l, 'close': c,
                             'preclose': pre, 'limit_up_price': up, 'limit_down_price': down, 'limit_rule_status': 'NORMAL',
                             'is_one_word_limit_up': False, 'touched_limit_up': h >= up, 'is_limit_up_close': c == up})
                if i < 55:
                    events.append({'date': day, 'code': code, 'board': 'MAIN', 'is_st': False, 'limit_up_streak': 1 + code_index,
                                   'is_limit_up_close': True, 't1_open_ret': 0.0})
                pre = c
        states = pl.DataFrame(rows)
        with TemporaryDirectory() as tmp:
            registry = EventStudyRegistry(Path(tmp), now_fn=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc),
                                          event_library=FakeEvents(pl.DataFrame(events)), sentiment_library=FakeSentiment(),
                                          state_batches=lambda manifest: {'last_pos': 59, 'batches': iter([states.filter(pl.col('code') == 'sh.600100'),
                                                                                                    states.filter(pl.col('code') == 'sz.000200')])})
            spec = {'family': 'exec-test', 'hypothesis': '次日开盘买入、再次日开盘卖出的净收益', 'library_build_id': '11111111-1111-1111-1111-111111111111',
                    'condition': 'limit_up_streak >= 1', 'outcome': 'net_return', 'min_events': 10,
                    'execution': {'entry': 't1_open', 'exit': 'next_open', 'scenario': 'conservative'}}
            with self.assertRaises(EventStudyError):
                registry.register({**spec, 'outcome': 't1_open_ret'})
            with self.assertRaises(EventStudyError):
                registry.register({**spec, 'execution': {'entry': 'magic'}})
            study = registry.register(spec)
            result = registry.run('exec-test', study['study_id'])['result']
            summary = result['execution']['all']
            self.assertEqual(summary['events'], 110)
            self.assertEqual(summary['status_counts']['NO_FILL_OPEN_AT_LIMIT_UP'], 22)
            self.assertEqual(result['samples']['all']['events'], summary['entered'])
            self.assertEqual((summary['pending'], summary['fill_rate']), (0, 88 / 110))
            self.assertEqual(study['spec']['execution']['model_version'], 'limit-execution-model-v1')
            self.assertTrue(any('limit-execution-model-v1' in item and 't1_open' in item for item in result['limitations']))
            self.assertFalse(any('未计费用' in item for item in result['limitations']))

    def test_same_day_limit_price_entry_rejects_close_information(self):
        with TemporaryDirectory() as tmp:
            registry = EventStudyRegistry(Path(tmp), event_library=FakeEvents(synthetic_events()), sentiment_library=FakeSentiment(),
                                          state_batches=lambda manifest: {'last_pos': 0, 'batches': iter([])})
            spec = {'family': 'exec-test', 'hypothesis': '昨日涨停今日回封打板的净收益', 'library_build_id': '11111111-1111-1111-1111-111111111111',
                    'condition': 'prev_limit_up_streak >= 1 and touched_limit_up', 'outcome': 'net_return',
                    'execution': {'entry': 't0_limit_price', 'exit': 'next_open'}}
            self.assertTrue(registry.register(spec)['created'])
            for bad in ({'condition': 'limit_up_streak >= 2'}, {'condition': 'touched_limit_up and is_broken_board'},
                        {'condition': 'touched_limit_up and mkt_limit_up_count > 50', 'sentiment_build_id': 'x'},
                        {'baseline_condition': 'is_limit_up_close'}, {'group_by': 'streak_bucket'}):
                with self.assertRaises(EventStudyError) as ctx:
                    registry.register({**spec, **bad})
                self.assertEqual(ctx.exception.code, 'LOOKAHEAD_FOR_ENTRY', bad)
            self.assertTrue(registry.register({**spec, 'execution': {'entry': 't1_limit_price'}, 'condition': 'limit_up_streak >= 2'})['created'])


class CliTests(unittest.TestCase):
    def test_cli_requires_arguments_and_reports_empty_family(self):
        with TemporaryDirectory() as tmp:
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'report', '--family', 'empty-family']), 0)
            self.assertEqual(json.loads(stream.getvalue())['data']['registered'], 0)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'run']), 2)

if __name__ == '__main__':
    unittest.main()
