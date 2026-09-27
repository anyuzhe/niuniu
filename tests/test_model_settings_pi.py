import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from quantlab.agent.model_config import ModelConfig,save_model_config,load_model_config
from quantlab.desktop.model_settings import ModelSettings
from quantlab.desktop.app import MainWindow


class PiModelSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.windows=[];self.widgets=[]
    def wait(self,predicate):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def tearDown(self):
        for window in self.windows:
            for dialog in window.dialogs:dialog.close()
            self.wait(lambda:not window.callbacks);window.close()
        for widget in self.widgets:widget.close()
        QApplication.processEvents();self.tmp.cleanup()
    def open_dialog(self,**changes):
        cfg=ModelConfig(provider='pi_sdk',model='fake/unit',max_context_chars=200000,**changes)
        save_model_config(self.root,cfg)
        window=MainWindow(self.root);self.windows.append(window);window.research_chat()
        return window,window._research_chat_dialog,cfg
    def test_pi_configuration_roundtrip_and_transport_fields(self):
        cfg=ModelConfig(provider='pi_sdk',model='custom/model/path',pi_path='/test/bin/pi')
        widget=ModelSettings(cfg);self.widgets.append(widget)
        self.assertEqual(widget.provider.currentData(),'pi_sdk');self.assertEqual(widget.collect(),cfg)
        self.assertTrue(widget.pi.isEnabled());self.assertFalse(widget.codex.isEnabled())
        self.assertFalse(widget.url.isEnabled());self.assertFalse(widget.key.isEnabled())
        self.assertFalse(widget.key_env.isEnabled());self.assertFalse(widget.compat.isEnabled())
        self.assertIn('provider/model',widget.model.lineEdit().placeholderText())
    def test_switch_to_pi_clears_ephemeral_api_key_and_path_change_revokes_consent(self):
        widget=ModelSettings(ModelConfig(provider='responses',model='api-model'));self.widgets.append(widget)
        widget.key.setText('fixture-only-secret');widget.allow.setChecked(True)
        widget.provider.setCurrentIndex(widget.provider.findData('pi_sdk'))
        self.assertEqual(widget.key.text(),'');self.assertFalse(widget.allow.isChecked())
        widget.model.setEditText('fake/unit');widget.allow.setChecked(True);widget.pi.setText('/new/bin/pi')
        self.assertFalse(widget.allow.isChecked());self.assertEqual(widget.collect().pi_path,'/new/bin/pi')
        widget.provider.setCurrentIndex(widget.provider.findData('codex_cli'))
        self.assertTrue(widget.codex.isEnabled());self.assertFalse(widget.pi.isEnabled())
    def test_research_dialog_load_save_probe_and_correct_pi_destination(self):
        window,dialog,cfg=self.open_dialog()
        self.assertEqual(dialog.settings.collect(),cfg)
        self.assertIn('Pi SDK',dialog.consent.text());self.assertIn('fake/unit',dialog.consent.text())
        self.assertNotIn('https://api.openai.com',dialog.consent.text())
        dialog.consent.setChecked(True);dialog.settings.pi.setText('/test/pi')
        self.assertFalse(dialog.consent.isChecked());dialog.save_settings()
        self.assertEqual(load_model_config(self.root).pi_path,'/test/pi')
        with patch('quantlab.desktop.research_chat.make_provider') as factory:
            factory.return_value.probe.return_value={'provider':'pi_sdk','pi_provider':'fake','model':'unit','available':True}
            dialog.consent.setChecked(True);dialog.probe();self.wait(lambda:not dialog.busy)
        self.assertIn('Pi 已找到配置模型 fake/unit',dialog.status.text())
        self.assertIn('未执行推理或研究',dialog.status.text());self.assertNotIn('返回 0 个模型',dialog.status.text())
        self.assertFalse((self.root/'_jobs').exists())
    def test_real_node_bridge_partial_is_visible_through_desktop_runtime_adapter(self):
        from quantlab.devstudio.pi_provider import resolve_pi
        node=resolve_pi()[0];fixture=Path(__file__).parent/'fixtures/pi_fake_runtime.mjs'
        window,dialog,cfg=self.open_dialog(max_rounds=1)
        with patch('quantlab.devstudio.pi_provider.resolve_pi',return_value=(node,str(fixture))):
            dialog.consent.setChecked(True);dialog.input.setPlainText('核对已有信息，不运行研究。')
            dialog.send();self.wait(lambda:not dialog.busy)
        turn=dialog.runtime.store.turns(dialog.session_id)[-1]
        self.assertEqual(turn['status'],'partial');self.assertTrue(turn['metadata']['needs_followup'])
        self.assertEqual(turn['metadata']['tool_calls'],0)
        self.assertIn('未完成',dialog.transcript.toPlainText());self.assertIn('暂停',dialog.status.text())
        self.assertTrue(dialog.recovery_button.isEnabled());self.assertFalse((self.root/'_jobs').exists())
    def test_stale_workspace_probe_never_launches_transport(self):
        window,dialog,cfg=self.open_dialog();old=window.output;window.output=self.root/'different'
        try:
            with patch('quantlab.desktop.research_chat.make_provider') as factory:
                dialog.consent.setChecked(True);dialog.probe();factory.assert_not_called()
            self.assertIn('工作空间已变化',dialog.status.text())
        finally:window.output=old


if __name__=='__main__':unittest.main()
