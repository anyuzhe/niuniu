from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import json
import unittest

from quantlab.data.eastmoney_sources import billboard_sources, default_sources, secucode_symbol
from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError

TZ = ZoneInfo('Asia/Shanghai')
DAY = date(2026, 9, 15)


def daily_item(code, suffix, trade_id, reason='日涨幅偏离值达到7%的前5只证券', **extra):
    item = {'TRADE_DATE': '2026-09-15 00:00:00', 'SECUCODE': f'{code}.{suffix}', 'SECURITY_CODE': code, 'SECURITY_NAME_ABBR': '样本',
            'EXPLANATION': reason, 'CLOSE_PRICE': 4.12, 'CHANGE_RATE': -10.04, 'TURNOVERRATE': 8.89, 'FREE_MARKET_CAP': 4197975120,
            'ACCUM_AMOUNT': 383983730, 'BILLBOARD_BUY_AMT': 79857785.62, 'BILLBOARD_SELL_AMT': 62449707.74,
            'BILLBOARD_NET_AMT': 17408077.88, 'BILLBOARD_DEAL_AMT': 142307493.36, 'DEAL_NET_RATIO': 4.53, 'DEAL_AMOUNT_RATIO': 37.06,
            'EXPLAIN': '主力做T', 'CHANGE_TYPE': '137001002002001', 'TRADE_ID': trade_id, 'MARKET': suffix,
            'D1_CLOSE_ADJCHRATE': -1.45, 'D2_CLOSE_ADJCHRATE': None, 'BUY_SEAT': 31333}
    item.update(extra)
    return item


def body(items, pages=1, count=None):
    return json.dumps({'version': 'x', 'result': {'pages': pages, 'count': len(items) if count is None else count, 'data': items},
                       'success': True, 'message': 'ok', 'code': 0}, ensure_ascii=False).encode()


EMPTY = json.dumps({'version': None, 'result': None, 'success': False, 'message': '返回数据为空', 'code': 9201}, ensure_ascii=False).encode()


class Http:
    def __init__(self, pages):
        self.pages = pages; self.urls = []
    def __call__(self, spec):
        self.urls.append(spec.url)
        page = int(spec.url.split('pageNumber=')[1].split('&')[0])
        return 200, spec.url, 'application/json', self.pages[page - 1]


class BillboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def capture(self, pages, source_index=0, when=datetime(2026, 9, 15, 19, 0, tzinfo=TZ)):
        http = Http(pages)
        archive = PublicEvidenceArchive(self.output, sources=billboard_sources(), now_fn=lambda: when, http=http, sleep=lambda s: None)
        return archive, archive.capture(billboard_sources()[source_index].source_id, DAY), http

    def test_pagination_drops_future_columns_and_flags_non_a_shares(self):
        first = body([daily_item('000428', 'SZ', 100412945), daily_item('111024', 'SH', 100412946)], pages=2, count=3)
        second = body([daily_item('920071', 'BJ', 100413260, BUY_SEAT_NEW='1')], pages=2, count=3)
        archive, manifest, http = self.capture([first, second])
        self.assertEqual(len(http.urls), 2); self.assertIn("TRADE_DATE%3D%272026-09-15%27", http.urls[0])
        self.assertEqual(manifest['rows'], 3); self.assertEqual(manifest['warnings'], [])
        frame, _ = archive.read_table('em_billboard_daily', DAY)
        self.assertNotIn('D1_CLOSE_ADJCHRATE', frame.columns); self.assertFalse(any('d1' in c.lower() for c in frame.columns))
        rows = {r['symbol']: r for r in frame.to_dicts()}
        self.assertFalse(rows['sh.111024']['is_a_share']); self.assertTrue(rows['bj.920071']['is_a_share'])
        self.assertEqual(rows['sz.000428']['trade_id'], '100412945')

    def test_not_published_count_mismatch_and_wrong_day_fail_closed(self):
        with self.assertRaises(PublicEvidenceError) as ctx:
            self.capture([EMPTY])
        self.assertEqual(ctx.exception.code, 'NOT_READY')
        with self.assertRaises(PublicEvidenceError):
            self.capture([body([daily_item('000428', 'SZ', 1)], count=2)])
        with self.assertRaises(PublicEvidenceError):
            self.capture([body([daily_item('000428', 'SZ', 1, TRADE_DATE='2026-09-14 00:00:00')])])
        with self.assertRaises(PublicEvidenceError):
            self.capture([body([{k: v for k, v in daily_item('000428', 'SZ', 1).items() if k != 'BILLBOARD_NET_AMT'}])])
        self.assertFalse((self.output / '_market_data/public_evidence/em_billboard_daily/2026-09-15/accepted.json').exists())
        unexpected = body([daily_item('000428', 'SZ', 1, NEW_METRIC=5)])
        _, manifest, _ = self.capture([unexpected])
        self.assertEqual(manifest['warnings'], ['UNEXPECTED_FIELDS:NEW_METRIC'])

    def test_seat_tables_and_symbol_parsing(self):
        seat = {'SECURITY_CODE': '002815', 'SECUCODE': '002815.SZ', 'TRADE_DATE': '2026-09-15 00:00:00', 'OPERATEDEPT_CODE': '10634757',
                'OPERATEDEPT_NAME': '深股通专用', 'EXPLANATION': '连续三个交易日内，涨幅偏离值累计达到20%的证券', 'CHANGE_RATE': 2.55,
                'CLOSE_PRICE': 21.66, 'ACCUM_AMOUNT': 7614655626, 'ACCUM_VOLUME': 371339757, 'BUY': 696056184.51, 'SELL': None,
                'NET': 22363832.39, 'RISE_PROBABILITY_3DAY': None, 'TOTAL_BUYER_SALESTIMES_3DAY': 1277, 'CHANGE_TYPE': '1',
                'OPERATEDEPT_CODE_OLD': None, 'TOTAL_BUYRIO': 0.09, 'TOTAL_SELLRIO': None, 'TRADE_ID': '100412934'}
        archive, manifest, _ = self.capture([body([seat])], source_index=1)
        frame, _ = archive.read_table('em_billboard_buy_seats', DAY)
        row = frame.row(0, named=True)
        self.assertEqual((row['seat_name'], row['sell'], row['em_seat_times_3d']), ('深股通专用', None, 1277.0))
        self.assertEqual(secucode_symbol('920071.BJ'), 'bj.920071')
        with self.assertRaises(PublicEvidenceError):
            secucode_symbol('920071')
        self.assertEqual(len(default_sources()), 13)


if __name__ == '__main__':
    unittest.main()
