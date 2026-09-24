import os
import tempfile
import unittest
from pathlib import Path
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtCore import Qt,QDate
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QTableWidget
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop.decision_ledger import DecisionEditor
    from quantlab.trading.decision_store import DecisionStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class StrategyIntentDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.window=MainWindow(self.root);self.window.show();QTest.qWait(40)
    def tearDown(self):self.window.close();QTest.qWait(10);self.temp.cleanup()

    def editor(self,frame,action,thesis):
        dialog=DecisionEditor(self.window);self.window.show_dialog(dialog);dialog.symbol.setText('sh.600000');dialog.day.setDate(QDate(2026,9,11))
        dialog.frame.setCurrentIndex(dialog.frame.findData(frame));dialog.action.setCurrentIndex(dialog.action.findData(action));dialog.ai_thesis.setPlainText(thesis);return dialog

    def test_illegal_jump_is_blocked_and_position_board_shows_allowed_next(self):
        first=self.editor('PREP','WATCH','开始观察');first.save();QTest.qWait(10)
        bad=self.editor('R1','OPEN','不能直接跳到开仓');bad.confirm_trigger.setText('测试');bad.hold_reason.setText('测试');bad.save();QTest.qWait(10)
        self.assertIn('INVALID_TRANSITION',bad.status.text())
        self.assertEqual(DecisionStore(self.root).list(symbol='sh.600000')['total'],1)
        self.window.navigate_page('intent');QTest.qWait(20)
        tables=self.window.scroll.widget().findChildren(QTableWidget)
        board=next(t for t in tables if t.columnCount()==9)
        self.assertEqual(board.item(0,3).text(),'WATCH');self.assertIn('READY',board.item(0,4).text())
        self.assertFalse((self.root/'paper').exists())

    def test_valid_ready_transition_is_audited(self):
        first=self.editor('PREP','WATCH','开始观察');first.save();QTest.qWait(10)
        ready=self.editor('R1','READY','早盘确认');ready.transition_reason.setText('量价确认');ready.save();QTest.qWait(10)
        current=DecisionStore(self.root).latest_current('sh.600000')
        self.assertEqual(current['action'],'READY');self.assertEqual(current['intent_previous_action'],'WATCH')
        self.assertEqual(current['transition_reason'],'量价确认');self.assertEqual(current['position_scope'],'strategy_intent')


if __name__=='__main__':unittest.main()
