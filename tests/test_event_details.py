from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

import polars as pl

from quantlab.agent.event_details_cli import main as cli_main
from quantlab.data.public_evidence import PublicEvidenceError
from quantlab.trading.event_details import EventDetailError, EventDetailLibrary, detail_frame, minutes_after_open, reconcile
from quantlab.trading.event_study import EventStudyError, EventStudyRegistry

D = date(2026, 9, 17)
D2 = date(2026, 9, 18)


def table(schema, rows):
    return pl.DataFrame(rows, schema=schema, orient='row')


UP = table({'symbol': pl.String, 'limit_up_streak': pl.Int64, 'first_seal_time': pl.String, 'last_seal_time': pl.String, 'seal_fund': pl.Float64,
            'float_market_cap': pl.Float64, 'broken_times': pl.Int64, 'stat_days': pl.Int64, 'stat_limit_ups': pl.Int64, 'industry': pl.String},
           [('sh.600001', 2, '09:25:00', '09:25:00', 2.0e8, 4.0e9, 0, 2, 2, '电力'), ('sz.000002', 1, '13:44:30', '14:50:00', 5.0e7, 0.0, 3, 1, 1, '元件'),
            ('bj.920001', 1, '10:00:00', '10:00:00', 1.0e7, 1.0e9, 0, 1, 1, '北交')])
BROKEN = table({'symbol': pl.String, 'first_seal_time': pl.String, 'broken_times': pl.Int64}, [('sz.000003', '10:31:00', 2)])
DOWN = table({'symbol': pl.String, 'limit_down_streak': pl.Int64, 'seal_fund': pl.Float64, 'open_times': pl.Int64}, [('sh.600004', 1, 3.0e7, 4)])
POPULAR = table({'symbol': pl.String, 'rank': pl.Int64}, [('sh.600001', 3), ('sz.000009', 1)])
BILLBOARD = table({'symbol': pl.String, 'is_a_share': pl.Boolean, 'billboard_net': pl.Float64, 'billboard_deal': pl.Float64, 'deal_ratio': pl.Float64,
                   'trade_id': pl.String},
                  [('sh.600001', True, 1.0e7, 5.0e7, 12.0, 't1'), ('sh.600001', True, 9.0e7, 9.0e7, 20.0, 't2'), ('sz.123456', False, 1.0, 1.0, 1.0, 't3')])
SEATS = {'symbol': pl.String, 'trade_id': pl.String, 'seat_code': pl.String, 'seat_name': pl.String, 'net': pl.Float64}
BUY = table(SEATS, [('sh.600001', 't2', 's1', '机构专用', 3.0e7), ('sh.600001', 't2', 's2', '某营业部', 1.0e7), ('sh.600001', 't1', 's3', '机构专用', 5.0e6)])
SELL = table(SEATS, [('sh.600001', 't2', 's4', '机构专用', -1.0e7), ('sh.600001', 't2', 's1', '机构专用', 3.0e7)])
TABLES = {'limit_up': UP, 'broken': BROKEN, 'limit_down': DOWN, 'popularity': POPULAR, 'billboard': BILLBOARD, 'buy_seats': BUY,
          'sell_seats': SELL, 'strong': None}
SOURCES = {'limit_up': 'em_limit_up_pool', 'broken': 'em_broken_board_pool', 'limit_down': 'em_limit_down_pool', 'popularity': 'em_popularity_rank',
           'billboard': 'em_billboard_daily', 'buy_seats': 'em_billboard_buy_seats', 'sell_seats': 'em_billboard_sell_seats'}


def events_for(day, rows):
    return pl.DataFrame([{'date': day, 'code': c, 'is_st': st, 'is_limit_up_close': up, 'is_limit_down_close': down, 'is_broken_board': br,
                          'limit_up_streak': 1, 'board': 'MAIN', 't1_open_ret': ret} for c, st, up, down, br, ret in rows])


DAY_EVENTS = events_for(D, [('sh.600001', False, True, False, False, 0.03), ('sz.000002', False, True, False, False, -0.01),
                            ('sh.600005', True, True, False, False, 0.0), ('sz.000003', False, False, False, True, -0.02),
                            ('sz.000007', False, False, False, True, 0.01), ('sh.600004', False, False, True, False, -0.05)])


class FakeEvidence:
    def __init__(self, days):
        self.tables = {}
        for day in days:
            for key, source in SOURCES.items():
                self.tables[(source, day.isoformat())] = TABLES[key]
    def get(self, source, day):
        key = (source, day.isoformat() if isinstance(day, date) else day)
        if key not in self.tables:
            raise PublicEvidenceError('NOT_FOUND', 'missing')
        return {'capture_id': '11111111-1111-4111-8111-111111111111', 'content_hash': str(self.tables[key].height)}
    def read_table(self, source, day):
        return self.tables[(source, day.isoformat())], self.get(source, day)


class FakeEvents:
    def __init__(self, frame, last):
        self.frame = frame; self.last = last
    def latest_covering(self, day, current_code=False):
        return {'build_id': '22222222-2222-4222-8222-222222222222'} if day <= self.last else None
    def read_events(self, build_id, *, start=None, end=None, columns=None):
        frame = self.frame.filter((pl.col('date') >= start) & (pl.col('date') <= end))
        return (frame.select(columns) if columns else frame), {'events_sha256': 'x'}


class DetailTests(unittest.TestCase):
    def test_minutes_detail_rows_and_billboard_institutions(self):
        minutes = pl.DataFrame({'t': ['09:25:00', '09:31:10', '11:30:00', '12:00:00', '13:00:00', '13:44:30', '15:00:00', None]}).select(
            minutes_after_open(pl.col('t')).alias('m'))['m'].to_list()
        self.assertEqual(minutes, [0, 1, 120, 120, 120, 164, 240, None])
        frame = detail_frame(D, TABLES)
        rows = {r['code']: r for r in frame.to_dicts()}
        first = rows['sh.600001']
        self.assertEqual((first['em_in_limit_up_pool'], first['em_limit_up_streak'], first['em_first_seal_minute'], first['em_seal_fund_ratio']),
                         (True, 2, 0, 0.05))
        self.assertEqual((first['em_on_billboard'], first['em_billboard_reasons'], first['em_billboard_net'], first['em_billboard_deal_ratio']),
                         (True, 2, 9.0e7, 20.0))
        self.assertEqual((first['em_billboard_inst_net'], first['em_billboard_inst_seats'], first['em_popularity_rank']), (2.0e7, 2, 3))
        self.assertIsNone(first['em_in_strong_pool'])  # 强势股池未归档：保持空，不当作 False
        self.assertIsNone(rows['sz.000002']['em_seal_fund_ratio']); self.assertEqual(rows['sz.000002']['em_last_seal_minute'], 230)
        self.assertEqual((rows['sz.000003']['em_in_broken_pool'], rows['sz.000003']['em_broken_pool_times'], rows['sz.000003']['em_in_limit_up_pool']),
                         (True, 2, False))
        self.assertEqual((rows['sh.600004']['em_in_limit_down_pool'], rows['sh.600004']['em_down_open_times']), (True, 4))
        self.assertFalse(rows['sz.000009']['em_on_billboard']); self.assertNotIn('sz.123456', rows)

    def test_reconcile_requires_exact_limit_ups_and_vendor_subsets(self):
        status, checks = reconcile(DAY_EVENTS, TABLES)
        self.assertEqual(status, 'CONSISTENT'); self.assertEqual(checks['broken']['ours_only'], 1)
        missing_up = DAY_EVENTS.filter(pl.col('code') != 'sz.000002')
        status, checks = reconcile(missing_up, TABLES)
        self.assertEqual((status, checks['limit_up']['vendor_only']), ('INCONSISTENT', ['sz.000002']))
        vendor_extra = {**TABLES, 'broken': BROKEN.vstack(table(BROKEN.schema, [('sz.000008', '10:00:00', 1)]))}
        self.assertEqual(reconcile(DAY_EVENTS, vendor_extra)[0], 'INCONSISTENT')

    def test_library_build_reconciliation_attach_and_event_study_conditions(self):
        with TemporaryDirectory() as tmp:
            clock = [datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)]
            def now():
                clock[0] += timedelta(seconds=1); return clock[0]
            events = DAY_EVENTS.vstack(events_for(D2, [('sh.600001', False, True, False, False, 0.02)]))
            fake_events = FakeEvents(events, D)
            library = EventDetailLibrary(Path(tmp), now_fn=now, evidence=FakeEvidence([D, D2]), event_library=fake_events)
            self.assertFalse(library.is_current(D))
            first = library.build(D)
            self.assertEqual((first['reconciliation'], first['rows'], first['optional_sources_missing']), ('CONSISTENT', 6, ['em_strong_pool']))
            self.assertTrue(library.is_current(D)); self.assertFalse(library.build(D)['created'])
            unchecked = library.build(D2)
            self.assertEqual(unchecked['reconciliation'], 'UNCHECKED')  # 事件库尚未覆盖该日
            fake_events.last = D2
            self.assertFalse(library.is_current(D2))  # 事件库更新后需要重建并核对
            with self.assertRaises(EventDetailError):
                EventDetailLibrary(Path(tmp), evidence=FakeEvidence([]), event_library=fake_events).build(D)
            joined, used = library.attach(events, '2026-09-17', '2026-09-18')
            rows = {(r['date'], r['code']): r for r in joined.to_dicts()}
            self.assertEqual([u['reconciliation'] for u in used], ['CONSISTENT', 'UNCHECKED'])
            self.assertTrue(rows[(D, 'sh.600001')]['em_day_consistent']); self.assertEqual(rows[(D, 'sh.600001')]['em_first_seal_minute'], 0)
            self.assertFalse(rows[(D, 'sz.000007')]['em_in_broken_pool'])  # 核对日：不在池中为 False
            self.assertIsNone(rows[(D, 'sz.000007')]['em_in_strong_pool'])  # 未归档来源保持空
            self.assertFalse(rows[(D2, 'sh.600001')]['em_day_consistent']); self.assertIsNone(rows[(D2, 'sh.600001')]['em_first_seal_minute'])
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(cli_main(['--output', tmp, '--call', 'list']), 0)
            self.assertEqual(len(json.loads(stream.getvalue())['data']['days']), 2)

            class Library:
                def get(self, build_id):
                    return {'build_id': build_id}
                def read_events(self, build_id):
                    return events, {'events_sha256': 'a' * 64}
            registry = EventStudyRegistry(Path(tmp), event_library=Library(), detail_library=library)
            spec = {'family': 'detail-test', 'hypothesis': '早封（开盘 30 分钟内）涨停次日开盘收益', 'library_build_id': '11111111-1111-1111-1111-111111111111',
                    'condition': 'is_limit_up_close and em_first_seal_minute <= 30', 'outcome': 't1_open_ret', 'min_events': 10}
            study = registry.register(spec)
            result = registry.run('detail-test', study['study_id'])['result']
            self.assertEqual(result['samples']['all']['events'], 1)  # 只有核对一致日的早封涨停
            self.assertEqual([b['trading_day'] for b in result['detail_builds']], ['2026-09-17', '2026-09-18'])
            self.assertTrue(any('前瞻明细' in item for item in result['limitations']))
            with self.assertRaises(EventStudyError) as ctx:
                registry.register({**spec, 'condition': 'touched_limit_up and em_first_seal_minute <= 30', 'outcome': 'net_return',
                                   'execution': {'entry': 't0_limit_price'}})
            self.assertEqual(ctx.exception.code, 'LOOKAHEAD_FOR_ENTRY')


if __name__ == '__main__':
    unittest.main()
