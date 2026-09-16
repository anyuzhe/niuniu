from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import io
import json
import unittest

from quantlab.agent.public_evidence_cli import main as cli_main
from quantlab.data.eastmoney_sources import em_symbol, pool_sources
from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError, RequestSpec, capture_timing, http_fetch

TZ = ZoneInfo('Asia/Shanghai')
DAY = date(2026, 9, 15)


def local(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def zt_item(code, market, name, price, **extra):
    item = {'c': code, 'm': market, 'n': name, 'p': price, 'zdp': 10.0, 'amount': 1.0e9, 'ltsz': 4.6e9, 'tshare': 4.9e9,
            'hs': 23.3, 'lbc': 4, 'fbt': 92500, 'lbt': 140933, 'fund': 63104347, 'zbc': 5, 'hybk': '计算机设',
            'zttj': {'days': 4, 'ct': 4}}
    item.update(extra)
    return item


def pool_body(items, tc=None):
    return json.dumps({'rc': 0, 'rt': 110, 'data': {'tc': len(items) if tc is None else tc, 'qdate': 20260916, 'pool': items}},
                      ensure_ascii=False).encode('utf-8')


class StubHttp:
    def __init__(self, bodies):
        self.bodies = bodies; self.calls = []
    def __call__(self, spec):
        self.calls.append(spec.url)
        for key, body in self.bodies.items():
            if key in spec.url:
                if isinstance(body, Exception):
                    raise body
                return 200, spec.url, 'application/json', body
        return 200, spec.url, 'application/json', pool_body([])


class TimingTests(unittest.TestCase):
    def test_capture_timing_classes(self):
        self.assertEqual(capture_timing(DAY, local(2026, 9, 15, 14, 59)), 'NOT_AFTER_CLOSE')
        self.assertEqual(capture_timing(DAY, local(2026, 9, 14, 16, 0)), 'NOT_AFTER_CLOSE')
        self.assertEqual(capture_timing(DAY, local(2026, 9, 15, 15, 40)), 'SAME_DAY_AFTER_CLOSE')
        self.assertEqual(capture_timing(DAY, local(2026, 9, 16, 9, 14)), 'BEFORE_NEXT_SESSION')
        self.assertEqual(capture_timing(DAY, local(2026, 9, 16, 9, 15)), 'LATE')
        friday = date(2026, 9, 18)
        self.assertEqual(capture_timing(friday, local(2026, 9, 20, 22, 0)), 'BEFORE_NEXT_SESSION')
        self.assertEqual(capture_timing(friday, local(2026, 9, 21, 9, 30)), 'LATE')
        with self.assertRaises(PublicEvidenceError):
            capture_timing(DAY, datetime(2026, 9, 15, 16, 0))

    def test_symbol_mapping_and_host_allowlist(self):
        self.assertEqual(em_symbol('600110', 1), 'sh.600110'); self.assertEqual(em_symbol('002912', 0), 'sz.002912')
        self.assertEqual(em_symbol('920118', 0), 'bj.920118'); self.assertEqual(em_symbol('830799', 0), 'bj.830799')
        with self.assertRaises(PublicEvidenceError):
            em_symbol('60011', 1)
        with self.assertRaises(PublicEvidenceError) as ctx:
            http_fetch(RequestSpec('https://example.com/x'))
        self.assertEqual(ctx.exception.code, 'HOST_NOT_ALLOWED')
        with self.assertRaises(PublicEvidenceError):
            http_fetch(RequestSpec('http://push2ex.eastmoney.com/getTopicZTPool'))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.clock = [local(2026, 9, 15, 15, 45)]
        self.bodies = {'getTopicZTPool': pool_body([zt_item('002912', 0, '中新赛克', 28450), zt_item('600110', 1, '诺德股份', 12130, lbc=1, zbc=0)])}
        self.http = StubHttp(self.bodies)
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self, sources=None, calendar_days=None):
        return PublicEvidenceArchive(self.output, sources=sources or pool_sources()[:1], now_fn=lambda: self.clock[0],
                                     http=self.http, sleep=lambda s: None, calendar_days=calendar_days)

    def test_capture_stores_raw_bytes_table_and_accepts_first_capture(self):
        archive = self.archive(calendar_days={'2026-09-15'})
        manifest = archive.capture('em_limit_up_pool', DAY)
        self.assertTrue(manifest['created']); self.assertEqual(manifest['capture_timing'], 'SAME_DAY_AFTER_CLOSE')
        self.assertTrue(manifest['calendar_verified']); self.assertEqual(manifest['rows'], 2); self.assertEqual(manifest['capture_state'], 'accepted')
        self.assertIn('date=20260915', self.http.calls[0])
        frame, got = archive.read_table('em_limit_up_pool', DAY)
        rows = {r['symbol']: r for r in frame.to_dicts()}
        self.assertEqual(rows['sz.002912']['price'], 28.45); self.assertEqual(rows['sz.002912']['first_seal_time'], '09:25:00')
        self.assertEqual(rows['sh.600110']['last_seal_time'], '14:09:33'); self.assertEqual(rows['sz.002912']['stat_days'], 4)
        folder = self.output / '_market_data/public_evidence/em_limit_up_pool/2026-09-15' / manifest['capture_id']
        self.assertEqual((folder / 'responses/0000.bin').read_bytes(), self.bodies['getTopicZTPool'])
        self.assertTrue(got['accepted'])
        again = archive.capture('em_limit_up_pool', DAY)
        self.assertFalse(again['created']); self.assertEqual(again['capture_id'], manifest['capture_id'])
        self.assertEqual(archive.list_days('em_limit_up_pool')[0]['rows'], 2)

    def test_changed_content_is_revision_review_until_confirmed(self):
        archive = self.archive(); first = archive.capture('em_limit_up_pool', DAY)
        self.bodies['getTopicZTPool'] = pool_body([zt_item('002912', 0, '中新赛克', 28450)])
        self.clock[0] = local(2026, 9, 15, 18, 0)
        revision = archive.capture('em_limit_up_pool', DAY)
        self.assertTrue(revision['revision_detected']); self.assertEqual(revision['revision_of'], first['capture_id'])
        self.assertEqual(archive.get('em_limit_up_pool', DAY)['capture_id'], first['capture_id'])
        with self.assertRaises(PublicEvidenceError):
            archive.accept_revision('em_limit_up_pool', DAY, revision['capture_id'])
        archive.accept_revision('em_limit_up_pool', DAY, revision['capture_id'], confirmed=True)
        self.assertEqual(archive.get('em_limit_up_pool', DAY)['rows'], 1)

    def test_timing_weekend_and_late_policies(self):
        archive = self.archive()
        self.clock[0] = local(2026, 9, 15, 11, 0)
        with self.assertRaises(PublicEvidenceError) as ctx:
            archive.capture('em_limit_up_pool', DAY)
        self.assertEqual(ctx.exception.code, 'NOT_AFTER_CLOSE')
        self.clock[0] = local(2026, 9, 17, 10, 0)
        with self.assertRaises(PublicEvidenceError) as ctx:
            archive.capture('em_limit_up_pool', DAY)
        self.assertEqual(ctx.exception.code, 'LATE_CAPTURE_NOT_ALLOWED')
        late = archive.capture('em_limit_up_pool', DAY, allow_late=True)
        self.assertEqual((late['capture_timing'], late['qualification']), ('LATE', 'research_only_late_capture'))
        with self.assertRaises(PublicEvidenceError) as ctx:
            archive.capture('em_limit_up_pool', date(2026, 9, 19), allow_late=True)
        self.assertEqual(ctx.exception.code, 'NOT_TRADING_DAY')
        self.assertEqual(self.http.calls.count(self.http.calls[0]), 1)

    def test_schema_drift_and_provider_errors_fail_closed_without_writes(self):
        cases = [pool_body([zt_item('002912', 0, 'x', 28450)], tc=3), pool_body([{**zt_item('002912', 0, 'x', 28450), 'fbt': 999999}]),
                 json.dumps({'rc': 102, 'data': None}).encode(), b'<html>', pool_body([{k: v for k, v in zt_item('002912', 0, 'x', 1).items() if k != 'fund'}]),
                 pool_body([zt_item('002912', 0, 'x', 28450), zt_item('002912', 0, 'x', 28450)]), OSError('timeout')]
        for body in cases:
            self.bodies['getTopicZTPool'] = body
            with self.assertRaises(PublicEvidenceError):
                self.archive().capture('em_limit_up_pool', DAY)
        self.assertFalse((self.output / '_market_data/public_evidence/em_limit_up_pool/2026-09-15/accepted.json').exists())
        self.bodies['getTopicZTPool'] = pool_body([{**zt_item('002912', 0, 'x', 28450), 'newfield': 1}])
        manifest = self.archive().capture('em_limit_up_pool', DAY)
        self.assertEqual(manifest['warnings'], ['UNEXPECTED_FIELDS:newfield'])

    def test_tamper_detection_and_all_pool_parsers(self):
        archive = self.archive(); manifest = archive.capture('em_limit_up_pool', DAY)
        folder = self.output / '_market_data/public_evidence/em_limit_up_pool/2026-09-15' / manifest['capture_id']
        (folder / 'responses/0000.bin').write_bytes(b'x')
        with self.assertRaises(PublicEvidenceError):
            archive.get('em_limit_up_pool', DAY)
        samples = {
            'getYesterdayZTPool': {'c': '000981', 'm': 0, 'n': 'A', 'p': 3020, 'ztp': 3140, 'zdp': 5.9, 'amount': 4.6e9, 'ltsz': 2.8e10, 'tshare': 3.0e10, 'hs': 15.7, 'zf': 4.9, 'zs': 0.0, 'yfbt': 92500, 'ylbc': 1, 'hybk': '汽车零部', 'zttj': {'days': 2, 'ct': 1}},
            'getTopicZBPool': {'c': '000868', 'm': 0, 'n': 'B', 'p': 4000, 'ztp': 4300, 'zdp': 2.3, 'amount': 4.2e8, 'ltsz': 3.7e9, 'tshare': 3.7e9, 'hs': 10.8, 'fbt': 92500, 'zbc': 1, 'zf': 10.2, 'zs': 0.0, 'zttj': {'days': 2, 'ct': 1}, 'hybk': '商用车'},
            'getTopicDTPool': {'c': '603344', 'm': 1, 'n': 'C', 'p': 22790, 'zdp': -9.99, 'amount': 2.4e8, 'ltsz': 1.2e9, 'tshare': 4.4e9, 'pe': -32.6, 'hs': 19.0, 'fund': 3559798, 'lbt': 150000, 'fba': 30700446, 'days': 1, 'oc': 25, 'hybk': '电机Ⅱ'},
            'getTopicQSPool': {'c': '688004', 'm': 1, 'n': 'D', 'p': 27380, 'ztp': 27380, 'ztf': '1', 'zdp': 19.98, 'amount': 3.4e8, 'ltsz': 2.1e9, 'tshare': 2.1e9, 'hs': 15.7, 'nh': 1, 'cc': 3, 'lb': 6.02, 'zs': 0.0, 'zttj': {'days': 2, 'ct': 2}, 'hybk': 'IT服务Ⅱ'},
        }
        for api, item in samples.items():
            self.bodies[api] = pool_body([item])
        full = PublicEvidenceArchive(self.output, sources=pool_sources()[1:], now_fn=lambda: self.clock[0], http=self.http, sleep=lambda s: None)
        for source in pool_sources()[1:]:
            result = full.capture(source.source_id, DAY)
            self.assertEqual(result['rows'], 1, source.source_id)
        frame, _ = full.read_table('em_limit_down_pool', DAY)
        row = frame.row(0, named=True)
        self.assertEqual((row['symbol'], row['last_seal_time'], row['open_times'], row['pe_dynamic']), ('sh.603344', '15:00:00', 25, -32.6))

    def test_cli_sources_and_capture_errors(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'sources']), 0)
        self.assertEqual(len(json.loads(stream.getvalue())['data']['sources']), 13)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'get', '--source', 'em_limit_up_pool', '--date', '2026-09-15']), 2)


if __name__ == '__main__':
    unittest.main()
