"""Independent read-only report consistency and interpretation-boundary review."""
from copy import deepcopy
from uuid import uuid4
import json
import unittest
from unittest.mock import patch
import test_alpha_factory as fixtures
from quantlab.agent import factory_report as report_api
from quantlab.agent.alpha_factory_tools import AlphaFactoryAPI
from quantlab.storage.codec import digest
from quantlab.workbench.jobs import JobQueue


class FactoryReportReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.output=self.fx.output
    def plan(self):
        plan=self.fx.v2_plan()
        second=deepcopy(plan['candidate_refs'][0]);second['parameters']={'lookback':4};second['name']='second factor'
        plan['candidate_refs'].append(second)
        return plan
    def complete(self,plan=None):
        proposal=self.fx.service.propose(str(uuid4()),plan or self.plan())
        queue=JobQueue(self.output,self.fx.fx.root)
        try:self.fx.service.submit(proposal['proposal_id'],proposal['prepared_digest'],lambda:queue,confirmed=True)
        finally:queue.close()
        return self.fx.service.sync(proposal['proposal_id'])
    def write_both(self,state):
        parent=self.output/state['result_run_id']/'experiment.json';record=json.loads(parent.read_text())
        record['summary']['tests']=state['tests'];record['summary']['decisions']=state['decisions']
        parent.write_text(json.dumps(record,ensure_ascii=False))
        self.fx.service.store.save(state)
    def test_two_actual_candidate_pages_match_full_report_and_tool_data(self):
        state=self.complete();pid=state['proposal_id']
        first=report_api.build_factory_report(self.output,pid,limit=1)
        self.assertTrue(first['has_more']);self.assertEqual(first['next_offset'],1)
        last=report_api.build_factory_report(self.output,pid,offset=first['next_offset'],limit=1,expected_digest=first['report_digest'])
        full=report_api.build_factory_report(self.output,pid,limit=12)
        self.assertEqual(first['report_digest'],last['report_digest']);self.assertFalse(last['has_more'])
        self.assertEqual(first['candidates']+last['candidates'],full['candidates'])
        data=AlphaFactoryAPI(self.output,self.fx.fx.root).call('get_alpha_factory_report',{'proposal_id':pid,'offset':0,'limit':6,'expected_digest':''})
        self.assertTrue(data['ok'],data);self.assertEqual(data['data'],full)
        self.assertEqual(full['baseline_run_id'],self.fx.baseline.run_id)
        markdown=report_api.render_factory_report_markdown(first)
        self.assertIn('分页片段',markdown);self.assertIn(first['candidates'][0]['version'],markdown)
    def test_requested_cost_tests_are_not_claimed_completed_in_pending_report(self):
        execution=self.fx.baseline_execution()
        plan=self.fx.plan(require_net_return=True,baseline_execution_run_id=execution.run_id)
        pending=self.fx.service.propose(str(uuid4()),plan)
        result=report_api.build_factory_report(self.output,pending['proposal_id'])
        self.assertTrue(result['cost_evidence']['requested']);self.assertEqual(result['cost_evidence']['planned_tests'],1)
        self.assertEqual(result['cost_evidence']['completed_tests'],0);self.assertEqual(result['cost_evidence']['tests_with_p_value'],0)
        self.assertNotIn('execution_cost_tested',result['scope'])
        self.assertEqual(result['counts']['unknown_tests'],2)
    def test_duplicate_or_unknown_result_slots_rejected_even_if_state_and_parent_match(self):
        state=self.complete();original=deepcopy(state)
        state['tests'][1]=deepcopy(state['tests'][0]);self.write_both(state)
        with self.assertRaisesRegex(ValueError,'重复|非计划'):report_api.build_factory_report(self.output,state['proposal_id'])
        state=deepcopy(original);state['tests'][1]['id']='unplanned';self.write_both(state)
        with self.assertRaisesRegex(ValueError,'重复|非计划'):report_api.build_factory_report(self.output,state['proposal_id'])
    def test_missing_slot_is_visible_and_does_not_inherit_saved_positive_suggestion(self):
        state=self.complete();state['tests'].pop()
        state['decisions'][-1]['recommended_for_watchlist']=True
        self.write_both(state)
        result=report_api.build_factory_report(self.output,state['proposal_id'])
        self.assertEqual(result['counts']['unknown_tests'],1)
        self.assertEqual(result['candidates'][-1]['decision']['status'],'unknown')
        self.assertNotIn('recommended_for_watchlist',result['candidates'][-1]['decision'])
    def test_nonfinite_and_duplicate_json_keys_are_not_silently_changed_to_unknown(self):
        state=self.complete();parent=self.output/state['result_run_id']/'experiment.json';raw=parent.read_text()
        parent.write_text('{"duplicate":1,"duplicate":2,"run_id":"x"}')
        with self.assertRaisesRegex(ValueError,'JSON'):report_api.build_factory_report(self.output,state['proposal_id'])
        parent.write_text(raw[:-1]+',"bad":NaN}')
        with self.assertRaisesRegex(ValueError,'JSON'):report_api.build_factory_report(self.output,state['proposal_id'])
    def test_source_change_during_report_assembly_refuses_mixed_snapshot(self):
        state=self.complete();original=report_api._scope
        def change(prepared):
            current=self.fx.service.get(state['proposal_id']);current['last_sync_at']='concurrent-change'
            self.fx.service.store.save(current)
            return original(prepared)
        with patch.object(report_api,'_scope',side_effect=change),self.assertRaisesRegex(ValueError,'状态变化'):
            report_api.build_factory_report(self.output,state['proposal_id'])
    def test_parent_frozen_source_binding_mismatch_rejected(self):
        state=self.complete();parent=self.output/state['result_run_id']/'experiment.json';record=json.loads(parent.read_text())
        record['manifest']['source_fingerprints']={};record['experiment_id']=digest(record['manifest'])
        parent.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'source_fingerprints'):report_api.build_factory_report(self.output,state['proposal_id'])
    def test_markdown_untrusted_name_is_not_an_executable_link_or_image(self):
        plan=self.plan();plan['name']='![external](https://example.invalid/x) <img> |\n# injected'
        proposal=self.fx.service.propose(str(uuid4()),plan)
        rendered=report_api.render_factory_report_markdown(report_api.build_factory_report(self.output,proposal['proposal_id']))
        self.assertNotIn('![external]',rendered);self.assertNotIn('<img>',rendered)
        self.assertNotIn('\n# injected',rendered);self.assertIn('&lt;img&gt;',rendered)
    def test_noncompleted_result_identity_and_invalid_digest_refused(self):
        proposal=self.fx.service.propose(str(uuid4()),self.plan());state=self.fx.service.get(proposal['proposal_id'])
        state['result_run_id']=str(uuid4());self.fx.service.store.save(state)
        with self.assertRaisesRegex(ValueError,'非完成'):report_api.build_factory_report(self.output,state['proposal_id'])
        with self.assertRaisesRegex(ValueError,'expected_digest'):report_api.build_factory_report(self.output,state['proposal_id'],expected_digest='g'*64)

if __name__=='__main__':unittest.main()
