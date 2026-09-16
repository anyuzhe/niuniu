from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
import json
import unittest

from quantlab.data.eastmoney_sources import (
    EastmoneyBoardListSource, EastmoneyBoardMembersSource, EastmoneyPopularitySource, default_sources,
)
from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError

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
        self.assertEqual(len(default_sources()), 13)


if __name__ == '__main__':
    unittest.main()
