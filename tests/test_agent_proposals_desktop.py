import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import unittest
from pathlib import Path
from PyQt6.QtCore import Qt,QTimer,QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QMainWindow
import test_core
from test_workbench_jobs import spec as job_spec
from quantlab.desktop.agent_proposals import ProposalDialog
from quantlab.workbench.jobs import JobQueue,prepare
from quantlab.storage.codec import encode


class Window(QMainWindow):
    def __init__(self,output,data):
        super().__init__();self.output=output;self.data_root=data;self.queue=None;self.opened=None
        from quantlab.app import default_registry
        from quantlab.theory.templates import templates
        self.factors=json.loads(encode(default_registry().describe()));self.theories=templates();self.last_records=[]
    def async_call(self,work,callback,guarded=True):
        try:result=work()
        except Exception as error:callback(None,str(error))
        else:callback(result,'')
    def get_research_queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.data_root)
        return self.queue
    def open_run(self,run_id):self.opened=run_id


class ProposalDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.output=self.fixture.root/'proposal-ui';self.output.mkdir()
        self.window=Window(self.output,self.fixture.root);self.addCleanup(self.window.close)
        self.addCleanup(lambda:self.window.queue.close() if self.window.queue else None)
        self.dialog=ProposalDialog(self.window);self.dialog.show();self.addCleanup(self.dialog.close)
        self.spec=job_spec(symbols=list(self.fixture.symbols),replay=True)

    def test_user_review_submission_result_and_draft_is_not_approval(self):
        d=self.dialog;self.assertFalse(d.approve_button.isEnabled())
        d.draft.setPlainText(encode(self.spec));d.preview()
        self.assertEqual(list(self.output.iterdir()),[])
        d.create();self.assertIsNotNone(d.selected);self.assertIsNone(self.window.queue)
        d.confirm.setChecked(True);self.assertTrue(d.approve_button.isEnabled())
        d.draft.setPlainText(encode({**self.spec,'question':'another draft'}))
        self.assertFalse(d.approve_button.isEnabled());self.assertEqual(d.selected['plan']['spec']['question'],self.spec['question'])
        d.confirm.setChecked(True);QTest.mouseClick(d.approve_button,Qt.MouseButton.LeftButton)
        self.assertEqual(d.selected['status'],'submitted',d.status.text())
        deadline=time.time()+15
        while time.time()<deadline:
            job=self.window.queue.list()[0]
            if job['status'] not in ('queued','running'):break
            QTest.qWait(20)
        self.assertEqual(job['status'],'completed',job)
        self.assertEqual(job['spec']['question'],self.spec['question'])
        d.job_status();self.assertEqual(d.run_id,job['run_id']);self.assertIsNone(d.selected)
        self.assertFalse(d.approve_button.isEnabled());d.open_result()
        self.assertEqual(self.window.opened,job['run_id']);self.assertEqual(len(self.window.queue.list()),1)

    def test_preview_cannot_leave_old_proposal_armed(self):
        d=self.dialog;d.draft.setPlainText(encode(self.spec));d.create()
        d.confirm.setChecked(True);d.preview();d.confirm.setChecked(True)
        self.assertIsNone(d.selected);self.assertFalse(d.approve_button.isEnabled());self.assertIsNone(self.window.queue)

    def test_original_business_form_only_fills_draft(self):
        from quantlab.desktop.experiment import ExperimentDialog
        failures=[]
        def fill():
            modal=QApplication.activeModalWidget()
            try:
                self.assertIsInstance(modal,ExperimentDialog);modal.apply_spec(self.spec)
                QTest.mouseClick(modal.submit_button,Qt.MouseButton.LeftButton)
                if modal.isVisible():raise AssertionError(modal.status.text())
            except Exception as error:
                failures.append(error)
                if modal:modal.reject()
        QTimer.singleShot(0,fill);self.dialog.edit_form()
        self.assertFalse(failures,failures)
        self.assertEqual(prepare(json.loads(self.dialog.draft.toPlainText())).preview(),prepare(self.spec).preview())
        self.assertIsNone(self.window.queue);self.assertEqual(self.dialog.service.store.list(),[])

    def test_closed_dialog_ignores_late_background_result(self):
        from PyQt6 import sip
        pending=[]
        self.window.async_call=lambda work,callback,guarded=True:pending.append((work,callback))
        late=ProposalDialog(self.window)
        self.assertEqual(len(pending),1)
        late.close();late.deleteLater()
        QApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertTrue(sip.isdeleted(late))
        work,callback=pending.pop();callback(work(),'')
        self.assertIsNone(self.window.queue)
