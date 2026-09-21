"""Explicit F11 input checks, using real finite packages and no business data."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import os
import sys
import json
import unittest
from unittest.mock import patch

import test_archived_dataset_lifecycle as fixtures
from quantlab.data.archived_research_check import check_archived_daily_research
from quantlab.data.archived_daily_dataset import MARKER, ArchivedDailyDatasetProvider
from quantlab.storage.codec import digest, encode


class ArchivedResearchCheckTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ArchivedDatasetLifecycleTests();self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.exported=self.fx.export()

    def check(self, **changes):
        return check_archived_daily_research(self.fx.destination,{**self.fx.spec,**changes})

    def test_matching_input_is_readonly_reproducible_and_not_authorization(self):
        before=fixtures.files(self.fx.root);spec=deepcopy(self.fx.spec)
        with patch('quantlab.workbench.jobs.JobQueue',side_effect=AssertionError('queue')):
            result=self.check()
        self.assertTrue(result['compatible'],result)
        self.assertEqual(result['dataset_id'],self.exported['dataset_id'])
        self.assertEqual(result['requirements'][0]['rows'],len(self.fx.symbols)*len(self.fx.sessions))
        self.assertEqual(result['check_hash'],digest({k:v for k,v in result.items() if k!='check_hash'}))
        self.assertEqual(result,self.check())
        self.assertEqual(spec,self.fx.spec);self.assertEqual(before,fixtures.files(self.fx.root))
        for key in ('research_approved','research_executed','factor_computed','statistical_sufficiency_checked'):
            self.assertIs(result[key],False)

    def test_collects_all_scope_mismatches_without_modifying_spec(self):
        spec={**self.fx.spec,'symbols':['sh.600001'],'adjustment':'qfq','timeframe':'5m',
              'start':'2026-06-01','end':'2026-09-01','qualification':'strict_pit','universe':{'mode':'listing'}}
        original=deepcopy(spec)
        result=check_archived_daily_research(self.fx.destination,spec)
        codes={b['code'] for b in result['blockers']}
        self.assertEqual(codes,{'ADJUSTMENT_MISMATCH','TIMEFRAME_MISMATCH','SYMBOLS_OUTSIDE_PACKAGE',
                               'DATES_OUTSIDE_PACKAGE','QUALIFICATION_NOT_SUPPORTED','UNIVERSE_NOT_IN_PACKAGE'})
        self.assertFalse(result['compatible']);self.assertEqual(spec,original)
        self.assertIsNone(result['requirements'][0]['snapshot_id'])

    def test_omitted_adjustment_resolves_to_existing_qfq_default(self):
        spec={k:v for k,v in self.fx.spec.items() if k!='adjustment'}
        result=check_archived_daily_research(self.fx.destination,spec)
        self.assertEqual(result['requirements'][0]['adjustment'],'qfq')
        self.assertIn('ADJUSTMENT_MISMATCH',{b['code'] for b in result['blockers']})
        self.assertNotIn('adjustment',spec)

    def test_context_scope_is_not_hidden_by_primary_input_error(self):
        result=self.check(timeframe='5m',context={'start':'2026-06-01','factor_id':'BASE.MOMENTUM',
                           'version':'1.0.0','parameters':{'lookback':2}})
        self.assertEqual([r['role'] for r in result['requirements']],['signal','context'])
        self.assertIn(('signal','TIMEFRAME_MISMATCH'),{(b['role'],b['code']) for b in result['blockers']})
        self.assertIn(('context','DATES_OUTSIDE_PACKAGE'),{(b['role'],b['code']) for b in result['blockers']})

    def test_valid_subset_uses_exact_requested_rows(self):
        result=self.check(symbols=[self.fx.symbols[0]],start='2026-07-06',end='2026-07-10')
        self.assertTrue(result['compatible']);self.assertEqual(result['requirements'][0]['rows'],5)
        self.assertEqual(result['requirements'][0]['first_session'],'2026-07-06')

    def test_empty_trading_subrange_is_a_blocker_not_an_empty_success(self):
        result=self.check(start='2026-07-04',end='2026-07-05')
        self.assertFalse(result['compatible'])
        self.assertEqual(result['blockers'][0]['code'],'NO_TRADING_SESSIONS')

    def test_invalid_config_and_campaign_are_rejected_before_source_read(self):
        with patch('quantlab.data.archived_research_check.inspect_archived_daily_dataset',side_effect=AssertionError('read')) as read:
            for spec in ({**self.fx.spec,'unsupported':True},{'mode':'campaign'},
                         {**self.fx.spec,'universe':{'mode':'listing','reference_manifest':'/outside/secret'}}):
                with self.subTest(spec=spec),self.assertRaises(ValueError):
                    check_archived_daily_research(self.fx.destination,spec)
            read.assert_not_called()

    def test_wrong_roots_and_bad_package_never_fallback(self):
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('fallback')):
            for root in (None,self.fx.source):
                with self.subTest(root=root),self.assertRaises(ValueError):check_archived_daily_research(root,self.fx.spec)
            alias=self.fx.root/'alias';alias.symlink_to(self.fx.destination,target_is_directory=True)
            with self.assertRaises(ValueError):check_archived_daily_research(alias,self.fx.spec)
            (self.fx.destination/MARKER).write_text('{}')
            with self.assertRaises(ValueError):self.check()

    def test_later_tampering_is_not_served_from_a_previous_check(self):
        self.assertTrue(self.check()['compatible'])
        (self.fx.destination/'normalized/bars.parquet').write_bytes(b'bad')
        with self.assertRaises(ValueError):self.check()

    def test_mixed_source_identity_during_read_is_rejected(self):
        original=ArchivedDailyDatasetProvider.load
        def changed(provider,request):
            batch=original(provider,request)
            snapshot=replace(batch.snapshot,files=tuple({**f,'dataset_id':'0'*64} for f in batch.snapshot.files))
            return replace(batch,snapshot=snapshot)
        with patch.object(ArchivedDailyDatasetProvider,'load',changed),self.assertRaisesRegex(ValueError,'identity changed'):
            self.check()

    def test_strategy_envelope_supported_without_running_execution(self):
        from test_strategy_package_cli import package_fixture
        from quantlab.trading.strategy_package import compile_strategy
        package=package_fixture();package['spec'].update(symbols=self.fx.symbols,start=self.fx.start,end=self.fx.end,adjustment='raw')
        spec=compile_strategy(package)['spec']
        with patch('quantlab.experiments.execution.ExecutionStudy.run',side_effect=AssertionError('execution')):
            result=check_archived_daily_research(self.fx.destination,spec)
        self.assertTrue(result['compatible'],result);self.assertEqual(result['spec_digest'],digest(spec))

    def test_account_dependencies_are_not_certified_from_bars(self):
        result=self.check(mode='execution',execution={'price_mode':'account'})
        self.assertFalse(result['compatible'])
        self.assertIn('ACCOUNT_DEPENDENCIES_NOT_CHECKED',{b['code'] for b in result['blockers']})

    def test_real_chat_and_mcp_share_checker_and_do_not_gain_write_tools(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.mcp_server import build_mcp_api,build_mcp_server
        apis=[ChatRuntime(self.fx.output,self.fx.destination).api,build_mcp_api(self.fx.output,self.fx.destination)]
        expected=self.check();args={'spec_json':encode(self.fx.spec)}
        for api in apis:
            names=[t['name'] for t in api.schemas()]
            self.assertIn('check_archived_daily_research',names);self.assertEqual(len(names),len(set(names)))
            result=api.call('check_archived_daily_research',args)
            self.assertTrue(result['ok'],result);self.assertEqual(result['data'],expected)
            denied=api.call('check_archived_daily_research',{**args,'data_root':'/untrusted'})
            self.assertFalse(denied['ok'])
            for name in ('approve_proposal','export_archived_daily_dataset','authorize_grant'):
                self.assertNotIn(name,names)
        self.assertFalse((self.fx.output/'_jobs').exists())
        self.assertFalse((self.fx.output/'_approval_input_freezes').exists())
        self.assertFalse((self.fx.output/'_research_session_grants').exists())

    def test_real_mcp_stdio_and_inprocess_share_readonly_check(self):
        from mcp import Client, StdioServerParameters
        from quantlab.agent.mcp_server import build_mcp_server
        expected=self.check();before=fixtures.files(self.fx.root)
        params=StdioServerParameters(command=sys.executable,
            args=['-B','-m','quantlab.agent.mcp_server','--output',str(self.fx.output),
                  '--data-root',str(self.fx.destination)],
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        async def exercise():
            for server in (build_mcp_server(self.fx.output,self.fx.destination),params):
                async with Client(server,read_timeout_seconds=45) as client:
                    definitions=(await client.list_tools()).tools
                    by_name={t.name:t for t in definitions}
                    self.assertTrue(by_name['check_archived_daily_research'].annotations.read_only_hint)
                    result=await client.call_tool('check_archived_daily_research',{'spec_json':encode(self.fx.spec)})
                    self.assertFalse(result.is_error)
                    value=json.loads(result.content[0].text)
                    self.assertTrue(value['ok'],value);self.assertEqual(value['data'],expected)
        asyncio.run(exercise());self.assertEqual(before,fixtures.files(self.fx.root))

    def test_locked_original_spec_cannot_substitute_generic_input_check(self):
        import test_research_spec_fidelity as fidelity
        from quantlab.agent.research_specs import ResearchSpecStore
        from quantlab.agent.research_spec_tools import ResearchSpecAPI
        from quantlab.agent.mcp_server import build_mcp_api
        folder=self.fx.root/'original-spec';folder.mkdir()
        md,js=fidelity.synthetic_pair(folder)
        sid=ResearchSpecStore(self.fx.output).import_pair(md,js,confirmed=True)['spec_id']
        inner=build_mcp_api(self.fx.output,self.fx.destination)
        api=ResearchSpecAPI(inner,self.fx.output,self.fx.destination,active_spec=sid)
        self.assertNotIn('check_archived_daily_research',{t['name'] for t in api.schemas()})
        with patch('quantlab.data.archived_research_check.check_archived_daily_research',side_effect=AssertionError('dispatch')):
            value=api.call('check_archived_daily_research',{'spec_json':encode(self.fx.spec)})
        self.assertFalse(value['ok']);self.assertEqual(value['error']['code'],'SPEC_SUBSTITUTION_REJECTED')

    def test_tool_distinguishes_bad_request_from_valid_but_incompatible_request(self):
        from quantlab.agent.mcp_server import build_mcp_api
        api=build_mcp_api(self.fx.output,self.fx.destination)
        for text in ('{"mode":"single","mode":"execution"}','{"x":NaN}','x'*65537):
            self.assertFalse(api.call('check_archived_daily_research',{'spec_json':text})['ok'])
        result=api.call('check_archived_daily_research',{'spec_json':encode({**self.fx.spec,'adjustment':'qfq'})})
        self.assertTrue(result['ok']);self.assertFalse(result['data']['compatible'])
        self.assertTrue(result['data']['blockers'])


if __name__=='__main__':unittest.main()
