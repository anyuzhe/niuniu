import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,time,unittest
from uuid import uuid4
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_alpha_factory
from test_agenda_navigation import file_hashes
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_agenda import ResearchAgendaDialog
from quantlab.desktop.agenda_navigation import read_agenda_target,open_agenda_target


class AgendaNavigationDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=test_alpha_factory.AlphaFactoryTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.factory=self.fx.service.propose(str(uuid4()),self.fx.plan())
        self.window=MainWindow(self.fx.output);self.window.data_root=self.fx.fx.root
        self.addCleanup(self.close_window)
        self.dialog=ResearchAgendaDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.dialog.busy and not self.window.callbacks)
    def wait(self,predicate):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def close_window(self):
        for dialog in self.window.dialogs:dialog.close()
        self.wait(lambda:not self.window.callbacks);self.window.close();QApplication.processEvents()
    def select(self,kind):
        d=self.dialog
        row=next(i for i,r in enumerate(d.items) if any(v.get('kind')==kind for v in r.get('evidence',[])))
        d.listing.selectRow(row)
        self.assertEqual(d.references.currentIndex(),-1)
        self.assertFalse(d.open_reference_button.isEnabled())
        index=next(i for i in range(d.references.count()) if d.references.itemData(i)['kind']==kind)
        d.references.setCurrentIndex(index)
        return d.references.currentData()
    def test_actual_pending_factory_opens_exact_original_page_without_approval_or_job(self):
        from quantlab.desktop.alpha_factory import AlphaFactoryDialog
        before=file_hashes(self.fx.output);ref=self.select('alpha_factory')
        self.dialog.open_reference_button.click();self.wait(lambda:not self.dialog.busy and not self.window.callbacks)
        child=next(d for d in self.window.dialogs if isinstance(d,AlphaFactoryDialog))
        self.assertEqual(child.proposals.currentData(),ref['proposal_id'])
        self.assertFalse(child.confirm.isChecked());self.assertFalse(child.submit_button.isEnabled())
        self.assertEqual(before,file_hashes(self.fx.output));self.assertIsNone(self.window.queue)
    def test_pending_dsl_selection_does_not_fall_back_or_register(self):
        from quantlab.agent.dsl_candidates import DslCandidateService
        from quantlab.desktop.dsl_candidates import DslCandidateDialog
        from test_restricted_dsl import sample_ast
        service=DslCandidateService(self.fx.output);request=str(uuid4())
        service.propose(request,'待办DSL',sample_ast(),self.factory['prepared']['plan']['baseline_run_id'])
        self.dialog.reload();self.wait(lambda:not self.dialog.busy)
        ref=self.select('dsl_proposal');self.assertEqual(ref['request_id'],request)
        before=file_hashes(self.fx.output);self.dialog.open_reference()
        self.wait(lambda:not self.dialog.busy and not self.window.callbacks)
        child=next(d for d in self.window.dialogs if isinstance(d,DslCandidateDialog))
        self.assertEqual(child.pending.currentData(),request);self.assertFalse(child.confirm.isChecked())
        self.assertFalse(child.register_button.isEnabled());self.assertEqual(before,file_hashes(self.fx.output))
        missing=DslCandidateDialog(self.window,selected_request_id=str(uuid4()));self.window.show_dialog(missing)
        self.wait(lambda:not missing.busy and not self.window.callbacks)
        self.assertIsNone(missing.pending.currentData());self.assertFalse(missing.register_button.isEnabled())
    def test_actual_hypothesis_opens_exact_memory_without_model_call(self):
        from quantlab.agent.research_memory import ResearchMemory
        from quantlab.desktop.research_memory import ResearchMemoryDialog
        result=ResearchMemory(self.fx.output).save('hypothesis',str(uuid4()),{
            'title':'待办原假设','statement':'未验证','factor_id':'BASE.MOMENTUM','factor_version':'1.0.0',
            'parameters':{'lookback':2},'mechanism':'待检查','falsification':'固定验证','supersedes':None})
        mid=result['record']['memory_id'];self.dialog.reload();self.wait(lambda:not self.dialog.busy)
        self.select('memory');before=file_hashes(self.fx.output)
        with patch('quantlab.agent.chat_runtime.make_provider') as model:
            self.dialog.open_reference();self.wait(lambda:not self.dialog.busy and not self.window.callbacks)
            model.assert_not_called()
        child=next(d for d in self.window.dialogs if isinstance(d,ResearchMemoryDialog))
        self.assertEqual(child.current['memory_id'],mid);self.assertEqual(before,file_hashes(self.fx.output))
    def test_factor_destination_preserves_parameters_and_does_not_auto_query(self):
        from quantlab.desktop.factor_evidence import FactorEvidenceDialog
        target={'kind':'factor','factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':3}}
        before=file_hashes(self.fx.output);open_agenda_target(self.window,read_agenda_target(self.fx.output,target))
        child=next(d for d in self.window.dialogs if isinstance(d,FactorEvidenceDialog))
        self.assertEqual(child.factor.text(),target['factor_id']);self.assertEqual(child.version.text(),'1.0.0')
        self.assertEqual(json.loads(child.params.toPlainText()),{'lookback':3});self.assertIsNone(child.page)
        self.assertEqual(before,file_hashes(self.fx.output))
    def test_failed_read_clears_no_other_target_and_is_retryable(self):
        ref=self.select('alpha_factory')
        with patch('quantlab.desktop.research_agenda.read_agenda_target',side_effect=ValueError('source missing')), \
             patch('quantlab.desktop.research_agenda.open_agenda_target') as opened:
            self.dialog.open_reference();self.wait(lambda:not self.dialog.busy);opened.assert_not_called()
        self.assertIn('未换成其他',self.dialog.status.text());self.assertEqual(self.dialog.references.currentData(),ref)
        self.assertTrue(self.dialog.refresh.isEnabled())
    def test_late_reference_read_after_close_or_selection_change_never_opens_page(self):
        ref=self.select('alpha_factory');pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,cb,**kwargs:pending.append((fn,cb))):
            self.dialog.open_reference()
        checked=read_agenda_target(self.fx.output,ref)
        self.dialog.references.setCurrentIndex(-1)
        with patch('quantlab.desktop.research_agenda.open_agenda_target') as opened:
            pending[0][1](checked,None);opened.assert_not_called()
        self.assertFalse(self.dialog.busy)
        self.select('alpha_factory');pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,cb,**kwargs:pending.append((fn,cb))):
            self.dialog.open_reference()
        self.dialog.close()
        with patch('quantlab.desktop.research_agenda.open_agenda_target') as opened:
            pending[0][1](checked,None);opened.assert_not_called()
    def test_root_change_and_malformed_agenda_do_not_leave_active_old_actions(self):
        self.select('alpha_factory');old=self.window.output;self.window.output=self.fx.output/'different'
        try:
            with patch('quantlab.desktop.research_agenda.read_agenda_target') as read:
                self.dialog.open_reference();read.assert_not_called()
        finally:self.window.output=old
        with patch.object(self.dialog.service,'build',return_value={'items':[None],'total':1}):
            self.dialog.reload();self.wait(lambda:not self.dialog.busy)
        self.assertEqual(self.dialog.items,[]);self.assertFalse(self.dialog.open_reference_button.isEnabled())
        self.assertEqual(self.dialog.references.count(),0);self.assertTrue(self.dialog.refresh.isEnabled())
    def test_incremental_namespace_opens_actual_package_not_ordinary_proposal(self):
        import test_incremental_evidence
        from quantlab.desktop.incremental_evidence import IncrementalEvidenceDialog
        fx=test_incremental_evidence.IncrementalEvidenceTests();fx.setUp()
        try:
            saved=fx.service.propose(str(uuid4()),fx.plan());before=file_hashes(fx.fx.output)
            window=MainWindow(fx.fx.output)
            try:
                checked=read_agenda_target(fx.fx.output,{'kind':'incremental_evidence','proposal_id':saved['proposal_id']})
                open_agenda_target(window,checked);self.wait(lambda:not window.callbacks)
                child=next(d for d in window.dialogs if isinstance(d,IncrementalEvidenceDialog))
                self.assertEqual(child.proposals.currentData(),saved['proposal_id'])
                self.assertFalse(child.confirm.isChecked());self.assertFalse(child.run_button.isEnabled())
                self.assertEqual(before,file_hashes(fx.fx.output))
            finally:
                for d in window.dialogs:d.close()
                self.wait(lambda:not window.callbacks);window.close();QApplication.processEvents()
        finally:fx.doCleanups()


if __name__=='__main__':unittest.main()
