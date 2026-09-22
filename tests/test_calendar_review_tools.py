"""F16 real API/CLI/stdio boundaries on isolated data, not real-model research."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch
import polars as pl
import test_calendar_review as fixtures
from quantlab.agent.mcp_server import build_mcp_api, build_mcp_server
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.data_review_cli import main
from quantlab.agent.archived_data_tools import MAX_RESPONSE_BYTES
from quantlab.storage.codec import encode

NAMES={'get_trading_calendar','check_daily_date_coverage'}

class Setup:
    def setUp(self):
        self.f=fixtures.CalendarReviewTests();self.addCleanup(self.f.doCleanups);self.f.setUp()
        self.output=self.f.root/'out';self.output.mkdir()
        self.api=build_mcp_api(self.output,self.f.root)
        self.args={**self.f.args,'symbols':'sh.600001'}
    def cli(self,command='daily-coverage',*extra):
        args=[command,'--source','baostock_bronze','--data-root',str(self.f.root),
              '--start',self.f.args['start'],'--end',self.f.args['end']]
        if command=='daily-coverage':args+=['--symbols','sh.600001']
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=main([*args,*extra])
        return code,json.loads(out.getvalue())

class CalendarToolTests(Setup,TestCase):
    def test_cli_same_source_and_complete_incomplete_failure_exit_codes(self):
        expected=self.api.call('check_daily_date_coverage',self.args)
        self.assertTrue(expected['ok'],expected)
        code,got=self.cli();self.assertEqual(code,0);self.assertEqual(got,expected)
        self.f.bars.head(1).write_parquet(self.f.bar_path)
        code,got=self.cli();self.assertEqual(code,3);self.assertTrue(got['data']['incomplete'])
        self.f.calendar_path.write_bytes(b'broken')
        code,got=self.cli('calendar');self.assertEqual(code,2);self.assertFalse(got['ok'])
    def test_calendar_stale_exits_three_and_never_opens_market(self):
        self.f.calendar.head(4).write_parquet(self.f.calendar_path)
        with patch('quantlab.data.calendar_review._Source.bars',side_effect=AssertionError('do not read')) as read:
            code,result=self.cli();self.assertEqual(code,3);read.assert_not_called()
        self.assertEqual(result['data']['status'],'blocked')
    def test_schema_no_default_source_no_model_paths_and_unique_tools(self):
        tools=self.api.schemas();names=[t['name'] for t in tools]
        self.assertEqual(len(names),len(set(names)));self.assertTrue(NAMES<=set(names))
        caps=self.api.call('get_capabilities',{})['data']
        self.assertTrue(caps['calendar_source_review_available']);self.assertFalse(caps['calendar_review_write_authorized'])
        for args in ({k:v for k,v in self.args.items() if k!='source'},
                     {**self.args,'path':str(self.f.root)}, {**self.args,'source':'latest'},
                     {**self.args,'symbols':' '.join('sh.'+str(600001+i) for i in range(11))}):
            self.assertFalse(self.api.call('check_daily_date_coverage',args)['ok'])
    def test_native_chat_uses_actual_tools_without_creating_jobs(self):
        from test_agent_chat import FakeProvider
        from quantlab.agent.model_config import ModelConfig
        before=self.f.tree();runtime=ChatRuntime(self.output,self.f.root,local_data_only=True)
        provider=FakeProvider([('get_trading_calendar',self.f.args),('check_daily_date_coverage',self.args)])
        result=runtime.send(runtime.store.create(),'只核对这批日期，不执行研究',
                            ModelConfig(max_context_chars=150000),allow_send=True,provider=provider)
        self.assertEqual(result['tool_calls'],2)
        self.assertTrue(all(r['ok'] for r in provider.results),provider.results)
        self.assertFalse((self.output/'_jobs').exists());self.assertFalse((self.output/'_approval_input_freezes').exists())
        # Chat journal is expected; only data files must be unchanged.
        self.assertEqual({k:v for k,v in self.f.tree().items() if not k.startswith('out/')},
                         {k:v for k,v in before.items() if not k.startswith('out/')})
    def test_reviewer_and_locked_qm50_permissions_not_extended(self):
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        import test_qm50_archived_inputs as locked_fixture
        f=locked_fixture.ArchivedQM50Tests();self.addCleanup(f.doCleanups);f.setUp()
        locked=ChatRuntime(f.output,local_data_only=True,research_spec=f.sid,spec_source_workspace=f.source).api
        reviewer=ReviewReadOnlyAPI(self.output,self.f.root)
        for api in (locked,reviewer):
            self.assertTrue(NAMES.isdisjoint({t['name'] for t in api.schemas()}))
            for name in NAMES:self.assertFalse(api.call(name,{})['ok'])
    def test_oversized_full_dates_are_rejected_not_truncated_success(self):
        with patch('quantlab.data.calendar_review.check_daily_date_coverage',return_value={
                'records':[{'missing_dates':['2025-01-01']*10000}],'evidence':[]}):
            result=self.api.call('check_daily_date_coverage',self.args)
        self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'RESULT_TOO_LARGE')
        self.assertLessEqual(len(encode(result).encode()),MAX_RESPONSE_BYTES)
    def test_mcp_rejects_extra_fields_before_reading_even_on_existing_tool(self):
        import asyncio
        from mcp.server.mcpserver.exceptions import ToolError
        server=build_mcp_server(self.output,self.f.root)
        async def probe():
            with patch('quantlab.data.calendar_review.get_trading_calendar',side_effect=AssertionError('no read')) as read:
                with self.assertRaises(ToolError):
                    await server.call_tool('get_trading_calendar',{**self.f.args,'path':'/tmp'})
                read.assert_not_called()
            with self.assertRaises(ToolError):
                await server.call_tool('get_adjustment_review_contract',{'source':'override'})
            with self.assertRaises(ToolError):
                await server.call_tool('get_trading_calendar',{'source':'baostock_bronze'})
        asyncio.run(probe())
    def test_retro_cli_requires_separate_explicit_source_workspace(self):
        import test_archived_daily_dataset as archive_fixture
        f=archive_fixture.ArchivedDailyDatasetTests();self.addCleanup(f.doCleanups);f.setUp()
        args=['daily-coverage','--source','retro_capture','--capture-id',f.capture_id,
              '--start',f.start,'--end',f.end,'--symbols',f.symbols]
        for additional,expected in (([],2),(['--source-workspace',str(f.source)],0)):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):code=main(args+additional)
            self.assertEqual(code,expected,out.getvalue())

class CalendarMCPTests(Setup,IsolatedAsyncioTestCase):
    async def test_real_stdio_matches_direct_and_rejects_extra_fields(self):
        from mcp import Client,StdioServerParameters
        expected=self.api.call('check_daily_date_coverage',self.args)
        params=StdioServerParameters(command=sys.executable,args=['-B','-m','quantlab.agent.mcp_server',
            '--output',str(self.output),'--data-root',str(self.f.root)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        for server in (build_mcp_server(self.output,self.f.root),params):
            async with Client(server,read_timeout_seconds=45) as client:
                definitions=(await client.list_tools()).tools;tools={t.name:t for t in definitions}
                self.assertTrue(all(tools[n].annotations.read_only_hint for n in NAMES))
                self.assertTrue(all(tools[n].input_schema.get('additionalProperties') is False for n in NAMES))
                result=await client.call_tool('check_daily_date_coverage',self.args)
                self.assertEqual(json.loads(result.content[0].text),expected)
                invalid=await client.call_tool('get_trading_calendar',{**self.f.args,'path':'/tmp'})
                self.assertTrue(invalid.is_error)
        self.assertFalse((self.output/'_jobs').exists())
