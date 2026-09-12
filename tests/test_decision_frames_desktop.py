import os,tempfile,unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtCore import Qt,QDate
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QPushButton,QTableWidget
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop.decision_frames import FrameComparisonDialog,FramePolicyDialog
    from quantlab.desktop.decision_ledger import DecisionEditor
    from quantlab.trading.decision_store import DecisionStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class DecisionFrameDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.window=MainWindow(self.root);self.window.show();QTest.qWait(30)
    def tearDown(self):self.window.close();QTest.qWait(10);self.temp.cleanup()

    def create(self,when,**updates):
        payload={'symbol':'sh.600000','trading_day':'2026-09-11','frame':'R1','action':'WATCH','role_id':'human','theme':'银行','ai_thesis':'观察','source':'ui-test'}
        payload.update(updates);store=DecisionStore(self.root,now_fn=lambda:datetime.fromisoformat(when));return store.create(str(uuid4()),payload)

    def test_review_page_and_cross_round_dialog_show_submission_status(self):
        self.create('2026-09-11T02:00:00+00:00',frame='R1',action='WATCH',ai_thesis='R1')
        self.create('2026-09-11T06:00:00+00:00',frame='R2',action='READY',ai_thesis='R2')
        self.window.navigate_root(4);QTest.qWait(20)
        tables=self.window.scroll.widget().findChildren(QTableWidget)
        self.assertTrue(any(any(t.item(r,c) and t.item(r,c).text()=='ON_TIME' for r in range(t.rowCount()) for c in range(t.columnCount())) for t in tables))
        dialog=FrameComparisonDialog(self.window,'sh.600000','2026-09-11');self.window.show_dialog(dialog);QTest.qWait(20)
        table=dialog.findChild(QTableWidget);self.assertEqual(table.rowCount(),5)
        rows={table.item(r,0).text():[table.item(r,c).text() for c in range(table.columnCount())] for r in range(table.rowCount())}
        self.assertEqual(rows['AUCTION'][1],'missing');self.assertEqual(rows['R1'][2],'WATCH');self.assertEqual(rows['R2'][2],'READY')

    def test_policy_change_requires_new_version(self):
        dialog=FramePolicyDialog(self.window);self.window.show_dialog(dialog)
        dialog.controls['R1'][1].setText('10:45');dialog.save()
        self.assertIn('version',dialog.status.text())
        dialog.version.setText('custom-ui-v1');dialog.save();QTest.qWait(10)
        self.assertEqual(dialog.store.load()['version'],'custom-ui-v1')
        self.assertEqual(dialog.store.load()['windows']['R1']['end'],'10:45')

    def test_d1_editor_can_fill_latest_prior_reference(self):
        source=self.create('2026-09-11T02:00:00+00:00',frame='R1')
        editor=DecisionEditor(self.window);self.window.show_dialog(editor)
        editor.symbol.setText('sh.600000');editor.day.setDate(QDate(2026,9,12));editor.frame.setCurrentIndex(editor.frame.findData('D1'))
        editor.fill_reference();self.assertEqual(editor.reference.text(),source['decision_id'])
        editor.ai_thesis.setPlainText('D1跟踪');editor.save();QTest.qWait(10)
        latest=DecisionStore(self.root).list(symbol='sh.600000')['records'][0]
        self.assertEqual(latest['frame'],'D1');self.assertEqual(latest['reference_decision_id'],source['decision_id'])
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
