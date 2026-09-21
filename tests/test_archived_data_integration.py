"""Real product entry tests on isolated archives; no market network or real model."""
import hashlib
import json
import os
import sys
import unittest

import test_qm50_archived_inputs as daily_fixture
import test_tdx_lake as tdx_fixture
from test_agent_chat import FakeProvider
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.model_config import ModelConfig
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from mcp import Client, StdioServerParameters

GENERIC = {'list_archived_daily_sources', 'list_archived_daily_symbols',
           'inspect_archived_daily', 'get_tdx_data_status', 'read_tdx_data'}
DAILY_GENERIC = GENERIC - {'get_tdx_data_status', 'read_tdx_data'}


def fingerprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class DailySetup:
    def setUp(self):
        self.fixture = daily_fixture.ArchivedQM50Tests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.source = self.fixture.source
        self.output = self.fixture.output
        self.cap = self.fixture.cap
        self.inspect = {'capture_id': self.cap, 'symbols': 'sh.600000 sz.000001',
                        'start': self.fixture.start, 'end': self.fixture.end}
        self.symbols = {'capture_id': self.cap, 'offset': 0, 'limit': 1, 'filter_kind': 'all'}


class ArchivedDataIntegrationTests(DailySetup, unittest.TestCase):
    def test_native_chat_calls_real_shared_tools_and_saves_evidence_without_research(self):
        runtime = ChatRuntime(self.source, local_data_only=True)
        before = fingerprint(self.source / '_market_data')
        provider = FakeProvider([
            ('list_archived_daily_sources', {}),
            ('list_archived_daily_symbols', self.symbols),
            ('inspect_archived_daily', self.inspect),
        ])
        # This integration covers three complete responses; the product's
        # independent default-context guard remains covered by test_agent_chat.
        result = runtime.send(runtime.store.create(), '核对已有日线归档，不生成研究。',
                              ModelConfig(max_context_chars=100000), allow_send=True, provider=provider)
        self.assertEqual(result['tool_calls'], 3)
        self.assertTrue(all(r['ok'] for r in provider.results), provider.results)
        self.assertEqual(provider.results[0]['data']['captures'][0]['capture_id'], self.cap)
        self.assertEqual(provider.results[1]['data']['next_offset'], 1)
        inspected = provider.results[2]['data']
        self.assertTrue(inspected['raw_and_typed_bytes_verified'])
        self.assertFalse(inspected['strict_pit_qualified'])
        self.assertEqual(inspected['symbols'][0]['st_rows'], 1)
        self.assertEqual(inspected['symbols'][1]['suspended_rows'], 1)
        self.assertIn('preclose', inspected['symbols'][0]['null_counts'])
        self.assertIn('turn', inspected['symbols'][0]['null_counts'])
        self.assertTrue(result['evidence'])
        self.assertEqual(before, fingerprint(self.source / '_market_data'))
        self.assertFalse((self.source / '_jobs').exists())
        self.assertFalse((self.source / '_approval_input_freezes').exists())

    def test_legacy_aliases_share_exact_bytes_and_fixed_spec_does_not_expand(self):
        generic = build_mcp_api(self.source)
        locked = ChatRuntime(self.output, local_data_only=True,
                             research_spec=self.fixture.sid, spec_source_workspace=self.source)
        names = [t['name'] for t in locked.api.schemas()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(DAILY_GENERIC.isdisjoint(names))
        aliases = [('list_qm50_archived_sources', 'list_archived_daily_sources', {}),
                   ('list_qm50_archived_symbols', 'list_archived_daily_symbols', self.symbols),
                   ('inspect_qm50_archived_daily', 'inspect_archived_daily', self.inspect)]
        for old, new, args in aliases:
            with self.subTest(tool=old):
                legacy = locked.api.call(old, args)
                current = generic.call(new, args)
                self.assertTrue(legacy['ok'], legacy)
                self.assertEqual(legacy['tool'], old)
                self.assertEqual(legacy['data'], current['data'])
                self.assertEqual(legacy['evidence'], current['evidence'])
        for name in DAILY_GENERIC:
            denied = locked.api.call(name, {})
            self.assertEqual(denied['error']['code'], 'SPEC_SUBSTITUTION_REJECTED')
        denied = locked.api.call('run_qm50_archived_inputs', {'spec_id': self.fixture.sid, **self.inspect})
        self.assertEqual(denied['error']['code'], 'SPEC_TEST_NOT_AUTHORIZED')
        self.assertFalse((self.output / '_jobs').exists())

    def test_tools_and_capabilities_are_unique_but_presence_is_not_claimed(self):
        runtime = ChatRuntime(self.output, local_data_only=True)
        for api in (runtime.api, build_mcp_api(self.output)):
            names = [t['name'] for t in api.schemas()]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(GENERIC <= set(names))
            capability = api.call('get_capabilities', {})['data']
            self.assertEqual(set(capability['tools']), set(names))
            self.assertTrue(capability['archived_daily_read_available'])
            self.assertTrue(capability['tdx_read_available'])
            self.assertFalse(capability['archived_data_write_authorized'])
            absent = api.call('list_archived_daily_sources', {})
            self.assertTrue(absent['ok'], absent)
            self.assertEqual(absent['data']['captures'], [])
            self.assertFalse(api.call('get_tdx_data_status', {})['ok'])
        reviewer = ReviewReadOnlyAPI(self.output)
        self.assertTrue(GENERIC.isdisjoint({t['name'] for t in reviewer.schemas()}))
        for name in GENERIC:
            self.assertEqual(reviewer.call(name, {})['error']['code'], 'REVIEW_TOOL_DENIED')

    def test_raw_root_spelling_survives_mcp_and_native_chat_construction(self):
        target = self.fixture.root / 'data'; target.mkdir()
        linked = self.fixture.root / 'data-link'; linked.symlink_to(target, target_is_directory=True)
        for api in (build_mcp_api(self.output, linked),
                    ChatRuntime(self.output, linked, local_data_only=True).api):
            result = api.call('get_tdx_data_status', {})
            self.assertFalse(result['ok'], result)
            self.assertIsNone(result['data'])
        self.assertEqual(list(target.iterdir()), [])


class ArchivedMCPIntegrationTests(DailySetup, unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_and_inprocess_read_identical_packed_archives(self):
        self.fixture.retro.consolidate(self.cap, confirmed=True, remove_originals=True)
        before = fingerprint(self.source / '_market_data')
        expected = build_mcp_api(self.source).call('inspect_archived_daily', self.inspect)
        self.assertTrue(expected['ok'], expected)
        self.assertTrue(expected['data']['source_evidence']['packed'])
        params = StdioServerParameters(command=sys.executable,
            args=['-B', '-m', 'quantlab.agent.mcp_server', '--output', str(self.source)],
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        for server in (build_mcp_server(self.source), params):
            async with Client(server, read_timeout_seconds=45) as client:
                definitions = (await client.list_tools()).tools
                by_name = {t.name: t for t in definitions}
                self.assertEqual(len(by_name), len(definitions))
                self.assertTrue(GENERIC <= set(by_name))
                self.assertTrue(all(by_name[n].annotations.read_only_hint for n in GENERIC))
                self.assertNotIn('run_qm50_archived_inputs', by_name)
                self.assertNotIn('approve_proposal', by_name)
                result = await client.call_tool('inspect_archived_daily', self.inspect)
                self.assertFalse(result.is_error)
                self.assertEqual(json.loads(result.content[0].text), expected)
                bad = await client.call_tool('list_archived_daily_symbols', {**self.symbols, 'limit': 0})
                self.assertTrue(bad.is_error)
        self.assertEqual(before, fingerprint(self.source / '_market_data'))

    async def test_mcp_tdx_read_matches_legacy_preserves_units_and_structured_failure(self):
        fixture = tdx_fixture.TdxLakeTests(); self.addCleanup(fixture.doCleanups); fixture.setUp()
        row = {'time': '09:25:00', 'price': 10.2, 'matched_volume': 42,
               'unmatched_volume': 13, 'unit_note': 'unknown provider units'}
        manifest, _ = fixture.lake.save_page(fixture.job('auction'),
            {'exchange': 'sz', 'code': '000001', 'trading_date': '2026-09-17', 'points': [row]},
            observed_at='2026-09-18T01:00:00+00:00')
        args = {'family': 'auction', 'symbol': 'sz.000001', 'start': '2026-09-17',
                'end': '2026-09-17', 'offset': 0, 'limit': 1}
        api = build_mcp_api(self.output, fixture.root)
        expected = api.call('read_tdx_data', args)
        legacy = ResearchSpecAPI(api, self.output, fixture.root).call('read_tdx_data', args)
        self.assertEqual(legacy, expected)
        self.assertTrue(expected['ok'], expected)
        value = expected['data']['rows'][0]
        self.assertEqual(value['source_id'], manifest['source_id'])
        self.assertEqual(value['original_record'], row)
        self.assertEqual(value['volume_unit'], 'auction_matched_provider_units_unverified')
        self.assertEqual(value['observed_at'], '2026-09-18T01:00:00+00:00')
        self.assertNotIn('historical_available_at', value)
        async with Client(build_mcp_server(self.output, fixture.root), read_timeout_seconds=45) as client:
            result = await client.call_tool('read_tdx_data', args)
            self.assertEqual(json.loads(result.content[0].text), expected)
            invalid = await client.call_tool('read_tdx_data', {**args, 'start': '2026-09-18'})
            self.assertFalse(json.loads(invalid.content[0].text)['ok'])
        self.assertFalse((self.output / '_jobs').exists())


if __name__ == '__main__':
    unittest.main()
