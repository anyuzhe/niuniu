import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtCore import QDate
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from quantlab.desktop.app import MainWindow
    from quantlab.desktop.trading_cockpit import TradingCockpitWidget
    from quantlab.trading.strategy_intent import StrategyIntentService
    from quantlab.trading.theme_store import ThemeStore


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class TradingCockpitDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        moment=datetime.fromisoformat('2026-09-11T10:00:00+08:00');service=StrategyIntentService(self.root,now_fn=lambda:moment)
        service.transition(str(uuid4()),{'symbol':'sh.600000','trading_day':'2026-09-11','frame':'R1','action':'WATCH','role_id':'human','theme':'银行','ai_thesis':'等待确认','source':'ui-test'})
        ThemeStore(self.root).create(str(uuid4()),{'theme':'银行','trading_day':'2026-09-11','frame':'R1','machine_state':'START','ai_state':'PREHEAT','source':'ui-test'})
        self.window=MainWindow(self.root);self.window.show();self.wait()

    def wait(self):
        QTest.qWait(30);end=30
        while self.window.callbacks and end>0:QTest.qWait(20);end-=1
        self.assertFalse(self.window.callbacks)

    def tearDown(self):self.window.close();QTest.qWait(10);self.temp.cleanup()

    def test_default_home_uses_latest_evidence_day_and_is_read_only(self):
        widget=self.window.scroll.widget().findChild(TradingCockpitWidget);self.assertIsNotNone(widget)
        self.assertEqual(widget.value['trading_day'],'2026-09-11');self.assertEqual(widget.value['day_source'],'latest_workspace_evidence')
        self.assertEqual(widget.value['candidates'][0]['symbol'],'sh.600000');self.assertEqual(widget.value['themes'][0]['theme'],'银行')
        self.assertFalse((self.root/'_jobs').exists())

    def test_date_switch_reads_exact_day_without_creating_jobs(self):
        widget=self.window.scroll.widget().findChild(TradingCockpitWidget)
        widget.day.setDate(QDate(2026,9,10));self.wait()
        self.assertEqual(widget.value['trading_day'],'2026-09-10');self.assertEqual(widget.value['day_source'],'explicit')
        self.assertEqual(widget.value['themes'],[]);self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
