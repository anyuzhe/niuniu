from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

import polars as pl

from quantlab.agent.theme_facts_cli import main as cli_main
from quantlab.data.public_evidence import PublicEvidenceError
from quantlab.trading.theme_engine import ThemeEngineError, ThemeFactsLibrary, compute_family, is_generic, pool_industries
from quantlab.trading.theme_store import ThemeStore

D = date(2026, 9, 17)
PREV = [D - timedelta(days=1), D - timedelta(days=2), D - timedelta(days=3)]


def up_pool(rows):
    return pl.DataFrame(rows, schema={'symbol': pl.String, 'name': pl.String, 'pct_change': pl.Float64, 'limit_up_streak': pl.Int64,
                                      'first_seal_time': pl.String, 'seal_fund': pl.Float64, 'industry': pl.String}, orient='row')


def symbols_pool(symbols):
    return pl.DataFrame({'symbol': symbols, 'name': [s[-4:] for s in symbols]}, schema={'symbol': pl.String, 'name': pl.String})


TODAY_UP = up_pool([('sh.600001', 'A', 10.0, 3, '09:31:00', 1.0e8, '机器人'), ('sh.600002', 'B', 10.0, 1, '09:45:00', 5.0e7, '机器人'),
                    ('sz.000003', 'C', 10.0, 1, '10:00:00', 2.0e7, '软件开发'), ('sz.300005', 'E', 20.0, 2, '09:30:05', 3.0e7, '软件开发')])
MEMBERS = pl.DataFrame([('BK1090', '机器人概念', 'sh.600001'), ('BK1090', '机器人概念', 'sh.600002'), ('BK1090', '机器人概念', 'sz.000003'),
                        ('BK1090', '机器人概念', 'sz.000004'), ('BK0815', '昨日涨停', 'sh.600001'), ('BK0815', '昨日涨停', 'sh.600002'),
                        ('BK1134', '算力概念', 'sz.000003'), ('BK1134', '算力概念', 'sz.300005'), ('BK1166', '低空经济', 'sz.000006')],
                       schema={'board_code': pl.String, 'board_name': pl.String, 'symbol': pl.String}, orient='row')
QUOTES = pl.DataFrame({'board_code': ['BK1090', 'BK1134'], 'pct_change': [3.2, 1.5], 'up_count': [30, 20], 'down_count': [5, 9], 'amount': [5.0e10, 3.0e10]})


class FakeEvidence:
    def __init__(self):
        self.tables = {}
    def put(self, source, day, frame):
        self.tables[(source, day.isoformat())] = frame
    def get(self, source, day):
        key = (source, day.isoformat() if isinstance(day, date) else day)
        if key not in self.tables:
            raise PublicEvidenceError('NOT_FOUND', 'missing')
        return self.manifest(*key)
    def manifest(self, source, day):
        frame = self.tables[(source, day)]
        return {'trading_day': day, 'capture_id': f'00000000-0000-4000-8000-{abs(hash((source, day))) % 10**12:012d}',
                'content_hash': str(hash((source, day, frame.height))), 'finished_at': f'{day}T08:00:00+00:00'}
    def read_table(self, source, day):
        key = (source, day.isoformat() if isinstance(day, date) else day)
        return self.tables[key], self.manifest(*key)
    def list_days(self, source, limit=40):
        days = sorted((d for s, d in self.tables if s == source), reverse=True)
        return [{'trading_day': d} for d in days[:limit]]


def evidence():
    fake = FakeEvidence()
    fake.put('em_limit_up_pool', D, TODAY_UP)
    fake.put('em_broken_board_pool', D, symbols_pool(['sz.000004']))
    fake.put('em_limit_down_pool', D, symbols_pool(['sz.000006']))
    fake.put('em_concept_boards', D, QUOTES)
    fake.put('em_concept_board_members', PREV[0], MEMBERS)
    fake.put('em_industry_board_members', D - timedelta(days=15), MEMBERS)  # 过旧，跳过
    fake.put('em_limit_up_pool', PREV[0], up_pool([('sh.600001', 'A', 10.0, 2, '09:40:00', 1.0, ''), ('sz.000003', 'C', 10.0, 1, '09:50:00', 1.0, ''),
                                                   ('sz.300005', 'E', 20.0, 1, '10:10:00', 1.0, '')]))
    fake.put('em_limit_up_pool', PREV[1], up_pool([('sh.600001', 'A', 10.0, 1, '10:40:00', 1.0, '')]))
    return fake


class ThemeFactsTests(unittest.TestCase):
    def test_board_facts_ladder_leaders_persistence_and_generic_boards(self):
        pools = {'limit_up': TODAY_UP, 'broken': symbols_pool(['sz.000004']), 'limit_down': symbols_pool(['sz.000006'])}
        history = [(PREV[0], ['sh.600001', 'sz.000003', 'sz.300005']), (PREV[1], ['sh.600001'])]
        frame = compute_family(D, 'concept', MEMBERS, PREV[0].isoformat(), pools, QUOTES, history, truncated=True)
        rows = {r['board_code']: r for r in frame.to_dicts()}
        robot = rows['BK1090']
        self.assertEqual((robot['rank'], robot['constituents'], robot['limit_up_count'], robot['first_board_count'], robot['streak_3_count'],
                          robot['max_streak'], robot['broken_count'], robot['limit_down_count']), (1, 4, 3, 2, 1, 3, 1, 0))
        self.assertEqual(robot['leader_symbols'], ['sh.600001', 'sh.600002', 'sz.000003'])
        self.assertTrue(robot['leaders'].startswith('sh.600001 A 3板 09:31:00'))
        self.assertEqual((robot['earliest_first_seal_time'], robot['seal_fund_total']), ('09:31:00', 1.7e8))
        self.assertEqual((robot['persistence_days'], robot['persistence_days_3plus'], robot['limit_up_count_prev'],
                          robot['persistence_history_days'], robot['persistence_truncated']), (3, 1, 2, 2, True))
        self.assertEqual((robot['board_pct_change'], robot['breadth_up'], robot['membership_age_days']), (3.2, 30, 1))
        compute = rows['BK1134']
        self.assertEqual((compute['rank'], compute['limit_up_count'], compute['twenty_cm_limit_up_count'], compute['max_streak'],
                          compute['persistence_days'], compute['persistence_days_3plus']), (2, 2, 1, 2, 2, 0))
        self.assertTrue(rows['BK0815']['is_generic']); self.assertIsNone(rows['BK0815']['rank']); self.assertEqual(rows['BK0815']['limit_up_count'], 2)
        self.assertEqual((rows['BK1166']['rank'], rows['BK1166']['limit_down_count'], rows['BK1166']['persistence_days']), (None, 1, 0))
        self.assertTrue(is_generic('2026中报预增') and is_generic('养老金') and not is_generic('养老概念') and not is_generic('人形机器人'))
        industries = pool_industries(TODAY_UP)
        self.assertEqual(industries.row(0, named=True)['industry'], '机器人'); self.assertEqual(industries['limit_up_count'].to_list(), [2, 2])

    def test_library_build_identity_skips_stale_membership_and_publishes_idempotently(self):
        with TemporaryDirectory() as tmp:
            fake = evidence()
            clock = [datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)]
            def now():
                clock[0] += timedelta(seconds=1); return clock[0]
            library = ThemeFactsLibrary(Path(tmp), now_fn=now, evidence=fake, calendar_fn=lambda day, count: PREV[:count])
            self.assertFalse(library.is_current(D))
            build = library.build(D)
            self.assertTrue(build['created']); self.assertTrue(library.is_current(D))
            self.assertEqual((build['families'], build['skipped_families'], build['history_days'], build['history_truncated']),
                             (['concept'], {'industry': 'MEMBERSHIP_UNAVAILABLE'}, [PREV[0].isoformat(), PREV[1].isoformat()], True))
            self.assertEqual(build['top']['concept'][0]['board_name'], '机器人概念'); self.assertEqual(build['facts_as_of'], f'{D}T08:00:00+00:00')
            self.assertFalse(library.build(D)['created'])
            themes, _ = library.read(D)
            self.assertEqual(themes.filter(pl.col('rank').is_not_null())['board_code'].to_list(), ['BK1090', 'BK1134'])
            fake.put('em_concept_boards', D, QUOTES.head(1))  # 输入变化 → 新 build
            self.assertFalse(library.is_current(D))
            rebuilt = library.build(D)
            self.assertNotEqual(rebuilt['build_id'], build['build_id']); self.assertEqual(library.get(D)['build_id'], rebuilt['build_id'])
            with self.assertRaises(ThemeEngineError) as ctx:
                library.publish(D)
            self.assertEqual(ctx.exception.code, 'CONFIRMATION_REQUIRED')
            contents = library.snapshot_contents(D, min_limit_ups=2)
            self.assertEqual([c['content']['theme'] for c in contents], ['机器人概念', '算力概念'])
            facts = contents[0]['content']['facts']
            self.assertEqual((facts['limit_up_count'], facts['max_streak'], facts['persistence_days'], facts['leader_symbol']), (3, 3, 3, 'sh.600001'))
            self.assertIn('梯队 3板1/首板2', facts['note'])
            first = library.publish(D, confirmed=True, min_limit_ups=2)
            again = library.publish(D, confirmed=True, min_limit_ups=2)
            self.assertEqual([w['snapshot_id'] for w in first['written']], [w['snapshot_id'] for w in again['written']])
            stored = ThemeStore(Path(tmp)).get(first['written'][0]['snapshot_id'])
            self.assertEqual((stored['machine_state'], stored['ai_state'], stored['frame'], stored['source']), ('UNKNOWN', 'UNKNOWN', 'R3', 'machine_theme_facts'))
            del fake.tables[('em_broken_board_pool', D.isoformat())]
            with self.assertRaises(ThemeEngineError) as ctx:
                library.build(D)
            self.assertEqual(ctx.exception.code, 'POOLS_MISSING')

    def test_cli_reads_real_layout_errors_cleanly(self):
        with TemporaryDirectory() as tmp:
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'list']), 0)
            self.assertEqual(json.loads(stream.getvalue())['data']['days'], [])
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'build', '--date', '2026-09-17']), 2)
            self.assertEqual(json.loads(stream.getvalue())['error']['code'], 'POOLS_MISSING')


if __name__ == '__main__':
    unittest.main()
