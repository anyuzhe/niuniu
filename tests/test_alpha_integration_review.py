"""Independent regression cases for evidence provenance, pagination and native UI routing."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from quantlab.trading.research_evidence import find_factor_evidence, archive_research_reference
from quantlab.desktop.factor_evidence import FactorEvidenceDialog
from quantlab.desktop.data_workbench import DataConnectedWorkbench, DataResearchChatDialog
from quantlab.desktop.research_chat import ResearchChatDialog
import test_phase1_desktop_evidence as fixtures

class IntegrationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def record(self,i,*,version='1',raw=None,resolved=None):
        rid=str(UUID(int=i));folder=self.root/rid;folder.mkdir()
        manifest={'config':{'factor_id':'BASE.TEST','factor_version':version,'parameters':raw or {},'data':{}},
                  'execution':{'commission_rate':0.0001,'stamp_duty':0.0005}}
        if resolved is not None:manifest['parameters']=resolved
        record={'run_id':rid,'experiment_id':'fixture','status':'completed','manifest':manifest,
                'created_at':'2026-09-27T00:00:00Z','limitations':['fixture, not formal research']}
        (folder/'experiment.json').write_text(json.dumps(record))
        return rid
    def test_pagination_never_consumes_unreturned_matches_or_errors(self):
        expected=[self.record(i) for i in range(1,46)]
        bad=str(UUID(int=46));(self.root/bad).mkdir();(self.root/bad/'experiment.json').write_text('{broken')
        offset=0;seen=[];errors=[]
        while True:
            result=find_factor_evidence(self.root,factor_id='BASE.TEST',limit=20,scan_budget=60,offset=offset)
            seen.extend(r['source']['run_id'] for r in result['matches']);errors.extend(result['errors'])
            self.assertLessEqual(len(result['matches'])+len(result['mismatches'])+len(result['errors']),20)
            if result['next_offset'] is None:break
            self.assertGreater(result['next_offset'],offset);offset=result['next_offset']
        self.assertEqual(sorted(seen),expected);self.assertEqual(errors[0]['run_id'],bad)
    def test_manifest_parameters_and_execution_are_authoritative_header_fields(self):
        rid=self.record(1,raw={},resolved={'lookback':20})
        result=find_factor_evidence(self.root,factor_id='BASE.TEST',parameters={'lookback':20})
        self.assertEqual(len(result['matches']),1)
        reference=archive_research_reference(self.root,rid)
        self.assertTrue(reference['metadata_only']);self.assertFalse(reference['deep_verified'])
        self.assertEqual(reference['costs']['configuration']['commission_rate'],0.0001)
        self.assertEqual(find_factor_evidence(self.root,factor_id='BASE.TEST',parameters={})['matches'],[])
    def test_pending_response_after_bad_json_or_close_cannot_restore_old_rows(self):
        self.record(1);window=fixtures._Window(self.root);dialog=FactorEvidenceDialog(window)
        dialog.factor.setText('BASE.TEST');dialog.reload(True);work,done,_=window.calls.pop()
        dialog.params.setPlainText('[');dialog.reload(True);done(work(),'')
        self.assertEqual(dialog.rows,[])
        dialog.params.setPlainText('');dialog.reload(True);work,done,_=window.calls.pop()
        dialog.reject();done(work(),'');self.assertEqual(dialog.rows,[])
    def test_open_rechecks_original_fingerprint_and_workspace(self):
        rid=self.record(1);window=fixtures._Window(self.root);dialog=FactorEvidenceDialog(window)
        dialog.factor.setText('BASE.TEST');dialog.reload(True);work,done,_=window.calls.pop();done(work(),'')
        dialog.open_row(0);work,done,_=window.calls.pop()
        p=self.root/rid/'experiment.json';r=json.loads(p.read_text());r['limitations'].append('revision');p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'变化'):work()
        done(None,'source changed');self.assertEqual(dialog.rows,[]);self.assertFalse(hasattr(window,'opened_run'))
    def test_data_workbench_routes_formal_and_daily_drafts_to_correct_native_dialog(self):
        class Host:
            def _open_research_chat(self,*args):self.args=args;return True
        host=Host()
        self.assertTrue(DataConnectedWorkbench.research_chat(host,profile='research',draft='正式草稿'))
        self.assertIs(host.args[0],DataResearchChatDialog);self.assertEqual(host.args[1:],('research','正式草稿'))
        DataConnectedWorkbench.research_chat(host,profile='everyday',draft='市场问题')
        self.assertIs(host.args[0],ResearchChatDialog)
