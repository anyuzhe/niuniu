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
    from PyQt6.QtWidgets import QApplication,QPushButton,QTableWidget,QLabel
    from quantlab.desktop.app import MainWindow,NAV,LEGACY_NAV
    from quantlab.desktop.decision_ledger import DecisionEditor
    from quantlab.trading.decision_store import DecisionStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class TradingDeskDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.window=MainWindow(self.root);self.window.show();QTest.qWait(50)

    def tearDown(self):
        self.window.close();QTest.qWait(10);self.temp.cleanup()

    def test_new_business_navigation_and_legacy_routes_both_work(self):
        self.assertEqual(NAV,['今日交易','主线市场','股票中心','持仓计划','复盘中心','AI 团队','研究实验室','系统中心'])
        self.assertEqual(len(self.window.nav),8);self.assertEqual(len(LEGACY_NAV),12)
        for index,title in enumerate(NAV):
            QTest.mouseClick(self.window.nav[index],Qt.MouseButton.LeftButton);QTest.qWait(20)
            self.assertTrue(self.window.nav[index].isChecked());self.assertEqual(self.window.root_current,index)
            self.assertTrue(any(w.text()==title for w in self.window.scroll.widget().findChildren(QLabel)))
        self.window.navigate(11);self.assertEqual(self.window.legacy_current,11);self.assertEqual(self.window.current,11)
        self.assertTrue(any('工作空间' in w.text() for w in self.window.scroll.widget().findChildren(QLabel)))

    def test_manual_decision_create_revision_search_and_no_research_job(self):
        self.window.new_decision();editor=self.window.dialogs[-1]
        self.assertIsInstance(editor,DecisionEditor)
        editor.symbol.setText('sh.600000');editor.day.setDate(QDate(2026,9,12))
        editor.action.setCurrentIndex(editor.action.findData('WATCH'))
        editor.theme.setText('银行');editor.theme_role.setText('观察')
        editor.ai_thesis.setPlainText('等待后续确认');editor.save();QTest.qWait(30)
        store=DecisionStore(self.root);current=store.list()['records']
        self.assertEqual(len(current),1);first=current[0];self.assertEqual(first['action'],'WATCH')
        self.assertFalse((self.root/'_jobs').exists())

        self.window.open_decision(first);detail=self.window.dialogs[-1]
        revise=next(b for b in detail.findChildren(QPushButton) if b.text()=='基于此 Decision 新建修订')
        QTest.mouseClick(revise,Qt.MouseButton.LeftButton);QTest.qWait(20)
        revision=self.window.dialogs[-1];self.assertIsInstance(revision,DecisionEditor)
        revision.action.setCurrentIndex(revision.action.findData('READY'));revision.ai_thesis.setPlainText('确认条件更接近')
        revision.save();QTest.qWait(30)
        self.assertEqual(store.list()['records'][0]['action'],'READY')
        self.assertEqual(store.list(include_superseded=True)['total'],2)

        self.window.search.setText('600000');self.window.global_search();QTest.qWait(20)
        tables=self.window.scroll.widget().findChildren(QTableWidget)
        self.assertTrue(any(t.rowCount()>=1 and t.columnCount()>=1 and t.item(0,0) and t.item(0,0).text()=='sh.600000' for t in tables))
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':
    unittest.main()
