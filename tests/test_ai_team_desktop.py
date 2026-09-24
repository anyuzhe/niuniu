import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QPushButton,QTabWidget

from quantlab.desktop.ai_team import AITeamWidget,PeerReviewCreateDialog,PeerReviewLaunchDialog
from quantlab.desktop.agent_scorecard import AgentScorecardDialog
from quantlab.desktop.app import MainWindow


class AITeamDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.window=MainWindow(self.root);self.window.show();QTest.qWait(30)
    def tearDown(self):self.window.close();QTest.qWait(10);self.temp.cleanup()

    def widget(self):
        self.window.navigate_page('ai_team');QTest.qWait(20);return self.window.findChild(AITeamWidget)

    def test_ai_team_page_is_real_and_read_only_on_open(self):
        widget=self.widget();self.assertIsNotNone(widget);self.assertFalse((self.root/'_jobs').exists())
        self.assertEqual(widget.service.list()['tasks'],[])
        self.assertFalse(widget.controls['developer'][0].isEnabled())

    def test_scorecard_opens_read_only_without_total_ranking(self):
        widget=self.widget();buttons=widget.findChildren(QPushButton);control=next(b for b in buttons if b.text()=='Agent Scorecard')
        before_jobs=(self.root/'_jobs').exists();control.click();QTest.qWait(20)
        dialog=self.window.dialogs[-1];self.assertIsInstance(dialog,AgentScorecardDialog)
        tabs=dialog.findChild(QTabWidget);self.assertEqual(tabs.count(),2)
        self.assertFalse(dialog.value['policy']['composite_score']);self.assertEqual((self.root/'_jobs').exists(),before_jobs)

    def test_team_model_override_saves_without_secret_or_model_call(self):
        widget=self.widget();widget.controls['skeptic'][1].setText('skeptic-model');widget.controls['skeptic'][2].setCurrentIndex(widget.controls['skeptic'][2].findData('high'))
        widget.save_team();team=widget.service.team.load();self.assertEqual(team['roles']['skeptic']['model'],'skeptic-model')
        self.assertNotIn('api_key',widget.service.team.path.read_text());self.assertFalse((self.root/'_jobs').exists())

    def test_create_dialog_only_creates_pending_task(self):
        widget=self.widget();dialog=PeerReviewCreateDialog(self.window,widget.service,widget.reload);self.window.show_dialog(dialog)
        dialog.question.setPlainText('请独立复核这个判断');dialog.context.setPlainText('共享事实背景')
        dialog.save();QTest.qWait(20);tasks=widget.service.list()['tasks']
        self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['status'],'pending');self.assertEqual(tasks[0]['rounds'],[])
        self.assertFalse((self.root/'_jobs').exists())

    def test_launch_without_explicit_send_consent_does_not_run(self):
        widget=self.widget();task=widget.service.propose(__import__('uuid').uuid4().__str__(),{
            'question':'复核','context':'','reviewers':['skeptic'],'parent_task_id':None})
        dialog=PeerReviewLaunchDialog(self.window,widget.service,task,widget.reload);self.window.show_dialog(dialog)
        dialog.start();QTest.qWait(20)
        self.assertEqual(widget.service.get(task['task_id'])['status'],'pending')
        self.assertIn('勾选',dialog.status.text());self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
