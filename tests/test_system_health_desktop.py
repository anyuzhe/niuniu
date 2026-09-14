import os
import tempfile
import unittest
from pathlib import Path
from importlib.util import find_spec

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QLabel
    from quantlab.desktop.app import MainWindow,NAV
    from quantlab.desktop.system_health import SystemHealthWidget


@unittest.skipUnless(HAS_QT,'Install desktop dependency')
class SystemHealthDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.data.mkdir()
        self.window=MainWindow(self.output,self.data);self.window.show();QTest.qWait(50)

    def tearDown(self):
        self.window.close();QTest.qWait(30);self.temp.cleanup()

    def test_system_center_renders_read_only_health_without_creating_service_state(self):
        index=NAV.index('系统中心');self.window.navigate_root(index);QTest.qWait(250)
        widgets=self.window.scroll.widget().findChildren(SystemHealthWidget);self.assertEqual(len(widgets),1)
        labels=[w.text() for w in self.window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('System Health' in text for text in labels))
        self.assertTrue(any(text=='Runtime' for text in labels));self.assertTrue(any(text=='Research Readiness' for text in labels))
        self.assertFalse((self.output/'_tracking_daemon').exists());self.assertFalse((self.output/'_daily_orchestrator').exists())
        self.assertFalse((self.output/'_jobs').exists())


if __name__=='__main__':unittest.main()
