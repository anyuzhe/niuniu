import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,unittest
from unittest.mock import patch
from uuid import uuid4
from PyQt6.QtWidgets import QApplication
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.desktop.agenda_navigation import read_agenda_target,open_agenda_target
import test_agenda_navigation_desktop as ui


# Use explicit helper delegation instead of inheriting any test_* methods.
class AgendaBoundaryReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=ui.AgendaNavigationDesktopTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
    def test_incomplete_memory_scan_does_not_claim_a_hypothesis_has_no_finding(self):
        hid=str(uuid4())
        rows=[{'kind':'hypothesis','title':'原假设','memory_id':hid}]
        rows += [{'kind':'finding','hypothesis_id':str(uuid4()),'memory_id':str(uuid4())} for _ in range(199)]
        def search(*_,offset=0,limit=20,**kwargs):
            return {'records':rows[offset:offset+limit],'total':201,'next_offset':offset+limit}
        with patch('quantlab.agent.research_agenda.MemoryStore') as store:
            store.return_value.search.side_effect=search
            items=self.fx.dialog.service._memory_items()
            self.assertEqual(store.return_value.search.call_count,10)
        kinds=[v['kind'] for v in items]
        self.assertNotIn('open_hypothesis',kinds);self.assertIn('memory_scan_limited',kinds)
        self.assertIn('hypothesis_review_needed',kinds)
        self.assertEqual(items[0]['evidence'][0]['memory_id'],hid)
    def test_complete_memory_scan_keeps_definite_open_and_excludes_linked_hypotheses(self):
        a,b=str(uuid4()),str(uuid4())
        records=[{'kind':'hypothesis','title':'open','memory_id':a},
                 {'kind':'hypothesis','title':'has finding','memory_id':b},
                 {'kind':'finding','hypothesis_id':b}]
        with patch('quantlab.agent.research_agenda.MemoryStore') as store:
            store.return_value.search.return_value={'records':records,'next_offset':None}
            items=self.fx.dialog.service._memory_items()
        self.assertEqual(len(items),1);self.assertEqual(items[0]['kind'],'open_hypothesis')
        self.assertEqual(items[0]['evidence'][0]['memory_id'],a)
    def test_bad_reference_receipt_does_not_open_different_factory(self):
        d=self.fx.dialog;self.fx.select('alpha_factory')
        wrong={'reference':{'kind':'alpha_factory','proposal_id':str(uuid4())},'source_digest':'a'*64}
        with patch('quantlab.desktop.research_agenda.read_agenda_target',return_value=wrong), \
             patch('quantlab.desktop.research_agenda.open_agenda_target') as opened:
            d.open_reference();self.fx.wait(lambda:not d.busy);opened.assert_not_called()
        self.assertIn('不一致',d.status.text())
    def test_exact_failed_job_record_opens_without_queue_or_retry(self):
        root=self.fx.fx.output;folder=root/'_jobs';folder.mkdir();jid=str(uuid4())
        path=folder/(jid+'.json');path.write_text(json.dumps({'job_id':jid,'status':'failed',
            'error':'engineering fixture failure','run_id':None,'attempt':1}))
        before=path.read_bytes();target={'kind':'job','job_id':jid}
        checked=read_agenda_target(root,target)
        open_agenda_target(self.fx.window,checked)
        self.assertEqual(checked['read_only_record']['status'],'failed')
        self.assertEqual(before,path.read_bytes());self.assertIsNone(self.fx.window.queue)
    def test_registered_dsl_and_memory_destinations_reject_stale_window_actions(self):
        from quantlab.desktop.dsl_candidates import DslCandidateDialog
        from quantlab.desktop.research_memory import ResearchMemoryDialog
        dsl=DslCandidateDialog(self.fx.window);self.fx.window.show_dialog(dsl)
        self.fx.wait(lambda:not self.fx.window.callbacks)
        memory=ResearchMemoryDialog(self.fx.window);self.fx.window.show_dialog(memory)
        self.fx.wait(lambda:not self.fx.window.callbacks)
        old=self.fx.window.output;self.fx.window.output=old/'changed'
        try:
            with patch.object(dsl.service,'register') as register,patch.object(memory.service,'get') as reader:
                dsl.confirm.setChecked(True);dsl.register();memory.load(str(uuid4()))
                register.assert_not_called();reader.assert_not_called()
        finally:self.fx.window.output=old
    def test_malformed_reference_does_not_crash_the_legacy_watch_shortcut(self):
        d=self.fx.dialog
        d.items=[{'title':'坏引用','evidence':[None,{'kind':[]},'not a reference']}]
        d.listing.setRowCount(1);d.listing.selectRow(0)
        self.assertEqual(d.references.count(),0);self.assertIsNone(d.selected_watch())
        self.assertFalse(d.open_watch_button.isEnabled());self.assertFalse(d.open_reference_button.isEnabled())
        self.assertIn('无效引用',d.status.text())
    def test_incremental_window_cannot_execute_after_close_even_if_confirmation_is_set(self):
        from quantlab.desktop.incremental_evidence import IncrementalEvidenceDialog
        child=IncrementalEvidenceDialog(self.fx.window);self.fx.window.show_dialog(child)
        self.fx.wait(lambda:not self.fx.window.callbacks)
        child.current={'status':'pending','proposal_id':str(uuid4()),'prepared_digest':'a'*64}
        child.confirm.setChecked(True);child.close()
        with patch.object(child.service,'execute') as execute:child.execute();execute.assert_not_called()


if __name__=='__main__':unittest.main()
