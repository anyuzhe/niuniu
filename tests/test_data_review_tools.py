"""Synthetic source checks through real model/MCP/CLI entry points; no production data."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI, MAX_RESPONSE_BYTES
from quantlab.agent.data_review_cli import main
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.storage.codec import encode

NAMES = {'get_tdx_data_coverage', 'get_adjustment_review_contract', 'inspect_corporate_action_sources'}

class Inner:
    def schemas(self): return []
    def call(self, name, args):
        return {'ok':True,'tool':name,'data':{},'evidence':[],'warnings':[],'error':None}

def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}

def seed_sources(testcase):
    from datetime import date
    import polars as pl
    import test_tdx_lake
    f=test_tdx_lake.TdxLakeTests();testcase.addCleanup(f.doCleanups);f.setUp()
    f.root=f.root.resolve()  # Canonicalize this TemporaryDirectory fixture only; product link checks remain unchanged.
    f.lake.save_page(f.job('bars_daily'),{'exchange':'sz','code':'000001','bars':[
        {'time':'2026-01-01T15:00:00+08:00','open':10.,'high':11.,'low':9.,'close':10.,'volume_wire_value':1000.,'amount':10000.},
        {'time':'2026-01-02T15:00:00+08:00','open':10.,'high':11.,'low':9.,'close':10.,'volume_wire_value':1000.,'amount':10000.}]},
        observed_at='2026-09-18T00:00:00+00:00')
    f.lake.save_page(f.job('capital_changes'),{'exchange':'sz','code':'000001','records':[
        {'exchange':'sz','code':'000001','date':'2026-01-02','category_name':'除权除息',
         'c1_float':29.7,'c2_float':0.,'c3_float':0.,'c4_float':0.}]},observed_at='2026-09-18T00:00:00+00:00')
    for supplier,rows in [
        ('ths',[{'code':'sz.000001','A股除权除息日':'2026-01-02','方案进度':'实施方案','报告期':period,
                 '实施公告日':'2025-12-20','分红方案说明':text} for period,text in
                 [('2025年报','10派4.6元(含税)'),('2025特别','10派25.1元(含税)')]]),
        ('eastmoney',[{'code':'sz.000001','除权除息日':date(2026,1,2),'方案进度':'实施分配',
                      '现金分红-现金分红比例':4.6,'送转股份-送转总比例':0.}])]:
        folder=f.root/'lake/bronze'/('provider='+supplier)/'corporate_actions_dividend';folder.mkdir(parents=True,exist_ok=True)
        pl.DataFrame(rows).write_parquet(folder/'sz_000001.parquet')
    folder=f.root/'lake/silver/qfq_kline_daily';folder.mkdir(parents=True)
    pl.DataFrame({'code':['sz.000001']*2,'date':[date(2026,1,1),date(2026,1,2)],
                  'close':[8.,9.],'factor':[.8,.9]}).write_parquet(folder/'sz_000001.parquet')
    return f

class DataReviewToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.output=self.root/'out';self.output.mkdir()
        self.data=self.root/'data';self.data.mkdir()
        self.api=ArchivedMarketDataAPI(Inner(),self.output,self.data)
    def test_tools_and_capabilities_are_real_unique_and_read_only(self):
        for api in (self.api,build_mcp_api(self.output,self.data),
                    ChatRuntime(self.output,self.data,local_data_only=True).api):
            names=[item['name'] for item in api.schemas()]
            self.assertEqual(len(names),len(set(names)));self.assertTrue(NAMES<=set(names))
            caps=api.call('get_capabilities',{});self.assertTrue(caps['ok'],caps)
            self.assertTrue(NAMES<=set(caps['data']['tools']))
            self.assertTrue(caps['data']['tdx_coverage_read_available'])
            self.assertFalse(caps['data']['adjustment_rebuild_authorized'])
            self.assertFalse(caps['data']['archived_data_write_authorized'])
        reviewer=ReviewReadOnlyAPI(self.output)
        self.assertTrue(NAMES.isdisjoint({t['name'] for t in reviewer.schemas()}))
        for name in NAMES:self.assertEqual(reviewer.call(name,{})['error']['code'],'REVIEW_TOOL_DENIED')
        self.assertEqual(tree(self.data),{});self.assertFalse((self.output/'_jobs').exists())
    def test_locked_original_spec_does_not_gain_review_tools(self):
        import test_qm50_archived_inputs as fixture
        from quantlab.agent.research_spec_tools import ResearchSpecAPI
        f=fixture.ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        api=ResearchSpecAPI(self.api,f.output,self.data,active_spec=f.sid)
        self.assertTrue(NAMES.isdisjoint({item['name'] for item in api.schemas()}))
        for name in NAMES:self.assertEqual(api.call(name,{})['error']['code'],'SPEC_SUBSTITUTION_REJECTED')
    def test_contract_has_no_data_dependency_and_cli_same_contract(self):
        actual=ArchivedMarketDataAPI(Inner(),None,None).call('get_adjustment_review_contract',{})
        self.assertTrue(actual['ok'],actual);stream=io.StringIO()
        with contextlib.redirect_stdout(stream):code=main(['contract'])
        self.assertEqual(code,0);self.assertEqual(json.loads(stream.getvalue()),actual)
        self.assertEqual(tree(self.data),{})
    def test_unbound_root_and_arguments_fail_without_fallback(self):
        missing=ArchivedMarketDataAPI(Inner(),self.output,None)
        args={'family':'bars_daily','symbol':'','start':'','end':''}
        self.assertFalse(missing.call('get_tdx_data_coverage',args)['ok'])
        self.assertFalse(self.api.call('get_tdx_data_coverage',{**args,'sql':'SELECT 1'})['ok'])
        action={'symbol':'sh.600000','start':'2020-01-01','end':'2020-01-02','offset':0,'limit':20}
        for changed in ({'path':'/tmp'},{'limit':True},{'offset':-1},{'limit':21}):
            self.assertFalse(self.api.call('inspect_corporate_action_sources',{**action,**changed})['ok'])
        self.assertEqual(tree(self.data),{})
    def test_oversize_candidate_is_error_not_truncated_success(self):
        args={'symbol':'sh.600000','start':'2020-01-01','end':'2020-01-02','offset':0,'limit':20}
        with patch('quantlab.data.corporate_action_review.inspect_corporate_action_sources',
                   return_value={'events':[{'text':'x'*70000}],'incomplete':True,'errors':['blocked']}):
            result=self.api.call('inspect_corporate_action_sources',args)
        self.assertFalse(result['ok']);self.assertIsNone(result['data'])
        self.assertEqual(result['error']['code'],'RESULT_TOO_LARGE')
        self.assertLessEqual(len(encode(result).encode()),MAX_RESPONSE_BYTES)
    def test_cli_incomplete_and_failure_are_not_zero_exit(self):
        argv=['corporate-actions','--data-root',str(self.data),'--symbol','sh.600000','--start','2020-01-01','--end','2020-01-02']
        with patch('quantlab.data.corporate_action_review.inspect_corporate_action_sources',
                   return_value={'incomplete':True,'errors':['missing_source']}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(argv),3)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['tdx-coverage','--data-root',str(self.data),'--family','BAD']),2)
    def test_qfq_notice_does_not_change_values_or_raw_contract(self):
        import test_core
        from quantlab.agent.local_data_tools import LocalMarketDataTools
        f=test_core.CoreTests();f.setUp();self.addCleanup(f.tearDown)
        before=tree(f.root);api=LocalMarketDataTools(f.root)
        args={'timeframe':'1d','adjustment':'qfq','offset':0,'limit':1}
        value=api.call('list_local_market_data',args);self.assertTrue(value['ok'],value)
        notice=value['data']['adjustment_review'];self.assertFalse(notice['corporate_actions_complete_verified'])
        self.assertEqual(notice['known_issue_list_status'],'not_bound')
        raw=api.call('list_local_market_data',{**args,'adjustment':'raw'})
        self.assertTrue(raw['ok'],raw);self.assertNotIn('adjustment_review',raw['data'])
        profile=api.call('inspect_local_market_data',{'timeframe':'1d','adjustment':'qfq','symbols':f.symbols[0],
                      'start':'2025-01-01','end':'2025-01-10'})
        self.assertTrue(profile['ok'],profile);self.assertTrue(profile['data']['request_loadable'])
        self.assertEqual(profile['data']['adjustment_review'],notice);self.assertEqual(before,tree(f.root))

    def test_actual_coverage_and_company_sources_are_shared_with_cli(self):
        f=seed_sources(self);before=tree(f.root)
        api=build_mcp_api(self.output,f.root)
        args={'family':'bars_daily','symbol':'sz.000001','start':'2026-01-01','end':'2026-01-02'}
        result=api.call('get_tdx_data_coverage',args);self.assertTrue(result['ok'],result)
        self.assertEqual(result['data']['rows'],2);self.assertEqual(result['data']['codes'],1)
        self.assertEqual(result['data']['event_dates'],2);self.assertEqual(result['data']['date_axis'],'event_date')
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):code=main(['tdx-coverage','--data-root',str(f.root),'--family','bars_daily',
            '--symbol','sz.000001','--start','2026-01-01','--end','2026-01-02'])
        self.assertEqual(code,0);self.assertEqual(json.loads(stream.getvalue()),result)
        action={'symbol':'sz.000001','start':'2026-01-01','end':'2026-01-02','offset':0,'limit':20}
        reviewed=api.call('inspect_corporate_action_sources',action);self.assertTrue(reviewed['ok'],reviewed)
        self.assertTrue(reviewed['data']['events']);self.assertFalse(reviewed['data']['official_verified'])
        self.assertFalse(reviewed['data']['reconstruction_authorized'])
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):code=main(['corporate-actions','--data-root',str(f.root),
            '--symbol','sz.000001','--start','2026-01-01','--end','2026-01-02'])
        self.assertIn(code,(0,3));self.assertEqual(json.loads(stream.getvalue()),reviewed)
        self.assertEqual(tree(f.root),before)

    def test_coverage_coexists_with_existing_read_connection(self):
        import duckdb
        f=seed_sources(self);before=tree(f.root)
        with duckdb.connect(str(f.lake.catalog),read_only=True) as other:
            settings=other.execute("select current_setting('threads'),current_setting('memory_limit')").fetchone()
            result=build_mcp_api(self.output,f.root).call('get_tdx_data_coverage',
                {'family':'bars_daily','symbol':'','start':'','end':''})
            self.assertTrue(result['ok'],result);self.assertEqual(result['data']['rows'],2)
            self.assertEqual(settings,other.execute("select current_setting('threads'),current_setting('memory_limit')").fetchone())
            self.assertEqual(other.execute('select count(*) from tdx_bars_daily').fetchone()[0],2)
        self.assertEqual(tree(f.root),before)

    def test_non_event_coverage_discloses_filter_warning(self):
        f=seed_sources(self)
        data=f.lake.coverage('depth',start='2026-09-17',end='2026-09-18')
        self.assertEqual(data['date_axis'],'observed_date')
        self.assertIn('date_filter_is_not_event_date',data['warnings'])
        self.assertIsNone(data['event_dates']);self.assertIsNone(data['per_symbol_event_days'])

    def test_chat_uses_actual_review_tools_without_starting_research(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        f=seed_sources(self);before=tree(f.root)
        runtime=ChatRuntime(self.output,f.root,local_data_only=True)
        provider=FakeProvider([('get_tdx_data_coverage',{'family':'bars_daily','symbol':'sz.000001','start':'','end':''}),
            ('inspect_corporate_action_sources',{'symbol':'sz.000001','start':'2026-01-01','end':'2026-01-02','offset':0,'limit':20})])
        result=runtime.send(runtime.store.create(),'只核对已存资料，不执行研究。',
            ModelConfig(max_context_chars=120000),allow_send=True,provider=provider)
        self.assertEqual(result['tool_calls'],2);self.assertTrue(all(r['ok'] for r in provider.results),provider.results)
        self.assertEqual(provider.results[0]['data']['rows'],2)
        self.assertFalse(provider.results[1]['data']['official_verified'])
        self.assertEqual(before,tree(f.root));self.assertFalse((self.output/'_jobs').exists())

class DataReviewMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_mcp_stdio_and_local_api_share_contract_and_bounds(self):
        from mcp import Client,StdioServerParameters
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();output=root/'out';data=root/'data';output.mkdir();data.mkdir()
            expected=build_mcp_api(output,data).call('get_adjustment_review_contract',{})
            params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
                '--output',str(output),'--data-root',str(data)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            for server in (build_mcp_server(output,data),params):
                async with Client(server,read_timeout_seconds=45) as client:
                    definitions=(await client.list_tools()).tools;tools={item.name:item for item in definitions}
                    self.assertEqual(len(tools),len(definitions));self.assertTrue(NAMES<=set(tools))
                    self.assertTrue(all(tools[n].annotations.read_only_hint for n in NAMES))
                    result=await client.call_tool('get_adjustment_review_contract',{})
                    self.assertEqual(json.loads(result.content[0].text),expected)
                    denied=await client.call_tool('inspect_corporate_action_sources',{'symbol':'sh.600000',
                        'start':'2020-01-01','end':'2020-01-02','offset':0,'limit':21})
                    self.assertTrue(denied.is_error)
            self.assertEqual(tree(data),{});self.assertFalse((output/'_jobs').exists())

    async def test_stdio_reads_actual_candidates_and_coverage(self):
        from mcp import Client,StdioServerParameters
        f=seed_sources(self);before=tree(f.root)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp).resolve();api=build_mcp_api(output,f.root)
            calls=[('get_tdx_data_coverage',{'family':'bars_daily','symbol':'sz.000001','start':'','end':''}),
                   ('inspect_corporate_action_sources',{'symbol':'sz.000001','start':'2026-01-01','end':'2026-01-02','offset':0,'limit':20})]
            params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
                '--output',str(output),'--data-root',str(f.root)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            async with Client(params,read_timeout_seconds=45) as client:
                for name,args in calls:
                    expected=api.call(name,args);self.assertTrue(expected['ok'],expected)
                    actual=await client.call_tool(name,args)
                    self.assertFalse(actual.is_error);self.assertEqual(json.loads(actual.content[0].text),expected)
            self.assertEqual(tree(f.root),before);self.assertFalse((output/'_jobs').exists())

if __name__=='__main__':unittest.main()
