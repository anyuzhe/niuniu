import os,tempfile,time,unittest
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QTableWidget
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop.theme_matrix import ThemeMatrixWidget,ThemeSnapshotEditor
    from quantlab.trading.decision_store import DecisionStore
    from quantlab.trading.theme_store import ThemeStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class ThemeMatrixDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        DecisionStore(self.root).create(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-11','frame':'R1','action':'WATCH','role_id':'human','theme':'软件AI','ai_thesis':'观察'})
        self.window=MainWindow(self.root);self.window.show();QTest.qWait(50)
    def tearDown(self):self.window.close();QTest.qWait(10);self.temp.cleanup()
    def wait(self):
        end=time.monotonic()+5
        while self.window.callbacks and time.monotonic()<end:QTest.qWait(20)
        self.assertFalse(self.window.callbacks)

    def test_decision_axis_without_snapshot_remains_unknown_then_snapshot_changes_cell(self):
        self.window.navigate_page('theme_matrix');QTest.qWait(30);widget=self.window.scroll.widget().findChild(ThemeMatrixWidget);self.assertIsNotNone(widget)
        table=widget.findChild(QTableWidget);self.assertEqual(table.rowCount(),1);self.assertEqual(table.item(0,0).text(),'软件AI')
        self.assertIn('未知',table.item(0,1).text());self.assertFalse((self.root/'_jobs').exists())
        saved=ThemeStore(self.root).create(str(uuid4()),{'theme':'软件AI','trading_day':'2026-09-11','frame':'R1','machine_state':'START','ai_state':'PREHEAT','ai_thesis':'开始转强','risk_review':'仍缺盘中事实','source':'test'})
        widget.reload();self.assertIn('启动',table.item(0,1).text());self.assertIn('AI:预热',table.item(0,1).text());self.assertFalse((self.root/'_jobs').exists())
        widget.open_cell(0,1);self.assertEqual(self.window.dialogs[-1].windowTitle(),'软件AI · 2026-09-11 · R1')
        self.assertEqual(saved['snapshot_id'],widget.records[0,1]['snapshot_id'])

    def test_editor_auto_links_exact_same_theme_day_frame_decision(self):
        editor=ThemeSnapshotEditor(self.window);editor.theme.setText('软件AI');editor.day.setDate(editor.day.date().fromString('2026-09-11','yyyy-MM-dd'))
        editor.frame.setCurrentIndex(editor.frame.findData('R1'));editor.machine.setCurrentIndex(editor.machine.findData('UNKNOWN'));editor.ai.setCurrentIndex(editor.ai.findData('UNKNOWN'));editor.save()
        self.assertIsNotNone(editor.saved);self.assertEqual(len(editor.saved['decision_ids']),1);self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
