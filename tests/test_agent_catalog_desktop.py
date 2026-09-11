import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from quantlab.desktop.agent_catalog import AgentCatalogDialog


class Window(QMainWindow):
    def __init__(self, output):
        super().__init__(); self.output = Path(output); self.opened = None
    def async_call(self, work, callback, guarded=True):
        callback(work(), '')
    def open_run(self, run_id):
        self.opened = run_id


class AgentCatalogDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def test_controls_use_real_read_only_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = Window(tmp); dialog = AgentCatalogDialog(window); dialog.show()
            self.addCleanup(window.close); self.addCleanup(dialog.close)
            QTest.mouseClick(dialog.run_button, Qt.MouseButton.LeftButton)
            self.assertIn('read_only', dialog.details.toPlainText())
            self.assertIn('只读查询完成', dialog.status.text())
            dialog.tools.setCurrentIndex(dialog.tools.findData('search_factors'))
            dialog.controls['query'].setText('MOMENTUM')
            self.assertFalse(dialog.controls['query'].isHidden())
            self.assertTrue(dialog.controls['run_id'].isHidden())
            QTest.mouseClick(dialog.run_button, Qt.MouseButton.LeftButton)
            self.assertIn('BASE.MOMENTUM', dialog.details.toPlainText())
            dialog.show_schemas(); self.assertIn('get_experiment', dialog.details.toPlainText())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_existing_main_window_has_inspection_entry(self):
        from quantlab.desktop.app import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(tmp); self.addCleanup(window.close)
            buttons = [b for b in window.findChildren(QPushButton) if b.text() == 'AI 研究接口']
            self.assertEqual(len(buttons), 1)
            QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
            self.assertTrue(any(isinstance(d, AgentCatalogDialog) for d in window.dialogs))
            for _ in range(100):
                QApplication.processEvents()
                if not window.callbacks: break
                QTest.qWait(10)
            for dialog in window.dialogs: dialog.close()
            window.close(); QApplication.processEvents()
