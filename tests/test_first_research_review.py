import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,unittest
from unittest.mock import patch
from pathlib import Path
from PyQt6.QtWidgets import QApplication
import test_first_research_draft as fixture
from quantlab.desktop.agent_proposals import open_research_draft,ProposalDialog
from quantlab.desktop.experiment import ExperimentDialog
from quantlab.workbench.jobs import prepare


class FirstResearchReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixture.FirstResearchDraftTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.window=self.fx.window
    def test_explicit_strict_request_is_not_downgraded_when_saving_fails(self):
        form=open_research_draft(self.window);self.fx.fill(form)
        form.qualification.setCurrentIndex(form.qualification.findData('strict_pit'))
        form.submit();self.fx.wait(lambda:self.fx.drafts() and not self.fx.drafts()[0].busy)
        owner=self.fx.drafts()[0];self.assertEqual(json.loads(owner.draft.toPlainText())['qualification'],'strict_pit')
        owner.create();self.fx.wait(lambda:not owner.busy)
        self.assertIsNone(owner.selected);self.assertIsNone(self.window.queue)
        self.assertEqual(owner.service.store.list(),[])
        self.assertEqual(json.loads(owner.draft.toPlainText())['qualification'],'strict_pit')
    def test_same_path_data_directory_replacement_is_not_the_original_context(self):
        data=self.fx.fx.root/'replaceable-data';data.mkdir();self.window.data_root=data
        form=open_research_draft(self.window);self.fx.fill(form)
        old=data.with_name('old-data');data.rename(old);data.mkdir()
        form.submit();self.assertIsNone(form.result_spec);self.assertFalse(self.fx.drafts())
        self.assertIn('工作空间已变化',form.status.text())
    def test_parent_closed_does_not_receive_an_accepted_child_draft(self):
        form=open_research_draft(self.window);self.fx.fill(form);form.submit()
        self.fx.wait(lambda:self.fx.drafts() and not self.fx.drafts()[0].busy);owner=self.fx.drafts()[0]
        original=owner.draft.toPlainText();child=owner.edit_form();child.question.setText('late result')
        owner.close();child.submit()
        self.assertEqual(owner.draft.toPlainText(),original)
        self.assertIsNone(self.window.queue);self.assertEqual(owner.service.store.list(),[])
    def test_root_changed_before_edit_does_not_mix_old_proposal_service_and_new_scope(self):
        form=open_research_draft(self.window);self.fx.fill(form);form.submit()
        self.fx.wait(lambda:self.fx.drafts() and not self.fx.drafts()[0].busy);owner=self.fx.drafts()[0]
        other=self.fx.fx.root/'different-data';other.mkdir();self.window.data_root=other
        self.assertIsNone(owner.edit_form());self.assertIn('数据根已变化',owner.status.text())
        self.assertIsNone(self.window.queue)
    def test_modal_factor_editor_result_is_not_accepted_after_parent_generation_changes(self):
        form=open_research_draft(self.window);form.pick_factor()
        from quantlab.desktop.research_picker import FactorPickerDialog
        picker=next(d for d in self.window.dialogs if isinstance(d,FactorPickerDialog))
        picker.search.setText('BASE.MOMENTUM');picker.versions.setCurrentRow(0)
        form.question.setText('edit while picker open');picker.use_button.click()
        self.assertEqual(form.target.currentIndex(),-1)
    def test_execution_draft_roundtrip_keeps_costs_and_does_not_execute(self):
        form=open_research_draft(self.window);base=self.fx.fill(form);form.reject()
        spec={**base,'mode':'execution','execution':{'price_mode':'research','top_n':2,'commission_bps':2,'slippage_bps':5}}
        received=[];editor=open_research_draft(self.window,initial_spec=spec,receive=received.append)
        self.assertEqual(prepare(editor.collect()).preview(),prepare(spec).preview())
        editor.submit();self.assertEqual(len(received),1)
        self.assertEqual(received[0]['execution'],spec['execution']);self.assertIsNone(self.window.queue)
    def test_bad_original_draft_is_preserved_instead_of_opening_default_form(self):
        owner=ProposalDialog(self.window);self.window.show_dialog(owner);self.fx.wait(lambda:not owner.busy)
        text='{"not_a_spec":true}';owner.draft.setPlainText(text)
        self.assertIsNone(owner.edit_form());self.assertEqual(owner.draft.toPlainText(),text)
        self.assertFalse([d for d in self.window.dialogs if isinstance(d,ExperimentDialog)])
    def test_saved_proposal_selection_and_confirmation_are_cleared_by_returned_form(self):
        form=open_research_draft(self.window);spec=self.fx.fill(form);form.submit()
        self.fx.wait(lambda:self.fx.drafts() and not self.fx.drafts()[0].busy);owner=self.fx.drafts()[0]
        owner.create();self.fx.wait(lambda:not owner.busy and owner.selected is not None)
        saved=owner.selected['proposal_id'];owner.confirm.setChecked(True)
        child=owner.edit_form();child.question.setText('new unsaved question');child.submit()
        self.assertIsNone(owner.selected);self.assertFalse(owner.confirm.isChecked())
        self.assertFalse(owner.approve_button.isEnabled());self.assertIsNone(self.window.queue)
        self.assertEqual(owner.service.store.get(saved)['plan']['spec']['question'],spec['question'])


if __name__=='__main__':unittest.main()
