from uuid import uuid4
import json
import unittest
from unittest.mock import patch

from test_alpha_factory import AlphaFactoryTests
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.agent.research_memory import ResearchMemory
from quantlab.agent.market_data_tools import MarketDataResearchAPI


class ResearchAgendaTests(unittest.TestCase):
    def setUp(self):
        self.fx=AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.agenda=ResearchAgendaService(self.fx.output,self.fx.fx.root)
    def test_registered_unresearched_candidate_is_suggested_read_only(self):
        before=list(self.fx.output.glob('_jobs/*.json'))
        result=self.agenda.build(20)
        kinds=[r['kind'] for r in result['items']]
        self.assertIn('candidate_unresearched',kinds)
        self.assertEqual(result['new_research_jobs'],0);self.assertFalse(result['automatic_execution'])
        self.assertEqual(before,list(self.fx.output.glob('_jobs/*.json')))
        self.assertFalse((self.fx.output/'_alpha_factory').exists())

    def test_pending_factory_and_open_hypothesis_are_prioritized(self):
        proposal=self.fx.service.propose(str(uuid4()),self.fx.plan())
        memory=ResearchMemory(self.fx.output)
        memory.save('hypothesis',str(uuid4()),{'title':'待验证动量假设','statement':'动量可能有预测力',
            'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':2},
            'mechanism':'趋势延续','falsification':'样本外失效','supersedes':None})
        result=self.agenda.build(20);kinds=[r['kind'] for r in result['items']]
        self.assertIn('factory_approval',kinds);self.assertIn('open_hypothesis',kinds)
        factory=next(r for r in result['items'] if r['kind']=='factory_approval')
        self.assertEqual(factory['evidence'][0]['proposal_id'],proposal['proposal_id'])

    def test_sequential_decay_evidence_becomes_review_agenda_not_action(self):
        class Store:
            def list(self):return {'watches':[{'watch_id':'00000000-0000-0000-0000-000000000001','name':'衰减监控'}],'unreadable':0}
        class Service:
            store=Store()
            def get(self,_):
                return {'source_integrity':'verified','latest':{'alerts':[{'kind':'sequential_rank_ic_degradation','severity':'review','horizon':'5'}]},
                    'active':True}
        with patch('quantlab.agent.research_agenda.WatchService',return_value=Service()):
            items=self.agenda._watch_items()
        self.assertEqual(len(items),1);self.assertEqual(items[0]['kind'],'watch_decay_evidence')
        self.assertIn('不要自动停用',items[0]['action']);self.assertEqual(items[0]['priority'],92)

    def test_agent_can_read_agenda_and_factory_but_not_execute(self):
        api=MarketDataResearchAPI(self.fx.output,self.fx.fx.root)
        agenda=api.call('get_research_agenda',{'limit':20})
        self.assertTrue(agenda['ok'],agenda);self.assertGreaterEqual(agenda['data']['total'],1)
        preview=api.call('preview_alpha_factory',{'plan_json':json.dumps(self.fx.plan())})
        self.assertTrue(preview['ok'],preview)
        request=str(uuid4());proposal=api.call('propose_alpha_factory',
            {'request_id':request,'plan_json':json.dumps(self.fx.plan())})
        self.assertTrue(proposal['ok'],proposal)
        self.assertFalse(api.call('submit_alpha_factory',{})['ok'])
        self.assertFalse(api.call('promote_alpha_candidate',{})['ok'])
        self.assertFalse((self.fx.output/'_jobs').exists())
