import json
import os
import tempfile
import time
import unittest
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QTabWidget,QTableWidget
    from quantlab.agent.watch_store import WatchStore
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop.stock_dossier import StockDossierDialog
    from quantlab.trading.decision_store import DecisionStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class StockDossierDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.symbol='sh.600000'
        DecisionStore(self.root).create(str(uuid4()),{'symbol':self.symbol,'trading_day':'2026-09-11','frame':'R1','action':'WATCH','role_id':'human','theme':'银行','ai_thesis':'观察'})
        run_id=str(uuid4());folder=self.root/run_id;folder.mkdir()
        (folder/'experiment.json').write_text(json.dumps({'run_id':run_id,'status':'completed','created_at':'2026-09-12T00:00:00+00:00','kind':'factor','manifest':{'config':{'research_question':'股票实验','factor_id':'BASE.MOMENTUM','data':{'symbols':[self.symbol],'start':'2026-01-01','end':'2026-06-30','timeframe':'1d'}}}}))
        watch_id=str(uuid4());WatchStore(self.root).initialize(watch_id,{'watch_id':watch_id,'name':'银行观察','base_run_id':run_id,'windows':[20],'min_dates':5,'rule':{'adjustment':'qfq','config':{'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{},'data':{'symbols':[self.symbol]}}}})
        self.window=MainWindow(self.root);self.window.show();QTest.qWait(50)

    def tearDown(self):
        self.window.close();QTest.qWait(10);self.temp.cleanup()

    def wait(self):
        end=time.monotonic()+10
        while self.window.callbacks and time.monotonic()<end:QTest.qWait(20)
        self.assertFalse(self.window.callbacks)

    def test_stock_dossier_opens_all_evidence_tabs_without_side_effects(self):
        self.window.open_stock_dossier(self.symbol);self.wait();dialog=self.window.dialogs[-1]
        self.assertIsInstance(dialog,StockDossierDialog)
        tabs=dialog.findChild(QTabWidget);self.assertEqual(tabs.count(),5)
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())],['当前概览','Decision 时间线','研究证据','Watch / 跟踪','Playbook / 10选2'])
        tables=dialog.findChildren(QTableWidget)
        self.assertTrue(any(t.rowCount()==1 and t.columnCount()==6 for t in tables))
        self.assertTrue(any(t.rowCount()==1 and t.columnCount()==6 and t.item(0,0).text()=='股票实验' for t in tables if t.item(0,0)))
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
