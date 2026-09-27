"""Independent Phase2 integration tests, using real local registry bindings."""
import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
from quantlab.experiments import computation as comp
from quantlab.storage.codec import encode, digest
from quantlab.agent.research_links import get_run_research_links
from quantlab.experiments.trial_registry import create_registry, bind_result, report_registry
from quantlab.storage.trial_reproduction import archive_registry
from quantlab.statistics.permutation import PermutationConfig
from test_context_experiments import ContextProvider, context_config, runner

class ComputationContractTests(unittest.TestCase):
    def test_real_resource_ui_and_dependency_changes_have_distinct_cache_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'experiments').mkdir();(root/'desktop').mkdir();(root/'factors').mkdir()
            core=root/'factors/core.py';core.write_text('x=1\n')
            resource=root/'factors/alpha_expressions.json';resource.write_text('{"a":1}')
            ui=root/'desktop/view.py';ui.write_text('ui=1\n')
            with patch.object(comp,'__file__',str(root/'experiments/computation.py')):
                original=comp.computation_fingerprint()
                ui.write_text('ui=2\n');self.assertEqual(original,comp.computation_fingerprint())
                resource.write_text('{"a":2}');resource_changed=comp.computation_fingerprint()
                self.assertNotEqual(original['code_hash'],resource_changed['code_hash'])
                core.write_text('x=2\n');self.assertNotEqual(resource_changed['code_hash'],comp.computation_fingerprint()['code_hash'])
                dep_changed={**original,'dependencies':{**original['dependencies'],'numpy':'different'}}
                self.assertNotEqual(comp.computation_cache_key(original),comp.computation_cache_key(dep_changed))
    def test_full_runtime_cannot_bypass_new_resource_or_dependency_mismatch(self):
        value=comp.computation_fingerprint();runtime={'code_hash':'full-python'}
        bad={**value,'code_hash':'0'*64}
        self.assertFalse(comp.manifest_runtime_compatible({'runtime':runtime,'computation_runtime':bad},runtime,value)[0])
        self.assertTrue(comp.manifest_runtime_compatible({'runtime':{'other':1},'computation_runtime':value},runtime,value)[0])
        self.assertFalse(comp.manifest_runtime_compatible({'runtime':{'other':1}},runtime,value)[0])
        self.assertTrue(comp.manifest_runtime_compatible({'runtime':runtime},runtime,value)[0])
        self.assertFalse(comp.manifest_runtime_compatible({'runtime':runtime,'computation_runtime':{}},runtime,value)[0])
        self.assertFalse(comp.archived_runtimes_compatible({'runtime':runtime,'computation_runtime':value},{'runtime':runtime,'computation_runtime':bad})[0])
    def test_malformed_computation_contract_never_matches_itself(self):
        value={'version':comp.VERSION,'code_hash':None,'python':None,'dependencies':{}}
        self.assertFalse(comp.compatible_computation_runtime(value,value)[0])
        with self.assertRaises(ValueError):comp.computation_cache_key(value)

class ResearchLinkContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def family(self):
        cfg=replace(context_config(),context=None,replay=True,horizons=(1,),quantiles=3,permutation=PermutationConfig())
        registry=self.root/'_trial_registries'/str(uuid4());registry.parent.mkdir(exist_ok=True)
        plan={'name':'predefined local family','alpha':0.05,'trials':[{'trial_id':'t1','config':json.loads(encode(asdict(cfg)))}]}
        create_registry(plan,registry)
        result=runner(ContextProvider(),self.root).run(cfg)
        bind_result(registry,'t1',result.artifact_path)
        return result,registry
    def test_live_and_archived_families_use_real_fingerprints(self):
        source,registry=self.family()
        live=get_run_research_links(self.root,source.run_id)
        self.assertEqual(live['status'],'REGISTERED');self.assertEqual(live['registered_families'][0]['source_kind'],'live_registry')
        report=self.root/'_trial_reports'/str(uuid4());report.parent.mkdir()
        report_registry(registry,report);archived=archive_registry(report,self.root)
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        data=get_run_research_links(self.root,source.run_id)
        self.assertEqual({x['source_kind'] for x in data['registered_families']},{'live_registry','archive'})
        self.assertIn(archived['run_id'],[x['registry_run_id'] for x in data['registered_families']])
        self.assertEqual(data['errors'],[])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_tampered_binding_is_unknown_not_registered(self):
        source,registry=self.family();p=registry/'results/t1.json';value=json.loads(p.read_text())
        value['binding_id']='invented';p.write_text(json.dumps(value))
        result=get_run_research_links(self.root,source.run_id)
        self.assertEqual(result['status'],'UNKNOWN');self.assertFalse(result['registered_families']);self.assertTrue(result['errors'])
    def test_paging_visits_each_source_without_false_negative_certificate(self):
        source,registry=self.family()
        for i in range(3):
            folder=self.root/str(uuid4());folder.mkdir();(folder/'experiment.json').write_text('{}')
        offset=0;scanned=0;families=[];inventory=None
        while True:
            page=get_run_research_links(self.root,source.run_id,offset=offset,limit=1)
            self.assertNotEqual(page['status'],'UNREGISTERED')
            if inventory is not None:self.assertEqual(inventory,page['inventory_digest'])
            inventory=page['inventory_digest'];scanned+=page['scanned'];families+=page['registered_families']
            if page['next_offset'] is None:break
            self.assertGreater(page['next_offset'],offset);offset=page['next_offset']
        self.assertEqual(scanned,page['total_sources']);self.assertEqual(len(families),1)
    def test_root_and_local_registry_symlinks_are_not_followed(self):
        source,registry=self.family();link=self.root.parent/(self.root.name+'-link')
        link.symlink_to(self.root);self.addCleanup(link.unlink)
        with self.assertRaises(ValueError):get_run_research_links(link,source.run_id)
        with self.assertRaises(ValueError):get_run_research_links(self.root,source.run_id,offset=True)
    def test_formal_chat_and_mcp_have_readonly_link_tools(self):
        source,registry=self.family()
        from quantlab.agent.chat_cli import headless_chat_runtime
        with headless_chat_runtime(self.root,local_data_only=True) as runtime:
            names={t['name'] for t in runtime.api.schemas()}
            self.assertIn('get_run_research_links',names)
            result=runtime.api.call('get_run_research_links',{'run_id':source.run_id,'offset':0,'limit':10})
            self.assertTrue(result['ok'],result);self.assertEqual(result['data']['status'],'REGISTERED')
        from quantlab.agent.mcp_server import build_mcp_server
        server=build_mcp_server(self.root)
        async def check():
            self.assertIn('get_run_research_links',{t.name for t in await server.list_tools()})
            result=await server.call_tool('get_run_research_links',{'run_id':source.run_id,'offset':0,'limit':10})
            self.assertIn('REGISTERED',str(result))
            with self.assertRaises(Exception):
                await server.call_tool('get_run_research_links',{'run_id':source.run_id,'offset':0,'limit':10,'path':'/tmp'})
        asyncio.run(check())
