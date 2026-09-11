import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from dataclasses import replace
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from quantlab.desktop.app import MainWindow
from quantlab.desktop.tracking_preview import TrackingPreviewDialog
from test_context_experiments import ContextProvider,context_config,runner


class TrackingPreviewDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate):
        end=time.monotonic()+10
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Tracking preview callback did not settle')
    def test_saved_run_preview_uses_core_without_new_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);runner(ContextProvider(),output).run(replace(context_config(),context=None,replay=True))
            window=MainWindow(output);window.tracking_preview()
            dialog=next(d for d in window.dialogs if isinstance(d,TrackingPreviewDialog))
            try:
                self.wait(lambda:not dialog.busy);self.assertEqual(dialog.source.count(),1)
                dialog.windows.setText('5');dialog.minimum.setValue(1);dialog.calculate()
                self.wait(lambda:not dialog.busy)
                self.assertIn('只读预览完成',dialog.status.text())
                self.assertIn('pending_observations',dialog.details.toPlainText())
                self.assertFalse((output/'_tracking').exists());self.assertFalse((output/'_jobs').exists())
                dialog.windows.setText('not-a-window');dialog.calculate()
                self.assertIn('整数',dialog.status.text())
            finally:
                dialog.close();self.wait(lambda:not window.callbacks);window.close();QApplication.processEvents()
