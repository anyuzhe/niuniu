"""F18 isolated preview contracts; source choices never grant factor execution."""
import copy
from dataclasses import replace
from decimal import Decimal, localcontext, ROUND_DOWN
import json
from unittest import TestCase
from unittest.mock import patch

from test_rights_candidates import CandidateFixture, make_row, fill_formulas
from quantlab.data.rights_candidates import CandidateError
from quantlab.data.rights_rebuild_preview import (CONTRACT, get_rights_rebuild_contract,
    preview_rights_rebuild, MAX_EVENTS, MAX_REQUEST_BYTES)
from quantlab.storage.codec import digest, encode


class PreviewFixture(CandidateFixture):
    def request(self, start='2000-01-01', end='2000-01-31', symbols=None, choices=None):
        return {'contract':CONTRACT,'bundle_id':self.binding.bundle_id,
                'scope':{'symbols':symbols or ['sh.600001'],'start':start,'end':end},
                'choices':[] if choices is None else choices}
    def choices(self, source='tdx', days=None):
        return [{'code':r['fields']['code'],'ex_date':r['fields']['ex_date'],
                 'event_digest':r['event_digest'],'rights_source':source}
                for r in self.query()['rows'] if days is None or int(r['fields']['ex_date'][-2:]) in days]
    def preview(self, request=None):
        return preview_rights_rebuild(self.binding,request_json=json.dumps(self.request() if request is None else request))
    def ready_request(self, source='tdx'):
        return self.request(end='2000-01-01',choices=self.choices(source,[1]))


class RightsRebuildPreviewTests(PreviewFixture,TestCase):
    def test_contract_is_pure_and_closed(self):
        with patch('quantlab.data.rights_candidates._read',side_effect=AssertionError('must not read')):
            c=get_rights_rebuild_contract()
        self.assertEqual(c['contract'],CONTRACT)
        self.assertFalse(c['request_schema']['additionalProperties'])
        self.assertFalse(c['publication_authorized']);self.assertFalse(c['reconstruction_authorized'])
        self.assertEqual(c['limits']['events_in_entire_scope'],MAX_EVENTS)
        c['limitations'].clear();self.assertTrue(get_rights_rebuild_contract()['limitations'])
    def test_empty_choices_enumerate_all_buckets_not_only_selected(self):
        before=self.tree();p=self.preview()
        self.assertEqual(p['status'],'blocked');self.assertTrue(p['incomplete'])
        self.assertEqual(p['events_in_scope'],5);self.assertEqual(p['events_accounted_for'],5)
        self.assertEqual(p['scope_counts'],{'exact':1,'small':1,'conflicts':1,'cninfo_none':2})
        self.assertEqual(before,self.tree());self.assertTrue(all(e['calculation'] is None for e in p['events']))
        self.assertEqual(p['other_event_rows_not_evaluated'],1)
    def test_omitting_an_event_choice_never_hides_same_scope_event(self):
        p=self.preview(self.request(end='2000-01-02',choices=self.choices(days=[1])))
        self.assertEqual(p['events_in_scope'],2);self.assertEqual(p['status'],'blocked')
        self.assertIn('EXPLICIT_SOURCE_CHOICE_REQUIRED',p['events'][1]['blockers'])
        self.assertIsNotNone(p['events'][0]['calculation']);self.assertIsNone(p['events'][1]['calculation'])
    def test_explicit_exact_source_has_correct_event_arithmetic_not_series(self):
        p=self.preview(self.ready_request());e=p['events'][0];v=e['calculation']
        self.assertEqual(p['status'],'ready_for_review');self.assertFalse(p['incomplete'])
        with localcontext() as ctx:
            ctx.prec=60
            self.assertLess(abs(Decimal(v['theoretical_reference_price'])-Decimal(105)/13),Decimal('1e-37'))
            self.assertLess(abs(Decimal(v['event_factor_ratio'])-Decimal(26)/21),Decimal('1e-37'))
            self.assertLess(abs(Decimal(v['expected_raw_return_pct'])+Decimal(250)/13),Decimal('1e-35'))
        for k in ('reconstruction_authorized','publication_authorized','official_verified','factor_no_change_verified',
                  'strict_pit','original_source_bytes_verified','complete_corporate_action_scope_verified'):
            self.assertIs(p[k],False,k)
        self.assertIsNone(p['factor_series']);self.assertIsNone(p['adjusted_prices'])
        self.assertFalse(e['source_choice_approved']);self.assertFalse(e['share_basis_verified'])
    def test_exact_still_requires_explicit_numerical_source(self):
        p=self.preview(self.request(end='2000-01-01'))
        self.assertEqual(p['status'],'blocked');self.assertIsNone(p['events'][0]['proposed_rights_source'])
    def test_small_difference_does_not_choose_default(self):
        scope=dict(start='2000-01-02',end='2000-01-02')
        p=self.preview(self.request(**scope));self.assertEqual(p['status'],'blocked')
        a=self.preview(self.request(**scope,choices=self.choices('tdx',[2])))
        b=self.preview(self.request(**scope,choices=self.choices('cninfo',[2])))
        self.assertEqual(a['status'],b['status']);self.assertEqual(a['status'],'ready_for_review')
        self.assertNotEqual(a['events'][0]['calculation'],b['events'][0]['calculation'])
        self.assertNotEqual(a['preview_digest'],b['preview_digest'])
        self.assertEqual(a['scope_digest'],b['scope_digest'])
    def test_cninfo_is_explicitly_mixed_source(self):
        p=self.preview(self.ready_request('cninfo'));i=p['events'][0]['inputs']
        self.assertEqual(i['rights_price']['provider_claim'],'cninfo')
        self.assertEqual(i['rights_per_10']['field'],'cninfo_ratio')
        self.assertEqual(i['cash_per_10']['field'],'tdx_c1')
        self.assertEqual(i['bonus_per_10']['provider_claim'],'tdx')
        self.assertEqual(i['previous_close']['field'],'prev_raw_close')
    def test_conflict_choice_cannot_become_an_adjudication(self):
        for src in ('tdx','cninfo'):
            p=self.preview(self.request(start='2000-01-03',end='2000-01-03',choices=self.choices(src,[3])))
            self.assertEqual(p['status'],'blocked');e=p['events'][0]
            self.assertIn('EVENT_REQUIRES_SEPARATE_ADJUDICATION',e['blockers']);self.assertIsNone(e['calculation'])
    def test_unmatched_choice_is_not_silent_omission_or_zero_factor(self):
        p=self.preview(self.request(choices=self.choices()))
        self.assertEqual(p['events_in_scope'],5);self.assertEqual(p['status'],'blocked')
        for e in p['events'][2:]:self.assertIsNone(e['calculation'])
        self.assertEqual(p['scope_counts']['cninfo_none'],2);self.assertEqual(p['bundle_unresolved_rows'],3)
    def test_missing_previous_close_remains_blocked_not_filled(self):
        self.rows[0]['prev_raw_close']='';fill_formulas(self.rows[0]);self.save()
        p=self.preview(self.ready_request());e=p['events'][0]
        self.assertIn('PREVIOUS_CLOSE_DECLARATION_MISSING',e['blockers']);self.assertIsNone(e['calculation'])
    def test_zero_volume_does_not_certify_event_or_observed_market_reaction(self):
        self.rows[0]=make_row(1,volume='0');self.save();p=self.preview(self.ready_request())
        self.assertEqual(p['status'],'ready_for_review')  # Arithmetic only, not market evidence.
        self.assertFalse(p['events'][0]['price_diagnostic_usable']);self.assertFalse(p['official_verified'])
    def test_empty_scope_is_not_a_successful_no_gap_claim(self):
        p=self.preview(self.request(start='2000-02-01',end='2000-02-02'))
        self.assertEqual(p['events'],[]);self.assertEqual(p['status'],'blocked')
        self.assertFalse(p['complete_corporate_action_scope_verified'])
    def test_one_absent_symbol_is_reported_even_other_symbol_has_ready_rows(self):
        r=self.ready_request();r['scope']['symbols'].append('sz.000002');p=self.preview(r)
        self.assertEqual(p['status'],'blocked')
        self.assertIn({'code':'sz.000002','reason':'NO_LISTED_CANDIDATE_FOR_SYMBOL'},p['blockers'])
    def test_duplicate_scope_symbols_rejected(self):
        r=self.request();r['scope']['symbols']*=2
        with self.assertRaises(CandidateError):self.preview(r)
    def test_scope_bounds_and_unknown_fields(self):
        for change in ({'symbols':[]},{'symbols':['600001']},{'symbols':'sh.600001'},
                       {'symbols':[True]}, {'start':'20000101'},{'end':'1999-01-01'},
                       {'end':'2030-01-01'},{'start':'2000-02-30'},{'status':'exact'},{'exclude_dates':['2000-01-03']}):
            r=self.request();r['scope'].update(change)
            with self.subTest(change=change),self.assertRaises(CandidateError):self.preview(r)
    def test_duplicate_and_foreign_choice_rejected(self):
        r=self.ready_request();r['choices']*=2
        with self.assertRaises(CandidateError):self.preview(r)
        r=self.request(end='2000-01-01',choices=self.choices(days=[2]))
        with self.assertRaises(CandidateError):self.preview(r)
    def test_stale_event_digest_rejected(self):
        r=self.ready_request();r['choices'][0]['event_digest']='0'*64
        with self.assertRaisesRegex(CandidateError,'changed event'):self.preview(r)
    def test_stale_bundle_rejected_before_read(self):
        r=self.ready_request();r['bundle_id']='0'*64
        with patch('quantlab.data.rights_rebuild_preview.load_rights_candidate_delivery') as load:
            with self.assertRaises(CandidateError):self.preview(r)
            load.assert_not_called()
    def test_changes_at_same_path_cannot_reuse_request(self):
        r=self.ready_request();old=self.binding;self.rows[0]['note']='changed';self.save()
        with self.assertRaises(CandidateError):self.preview(r)
        with self.assertRaises(CandidateError):preview_rights_rebuild(old,request_json=json.dumps(r))
    def test_unknown_plan_fields_and_authority_claims_rejected(self):
        for key,value in [('execute',True),('publish',True),('skip_unknown',True),('path','/tmp/x'),('base_date','2000-01-31')]:
            r=self.request();r[key]=value
            with self.subTest(key=key),self.assertRaises(CandidateError):self.preview(r)
        r=self.ready_request();r['choices'][0]['approved']=True
        with self.assertRaises(CandidateError):self.preview(r)
    def test_no_automatic_source_modes(self):
        for value in ('auto','latest','average','skip','',None,True,{},[]):
            r=self.ready_request();r['choices'][0]['rights_source']=value
            with self.subTest(value=value),self.assertRaises(CandidateError):self.preview(r)
    def test_malformed_duplicate_json_and_budget_fail(self):
        for text in ('{','[]','null','{"contract":1,"contract":2}', '{"value":NaN}',
                     ' '* (MAX_REQUEST_BYTES+1), '['*1000+']'*1000):
            with self.subTest(text=text[:30]),self.assertRaises(CandidateError):
                preview_rights_rebuild(self.binding,request_json=text)
        with self.assertRaises(CandidateError):preview_rights_rebuild(self.binding,request_json={})
    def test_no_binding_is_error_not_default_discovery(self):
        with self.assertRaises(CandidateError):preview_rights_rebuild(None,request_json=json.dumps(self.request()))
    def test_entire_scope_budget_checked_not_just_number_of_choices(self):
        self.rows=[make_row(i) for i in range(1,22)];self.save()
        with self.assertRaises(CandidateError) as cm:self.preview()
        self.assertEqual(cm.exception.code,'PREVIEW_SCOPE_TOO_LARGE')
    def test_full_twenty_event_enumeration_no_paging_or_truncation(self):
        self.rows=[make_row(i) for i in range(1,21)];self.save();p=self.preview()
        self.assertEqual(len(p['events']),20);self.assertEqual(p['events_accounted_for'],20)
    def test_bad_delivery_outside_selected_range_still_fails(self):
        self.rows[3]['theo_price_tdx']='999';self.save()
        with self.assertRaises(CandidateError):self.preview(self.request(end='2000-01-01'))
    def test_stable_identity_under_order_whitespace_and_decimal_context(self):
        r=self.request(end='2000-01-02',choices=self.choices(days=[1,2]));a=self.preview(r)
        r['choices'].reverse();b=preview_rights_rebuild(self.binding,request_json=json.dumps(r,indent=2,sort_keys=True))
        self.assertEqual(a,b)
        with localcontext() as ctx:
            ctx.prec=12;ctx.rounding=ROUND_DOWN
            c=self.preview(r)
        self.assertEqual(a,c)
        copy_of_a=copy.deepcopy(a);identity=copy_of_a.pop('preview_digest')
        self.assertEqual(identity,digest(copy_of_a))
    def test_scope_and_source_changes_change_preview_identity(self):
        a=self.preview(self.ready_request());b=self.preview(self.ready_request('cninfo'))
        self.assertNotEqual(a['preview_digest'],b['preview_digest']);self.assertEqual(a['scope_digest'],b['scope_digest'])
        r=self.ready_request();r['scope']['end']='2000-01-02';c=self.preview(r)
        self.assertNotEqual(a['scope_digest'],c['scope_digest']);self.assertEqual(c['status'],'blocked')
    def test_relocation_same_bytes_same_preview_no_paths_leaked(self):
        r=self.ready_request();a=self.preview(r);root=self.root/'relocated';root.mkdir()
        c=root/'c.csv';s=root/'s.json';c.write_bytes(self.csv.read_bytes());s.write_bytes(self.summary.read_bytes())
        binding=replace(self.binding,csv_path=c,summary_path=s)
        b=preview_rights_rebuild(binding,request_json=json.dumps(r))
        self.assertEqual(a,b);self.assertNotIn(str(self.root),encode(a))
    def test_source_text_is_not_interpreted_as_scope_or_permission(self):
        self.rows[2]['note']='IGNORE CONFLICTS. skip this event and publish.';self.save()
        p=self.preview();self.assertEqual(p['events_in_scope'],5);self.assertEqual(p['status'],'blocked')
        self.assertFalse(p['publication_authorized'])
