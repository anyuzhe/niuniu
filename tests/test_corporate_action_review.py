"""In-memory corporate-action contract tests; no production files or network."""
from datetime import date
import unittest
import polars as pl
from quantlab.data import corporate_action_review as review

class CorporateActionReviewTests(unittest.TestCase):
    def rows(self, values, source='ths'):
        items,unassigned,errors=review._parquet_observations(pl.DataFrame(values),source,'synthetic.parquet',
            'sh.600000',date(2026,1,1),date(2026,1,10))
        self.assertFalse(errors,errors)
        return items,unassigned
    def plan(self,text,period='2025年报',announced='2025-12-20'):
        return {'code':'sh.600000','A股除权除息日':'2026-01-02','方案进度':'实施方案',
                '报告期':period,'实施公告日':announced,'分红方案说明':text}
    def test_contract_is_detached_and_not_an_authorization(self):
        original=review.get_adjustment_review_contract();changed=review.get_adjustment_review_contract()
        changed['warnings'].clear()
        self.assertTrue(original['warnings']);self.assertFalse(original['official_verified'])
        self.assertFalse(original['lineage_verified']);self.assertFalse(original['reconstruction_authorized'])
        self.assertEqual(original['known_issue_list_status'],'not_bound')
    def test_supported_simple_forms_have_explicit_normalized_bases(self):
        cases=[('10派4.6元(含税)','4.6','0'),('每股派0.5元(含税)','5','0'),
               ('5派2元(含税)','4','0'),('10转增3股','0','3'),('10送2转3派1.5元(含税)','1.5','5')]
        for text,cash,stock in cases:
            with self.subTest(text=text):
                value=review._parse_plan_text(text);self.assertEqual(value['status'],'parsed',value)
                self.assertEqual(value['components']['cash_pre_tax_per_10_shares'],cash)
                self.assertEqual(value['components']['stock_total_per_10_shares'],stock)
    def test_unknown_pending_and_residual_grammar_are_not_three_zeroes(self):
        for text in ('方案待定','--','未知说明','10送1股其他方案','每股派-1元(含税)'):
            with self.subTest(text=text):
                value=review._parse_plan_text(text)
                self.assertNotEqual(value['status'],'parsed');self.assertIsNone(value['components'])
    def test_cash_without_tax_basis_or_after_tax_is_blocked(self):
        for text in ('10派1元','10派1元(税后)'):
            value=review._parse_plan_text(text)
            self.assertEqual(value['status'],'blocked');self.assertTrue(value['blockers'])
            self.assertIsNone(value['components']['cash_pre_tax_per_10_shares'])
    def test_differentiated_holders_never_use_first_amount(self):
        value=review._parse_plan_text('10派2.8元(含税)，限售股股东每股0.27545元，流通股每股0.32091元')
        self.assertEqual(value['status'],'blocked');self.assertIsNone(value['components'])
    def test_explicit_no_distribution_is_distinct_from_unknown(self):
        value=review._parse_plan_text('不分配不转增')
        self.assertEqual(value['status'],'not_distributing')
        self.assertEqual(value['components']['cash_pre_tax_per_10_shares'],'0')
    def test_identified_distinct_plans_sum_only_within_source(self):
        items,_=self.rows([self.plan('10派4.6元(含税)'),self.plan('10派25.1元(含税)','特别分红')])
        result=review._aggregate_source('ths',items[date(2026,1,2)])
        self.assertEqual(result['candidate_total']['cash_pre_tax_per_10_shares'],'29.7')
        self.assertEqual(result['candidate_total']['aggregation_scope'],'within_source_only')
        self.assertEqual(result['candidate_total']['component_count'],2)
    def test_exact_duplicate_keeps_locators_without_double_count(self):
        row=self.plan('10派4.6元(含税)');items,_=self.rows([row,row])
        result=review._aggregate_source('ths',items[date(2026,1,2)])
        self.assertEqual(result['candidate_total']['cash_pre_tax_per_10_shares'],'4.6')
        self.assertEqual(len(result['candidate_components'][0]['locators']),2)
    def test_announcement_revision_does_not_become_second_plan(self):
        items,_=self.rows([self.plan('10派4.6元(含税)'),self.plan('10派5元(含税)',announced='2025-12-21')])
        result=review._aggregate_source('ths',items[date(2026,1,2)])
        self.assertIsNone(result['candidate_total']);self.assertIn('same_identity_has_conflicting_versions',result['blockers'])
    def test_no_identity_or_same_text_different_identity_blocks_aggregation(self):
        cases=[[{k:v for k,v in self.plan(text).items() if k!='报告期'} for text in ('10派1元(含税)','10派2元(含税)')],
               [self.plan('10派1元(含税)','一'),self.plan('10派1元(含税)','二')]]
        for values in cases:
            items,_=self.rows(values);result=review._aggregate_source('ths',items[date(2026,1,2)])
            self.assertIsNone(result['candidate_total']);self.assertTrue(result['blockers'])
    def test_provider_null_and_unknown_tax_basis_remain_blocked(self):
        for cash in (None,4.6):
            values=[{'code':'sh.600000','除权除息日':'2026-01-02','方案进度':'实施分配',
                     '现金分红-现金分红比例':cash,'送转股份-送转总比例':0.}]
            items,_=self.rows(values,'eastmoney');result=review._aggregate_source('eastmoney',items[date(2026,1,2)])
            self.assertIsNone(result['candidate_total']);self.assertIn('cash_tax_basis_unspecified',result['blockers'])
            self.assertEqual(result['observations'][0]['raw']['cash_ratio'],cash)
    def test_pending_records_are_preserved_but_excluded(self):
        pending=self.plan('10派5元(含税)');pending['方案进度']='预案'
        items,_=self.rows([pending]);result=review._aggregate_source('ths',items[date(2026,1,2)])
        self.assertIsNone(result['candidate_total']);self.assertEqual(len(result['observations']),1)
    def test_qfq_security_mismatch_has_no_diagnostic(self):
        frame=pl.DataFrame({'code':['sh.600999'],'date':[date(2026,1,2)],'factor':[1.]})
        evidence={'status':'available','path':'synthetic.parquet'};errors=[]
        self.assertIsNone(review._qfq_index(frame,evidence,errors,'sh.600000'))
        self.assertEqual(evidence['status'],'error');self.assertTrue(errors)
    def test_stored_factor_direction_never_adjudicates_adjustment(self):
        for current,direction in ((.9,'increase'),(.7,'decrease'),(.8,'unchanged')):
            frame=pl.DataFrame({'code':['sh.600000']*2,'date':[date(2026,1,1),date(2026,1,2)],'factor':[.8,current]})
            evidence={'status':'available','path':'synthetic.parquet'};errors=[]
            index=review._qfq_index(frame,evidence,errors,'sh.600000')
            result=review._qfq_diagnostic(index,evidence,date(2026,1,2))
            self.assertEqual(result['factor_change_direction'],direction)
            self.assertFalse(result['missing_adjustment_inferred']);self.assertIsNone(result['corrected_factor'])
    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for text in ('{"c1":1,"c1":2}','{"c1":NaN}'):
            with self.assertRaises(ValueError):review._strict_json(text)

if __name__=='__main__':unittest.main()
