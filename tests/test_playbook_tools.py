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
        self.assertFalse(any(name.startswith(('create_playbook','save_playbook','record_playbook')) for name in names))
        listed=api.call('list_expert_sources',{'query':'期末' if False else '原始','offset':0,'limit':20})
        self.assertTrue(listed['ok']);self.assertEqual(listed['data']['total'],1)
        got=api.call('get_expert_source',{'source_id':source['source_id']})
        self.assertTrue(got['ok']);self.assertEqual(got['data']['completeness'],'VERIFIED')

    def test_peer_review_can_inspect_playbooks_but_not_write_them(self):
        api=ReviewReadOnlyAPI(self.root,self.root);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_playbook_overview',names);self.assertIn('get_playbook_case_bundle',names)
        result=api.call('get_playbook_overview',{})
        self.assertTrue(result['ok']);self.assertEqual(result['data']['sources'],0)
        denied=api.call('create_playbook_definition',{})
        self.assertFalse(denied['ok']);self.assertEqual(denied['error']['code'],'REVIEW_TOOL_DENIED')


if __name__=='__main__':unittest.main()
