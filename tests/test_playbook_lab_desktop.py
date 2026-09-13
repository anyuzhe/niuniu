import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QPushButton,QTabWidget,QTableWidget

from quantlab.desktop.app import MainWindow
from quantlab.desktop.playbook_lab import PlaybookLabDialog
from quantlab.trading.playbook_store import PlaybookStore


class PlaybookLabDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.window=MainWindow(self.root);self.window.show();QTest.qWait(40)

    def tearDown(self):
        self.window.close();QTest.qWait(10);self.temp.cleanup()

    def test_research_lab_has_playbook_entry_and_dialog_is_read_only_on_open(self):
        self.window.navigate_root(6);QTest.qWait(20)
        buttons=self.window.scroll.widget().findChildren(QPushButton)
        entry=next(b for b in buttons if b.text()=='高手玩法 / Playbook Lab')
        entry.click();QTest.qWait(30)
        dialog=self.window.dialogs[-1];self.assertIsInstance(dialog,PlaybookLabDialog)
        tabs=dialog.findChild(QTabWidget);self.assertEqual(tabs.count(),5)
        self.assertEqual([tabs.tabText(i) for i in range(5)],
            ['来源归档','玩法定义','案例 / 候选全集','历史验证','期末50分试点'])
        self.assertFalse((self.root/'_jobs').exists())

    def test_verified_source_appears_after_host_store_write(self):
        self.window.playbook_lab();QTest.qWait(20);dialog=self.window.dialogs[-1]
        store=PlaybookStore(self.root)
        store.create_source(str(uuid4()),{'expert_key':'qimofenshu','title':'原始实盘记录',
            'source_type':'LIVE_RECORD','locator':'local:test','available_at':'2024-01-01T09:00:00+08:00',
            'content_hash':'c'*64,'archive_ref':'local:test','completeness':'VERIFIED','notes':''})
        dialog.reload();QTest.qWait(20)
        tables=dialog.findChildren(QTableWidget)
        self.assertTrue(any(t.rowCount()==1 and t.item(0,0) and t.item(0,0).text()=='qimofenshu' for t in tables))
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
