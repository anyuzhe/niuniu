from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
import json
import unittest

from quantlab.data.eastmoney_sources import (
    EastmoneyAuctionSnapshotSource, EastmoneyBoardListSource, EastmoneyBoardMembersSource, EastmoneyPopularitySource, IntradayPoolSource,
    default_sources, intraday_sources, pool_sources,
)
from quantlab.data.public_evidence import STAGING, PublicEvidenceArchive, PublicEvidenceError

TZ = ZoneInfo('Asia/Shanghai')
DAY = date(2026, 9, 16)
BOARDS = [{'f12': f'BK{1000 + i}', 'f14': f'板块{i}', 'f13': 90, 'f2': 1000.0 + i, 'f3': 1.0, 'f5': 10, 'f6': 1.0e9, 'f8': 1.2,
           'f104': 10, 'f105': 5, 'f128': '领涨', 'f140': '600001', 'f141': 1, 'f136': 10.0} for i in range(150)]
BOARDS[3]['f2'] = '-'


def clist(total, diff):
    return json.dumps({'rc': 0, 'data': {'total': total, 'diff': diff}}, ensure_ascii=False).encode()


def member(i):
    code = f'{600000 + i:06d}' if i % 3 else f'{i:06d}'
    return {'f12': code, 'f13': 1 if i % 3 else 0, 'f14': f'股{i}', 'f2': 10.0, 'f3': 1.0, 'f6': 1.0e8}


class Http:
    def __init__(self, members=None, total_override=None):
        self.urls = []; self.members = members or {}; self.total_override = total_override
    def __call__(self, spec):
        self.urls.append(spec.url)
        if 'emappdata' in spec.url:
            data = [{'sc': 'SZ002491', 'rk': 1, 'rc': 0, 'hisRc': 0}, {'sc': 'SH600105', 'rk': 2, 'rc': -1, 'hisRc': 94}]
            return 200, spec.url, 'application/json', json.dumps({'status': 0, 'code': 0, 'data': data}).encode()
        q = parse_qs(urlparse(spec.url).query); fs = q['fs'][0]; page = int(q['pn'][0])
        if fs.startswith('b:'):
            board = fs[2:].split('+')[0]; items = self.members.get(board, [])
            return 200, spec.url, 'application/json', clist(len(items), items[(page - 1) * 100: page * 100])
        total = self.total_override or len(BOARDS)
        return 200, spec.url, 'application/json', clist(total, BOARDS[(page - 1) * 100: page * 100])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name); self.when = datetime(2026, 9, 16, 16, 0, tzinfo=TZ)
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self, source, http):
        return PublicEvidenceArchive(self.output, sources=[source], now_fn=lambda: self.when, http=http, sleep=lambda s: None)

    def test_board_list_pagination_and_totals(self):
        http = Http(); archive = self.archive(EastmoneyBoardListSource('concept'), http)
        manifest = archive.capture('em_concept_boards', DAY)
        self.assertEqual((manifest['rows'], len(http.urls)), (150, 2))
        self.assertTrue(all(u.startswith('https://push2delay.eastmoney.com/') for u in http.urls))
        frame, _ = archive.read_table('em_concept_boards', DAY)
        self.assertIsNone(frame.filter(frame['board_code'] == 'BK1003')['index_price'][0])
        self.assertEqual(frame['leader_symbol'][0], 'sh.600001')
        with self.assertRaises(PublicEvidenceError):
            self.archive(EastmoneyBoardListSource('industry'), Http(total_override=151)).capture('em_industry_boards', DAY)

    def test_members_follow_boards_and_paginate_large_boards(self):
        members = {b['f12']: [member(i) for i in range(3)] for b in BOARDS}
        members['BK1001'] = [member(i) for i in range(230)]
        http = Http(members); archive = self.archive(EastmoneyBoardMembersSource('concept'), http)
        manifest = archive.capture('em_concept_board_members', DAY)
        self.assertEqual(manifest['rows'], 149 * 3 + 230)
        self.assertEqual(len(http.urls), 2 + 150 + 2)
        frame, _ = archive.read_table('em_concept_board_members', DAY)
        big = frame.filter(frame['board_code'] == 'BK1001')
        self.assertEqual(big.height, 230); self.assertEqual(big['board_name'][0], '板块1')
        self.assertIn('sz.000000', frame['symbol'].to_list())
        limited = self.archive(EastmoneyBoardMembersSource('industry', board_limit=2), Http(members)).capture('em_industry_board_members', DAY)
        self.assertEqual(limited['warnings'], ['BOARD_LIMIT:2']); self.assertEqual(limited['rows'], 3 + 230)

    def test_member_count_mismatch_fails_closed(self):
        members = {b['f12']: [member(i) for i in range(3)] for b in BOARDS}
        class Broken(Http):
            def __call__(self, spec):
                status, url, kind, body = super().__call__(spec)
                if 'b%3ABK1005' in spec.url:
                    body = clist(4, [member(i) for i in range(3)])
                return status, url, kind, body
        with self.assertRaises(PublicEvidenceError):
            self.archive(EastmoneyBoardMembersSource('concept'), Broken(members)).capture('em_concept_board_members', DAY)

    def test_popularity_and_snapshot_late_refusal(self):
        archive = self.archive(EastmoneyPopularitySource(), Http())
        manifest = archive.capture('em_popularity_rank', DAY)
        frame, _ = archive.read_table('em_popularity_rank', DAY)
        self.assertEqual(frame['symbol'].to_list(), ['sz.002491', 'sh.600105']); self.assertEqual(manifest['rows'], 2)
        self.when = datetime(2026, 9, 17, 10, 0, tzinfo=TZ)
        with self.assertRaises(PublicEvidenceError) as ctx:
            archive.capture('em_popularity_rank', date(2026, 9, 16), allow_late=True)
        self.assertEqual(ctx.exception.code, 'SNAPSHOT_SOURCE_LATE')
        self.assertEqual(len(default_sources()), 26)  # 13 after-close + 13 authorized auction/intraday snapshots


def stock(i, matched=True):
    code, market = (f'{600000 + i:06d}', 1) if i % 2 else (f'{i + 1:06d}', 0)
    return {'f12': code, 'f13': market, 'f14': f'股{i}', 'f2': 10.1 if matched else '-', 'f3': 1.0 if matched else '-', 'f5': 1000 if matched else '-',
            'f6': 1.0e6 if matched else '-', 'f15': 10.1 if matched else '-', 'f16': 10.1 if matched else '-', 'f17': 10.1 if matched else '-', 'f18': 10.0}


class AuctionHttp:
    def __init__(self, stocks):
        self.stocks, self.urls = stocks, []
    def __call__(self, spec):
        self.urls.append(spec.url)
        page = int(parse_qs(urlparse(spec.url).query)['pn'][0])
        return 200, spec.url, 'application/json', clist(len(self.stocks), self.stocks[(page - 1) * 100: page * 100])


class SessionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name); self.day = date(2026, 9, 17)
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self, source, http, clock):
        return PublicEvidenceArchive(self.output, sources=[source], now_fn=clock, http=http, sleep=lambda s: None)

    def test_auction_snapshot_window_real_time_host_and_readiness(self):
        stocks = [stock(i, matched=i % 25 != 0) for i in range(250)]
        http = AuctionHttp(stocks)
        manifest = self.archive(EastmoneyAuctionSnapshotSource(), http, lambda: datetime(2026, 9, 17, 9, 26, tzinfo=TZ)).capture('em_auction_snapshot', self.day)
        self.assertEqual((manifest['rows'], manifest['capture_timing'], len(http.urls)), (250, 'AUCTION', 3))
        self.assertTrue(all(url.startswith('https://push2.eastmoney.com/') for url in http.urls))  # never the delayed host
        frame, _ = PublicEvidenceArchive(self.output, sources=[EastmoneyAuctionSnapshotSource()]).read_table('em_auction_snapshot', self.day)
        self.assertEqual((frame['auction_matched'].sum(), frame.filter(~frame['auction_matched'])['open'].null_count()), (240, 10))
        self.assertEqual(frame['symbol'][0], 'sh.600001')
        for moment in (datetime(2026, 9, 17, 9, 25, 0, tzinfo=TZ), datetime(2026, 9, 17, 9, 29, 30, tzinfo=TZ), datetime(2026, 9, 17, 16, 0, tzinfo=TZ),
                       datetime(2026, 9, 18, 9, 26, tzinfo=TZ)):
            with self.assertRaises(PublicEvidenceError) as ctx:
                self.archive(EastmoneyAuctionSnapshotSource(), AuctionHttp(stocks), lambda moment=moment: moment).capture('em_auction_snapshot', self.day)
            self.assertEqual(ctx.exception.code, 'OUTSIDE_CAPTURE_WINDOW')
        clock = [datetime(2026, 9, 17, 9, 29, 0, tzinfo=TZ)]
        def slow():
            clock[0] += timedelta(seconds=20); return clock[0]
        with self.assertRaises(PublicEvidenceError) as ctx:  # pages fetched after the window closes are refused
            self.archive(EastmoneyAuctionSnapshotSource(), AuctionHttp(stocks), slow).capture('em_auction_snapshot', date(2026, 9, 17))
        self.assertEqual(ctx.exception.code, 'OUTSIDE_CAPTURE_WINDOW')
        early = [stock(i, matched=i % 2 == 0) for i in range(250)]
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(EastmoneyAuctionSnapshotSource(), AuctionHttp(early), lambda: datetime(2026, 9, 17, 9, 25, 40, tzinfo=TZ)).capture('em_auction_snapshot', self.day)
        self.assertEqual(ctx.exception.code, 'DATA_NOT_READY')
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(EastmoneyAuctionSnapshotSource(), AuctionHttp(stocks), lambda: datetime(2026, 9, 17, 9, 26, tzinfo=TZ)).capture(
                'em_auction_snapshot', self.day, max_seconds=60)
        self.assertEqual(ctx.exception.code, 'INVALID_ARGUMENT')

    def test_intraday_pool_slots_are_separate_windowed_sources(self):
        from test_public_evidence import pool_body, zt_item
        sources = intraday_sources()
        self.assertEqual(len(sources), 13)
        slot = next(s for s in sources if s.source_id == 'em_limit_up_pool_i1000')
        self.assertEqual((slot.window_timing, slot.capture_window[0].isoformat(), slot.capture_window[1].isoformat(), slot.snapshot_only),
                         ('INTRADAY', '10:00:00', '10:10:00', True))
        self.assertEqual(sorted(s.source_id for s in sources if s.source_id.endswith('_i1430')),
                         ['em_broken_board_pool_i1430', 'em_limit_down_pool_i1430', 'em_limit_up_pool_i1430'])
        with self.assertRaises(ValueError):
            IntradayPoolSource(pool_sources()[0], '0930')
        class PoolHttp:
            def __call__(self, spec):
                return 200, spec.url, 'application/json', pool_body([zt_item('600001', 1, '甲', 12100)])
        manifest = self.archive(slot, PoolHttp(), lambda: datetime(2026, 9, 17, 10, 3, tzinfo=TZ)).capture('em_limit_up_pool_i1000', self.day)
        self.assertEqual((manifest['rows'], manifest['capture_timing']), (1, 'INTRADAY'))
        self.assertTrue((self.output / '_market_data' / 'public_evidence' / 'em_limit_up_pool_i1000' / '2026-09-17' / 'accepted.json').is_file())
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(next(s for s in sources if s.source_id == 'em_limit_down_pool_i1000'), PoolHttp(),
                         lambda: datetime(2026, 9, 17, 10, 10, tzinfo=TZ)).capture('em_limit_down_pool_i1000', self.day)
        self.assertEqual(ctx.exception.code, 'OUTSIDE_CAPTURE_WINDOW')


class ResumableCaptureTests(unittest.TestCase):
    """Long member captures fetch in several calls: responses are staged, replayed and finalized once."""

    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.clock = [datetime(2026, 9, 16, 16, 0, tzinfo=TZ)]
        self.members = {b['f12']: [member(i) for i in range(3)] for b in BOARDS}
        self.members['BK1001'] = [member(i) for i in range(230)]
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self, http, source=None, output=None):
        def now():
            value = self.clock[0]; self.clock[0] = value + timedelta(seconds=1); return value
        return PublicEvidenceArchive(output or self.output, sources=[source or EastmoneyBoardMembersSource('concept')], now_fn=now,
                                     http=http, sleep=lambda s: None)
    def staging(self):
        return self.output / '_market_data' / 'public_evidence' / 'em_concept_board_members' / DAY.isoformat() / STAGING
    def run_until_done(self, http, max_seconds=60, source=None):
        calls = 0
        while True:
            calls += 1
            result = self.archive(http, source).capture('em_concept_board_members', DAY, max_seconds=max_seconds)
            if result.get('state') != 'IN_PROGRESS':
                return result, calls
            self.assertTrue(self.staging().is_dir()); self.assertLess(calls, 50)

    def test_staged_capture_resumes_without_refetching_and_matches_single_shot(self):
        reference_dir = TemporaryDirectory()
        try:
            single = self.archive(Http(self.members), output=Path(reference_dir.name)).capture('em_concept_board_members', DAY)
        finally:
            reference_dir.cleanup()
        self.clock[0] = datetime(2026, 9, 16, 16, 0, tzinfo=TZ)
        http = Http(self.members)
        first = self.archive(http).capture('em_concept_board_members', DAY, max_seconds=60)
        self.assertEqual(first['state'], 'IN_PROGRESS'); self.assertEqual(first['fetched'], len(http.urls))
        self.assertEqual(self.archive(http).list_days('em_concept_board_members'), [{'trading_day': DAY.isoformat(), 'error': 'IN_PROGRESS'}])
        manifest, calls = self.run_until_done(http)
        self.assertGreater(calls, 3)
        self.assertEqual(len(http.urls), 2 + 150 + 2)  # 每个请求只抓一次
        self.assertEqual(len(set(http.urls)), len(http.urls))
        self.assertEqual((manifest['rows'], manifest['content_hash']), (single['rows'], single['content_hash']))
        self.assertEqual(manifest['started_at'], first['started_at']); self.assertEqual(manifest['capture_timing'], 'SAME_DAY_AFTER_CLOSE')
        self.assertFalse(self.staging().exists())
        again, _ = self.run_until_done(Http(self.members), max_seconds=600)  # 显式重抓：内容相同不重复写入
        self.assertFalse(again['created']); self.assertFalse(self.staging().exists())

    def test_provider_error_keeps_progress_and_bad_staging_restarts(self):
        class Flaky(Http):
            failed = False
            def __call__(self, spec):
                if len(self.urls) == 20 and not self.failed:
                    self.failed = True
                    raise OSError('connection reset')
                return super().__call__(spec)
        http = Flaky(self.members)
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(http).capture('em_concept_board_members', DAY, max_seconds=600)
        self.assertEqual(ctx.exception.code, 'PROVIDER_ERROR'); self.assertEqual(len(list((self.staging() / 'responses').glob('*.json'))), 20)
        before = len(http.urls)
        self.archive(http).capture('em_concept_board_members', DAY, max_seconds=10)
        self.assertEqual(http.urls[before], http.urls[20])  # 从第 21 个请求继续
        (self.staging() / 'responses' / '0003.bin').write_bytes(b'tampered')
        restarted = Http(self.members)
        self.archive(restarted).capture('em_concept_board_members', DAY, max_seconds=10)
        self.assertIn('pn=1', restarted.urls[0]); self.assertNotIn('b%3A', restarted.urls[0])  # 暂存损坏：丢弃后从板块列表第一页重来
        class NewParser(EastmoneyBoardMembersSource):
            parser_version = 'em-board-members-v2'
        manifest, _ = self.run_until_done(Http(self.members), max_seconds=600, source=NewParser('concept'))
        self.assertEqual(manifest['parser_version'], 'em-board-members-v2')

    def test_window_and_data_errors_discard_staging(self):
        self.clock[0] = datetime(2026, 9, 17, 9, 14, 0, tzinfo=TZ)
        first = self.archive(Http(self.members)).capture('em_concept_board_members', DAY, max_seconds=20)
        self.assertEqual(first['state'], 'IN_PROGRESS')
        self.clock[0] = datetime(2026, 9, 17, 9, 16, 0, tzinfo=TZ)
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(Http(self.members)).capture('em_concept_board_members', DAY, max_seconds=20)
        self.assertEqual(ctx.exception.code, 'SNAPSHOT_SOURCE_LATE'); self.assertFalse(self.staging().exists())
        self.clock[0] = datetime(2026, 9, 17, 9, 13, 0, tzinfo=TZ)  # 一次抓完但跨过 09:15：按最晚时点判定为 LATE
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.archive(Http(self.members)).capture('em_concept_board_members', DAY, max_seconds=3600)
        self.assertEqual(ctx.exception.code, 'SNAPSHOT_SOURCE_LATE'); self.assertFalse(self.staging().exists())
        self.clock[0] = datetime(2026, 9, 16, 16, 0, tzinfo=TZ)
        class Garbage(Http):
            def __call__(self, spec):
                status, url, kind, body = super().__call__(spec)
                return (status, url, kind, b'not json') if 'pn=2' in spec.url and 'b%3A' not in spec.url else (status, url, kind, body)
        with self.assertRaises(PublicEvidenceError):
            self.archive(Garbage(self.members)).capture('em_concept_board_members', DAY, max_seconds=600)
        self.assertFalse(self.staging().exists())
        with self.assertRaises(PublicEvidenceError):
            self.archive(Http(self.members)).capture('em_concept_board_members', DAY, max_seconds=0)


if __name__ == '__main__':
    unittest.main()
