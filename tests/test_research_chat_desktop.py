import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QPushButton
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_chat import ResearchChatDialog
from quantlab.agent.model_config import load_model_config
from test_research_chat import FakeProvider


class ChatDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate,seconds=8):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def cleanup_window(self,window):
        for dialog in window.dialogs:dialog.close()
        self.wait(lambda:not window.callbacks);window.close();QApplication.processEvents()

    def test_chat_roundtrip_evidence_reopen_and_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp);self.addCleanup(lambda:self.cleanup_window(window))
            window.research_chat();dialog=window._research_chat_dialog;self.assertIsInstance(dialog,ResearchChatDialog)
            self.assertFalse(dialog.consent.isChecked())
            provider=FakeProvider([('describe_factor',{'factor_id':'BASE.MOMENTUM','version':'1.0.0'})],text='verified fixture')
            with patch('quantlab.agent.chat_runtime.make_provider',return_value=provider):
                dialog.input.setPlainText('查询动量');dialog.send();self.assertFalse(provider.called)
                dialog.consent.setChecked(True);dialog.send();self.wait(lambda:not dialog.busy)
            self.assertTrue(provider.called);self.assertIn('verified fixture',dialog.transcript.toPlainText())
            self.assertGreater(dialog.evidence.count(),0)
            reference={'kind':'research_skill_item','skill_key':'manager-skill','item_type':'HYPOTHESIS',
                'package_snapshot':'f'*64,'item_id':'cycle'}
            dialog.receive('tool_result',{'name':'search_research_skill_items',
                'result':{'ok':True,'evidence':[reference]}})
            entry=dialog.evidence.item(dialog.evidence.count()-1)
            self.assertIn('cycle',entry.text());dialog.evidence.setCurrentItem(entry);dialog.data_root=tmp
            result={'item_type':'HYPOTHESIS','records':[{'hypothesis_key':'cycle'}]}
            with patch('quantlab.knowledge.research_skill_library.ResearchSkillLibrary.search',
                    return_value=result) as open_library:
                dialog.open_reference();self.wait(lambda:not dialog.busy)
            open_library.assert_called_once_with('manager-skill','f'*64,'HYPOTHESIS','cycle','',0,100)
            self.assertIn('cycle',dialog.details.toPlainText())
            identifier=dialog.session_id;dialog.close();window.research_chat()
            self.assertEqual(window._research_chat_dialog.session_id,identifier)
            self.assertIn('verified fixture',dialog.transcript.toPlainText())
            dialog.consent.setChecked(True);dialog.settings.fields['model'].setEditText('another-model')
            self.assertFalse(dialog.consent.isChecked())
            dialog.save_settings();self.assertEqual(load_model_config(tmp).model,'another-model')

    def test_custom_api_configuration_key_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp);self.addCleanup(lambda:self.cleanup_window(window))
            window.research_chat();dialog=window._research_chat_dialog
            settings=dialog.settings;settings.provider.setCurrentIndex(settings.provider.findData('chat_completions'))
            settings.fields['model'].setEditText('my-local-model');settings.fields['effort'].setCurrentIndex(0)
            settings.fields['base_url'].setText('http://127.0.0.1:11434/v1');settings.key.setText('fixture-secret')
            dialog.save_settings();stored=load_model_config(tmp)
            self.assertEqual(stored.provider,'chat_completions');self.assertEqual(stored.model,'my-local-model')
            self.assertNotIn('fixture-secret',(Path(tmp)/'_assistant/model.json').read_text())
            settings.provider.setCurrentIndex(settings.provider.findData('codex_cli'))
            self.assertEqual(settings.key.text(),'')

    def test_catalog_entry_and_proposal_selection_never_auto_approve(self):
        from uuid import uuid4
        from quantlab.agent.proposals import ProposalService
        from quantlab.desktop.agent_catalog import AgentCatalogDialog
        from quantlab.desktop.agent_proposals import ProposalDialog
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,tmp);self.addCleanup(lambda:self.cleanup_window(window))
            catalog=AgentCatalogDialog(window);window.show_dialog(catalog)
            entry=next(b for b in catalog.findChildren(QPushButton) if b.text()=='打开内置研究助手')
            QTest.mouseClick(entry,Qt.MouseButton.LeftButton)
            self.assertIsInstance(window._research_chat_dialog,ResearchChatDialog)
            spec={'question':'fixture','symbols':['sh.600000','sh.600519','sz.000001'],
                'start':'2025-01-01','end':'2025-01-10','factor':'BASE.MOMENTUM','horizons':[1]}
            proposal=ProposalService(tmp,tmp).propose(str(uuid4()),spec)
            dialog=ProposalDialog(window,selected_id=proposal['proposal_id']);window.show_dialog(dialog)
            self.wait(lambda:not dialog.busy)
            self.assertEqual(dialog.selected['proposal_id'],proposal['proposal_id'])
            self.assertFalse(dialog.confirm.isChecked());self.assertFalse(dialog.approve_button.isEnabled())
            self.assertFalse(list(Path(tmp).glob('_jobs/*.json')))

    def test_close_requests_stop_without_destroying_callback_target(self):
        from threading import Event
        entered=Event()
        class SlowProvider:
            def complete(self,messages,tools,invoke,emit,stop):
                entered.set();stop.wait(5)
                return {'text':'should not complete','model':'fixture','provider':'fixture','usage':{}}
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp);self.addCleanup(lambda:self.cleanup_window(window))
            window.research_chat();dialog=window._research_chat_dialog
            dialog.consent.setChecked(True);dialog.input.setPlainText('test')
            with patch('quantlab.agent.chat_runtime.make_provider',return_value=SlowProvider()):
                dialog.send();self.wait(entered.is_set);dialog.close()
                self.assertTrue(dialog.stop_event.is_set())
                self.wait(lambda:not dialog.busy and not dialog.isVisible())
            states=[e['payload']['status'] for e in dialog.runtime.store.events(dialog.session_id)['events'] if e['kind']=='state']
            self.assertEqual(states[-1],'cancelled')
            self.assertFalse(list(Path(tmp).glob('_jobs/*.json')))
