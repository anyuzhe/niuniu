from copy import deepcopy
import unittest
from quantlab.statistics.sequence_overlap import sequence_overlap


class SequenceOverlapTest(unittest.TestCase):
    def test_runner_archives_chains_and_readable_report(self):
        import tempfile
        import json
        from pathlib import Path
        from test_context_experiments import ContextProvider,context_config,runner
        from quantlab.experiments.correlation import CorrelationConfig,CorrelationRunner
        with tempfile.TemporaryDirectory() as tmp:
            inputs={k:{'factor_id':'SEQ.REPEATED_BREAKOUT','parameters':{'lookback':1}} for k in ('a','b')}
            result=CorrelationRunner(runner(ContextProvider(),Path(tmp))).run(CorrelationConfig('完整链验收',context_config().data,inputs))
            record=json.loads((result.artifact_path/'experiment.json').read_text())
            self.assertEqual(record['sequence_overlap']['pairs'][0]['jaccard'],1)
            self.assertIn('完整事件链去重',(result.artifact_path/'report.md').read_text())

    def audit(self):
        events=[{'event_id':str(i),'factor_id':'EVT.BREAK','version':'1.0.0','symbol':'A','timeframe':'1d',
            'occurred_at':f'2025-01-0{i+1}T15:00:00+08:00','available_at':f'2025-01-0{i+1}T15:00:00+08:00','metadata':{}} for i in range(3)]
        match={'sequence_id':'SEQ.TEST','event_ids':['0','2'],'symbol':'A','timeframe':'1d','available_at':events[2]['available_at'],
            'status':'completed','completion_selected':True,'match_id':'m1'}
        a={'alias':'a','factor':{'factor_id':'SEQ.TEST'},'events':events,'transitions':[match]}
        b=deepcopy(a);b['alias']='b';b['transitions'][0]['match_id']='other-definition'
        return {'sequences':[a,b]}

    def test_exact_content_dedup_keeps_order_and_not_just_endpoint(self):
        audit=self.audit();audit['sequences'][0]['transitions']*=2
        result=sequence_overlap(audit);self.assertEqual(result['pairs'][0]['jaccard'],1)
        self.assertEqual(result['aliases']['a']['duplicate_records'],1)
        audit['sequences'][1]['transitions'][0]['event_ids']=['1','2']
        self.assertEqual(sequence_overlap(audit)['pairs'][0]['jaccard'],0)
        audit['sequences'][1]['transitions'][0]['event_ids']=['2','0']
        with self.assertRaisesRegex(ValueError,'Noncausal'):sequence_overlap(audit)

    def test_ineligible_incomplete_and_missing_evidence(self):
        audit=self.audit();audit['sequences'][0]['transitions'][0]['completion_selected']=False
        self.assertEqual(sequence_overlap(audit)['pairs'][0]['left_unique_chains'],0)
        audit['sequences'][1]['transitions'][0]['status']='active'
        self.assertIsNone(sequence_overlap(audit)['pairs'][0]['jaccard'])
        audit=self.audit();audit['sequences'][1]['events'].pop()
        with self.assertRaisesRegex(ValueError,'missing events'):sequence_overlap(audit)

    def test_component_parent_trace_is_not_component_sequence(self):
        audit=self.audit();audit['sequences'][1]['factor']['factor_id']='COMPONENT.OTHER'
        self.assertEqual(sequence_overlap(audit)['pairs'][0]['right_unique_chains'],0)
