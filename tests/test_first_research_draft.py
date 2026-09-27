import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib,json,time,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtTest import QTest
import test_core
from quantlab.desktop.app import MainWindow
from quantlab.desktop.experiment import ExperimentDialog
from quantlab.desktop.agent_proposals import ProposalDialog,open_research_draft
from quantlab.desktop.factory_builder import FactoryPlanDialog
from quantlab.desktop.research_picker import FactorPickerDialog
from quantlab.desktop.proposal_progress import ProposalProgressDialog
from quantlab.trading.research_evidence import archive_research_reference
from quantlab.workbench.jobs import prepare


class FirstResearchDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.output=self.fx.root/'first-research';self.output.mkdir()
        self.window=MainWindow(self.output);self.window.data_root=self.fx.root
        self.addCleanup(self.cleanup)
        self.factor=next(d for d in self.window.factors if d['definition']['factor_id']=='BASE.MOMENTUM')
    def wait(self,predicate):
        end=time.monotonic()+30
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def cleanup(self):
        for d in self.window.dialogs:d.close()
        if self.window.queue:self.window.queue.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close();QApplication.processEvents()
    def fill(self,dialog):
        dialog.use_factor(self.factor);dialog.question.setText('工程配置链验收，不是Alpha检验')
        dialog.symbols.setText(' '.join(self.fx.symbols));dialog.start.setDate(QDate(2025,1,1));dialog.end.setDate(QDate(2025,1,10))
        dialog.adjustment.setCurrentIndex(dialog.adjustment.findData('raw'))
        dialog.horizons.setText('1 2');dialog.quantiles.setValue(3)
        dialog.parameters.setPlainText('{"lookback":2}')
        return dialog.collect()
    def drafts(self):return [d for d in self.window.dialogs if isinstance(d,ProposalDialog)]
    def test_blank_entry_does_not_inherit_recent_symbols_or_choose_factor(self):
        self.window.last_records=[{'symbols':['sh.699999'],'start':'2001-01-01','end':'2001-01-02'}]
        dialog=open_research_draft(self.window)
        self.assertTrue(dialog.draft_only);self.assertEqual(dialog.target.currentIndex(),-1)
        self.assertEqual(dialog.symbols.text(),'');self.assertEqual(dialog.question.text(),'')
        self.assertIsNone(self.window.queue);self.assertFalse(list(self.output.glob('*/experiment.json')))
        dialog.submit();self.assertIsNone(dialog.result_spec);self.assertFalse(self.drafts())
    def test_native_submit_method_in_draft_mode_cannot_acquire_queue_or_read_prices(self):
        dialog=open_research_draft(self.window);spec=self.fill(dialog)
        with patch.object(self.window,'get_research_queue',side_effect=AssertionError('must not acquire')) as queue, \
             patch('quantlab.data.qualification.qualify_spec',side_effect=AssertionError('not input validation')) as qualify:
            dialog.submit();queue.assert_not_called();qualify.assert_not_called()
        self.wait(lambda:self.drafts() and not self.drafts()[0].busy)
        proposal=self.drafts()[0]
        self.assertEqual(json.loads(proposal.draft.toPlainText()),spec)
        self.assertFalse(proposal.confirm.isChecked());self.assertIsNone(proposal.selected)
        self.assertEqual(proposal.service.store.list(),[]);self.assertFalse((self.output/'_jobs').exists())
        self.assertTrue(dialog.closed);self.assertEqual(dialog.result_spec,spec)
        dialog.submit();self.assertEqual(len(self.drafts()),1)
    def test_draft_without_data_root_is_allowed_but_does_not_certify_pit(self):
        self.window.data_root=None;dialog=open_research_draft(self.window);self.fill(dialog)
        dialog.qualification.setCurrentIndex(dialog.qualification.findData('strict_pit'))
        self.assertTrue(dialog.validate(),dialog.status.text());self.assertIn('未读取行情或核验数据资格',dialog.status.text())
        dialog.submit();self.assertFalse(dialog.closed);self.assertFalse(self.drafts())
        self.assertIn('尚未指定有效行情目录',dialog.status.text())
        self.assertEqual(dialog.collect()['qualification'],'strict_pit');self.assertIsNone(dialog.result_spec)
        self.assertFalse(list(self.output.glob('_jobs/*.json')))
    def test_cancel_and_workspace_change_never_deliver_or_run(self):
        dialog=open_research_draft(self.window);self.fill(dialog);dialog.reject();dialog.submit()
        self.assertIsNone(dialog.result_spec);self.assertFalse(self.drafts())
        other=open_research_draft(self.window);self.fill(other)
        original=self.window.output;self.window.output=self.fx.root/'different'
        try:other.submit();self.assertIsNone(other.result_spec);self.assertFalse(self.drafts())
        finally:self.window.output=original
        other.reject()
    def test_exact_factor_picker_is_shared_and_does_not_fallback_on_unknown_version(self):
        dialog=open_research_draft(self.window);dialog.pick_factor()
        picker=next(d for d in self.window.dialogs if isinstance(d,FactorPickerDialog))
        picker.search.setText('BASE.MOMENTUM');picker.versions.setCurrentRow(0);picker.use_button.click()
        self.assertEqual(dialog.definitions[dialog.target.currentIndex()]['definition']['factor_id'],'BASE.MOMENTUM')
        bad=deepcopy(self.factor);bad['definition']['version']='not-installed'
        with self.assertRaises(ValueError):dialog.use_factor(bad)
        self.assertFalse((self.output/'_jobs').exists())
    def test_reopening_existing_draft_preserves_parameters_and_rejects_late_overwrite(self):
        first=open_research_draft(self.window);spec=self.fill(first);first.submit()
        self.wait(lambda:self.drafts() and not self.drafts()[0].busy);proposal=self.drafts()[0]
        edit=proposal.edit_form();self.assertTrue(edit.draft_only);self.assertEqual(edit.collect(),spec)
        edit.question.setText('prepared old change')
        newer={**spec,'question':'newer owner edit'};proposal.draft.setPlainText(json.dumps(newer))
        edit.submit();self.assertEqual(json.loads(proposal.draft.toPlainText()),newer)
        self.assertIn('没有覆盖较新的编辑',self.window.status.text());self.assertFalse((self.output/'_jobs').exists())
        again=proposal.edit_form();again.question.setText('explicit current form edit');again.submit()
        self.assertEqual(json.loads(proposal.draft.toPlainText())['question'],'explicit current form edit')
        self.assertFalse(proposal.confirm.isChecked())
    def test_lab_and_factory_entry_do_not_mutate_existing_factory_plan(self):
        self.window.navigate_page('lab');self.wait(lambda:not self.window.callbacks)
        button=next(b for b in self.window.findChildren(QPushButton) if b.text()=='新建待审批研究（无需已有实验）')
        button.click();form=next(d for d in self.window.dialogs if isinstance(d,ExperimentDialog));self.assertTrue(form.draft_only);form.reject()
        factory=FactoryPlanDialog(self.window);self.window.show_dialog(factory)
        factory.name.setText('保留本次Factory');factory.set_factor(self.factor);factory.add_candidate()
        candidates=deepcopy(factory.candidate_refs)
        factory.first_research_button.click()
        self.assertEqual(factory.name.text(),'保留本次Factory');self.assertEqual(factory.candidate_refs,candidates)
        self.assertIsNone(factory.baseline);self.assertFalse((self.output/'_jobs').exists())
    def test_empty_workspace_to_first_approved_archive_and_factory_preflight(self):
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.fx.root/'lake').rglob('*.parquet')}
        self.assertFalse(list(self.output.glob('*/experiment.json')))
        form=open_research_draft(self.window);self.fill(form);form.submit()
        self.wait(lambda:self.drafts() and not self.drafts()[0].busy);proposal=self.drafts()[0]
        proposal.create();self.wait(lambda:not proposal.busy and proposal.selected is not None)
        self.assertEqual(proposal.selected['status'],'pending');self.assertIsNone(self.window.queue)
        proposal.approve();self.assertFalse(list(self.output.glob('_jobs/*.json')))
        proposal.confirm.setChecked(True);proposal.approve();self.wait(lambda:not proposal.busy)
        self.wait(lambda:self.window.queue is not None and all(j['status']=='completed' for j in self.window.queue.list()))
        jobs=self.window.queue.list();self.assertEqual(len(jobs),1);run_id=jobs[0]['run_id']
        proposal.open_progress();progress=next(d for d in self.window.dialogs if isinstance(d,ProposalProgressDialog))
        self.wait(lambda:not progress.busy and progress.report is not None)
        self.assertEqual(progress.report['result']['run_id'],run_id);self.assertTrue(progress.report['can_open_result'])
        ref=archive_research_reference(self.output,run_id)
        factory=FactoryPlanDialog(self.window);self.window.show_dialog(factory)
        factory.name.setText('首份归档用于Factory预检');factory.use_archive('baseline',ref);factory.use_archive('control',ref)
        factory.set_factor(self.factor);factory.parameters={'lookback':3};factory.add_candidate()
        factory.train_end.setText('2025-01-06');factory.evaluation_start.setText('2025-01-07');factory.horizon.setCurrentIndex(factory.horizon.findData(1))
        factory.preview_plan();self.wait(lambda:not factory.busy)
        self.assertIsNotNone(factory.prepared,factory.status.text());self.assertIsNone(factory.saved)
        self.assertEqual(len(self.window.queue.list()),1)
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.fx.root/'lake').rglob('*.parquet')})


if __name__=='__main__':unittest.main()
