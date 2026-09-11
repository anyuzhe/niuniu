import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from quantlab.desktop.app import MainWindow
from quantlab.desktop.factor_watches import FactorWatchDialog
from quantlab.desktop.agent_proposals import ProposalDialog
import test_watchlist


class WatchDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def wait(self, predicate):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate(): return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def cleanup(self,window):
        self.wait(lambda:not window.callbacks)
        for dialog in window.dialogs: dialog.close()
        window.close(); QApplication.processEvents()
    def test_create_pause_history_and_refresh_opens_unchecked_approval(self):
        fixture=test_watchlist.WatchlistTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        window=MainWindow(fixture.output,fixture.root)
        self.addCleanup(lambda:self.cleanup(window))
        window.factor_watches()
        dialog=next(d for d in window.dialogs if isinstance(d,FactorWatchDialog))
        self.wait(lambda:not dialog.busy)
        dialog.source.setCurrentIndex(dialog.source.findData(fixture.source.run_id))
        dialog.name.setText('桌面跟踪'); dialog.windows.setText('5'); dialog.minimum.setValue(1)
        dialog.create_button.click()
        self.wait(lambda:not dialog.busy and dialog.selected is not None)
        self.assertEqual(dialog.selected['snapshot_count'],1)
        self.assertIsNone(window.queue)
        watch_id=dialog.watches.currentData()
        dialog.pause_button.click(); self.wait(lambda:not dialog.busy and not dialog.selected['active'])
        dialog.pause_button.click(); self.wait(lambda:not dialog.busy and dialog.selected['active'])
        self.assertEqual(dialog.watches.currentData(),watch_id)
        self.assertEqual(dialog.history.count(),1)
        dialog.end.setDate(QDate(2025,1,10)); dialog.propose_button.click()
        self.wait(lambda:not dialog.busy and dialog.requests.count()==1)
        approvals=[d for d in window.dialogs if isinstance(d,ProposalDialog)]
        self.assertEqual(len(approvals),1)
        self.wait(lambda:not approvals[0].busy)
        self.assertFalse(approvals[0].confirm.isChecked())
        self.assertFalse(approvals[0].approve_button.isEnabled())
        self.assertFalse(list(fixture.output.glob('_jobs/*.json')))
