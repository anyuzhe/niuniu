import gzip
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import duckdb

from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI, NAMES, TOOLS
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.data.tdx_lake import TdxLake
from test_retro_daily import FakeSDK, bar


class InnerAPI:
    def __init__(self):
        self.calls = []
    def schemas(self):
        return [{'name': 'get_capabilities', 'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}},
                {'name': 'inner_tool', 'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}},
                {'name': 'read_tdx_data', 'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}]
    def call(self, name, args):
        self.calls.append((name, args))
        if name == 'get_capabilities':
            return {'ok': True, 'tool': name, 'data': {'inner': True, 'tools': ['inner_tool']}, 'evidence': [], 'warnings': [], 'error': None}
        return {'ok': True, 'tool': name, 'data': {'delegated': args}, 'evidence': [], 'warnings': [], 'error': None}


class ArchivedDataToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'output'; self.output.mkdir()
        self.source = self.root / 'source'; self.source.mkdir()
        self.days = [date(2026, 7, 1) + timedelta(days=i) for i in range(40)]
        self.sessions = [d for d in self.days if d.weekday() < 5]
        calendar = [(d.isoformat(), '1' if d.weekday() < 5 else '0') for d in self.days]
        basic = [('sh.600000', 'name', '2000-01-01', '', '1', '1'), ('sz.000001', 'name', '2000-01-01', '', '1', '1')]
        bars = {s: [bar(d.isoformat(), s, 10.0 + i / 10, 10.0 + max(i - 1, 0) / 10, st='1' if i == 3 else '0')
                    for i, d in enumerate(self.sessions)] for s in ('sh.600000', 'sz.000001')}
        bars['sz.000001'][4] = bar(self.sessions[4].isoformat(), 'sz.000001', 0, 10.3, tradestatus='0')
        store = RetroDailyStore(self.source, today_fn=lambda: date(2026, 9, 21), now_fn=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
        self.capture = store.create_plan(self.days[0].isoformat(), self.days[-1].isoformat(), sdk=FakeSDK(basic=basic, calendar=calendar, bars=bars))['capture_id']
        store.fetch(self.capture, sdk=FakeSDK(basic=basic, calendar=calendar, bars=bars))
        self.retro = store
        self.start, self.end = self.sessions[0].isoformat(), self.sessions[6].isoformat()
        self.inner = InnerAPI()
        from types import SimpleNamespace
        disk = patch('quantlab.data.tdx_lake.shutil.disk_usage', return_value=SimpleNamespace(free=200 * 1024 ** 3))
        disk.start(); self.addCleanup(disk.stop)

    def make_api(self, data_root=None, source_workspace=None):
        return ArchivedMarketDataAPI(self.inner, self.output, data_root, source_workspace=source_workspace)

    def make_lake(self):
        data = self.root / 'tdx'; (data / 'catalog').mkdir(parents=True)
        with duckdb.connect(str(data / 'catalog/mqc.duckdb')) as con:
            con.execute('CREATE TABLE keep_existing(x INTEGER)')
        lake = TdxLake(data, create=True)
        body = {'symbols': ['sz.000001'], 'trading_days': ['2026-09-17'], 'server_handshake': {'large': True},
                'calendar_extension': ['x'], 'personal_research_only': True}
        pid = lake.add_plan(body)
        job_id = lake.enqueue(pid, 'bars_1m', 'sz.000001', '2026-09-17', 0)
        job = {'job_id': job_id, 'plan_id': pid, 'family': 'bars_1m', 'symbol': 'sz.000001', 'day': '2026-09-17', 'offset': 0}
        return data, lake, job

    def test_init_and_schemas_do_not_touch_sources_and_merge_without_duplicates(self):
        with patch('quantlab.agent.qm50_archived_inputs.ArchivedDailyBridge', side_effect=AssertionError('no eager read')):
            api = self.make_api()
            names = [t['name'] for t in api.schemas()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(NAMES <= set(names)); self.assertIn('inner_tool', names)
        self.assertEqual({t['name'] for t in TOOLS}, NAMES)

    def test_default_workspace_is_output_and_explicit_source_binds_root(self):
        self.assertEqual(self.make_api().call('list_archived_daily_sources', {})['data']['captures'], [])
        result = self.make_api(source_workspace=self.source).call('list_archived_daily_sources', {})
        self.assertTrue(result['ok'], result); self.assertEqual(result['data']['captures'][0]['capture_id'], self.capture)
        self.assertFalse(result['data']['incomplete'])

    def test_daily_paging_filters_errors_and_unknown_arguments(self):
        api = self.make_api(source_workspace=self.source)
        result = api.call('list_archived_daily_symbols', {'capture_id': self.capture, 'offset': 0, 'limit': 1, 'filter_kind': 'has_suspension'})
        self.assertTrue(result['ok'], result); self.assertEqual(result['data']['records'][0]['symbol'], 'sz.000001')
        all_rows = api.call('list_archived_daily_symbols', {'capture_id': self.capture, 'offset': 0, 'limit': 1, 'filter_kind': 'all'})
        self.assertIsNotNone(all_rows['data']['next_offset'])
        bad = api.call('list_archived_daily_symbols', {'capture_id': self.capture, 'offset': 0, 'limit': 1, 'filter_kind': 'all', 'path': '/tmp'})
        self.assertFalse(bad['ok']); self.assertEqual(bad['error']['code'], 'INVALID_ARGUMENT')

    def test_inspect_daily_verifies_raw_and_typed_and_packed_same_source(self):
        api = self.make_api(source_workspace=self.source)
        unpacked = api.call('inspect_archived_daily', {'capture_id': self.capture, 'symbols': 'sh.600000 sz.000001', 'start': self.start, 'end': self.end})
        self.assertTrue(unpacked['ok'], unpacked); self.assertTrue(unpacked['data']['raw_and_typed_bytes_verified'])
        self.retro.consolidate(self.capture, confirmed=True, remove_originals=True)
        packed = api.call('inspect_archived_daily', {'capture_id': self.capture, 'symbols': 'sh.600000 sz.000001', 'start': self.start, 'end': self.end})
        self.assertTrue(packed['ok'], packed); self.assertTrue(packed['data']['source_evidence']['packed'])
        self.assertEqual(unpacked['data']['source_evidence']['symbols'], packed['data']['source_evidence']['symbols'])

    def test_daily_corruption_is_structured_failure_not_empty_success(self):
        raw = self.retro._symbol_dir(self.capture, 'sh.600000') / 'rows.json.gz'
        value = json.loads(gzip.decompress(raw.read_bytes())); value['rows'][0][0] = '2026-01-01'
        raw.write_bytes(gzip.compress(json.dumps(value).encode()))
        result = self.make_api(source_workspace=self.source).call('inspect_archived_daily', {'capture_id': self.capture, 'symbols': 'sh.600000', 'start': self.start, 'end': self.end})
        self.assertFalse(result['ok']); self.assertIn(result['error']['code'], {'CORRUPT_ARCHIVE', 'INVALID_ARGUMENT'})

    def test_tdx_not_configured_and_status_redacts_large_plan_fields(self):
        not_configured = self.make_api().call('get_tdx_data_status', {})
        self.assertFalse(not_configured['ok']); self.assertEqual(not_configured['error']['code'], 'TDX_NOT_CONFIGURED')
        data, lake, job = self.make_lake(); lake.save_page(job, {'exchange': 'sz', 'code': '000001', 'bars': []})
        status = self.make_api(data_root=data).call('get_tdx_data_status', {})
        self.assertTrue(status['ok'], status); self.assertNotIn('symbols', status['data']['plans'][0]); self.assertNotIn('trading_days', status['data']['plans'][0])

    def test_read_tdx_preserves_original_record_units_observed_and_rejects_reverse_dates(self):
        data, lake, job = self.make_lake()
        lake.save_page(job, {'exchange': 'sz', 'code': '000001', 'bars': [{'time': '2026-09-17T09:31:00+08:00', 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume_wire_value': 100, 'amount': 200, 'mystery_unit': 'kept'}]}, observed_at='2026-09-18T00:00:00+00:00')
        api = self.make_api(data_root=data)
        result = api.call('read_tdx_data', {'family': 'bars_1m', 'symbol': 'sz.000001', 'start': '2026-09-17', 'end': '2026-09-17', 'offset': 0, 'limit': 1})
        self.assertTrue(result['ok'], result); row = result['data']['rows'][0]
        self.assertEqual(row['original_record']['mystery_unit'], 'kept'); self.assertEqual(row['volume_unit'], 'shares_wire_value')
        self.assertEqual(row['observed_at'], '2026-09-18T00:00:00+00:00'); self.assertTrue(result['evidence'][0]['source_id'])
        bad = api.call('read_tdx_data', {'family': 'bars_1m', 'symbol': 'sz.000001', 'start': '2026-09-18', 'end': '2026-09-17', 'offset': 0, 'limit': 1})
        self.assertFalse(bad['ok']); self.assertEqual(bad['error']['code'], 'INVALID_ARGUMENT')

    def test_tdx_provider_unspecified_unit_and_no_network(self):
        data, lake, _job = self.make_lake()
        pid = lake.add_plan({'personal_research_only': True})
        jid = lake.enqueue(pid, 'finance', 'sz.000001', '2026-09-17', 0)
        lake.save_page({'job_id': jid, 'plan_id': pid, 'family': 'finance', 'symbol': 'sz.000001', 'day': '2026-09-17', 'offset': 0}, {'records': [{'updated_date': '2026-09-17', 'liu_tong_gu_ben_raw_float': 1.5}]})
        with patch('quantlab.agent.tdx_collection_cli.Source', side_effect=AssertionError('network')):
            result = self.make_api(data_root=data).call('read_tdx_data', {'family': 'finance', 'symbol': 'sz.000001', 'start': '', 'end': '', 'offset': 0, 'limit': 1})
        self.assertTrue(result['ok'], result); self.assertEqual(result['data']['rows'][0]['volume_unit'], 'provider_unspecified')
        self.assertEqual(result['data']['rows'][0]['original_record']['liu_tong_gu_ben_raw_float'], 1.5)

    def test_structured_sqlite_duckdb_and_symlink_errors(self):
        data = self.root / 'broken'; (data / 'catalog').mkdir(parents=True); (data / 'catalog/tdx_ingestion.sqlite3').write_text('not sqlite')
        status = self.make_api(data_root=data).call('get_tdx_data_status', {})
        self.assertFalse(status['ok']); self.assertIn(status['error']['code'], {'IO_ERROR', 'READ_FAILED', 'CORRUPT_ARCHIVE'})
        missing = self.make_api(data_root=data).call('read_tdx_data', {'family': 'bars_1m', 'symbol': '', 'start': '', 'end': '', 'offset': 0, 'limit': 1})
        self.assertFalse(missing['ok'])
        link = self.root / 'link'; link.symlink_to(self.source, target_is_directory=True)
        denied = self.make_api(source_workspace=link).call('list_archived_daily_sources', {})
        self.assertFalse(denied['ok']); self.assertEqual(denied['error']['code'], 'PATH_REJECTED')

    def test_result_over_64k_is_rejected_not_truncated_ok(self):
        data, lake, job = self.make_lake()
        lake.save_page(job, {'exchange': 'sz', 'code': '000001', 'bars': [{'time': '2026-09-17T09:31:00+08:00', 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume_wire_value': 1, 'amount': 1, 'blob': 'x' * 70000}]})
        result = self.make_api(data_root=data).call('read_tdx_data', {'family': 'bars_1m', 'symbol': 'sz.000001', 'start': '', 'end': '', 'offset': 0, 'limit': 1})
        self.assertFalse(result['ok']); self.assertEqual(result['error']['code'], 'RESULT_TOO_LARGE'); self.assertIsNone(result['data'])

    def test_capabilities_lists_actual_schemas_and_delegates_unknown(self):
        api = self.make_api(source_workspace=self.source)
        caps = api.call('get_capabilities', {})
        self.assertTrue(caps['ok']); self.assertTrue(caps['data']['archived_daily_read_available']); self.assertFalse(caps['data']['archived_data_write_authorized'])
        self.assertEqual(set(caps['data']['tools']), {t['name'] for t in api.schemas()})
        delegated = api.call('inner_tool', {'x': 1})
        self.assertTrue(delegated['ok']); self.assertEqual(self.inner.calls[-1], ('inner_tool', {'x': 1}))


    def test_capability_failure_and_warnings_survive_composition(self):
        api = self.make_api()
        failure = {'ok': False, 'tool': 'get_capabilities', 'data': None,
                   'evidence': [], 'warnings': ['inner warning'],
                   'error': {'code': 'INNER_FAILED', 'message': 'unavailable'}}
        with patch.object(self.inner, 'call', return_value=failure):
            self.assertEqual(api.call('get_capabilities', {}), failure)
        self.assertFalse(api.call('get_capabilities', {'path': '/tmp'})['ok'])
        good = {'ok': True, 'data': {'execution_tools_available': False},
                'evidence': [{'kind': 'original'}], 'warnings': ['inner warning']}
        with patch.object(self.inner, 'call', return_value=good):
            actual = api.call('get_capabilities', {})
        self.assertEqual(actual['evidence'], good['evidence'])
        self.assertIn('inner warning', actual['warnings'])
        self.assertFalse(actual['data']['execution_tools_available'])

    def test_capture_scan_is_bounded_before_opening_any_plans(self):
        from uuid import uuid4
        root = self.output / '_market_data' / 'retro_daily'; root.mkdir(parents=True)
        for _ in range(51): (root / str(uuid4())).mkdir()
        with patch('quantlab.agent.qm50_archived_inputs.ArchivedDailyBridge.list_sources',
                   side_effect=AssertionError('must reject before loading all plans')) as listing:
            result = self.make_api().call('list_archived_daily_sources', {})
        self.assertFalse(result['ok']); self.assertIn('50 captures', result['error']['message'])
        listing.assert_not_called()

    def test_broken_capture_remains_visible_and_listing_does_not_write(self):
        import hashlib
        from uuid import uuid4
        bad = self.retro.root / str(uuid4()); bad.mkdir(); (bad / 'plan.json').write_text('{broken')
        def hashes():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.source.rglob('*') if p.is_file()}
        before = hashes()
        result = self.make_api(source_workspace=self.source).call('list_archived_daily_sources', {})
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['data']['incomplete'])
        self.assertEqual(len(result['data']['captures']), 2)
        self.assertEqual(result['data']['errors'][0]['capture_id'], bad.name)
        self.assertEqual(result['data']['verification'], 'plan_metadata_only')
        self.assertFalse(result['data']['history_complete'])
        self.assertEqual(hashes(), before)

    def test_oversized_error_evidence_and_nonfinite_result_are_not_success(self):
        from quantlab.agent.archived_data_tools import _ok, _error, MAX_RESPONSE_BYTES
        from quantlab.storage.codec import encode
        result = _ok('read_tdx_data', {'rows': []}, evidence=[{'body': 'x' * 100000}])
        self.assertFalse(result['ok']); self.assertEqual(result['error']['code'], 'RESULT_TOO_LARGE')
        self.assertLessEqual(len(encode(result).encode()), MAX_RESPONSE_BYTES)
        self.assertTrue(result['error']['response_details_omitted'])
        nonfinite = _ok('read_tdx_data', {'price': float('nan')})
        self.assertFalse(nonfinite['ok']); self.assertEqual(nonfinite['error']['code'], 'NON_JSON_RESULT')
        huge_error = _error('read_tdx_data', 'READ_FAILED', 'broken' * 20000)
        self.assertTrue(huge_error['error']['message_truncated'])
        self.assertLessEqual(len(encode(huge_error).encode()), MAX_RESPONSE_BYTES)

if __name__ == '__main__':
    unittest.main()
