import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication,QMainWindow
from quantlab.desktop.agent_chat import AgentChatDialog
from quantlab.desktop.agent_proposals import ProposalDialog
from test_agent_chat import FakeProvider,SPEC
import json


class Window(QMainWindow):
    def __init__(self,path):
        super().__init__();self.output=Path(path);self.data_root=Path(path);self.dialogs=[];self.opened=None
    def async_call(self,work,done,guarded=True):
        try:result=work()
        except Exception as exc:done(None,str(exc))
        else:done(result,'')
    def show_dialog(self,dialog):self.dialogs.append(dialog);dialog.show()
    def open_run(self,run_id):self.opened=run_id
    def show_jobs(self):self.opened='jobs'
    def registry_page(self,kind,query):self.opened=(kind,query)


class ChatDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_dialog_uses_runtime_and_persists_model_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=Window(tmp);dialog=AgentChatDialog(window);self.addCleanup(window.close)
            dialog.settings.allow.setChecked(True);dialog.settings.key.setText('test-key-not-saved')
            dialog.input.setPlainText('查询动量')
            p=FakeProvider([('search_factors',{'query':'MOMENTUM','offset':0,'limit':5})],text='actual result')
            with patch('quantlab.agent.chat_runtime.provider_for',return_value=p):dialog.send()
            self.assertFalse(dialog.busy);self.assertIn('actual result',dialog.transcript.toPlainText())
            self.assertGreater(dialog.references.count(),0)
            self.assertNotIn('test-key-not-saved',(Path(tmp)/'_assistant/model.json').read_text())
            cid=dialog.sessions.currentData();dialog.close();self.assertEqual(dialog.settings.key.text(),'')
            again=AgentChatDialog(window);self.addCleanup(again.close)
            self.assertEqual(again.sessions.currentData(),cid);self.assertIn('actual result',again.transcript.toPlainText())
    def test_no_consent_no_network_and_model_list_is_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=Window(tmp);dialog=AgentChatDialog(window);self.addCleanup(dialog.close);self.addCleanup(window.close)
            dialog.input.setPlainText('hello')
            with patch('quantlab.agent.chat_runtime.provider_for') as provider:dialog.send();provider.assert_not_called()
            self.assertIn('允许',dialog.status.text())
            dialog.settings.allow.setChecked(True)
            with patch('quantlab.desktop.agent_chat.probe_model',return_value={'provider':'codex_cli','models':[{'id':'other-model'}]}):dialog.probe()
            self.assertTrue(dialog.settings.model.isEditable());self.assertGreaterEqual(dialog.settings.model.findText('other-model'),0)
            dialog.settings.model.setEditText('freely-chosen-model')
            self.assertEqual(dialog.settings.collect().model,'freely-chosen-model')
    def test_proposal_reference_opens_host_review_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=Window(tmp);dialog=AgentChatDialog(window);self.addCleanup(window.close);self.addCleanup(dialog.close)
            dialog.settings.allow.setChecked(True);dialog.input.setPlainText('生成提案')
            p=FakeProvider([('propose_experiment',{'request_id':'model-id','spec_json':json.dumps(SPEC)})])
            with patch('quantlab.agent.chat_runtime.provider_for',return_value=p):dialog.send()
            self.assertEqual(dialog.references.count(),1);dialog.references.setCurrentRow(0);dialog.open_reference()
            review=window.dialogs[-1];self.addCleanup(review.close)
            self.assertIsInstance(review,ProposalDialog);self.assertIsNotNone(review.selected)
            self.assertEqual(review.selected['status'],'pending');self.assertFalse(review.confirm.isChecked())
            self.assertFalse((Path(tmp)/'_jobs').exists())
