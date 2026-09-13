import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.trading.playbook_store import PlaybookError, PlaybookStore


class PlaybookLabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=PlaybookStore(self.root)
    def tearDown(self):self.temp.cleanup()

    def source(self, **updates):
        value={'expert_key':'qimofenshu','title':'可核验原始交易记录','source_type':'PUBLIC_POST',
            'locator':'https://example.invalid/original','published_at':'2024-01-02T09:00:00+08:00',
            'available_at':'2024-01-02T09:00:00+08:00','content_hash':'a'*64,'archive_ref':'local:test',
            'completeness':'VERIFIED','notes':'测试来源'}
        value.update(updates);return value

    def definition(self, source_id, **updates):
        value={'playbook_key':'qimofenshu','name':'期末50分试点','version':'v1','state':'FROZEN',
            'source_ids':[source_id],'market_context':{'theme':'mainline'},
            'eligibility':{'rule':'frozen eligibility'},'selection':{'rule':'rank within candidates'},
            'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''}
        value.update(updates);return value

    def case(self, definition_id, source_id, **updates):
        value={'definition_id':definition_id,'trading_day':'2024-01-02','frame':'R1',
            'as_of':'2024-01-02T09:35:00+08:00','source_ids':[source_id],
            'summary':'重建当天候选与真实选择','notes':''}
        value.update(updates);return value

    def candidates(self, case_id, definition_id, **updates):
        members=[]
        for symbol in ('sh.600000','sz.000001','sz.000002'):
            members.append({'symbol':symbol,'eligibility_reasons':['满足冻结玩法条件'],
                'features':{'theme_rank':1},'evidence_ids':['snapshot-1']})
        value={'case_id':case_id,'definition_id':definition_id,'trading_day':'2024-01-02','frame':'R1',
            'as_of':'2024-01-02T09:35:00+08:00','completeness':'FULL','pit_status':'STRICT_PIT',
            'universe_source':'A股当日可交易全集 snapshot-1','generation_method':'playbook-v1 eligibility',
            'candidates':members,'evidence_ids':['snapshot-1']}
        value.update(updates);return value

    def build_strict_case(self):
        source=self.store.create_source(str(uuid4()),self.source())
        definition=self.store.create_definition(str(uuid4()),self.definition(source['source_id']))
        case=self.store.create_case(str(uuid4()),self.case(definition['definition_id'],source['source_id']))
        candidates=self.store.create_candidate_set(str(uuid4()),self.candidates(case['case_id'],definition['definition_id']))
        return source,definition,case,candidates

    def test_verified_source_required_before_definition_can_freeze(self):
        pending=self.store.create_source(str(uuid4()),self.source(completeness='PENDING',available_at=None,content_hash=''))
        with self.assertRaises(PlaybookError) as error:
            self.store.create_definition(str(uuid4()),self.definition(pending['source_id']))
        self.assertEqual(error.exception.code,'SOURCE_NOT_VERIFIED')
        draft=self.store.create_definition(str(uuid4()),self.definition(pending['source_id'],version='draft-1',state='DRAFT'))
        self.assertEqual(draft['state'],'DRAFT');self.assertFalse((self.root/'_jobs').exists())

    def test_candidate_set_is_frozen_complete_universe_and_selection_is_subset(self):
        _,definition,case,candidates=self.build_strict_case()
        self.assertEqual(candidates['candidate_count'],3);self.assertEqual(candidates['completeness'],'FULL')
        target=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'OBSERVED_EXPERT','selected_symbols':['sh.600000'],'ranked_symbols':[],
            'reasons':{'sh.600000':['高手实际选择']},'evidence_ids':['source-trade'],
            'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        self.assertEqual(target['unselected_symbols'],['sz.000001','sz.000002'])
        with self.assertRaises(PlaybookError) as outside:
            self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
                'kind':'OBSERVED_EXPERT','selected_symbols':['sh.601398'],'ranked_symbols':[],
                'reasons':{},'evidence_ids':[],'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        self.assertEqual(outside.exception.code,'OUTSIDE_CANDIDATE_SET')

    def test_system_prediction_cannot_be_backfilled_after_candidate_snapshot(self):
        _,_,_,candidates=self.build_strict_case()
        with self.assertRaises(PlaybookError) as error:
            self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
                'kind':'SYSTEM_PREDICTION','selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000'],
                'reasons':{},'evidence_ids':[],'as_of':'2024-01-02T10:00:00+08:00','notes':''})
        self.assertEqual(error.exception.code,'LOOKAHEAD_BLOCKED')

    def test_formal_validation_computes_ten_choose_two_style_match_without_alpha_claim(self):
        _,definition,case,candidates=self.build_strict_case()
        target=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'OBSERVED_EXPERT','selected_symbols':['sh.600000','sz.000001'],'ranked_symbols':[],
            'reasons':{},'evidence_ids':['expert-trade'],'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        model=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'SYSTEM_PREDICTION','selected_symbols':['sh.600000','sz.000002'],
            'ranked_symbols':['sh.600000','sz.000002','sz.000001'],'reasons':{},'evidence_ids':['model-1'],
            'as_of':'2024-01-02T09:35:00+08:00','notes':''})
        validation=self.store.create_validation(str(uuid4()),{'definition_id':definition['definition_id'],
            'method':'HOLDOUT','pairs':[{'case_id':case['case_id'],'target_selection_id':target['selection_id'],
                'model_selection_id':model['selection_id']}],'execution_evidence_ids':['account-run-1'],
            'execution_summary':{'gross_return':0.10,'net_return':0.08,'costs':0.01,'slippage':0.01,
                't_plus_one_checked':True,'price_limit_checked':True,'suspension_checked':True},'notes':'冻结样本外验证'})
        self.assertEqual(validation['status'],'AUDIT_COMPLETE')
        self.assertEqual(validation['metrics']['micro_precision'],0.5)
        self.assertEqual(validation['metrics']['micro_recall'],0.5)
        self.assertFalse(validation['alpha_verified']);self.assertEqual(validation['profitability_claim'],'not_established')
        self.assertTrue(validation['audit']['execution']['ready'])

    def test_formal_validation_requires_observed_expert_evidence(self):
        _,definition,case,candidates=self.build_strict_case()
        target=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'OBSERVED_EXPERT','selected_symbols':['sh.600000'],'ranked_symbols':[],'reasons':{},
            'evidence_ids':[],'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        model=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'SYSTEM_PREDICTION','selected_symbols':['sh.600000'],'ranked_symbols':['sh.600000'],
            'reasons':{},'evidence_ids':['model'],'as_of':'2024-01-02T09:35:00+08:00','notes':''})
        with self.assertRaises(PlaybookError) as error:
            self.store.create_validation(str(uuid4()),{'definition_id':definition['definition_id'],'method':'HOLDOUT',
                'pairs':[{'case_id':case['case_id'],'target_selection_id':target['selection_id'],
                    'model_selection_id':model['selection_id']}],'execution_evidence_ids':['run'],
                'execution_summary':{},'notes':''})
        self.assertEqual(error.exception.code,'TARGET_EVIDENCE_REQUIRED')

    def test_holdout_is_blocked_when_candidate_universe_is_not_full_strict_pit(self):
        source=self.store.create_source(str(uuid4()),self.source())
        definition=self.store.create_definition(str(uuid4()),self.definition(source['source_id']))
        case=self.store.create_case(str(uuid4()),self.case(definition['definition_id'],source['source_id']))
        candidates=self.store.create_candidate_set(str(uuid4()),self.candidates(case['case_id'],definition['definition_id'],
            completeness='PARTIAL',pit_status='RETROSPECTIVE_REFERENCE'))
        target=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'OBSERVED_EXPERT','selected_symbols':[],'ranked_symbols':[],'reasons':{},'evidence_ids':['expert-no-trade'],
            'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        model=self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'SYSTEM_PREDICTION','selected_symbols':[],'ranked_symbols':[],'reasons':{},'evidence_ids':[],
            'as_of':'2024-01-02T09:35:00+08:00','notes':''})
        with self.assertRaises(PlaybookError) as error:
            self.store.create_validation(str(uuid4()),{'definition_id':definition['definition_id'],'method':'HOLDOUT',
                'pairs':[{'case_id':case['case_id'],'target_selection_id':target['selection_id'],
                    'model_selection_id':model['selection_id']}],'execution_evidence_ids':[],
                'execution_summary':{},'notes':''})
        self.assertEqual(error.exception.code,'FORMAL_VALIDATION_BLOCKED')

    def test_idempotency_version_lock_tamper_and_symbol_history(self):
        request=str(uuid4());source=self.store.create_source(request,self.source())
        self.assertEqual(self.store.create_source(request,self.source())['source_id'],source['source_id'])
        definition=self.store.create_definition(str(uuid4()),self.definition(source['source_id']))
        with self.assertRaises(PlaybookError) as duplicate:
            self.store.create_definition(str(uuid4()),self.definition(source['source_id']))
        self.assertEqual(duplicate.exception.code,'VERSION_EXISTS')
        case=self.store.create_case(str(uuid4()),self.case(definition['definition_id'],source['source_id']))
        candidates=self.store.create_candidate_set(str(uuid4()),self.candidates(case['case_id'],definition['definition_id']))
        self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],
            'kind':'OBSERVED_EXPERT','selected_symbols':['sh.600000'],'ranked_symbols':[],'reasons':{},
            'evidence_ids':[],'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        history=self.store.symbol_history('sh.600000');self.assertEqual(history[0]['selected_by'],['OBSERVED_EXPERT'])
        db=sqlite3.connect(self.store.path);db.execute("UPDATE sources SET payload='{}' WHERE id=?",(source['source_id'],));db.commit();db.close()
        with self.assertRaises(PlaybookError) as corrupt:self.store.get_source(source['source_id'])
        self.assertEqual(corrupt.exception.code,'CORRUPT_RECORD')
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
