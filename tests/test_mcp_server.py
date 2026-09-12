import asyncio
from importlib.util import find_spec
from pathlib import Path
import sys,tempfile,unittest

MCP_AVAILABLE=find_spec('mcp') is not None
if MCP_AVAILABLE:
    from mcp import Client,StdioServerParameters
    from quantlab.agent.mcp_server import build_mcp_server,run_mcp
    from quantlab.agent.market_data_tools import MarketDataResearchAPI


@unittest.skipUnless(MCP_AVAILABLE,'optional mcp dependency is not installed')
class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_process_tools_match_existing_model_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);server=build_mcp_server(root)
            expected=[t['name'] for t in MarketDataResearchAPI(root).schemas()]
            async with Client(server) as client:
                listed=await client.list_tools();names=[t.name for t in listed.tools]
                self.assertEqual(names,expected);self.assertTrue(client.protocol_version)
                result=await client.call_tool('get_capabilities',{})
                self.assertFalse(result.is_error);self.assertIn('execution_tools_available',result.content[0].text)
                by_name={t.name:t for t in listed.tools}
                self.assertTrue(by_name['describe_factor'].annotations.read_only_hint)
                self.assertFalse(by_name['propose_dsl_candidate'].annotations.read_only_hint)
            for forbidden in ('approve_proposal','register_dsl_candidate','execute_incremental_evidence','submit_alpha_factory',
                    'sync_alpha_factory','promote_alpha_candidate','download_baostock','authorize_tracking','run_shell'):
                self.assertNotIn(forbidden,names)

    async def test_stdio_subprocess_and_argument_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            params=StdioServerParameters(command=sys.executable,args=['-m','quantlab.agent.mcp_server','--output',str(root)])
            async with Client(params,read_timeout_seconds=15) as client:
                listed=await client.list_tools();self.assertGreater(len(listed.tools),20)
                good=await client.call_tool('search_factors',{'query':'momentum','offset':0,'limit':3})
                self.assertFalse(good.is_error);self.assertIn('BASE.MOMENTUM',good.content[0].text)
                bad=await client.call_tool('search_factors',{'query':'','offset':0,'limit':0})
                self.assertTrue(bad.is_error)

    async def test_http_never_binds_non_loopback(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'回环'):
                run_mcp(Path(temp),transport='streamable-http',host='0.0.0.0',port=8766)
