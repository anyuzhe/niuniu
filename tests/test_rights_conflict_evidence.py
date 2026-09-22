"""F19 supplemental rights evidence validation on synthetic deliveries only."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import copy, hashlib, json

from test_rights_candidates import CandidateFixture
from quantlab.data.rights_candidates import CandidateError
from quantlab.data.rights_conflict_evidence import (
    RightsConflictEvidenceBinding, EvidenceError, canonical_parent_event_digest,
    get_rights_conflict_evidence_manifest, query_rights_conflict_evidence,
)
from quantlab.data.rights_rebuild_preview import preview_rights_rebuild


def sha(b): return hashlib.sha256(b).hexdigest()


class ConflictEvidenceFixture(CandidateFixture):
    def setUp(self):
        super().setUp()
        conflict = next(r for r in self.query(status='conflicts')['rows'])
        f = conflict['fields']
        self.evidence_row = {
            'action_or_plan_id':'unknown','action_or_plan_id_reason':'no id',
            'cninfo_allotted_shares':100.0,'cninfo_announce_date':'1999-12-20','cninfo_ex_date':f['ex_date'],
            'cninfo_issue_method':None,'cninfo_listing_date':'2000-01-20','cninfo_other_plans_within_10d':'',
            'cninfo_plan_matched_on_ex_date':1,'cninfo_plans_for_code':1,
            'cninfo_price':float(f['cninfo_price']),'cninfo_ratio':float(f['cninfo_ratio']),
            'cninfo_record_date':'2000-01-02','cninfo_shares_after_float':None,
            'cninfo_shares_after_total':1100.0,'cninfo_shares_before_float':None,
            'cninfo_shares_before_total':1000.0,'cninfo_underwriting':None,
            'code':f['code'],'diagnostics':{'tdx_only_allotted_shares':None,
                'tdx_only_vs_cninfo_allotted_rel':None,'NOTE':'diagnostic only'},
            'dispute_locus':{'price_rel_diff':None,'ratio_rel_diff':0.0,'price_in_dispute':None,
                'ratio_in_dispute':False,'tdx_zero_slots':['tdx_c2_price'],
                'locus':'PRICE_SLOT_ONLY__TDX_PRICE_IS_ZERO','note':'do not swap slots'},
            'dividend_corroboration':'NO_SOURCE_COVERS_THIS_DATE',
            'dividend_source_coverage':{'eastmoney':{'covered':False},'ths':{'covered':False}},
            'event_class':'rights_issue_missing','ex_date':f['ex_date'],
            'missing_evidence':['official implementation notice','share base'],
            'parent_csv_sha256':self.binding.csv_sha256,
            'parent_event_digest':canonical_parent_event_digest(f),
            'parent_summary_sha256':self.binding.summary_sha256,
            'plan_match_warning':'','questions':{'q1_same_plan':'UNKNOWN'},
            'share_base_finding':{'cninfo_over_tdx_reported_before_total':1.0,
                'bonus_factor_from_tdx_c3':1.1,'finding':'REPORTED_TOTALS_AGREE',
                'allotted_shares_cross_source_confirmed':False,
                'tdx_ratio_base_identified':False,'tdx_ratio_base_match':None,
                'cninfo_ratio_base_identified':False,'cninfo_ratio_base_match':None},
            'tdx_c1_cash':float(f['tdx_c1']),'tdx_c2_price':float(f['tdx_c2_price']),
            'tdx_c3_bonus':float(f['tdx_c3']),'tdx_c4_ratio':float(f['tdx_c4_ratio']),
            'tdx_capital_rows_window':[],'tdx_categories_on_ex_date':'除权除息',
            'tdx_float_shares_before':None,'tdx_n_events_60d':1,'tdx_timeline_60d':[],
            'tdx_total_shares_after':None,'tdx_total_shares_before':None,
            'verdict':'UNRESOLVED','verdict_reason':'missing original announcement',
        }
        self.evidence_jsonl=self.root/'rights-19-evidence.jsonl'
        self.evidence_summary=self.root/'rights-19-summary.json'
        self.save_evidence()

    def save_evidence(self, rows=None, summary_changes=None):
        rows = [self.evidence_row] if rows is None else rows
        payload = ''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for r in rows).encode()
        self.evidence_jsonl.write_bytes(payload)
        share = {}
        locus = {}
        dividends = {}
        verdicts = {}
        for r in rows:
            verdicts[r['verdict']]=verdicts.get(r['verdict'],0)+1
            s=r['share_base_finding']['finding'];share[s]=share.get(s,0)+1
            l=r['dispute_locus']['locus'];locus[l]=locus.get(l,0)+1
            d=r['dividend_corroboration'];dividends[d]=dividends.get(d,0)+1
        summary={'deterministic':True,'note':'synthetic','parent_csv_sha256':self.binding.csv_sha256,
            'parent_summary_sha256':self.binding.summary_sha256,'summarises_jsonl_sha256':sha(payload),
            'source_of_truth':'evidence/rights-19-evidence.jsonl','scope':'synthetic conflict set',
            'n_records':len(rows),'n_unique_code_exdate':len({(r['code'],r['ex_date']) for r in rows}),
            'verdicts':verdicts,'share_base_findings':share,'dispute_locus':locus,
            'allotted_shares_tdx_derivable':0,'allotted_shares_cross_source_confirmed':0,
            'allotted_shares_cross_source_conflict':0,'dividend_corroboration':dividends,
            'adjudications_made':0,'price_evidence_used':False,'parent_files_modified':False}
        if summary_changes: summary.update(summary_changes)
        self.evidence_summary.write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True))
        self.evidence_binding=RightsConflictEvidenceBinding(
            self.evidence_jsonl,self.evidence_summary,sha(self.evidence_jsonl.read_bytes()),sha(self.evidence_summary.read_bytes()))

    def evidence_query(self, **changes):
        args={'symbol':'','start':'2000-01-01','end':'2000-01-31','offset':0,'limit':5}
        return query_rights_conflict_evidence(self.binding,self.evidence_binding,**{**args,**changes})


class RightsConflictEvidenceTests(ConflictEvidenceFixture,TestCase):
    def test_manifest_and_query_are_unresolved_read_only(self):
        before=self.tree();m=get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)
        self.assertEqual((m['records'],m['unresolved_records'],m['adjudications_made']),(1,1,0))
        self.assertFalse(m['price_evidence_used']);self.assertFalse(m['adjudication_authorized'])
        q=self.evidence_query();self.assertEqual(q['pagination']['total'],1)
        r=q['rows'][0];self.assertEqual(r['verdict'],'UNRESOLVED');self.assertIsNone(r['source_choice'])
        self.assertEqual(before,self.tree())

    def test_parent_digest_matches_data_side_serialization(self):
        conflict=next(r for r in self.query(status='conflicts')['rows'])
        self.assertEqual(canonical_parent_event_digest(conflict['fields']),self.evidence_row['parent_event_digest'])

    def test_wrong_hash_and_changed_bytes_fail(self):
        old=self.evidence_binding
        bad=replace(old,jsonl_sha256='0'*64)
        with self.assertRaises(CandidateError):get_rights_conflict_evidence_manifest(self.binding,bad)
        self.evidence_jsonl.write_bytes(self.evidence_jsonl.read_bytes()+b'\n')
        with self.assertRaises(CandidateError):get_rights_conflict_evidence_manifest(self.binding,old)

    def test_summary_parent_or_jsonl_binding_mismatch_fails(self):
        # Boolean values are not valid integer counters even though bool subclasses int.
        for change in ({'parent_csv_sha256':'0'*64},{'parent_summary_sha256':'0'*64},
                       {'summarises_jsonl_sha256':'0'*64},{'adjudications_made':1},
                       {'price_evidence_used':True},{'parent_files_modified':True}):
            self.save_evidence(summary_changes=change)
            with self.subTest(change=change),self.assertRaises(EvidenceError):
                get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_summary_boolean_counters_do_not_pass_as_ints(self):
        for field in ('n_records','n_unique_code_exdate','allotted_shares_tdx_derivable','adjudications_made'):
            self.save_evidence(summary_changes={field: True})
            with self.subTest(field=field),self.assertRaises(EvidenceError):
                get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_missing_duplicate_foreign_and_parent_digest_fail(self):
        self.save_evidence(rows=[])
        with self.assertRaises(EvidenceError):get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)
        self.save_evidence(rows=[self.evidence_row,copy.deepcopy(self.evidence_row)])
        with self.assertRaises(EvidenceError):get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)
        for field,value in [('code','sz.000999'),('parent_event_digest','0'*64),('verdict','CONFIRMED')]:
            r=copy.deepcopy(self.evidence_row);r[field]=value;self.save_evidence(rows=[r])
            with self.subTest(field=field),self.assertRaises(EvidenceError):
                get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_parent_numeric_claims_must_match(self):
        for field in ('tdx_c1_cash','tdx_c2_price','tdx_c3_bonus','tdx_c4_ratio','cninfo_price','cninfo_ratio'):
            r=copy.deepcopy(self.evidence_row);r[field]=(r[field] or 0)+1;self.save_evidence(rows=[r])
            with self.subTest(field=field),self.assertRaises(EvidenceError):
                get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_nonfinite_duplicate_key_and_extra_field_fail(self):
        raw=json.dumps(self.evidence_row,ensure_ascii=False).replace('"cninfo_price": 3.0','"cninfo_price": NaN')
        self.evidence_jsonl.write_text(raw+'\n');self.evidence_binding=replace(
            self.evidence_binding,jsonl_sha256=sha(self.evidence_jsonl.read_bytes()))
        self.save_summary_for_current_jsonl = None
        # Summary hash must bind this corrupted JSONL so failure reaches JSON parsing.
        s=json.loads(self.evidence_summary.read_text());s['summarises_jsonl_sha256']=self.evidence_binding.jsonl_sha256
        self.evidence_summary.write_text(json.dumps(s));self.evidence_binding=replace(
            self.evidence_binding,summary_sha256=sha(self.evidence_summary.read_bytes()))
        with self.assertRaises(EvidenceError):get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)
        r=copy.deepcopy(self.evidence_row);r['extra']='x';self.save_evidence(rows=[r])
        with self.assertRaises(EvidenceError):get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_counted_diagnostics_require_finite_numbers_or_null(self):
        for field in ('tdx_only_allotted_shares','tdx_only_vs_cninfo_allotted_rel'):
            for value in (False, True, '1.25'):
                r=copy.deepcopy(self.evidence_row);r['diagnostics'][field]=value;self.save_evidence(rows=[r])
                with self.subTest(field=field,value=value),self.assertRaises(EvidenceError):
                    get_rights_conflict_evidence_manifest(self.binding,self.evidence_binding)

    def test_preview_attaches_evidence_but_never_removes_conflict_blocker(self):
        event=next(r for r in self.query(status='conflicts')['rows'])
        request={'contract':'niuniu-rights-rebuild-preview-v1','bundle_id':self.binding.bundle_id,
            'scope':{'symbols':[event['fields']['code']],'start':event['fields']['ex_date'],'end':event['fields']['ex_date']},
            'choices':[{'code':event['fields']['code'],'ex_date':event['fields']['ex_date'],
                'event_digest':event['event_digest'],'rights_source':'tdx'}]}
        import json as _json
        plain=preview_rights_rebuild(self.binding,request_json=_json.dumps(request))
        enriched=preview_rights_rebuild(self.binding,request_json=_json.dumps(request),evidence_binding=self.evidence_binding)
        self.assertEqual(plain['status'],enriched['status']);self.assertEqual(enriched['status'],'blocked')
        self.assertIn('EVENT_REQUIRES_SEPARATE_ADJUDICATION',enriched['events'][0]['blockers'])
        self.assertNotIn('supplemental_evidence',plain['events'][0])
        self.assertNotIn('supplemental_evidence_bound',plain)
        self.assertEqual(enriched['events'][0]['supplemental_evidence']['verdict'],'UNRESOLVED')
        self.assertTrue(enriched['supplemental_evidence_bound']);self.assertFalse(enriched['reconstruction_authorized'])

    def test_query_bounds_and_empty_not_resolution(self):
        q=self.evidence_query(symbol='sz.000999');self.assertEqual(q['rows'],[]);self.assertFalse(q['query_scope_complete'])
        for args in ({'offset':True},{'limit':6},{'symbol':'600001'},{'start':'bad'},{'start':'20000101'},
                     {'end':'21000101'},{'end':'1999-01-01'}):
            with self.subTest(args=args),self.assertRaises(EvidenceError):self.evidence_query(**args)
