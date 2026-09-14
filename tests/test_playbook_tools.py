import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.playbook_tools import PlaybookResearchAPI
from quantlab.trading.playbook_store import PlaybookStore


class PlaybookToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=PlaybookStore(self.root)
    def tearDown(self):self.temp.cleanup()

    def test_agent_can_only_read_playbook_evidence(self):
        source=self.store.create_source(str(uuid4()),{'expert_key':'qimofenshu','title':'原始记录',
            'source_type':'PUBLIC_POST','locator':'https://example.invalid/x','available_at':'2024-01-01T09:00:00+08:00',
            'content_hash':'b'*64,'completeness':'VERIFIED'})
        api=PlaybookResearchAPI(self.root);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_playbook_overview',names);self.assertIn('list_expert_sources',names)
        self.assertIn('list_strategy_sources',names);self.assertIn('get_playbook_definition_sources',names)
        self.assertFalse(any(name.startswith(('create_playbook','save_playbook','record_playbook')) for name in names))
        listed=api.call('list_expert_sources',{'query':'期末' if False else '原始','offset':0,'limit':20})
        self.assertTrue(listed['ok']);self.assertEqual(listed['data']['total'],1)
        got=api.call('get_expert_source',{'source_id':source['source_id']})
        self.assertTrue(got['ok']);self.assertEqual(got['data']['completeness'],'VERIFIED')
        unified=api.call('list_strategy_sources',{'query':'原始','source_kind':'TRADER','offset':0,'limit':20})
        self.assertTrue(unified['ok']);self.assertEqual(unified['data']['total'],1)
        self.assertEqual(unified['data']['records'][0]['strategy_source_id'],source['source_id'])
        self.assertFalse(any(name.startswith(('create_strategy','save_strategy','link_strategy')) for name in names))

    def test_agent_can_read_generic_source_links_without_write_tools(self):
        source=self.store.create_strategy_source(str(uuid4()),{'source_key':'user-note','source_kind':'USER_EXPERIENCE',
            'title':'用户经验','locator':'local:user-note','published_at':None,
            'available_at':'2026-09-14T12:00:00+08:00','content_hash':'c'*64,'archive_ref':'',
            'completeness':'VERIFIED','notes':'','evidence_ids':[]})
        definition=self.store.create_definition(str(uuid4()),{'playbook_key':'high_low_switch','name':'高低切',
            'version':'draft-1','state':'DRAFT','source_ids':[],'market_context':{},'eligibility':{},
            'selection':{},'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},
            'reduce':{},'exit':{},'notes':''})
        link=self.store.create_source_link(str(uuid4()),{'definition_id':definition['definition_id'],
            'strategy_source_id':source['strategy_source_id'],'relation':'SUPPORT','notes':'','evidence_ids':[]})
        api=PlaybookResearchAPI(self.root)
        links=api.call('list_playbook_source_links',{'definition_id':definition['definition_id'],
            'strategy_source_id':'','relation':'','offset':0,'limit':20})
        self.assertTrue(links['ok']);self.assertEqual(links['data']['records'][0]['link_id'],link['link_id'])
        bundle=api.call('get_playbook_definition_sources',{'definition_id':definition['definition_id']})
        self.assertTrue(bundle['ok']);self.assertEqual(bundle['data']['strategy_source_links'][0]['source']['source_kind'],'USER_EXPERIENCE')
        names={tool['name'] for tool in api.schemas()}
        self.assertFalse(any(name in names for name in ('create_strategy_source','create_playbook_source_link')))

    def test_peer_review_can_inspect_playbooks_but_not_write_them(self):
        api=ReviewReadOnlyAPI(self.root,self.root);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_playbook_overview',names);self.assertIn('get_playbook_case_bundle',names)
        self.assertIn('list_strategy_sources',names);self.assertIn('list_playbook_source_links',names)
        result=api.call('get_playbook_overview',{})
        self.assertTrue(result['ok']);self.assertEqual(result['data']['sources'],0)
        denied=api.call('create_playbook_definition',{})
        self.assertFalse(denied['ok']);self.assertEqual(denied['error']['code'],'REVIEW_TOOL_DENIED')


if __name__=='__main__':unittest.main()
