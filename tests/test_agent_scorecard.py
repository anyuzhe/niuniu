import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.agent.scorecard import AgentScorecardService
from quantlab.storage.codec import digest
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.playbook_store import PlaybookStore


def moment(value):return datetime.fromisoformat(value)


class AgentScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_empty_scorecard_is_read_only_and_has_no_composite_ranking(self):
        before=set(self.root.iterdir());result=AgentScorecardService(self.root,now_fn=lambda:moment('2026-09-14T21:00:00+08:00')).build()
        self.assertEqual(set(self.root.iterdir()),before)
        self.assertFalse(result['policy']['composite_score']);self.assertFalse(result['policy']['automatic_model_weighting'])
        self.assertFalse(result['policy']['evidence_correctness_automatic_score']);self.assertFalse(result['policy']['rejected_constraint_attempts_observable'])
        self.assertTrue(all(row['sample_status']=='NO_SAMPLES' for row in result['rows']))
        self.assertNotIn('total_score',json.dumps(result,ensure_ascii=False))

    def _decision(self,symbol,day,frame='R1',**updates):
        value={'symbol':symbol,'trading_day':day,'frame':frame,'action':'WATCH','role_id':'chief_researcher',
            'agent_id':'chief','model_provider':'fixture','model_id':'model-a','prompt_version':'p1',
            'ai_thesis':'证据化判断','research_evidence_ids':['evidence-1'],'risk_flags':['watch_risk'],'source':'scorecard-test'}
        value.update(updates);return value

    def test_decision_metrics_measure_discipline_not_correctness(self):
        a=DecisionStore(self.root,now_fn=lambda:moment('2026-09-14T09:35:00+08:00')).create(str(uuid4()),self._decision('sh.600000','2026-09-14'))
        DecisionStore(self.root,now_fn=lambda:moment('2026-09-14T09:40:00+08:00')).create(str(uuid4()),self._decision('sz.000001','2026-09-14'))
        DecisionStore(self.root,now_fn=lambda:moment('2026-09-14T11:00:00+08:00')).create(str(uuid4()),self._decision('sz.000002','2026-09-14',risk_flags=[]))
        DecisionStore(self.root,now_fn=lambda:moment('2026-09-15T10:00:00+08:00')).create(str(uuid4()),
            self._decision('sh.600000','2026-09-15',frame='D1',reference_decision_id=a['decision_id'],research_evidence_ids=[]))
        result=AgentScorecardService(self.root).build();row=next(r for r in result['rows'] if r['role_id']=='chief_researcher' and r['task_type']=='decision')
        self.assertEqual(row['samples'],4);self.assertEqual(row['metrics']['on_time_rate']['denominator'],3)
        self.assertEqual(row['metrics']['on_time_rate']['numerator'],2);self.assertEqual(row['metrics']['off_window_count'],1)
        self.assertEqual(row['metrics']['follow_up_rate']['numerator'],1);self.assertEqual(row['metrics']['follow_up_rate']['denominator'],3)
        self.assertIn('evidence_correctness',row['not_scored']);self.assertNotIn('score',row)

    def _write_peer_task(self,value):
        root=self.root/'_assistant'/'peer_reviews';root.mkdir(parents=True)
        wrapped={**value,'checksum':digest(value)};(root/(value['task_id']+'.json')).write_text(json.dumps(wrapped,ensure_ascii=False))

    def test_peer_review_rows_keep_roles_and_task_types_separate(self):
        self._write_peer_task({'task_id':str(uuid4()),'status':'completed','created_at':'2026-09-14T10:00:00+00:00',
            'spec':{'question':'q','context':'','reviewers':['skeptic','market_scanner'],'parent_task_id':None},
            'rounds':[{'round':1,'kind':'independent','outputs':[
                {'role_id':'skeptic','status':'completed','tool_calls':2,'evidence':[{'kind':'x'}],'model':'m-s','provider':'fixture'},
                {'role_id':'market_scanner','status':'failed','tool_calls':0,'evidence':[],'model':'','provider':''}]},
                {'round':2,'kind':'chief_synthesis','outputs':[{'role_id':'chief_researcher','status':'completed','tool_calls':1,
                    'evidence':[],'model':'m-c','provider':'fixture'}]}]})
        result=AgentScorecardService(self.root).build()
        skeptic=next(r for r in result['rows'] if r['role_id']=='skeptic' and r['task_type']=='peer_review_independent')
        market=next(r for r in result['rows'] if r['role_id']=='market_scanner' and r['task_type']=='peer_review_independent')
        chief=next(r for r in result['rows'] if r['role_id']=='chief_researcher' and r['task_type']=='peer_review_synthesis')
        self.assertEqual(skeptic['metrics']['completion_rate']['value'],1.0);self.assertEqual(skeptic['metrics']['explicit_evidence_rate']['value'],1.0)
        self.assertEqual(market['metrics']['completion_rate']['value'],0.0);self.assertEqual(market['metrics']['failure_count'],1)
        self.assertEqual(chief['metrics']['reviewer_input_completion_rate']['value'],0.5)
        self.assertIn('majority_vote',skeptic['not_scored']);self.assertIn('synthesis_correctness',chief['not_scored'])

    def test_playbook_prediction_match_requires_observed_label_and_is_not_alpha(self):
        now=moment('2026-09-14T09:35:00+08:00');store=PlaybookStore(self.root,now_fn=lambda:now)
        source=store.create_source(str(uuid4()),{'expert_key':'score','title':'source','source_type':'PUBLIC_POST',
            'locator':'local:test','available_at':'2026-09-14T09:00:00+08:00','content_hash':'a'*64,'archive_ref':'',
            'completeness':'VERIFIED','notes':''})
        definition=store.create_definition(str(uuid4()),{'playbook_key':'score','name':'Score','version':'v1','state':'DRAFT',
            'source_ids':[source['source_id']],'market_context':{},'eligibility':{'x':1},'selection':{'x':1},'veto':{},
            'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        case=store.create_case(str(uuid4()),{'definition_id':definition['definition_id'],'trading_day':'2026-09-14','frame':'R1',
            'as_of':'2026-09-14T09:35:00+08:00','source_ids':[source['source_id']],'summary':'case','notes':''})
        cset=store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':definition['definition_id'],
            'trading_day':'2026-09-14','frame':'R1','as_of':'2026-09-14T09:35:00+08:00','completeness':'FULL','pit_status':'STRICT_PIT',
            'universe_source':'fixture','generation_method':'fixture','candidates':[
                {'symbol':'sh.600000','eligibility_reasons':['x'],'features':{},'evidence_ids':[]},
                {'symbol':'sz.000001','eligibility_reasons':['x'],'features':{},'evidence_ids':[]}],'evidence_ids':[]})
        store.create_selection(str(uuid4()),{'candidate_set_id':cset['candidate_set_id'],'kind':'SYSTEM_PREDICTION',
            'selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000','sz.000001'],'reasons':{},'evidence_ids':[],
            'as_of':'2026-09-14T09:35:00+08:00','notes':''})
        before=AgentScorecardService(self.root).build()['system_baselines']['playbook_prediction']
        self.assertEqual(before['metrics']['labeled_predictions'],0);self.assertIsNone(before['metrics']['exact_match_rate']['value'])
        store.create_selection(str(uuid4()),{'candidate_set_id':cset['candidate_set_id'],'kind':'OBSERVED_EXPERT',
            'selected_symbols':['sh.600000'],'ranked_symbols':[],'reasons':{},'evidence_ids':['expert-trade'],
            'as_of':'2026-09-14T09:36:00+08:00','notes':''})
        after=AgentScorecardService(self.root).build()['system_baselines']['playbook_prediction']
        self.assertEqual(after['metrics']['labeled_predictions'],1);self.assertEqual(after['metrics']['exact_match_rate']['value'],1.0)
        self.assertEqual(after['metrics']['false_negative_count'],0);self.assertEqual(after['metrics']['false_positive_count'],0)
        self.assertEqual(after['label_status'],'INSUFFICIENT_SAMPLES');self.assertIn('alpha',after['not_scored'])

    def test_corrupt_peer_review_is_counted_not_silently_scored(self):
        root=self.root/'_assistant'/'peer_reviews';root.mkdir(parents=True);(root/(str(uuid4())+'.json')).write_text('{}')
        result=AgentScorecardService(self.root).build();self.assertEqual(result['meta']['unreadable_peer_reviews'],1)


if __name__=='__main__':unittest.main()
