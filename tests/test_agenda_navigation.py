import json
import hashlib
import unittest
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
import test_alpha_factory
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.agent.research_memory import ResearchMemory
from quantlab.desktop.agenda_navigation import agenda_targets,canonical_target,read_agenda_target


def file_hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


class AgendaNavigationTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_alpha_factory.AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.agenda=ResearchAgendaService(self.fx.output,self.fx.fx.root)
    def test_fixed_registered_candidate_is_not_a_dsl_reference(self):
        plan=self.fx.plan();plan.pop('candidate_ids')
        plan.update(format='alpha-factory-plan-v2',candidate_refs=[{'kind':'registered_factor',
            'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':3},'name':'精确普通候选'}])
        state=self.fx.service.propose(str(uuid4()),plan)
        candidate=state['prepared']['candidates'][0];state=deepcopy(state)
        state.update(status='completed',recommended_candidate_ids=[candidate['candidate_id']])
        with patch('quantlab.agent.research_agenda.AlphaFactoryService') as factory:
            factory.return_value.list.return_value={'factories':[state],'errors':[]}
            rows=self.agenda._factory_items()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['title'],'精确普通候选')
        refs=rows[0]['evidence'];self.assertEqual([r['kind'] for r in refs],['alpha_factory','factor'])
        self.assertEqual(refs[1]['parameters'],{'lookback':3});self.assertEqual(refs[1]['version'],'1.0.0')
        targets,errors=agenda_targets(rows[0]);self.assertFalse(errors);self.assertEqual(len(targets),2)
        before=file_hashes(self.fx.output)
        for target in targets:read_agenda_target(self.fx.output,target['reference'])
        self.assertEqual(before,file_hashes(self.fx.output))
    def test_legacy_dsl_identity_and_unknown_candidate_are_not_guessed(self):
        state=self.fx.service.propose(str(uuid4()),self.fx.plan());state=deepcopy(state)
        cid=state['prepared']['candidates'][0]['candidate_id']
        state.update(status='completed',recommended_candidate_ids=[cid,str(uuid4())])
        with patch('quantlab.agent.research_agenda.AlphaFactoryService') as factory:
            factory.return_value.list.return_value={'factories':[state],'errors':[]}
            rows=self.agenda._factory_items()
        self.assertEqual(rows[0]['evidence'][1],{'kind':'dsl_candidate','candidate_id':cid})
        self.assertEqual(rows[1]['kind'],'factory_candidate_error')
        self.assertEqual([v['kind'] for v in rows[1]['evidence']],['alpha_factory'])
    def test_incremental_receipts_keep_separate_namespace_and_legacy_agenda_compatibility(self):
        pid=str(uuid4())
        with patch('quantlab.agent.research_agenda.IncrementalEvidenceService') as service:
            service.return_value.list.return_value={'proposals':[{'proposal_id':pid,'status':'pending'}],'errors':[]}
            rows=self.agenda._incremental_items()
        self.assertEqual(rows[0]['evidence'],[{'kind':'incremental_evidence','proposal_id':pid}])
        old={'kind':'incremental_approval','evidence':[{'kind':'proposal','proposal_id':pid}]}
        targets,errors=agenda_targets(old);self.assertFalse(errors)
        self.assertEqual(targets[0]['reference']['kind'],'incremental_evidence')
        ordinary={'kind':'anything_else','evidence':[{'kind':'proposal','proposal_id':pid}]}
        self.assertEqual(agenda_targets(ordinary)[0][0]['reference']['kind'],'proposal')
    def test_routing_preserves_order_parameters_and_reports_invalid_entries(self):
        first=str(uuid4());second=str(uuid4())
        refs=[{'kind':'watch','watch_id':first},{'kind':'watch','watch_id':second},
              {'kind':'watch','watch_id':first},{'kind':'job','job_id':'../escape'},
              {'kind':'exec','command':'write something'}, {'kind':[]}, None,
              {'kind':'factor','factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':3}}]
        targets,errors=agenda_targets({'evidence':refs})
        self.assertEqual(len(targets),3);self.assertEqual(len(errors),4)
        self.assertEqual([r['reference'].get('watch_id') for r in targets[:2]],[first,second])
        refs[-1]['parameters']['lookback']=99
        self.assertEqual(targets[-1]['reference']['parameters']['lookback'],3)
    def test_missing_or_mismatched_source_is_not_replaced_by_same_kind(self):
        self.fx.service.propose(str(uuid4()),self.fx.plan())
        before=file_hashes(self.fx.output)
        for ref in ({'kind':'alpha_factory','proposal_id':str(uuid4())},
                    {'kind':'job','job_id':str(uuid4())},
                    {'kind':'factor','factor_id':'BASE.MOMENTUM','version':'missing','parameters':{}},
                    {'kind':'dsl_proposal','request_id':str(uuid4())}):
            with self.assertRaises((ValueError,OSError,KeyError)):read_agenda_target(self.fx.output,ref)
        self.assertEqual(before,file_hashes(self.fx.output))
    def test_actual_memory_and_registered_dsl_reads_are_unchanged(self):
        memory=ResearchMemory(self.fx.output)
        value=memory.save('hypothesis',str(uuid4()),{'title':'精确父假设','statement':'待验证',
            'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':2},
            'mechanism':'未知机制','falsification':'固定检验','supersedes':None})
        state=self.fx.service.propose(str(uuid4()),self.fx.plan())
        cid=state['prepared']['candidates'][0]['candidate_id'];mid=value['record']['memory_id']
        before=file_hashes(self.fx.output)
        read_agenda_target(self.fx.output,{'kind':'memory','memory_id':mid})
        checked=read_agenda_target(self.fx.output,{'kind':'dsl_candidate','candidate_id':cid})
        self.assertIsNotNone(checked['read_only_record'])
        self.assertEqual(before,file_hashes(self.fx.output))
    def test_nonfinite_or_noncanonical_factor_reference_rejected(self):
        for ref in ({'kind':'factor','factor_id':'BASE.MOMENTUM'},
                    {'kind':'watch','watch_id':str(uuid4()).upper()},
                    {'kind':'factor','factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':float('nan')}}):
            with self.assertRaises(ValueError):canonical_target(ref)


if __name__=='__main__':unittest.main()
