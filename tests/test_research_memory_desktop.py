import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from PyQt6.QtWidgets import QApplication,QMainWindow,QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from quantlab.agent.research_memory import ResearchMemory
from quantlab.desktop.research_memory import ResearchMemoryDialog
from test_research_memory import hypothesis


class Window(QMainWindow):
    def __init__(self, output):
        super().__init__(); self.output=Path(output); self.opened=None
    def async_call(self, work, done, guarded=True):
        try: result=work()
        except Exception as error: done(None,str(error))
        else: done(result,'')
    def open_run(self, run_id): self.opened=run_id


class ResearchMemoryDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_search_and_revision_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory=ResearchMemory(tmp); old=memory.save('hypothesis',str(uuid4()),hypothesis())['record']['memory_id']
            new=memory.save('hypothesis',str(uuid4()),hypothesis(title='修订标题',supersedes=old))['record']['memory_id']
            window=Window(tmp); dialog=ResearchMemoryDialog(window)
            self.addCleanup(window.close); self.addCleanup(dialog.close)
            self.assertEqual(dialog.total,1)
            dialog.history.setChecked(True); dialog.search(); self.assertEqual(dialog.total,2)
            dialog.load(new); self.assertEqual(dialog.current['memory_id'],new)
            dialog.related('supersedes'); self.assertEqual(dialog.current['memory_id'],old)
            dialog.related('superseded_by'); self.assertEqual(dialog.current['memory_id'],new)
            self.assertIn('待复核',dialog.status.text())

    def test_late_callback_cannot_replace_new_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory=ResearchMemory(tmp)
            ids=[memory.save('hypothesis',str(uuid4()),hypothesis(title=str(n)))['record']['memory_id'] for n in range(2)]
            window=Window(tmp); callbacks=[]
            window.async_call=lambda work,done,guarded=True:callbacks.append((work,done))
            dialog=ResearchMemoryDialog(window); self.addCleanup(window.close); self.addCleanup(dialog.close)
            dialog.load(ids[0]); dialog.load(ids[1])
            for work,done in reversed(callbacks): done(work(),'')
            self.assertEqual(dialog.current['memory_id'],ids[1])

    def test_main_window_entry_and_no_model_needed(self):
        from quantlab.desktop.app import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp)
            self.addCleanup(window.close)
            buttons=[b for b in window.findChildren(QPushButton) if b.text()=='研究记忆']
            self.assertEqual(len(buttons),1); buttons[0].click()
            self.assertTrue(any(isinstance(d,ResearchMemoryDialog) for d in window.dialogs))
            for _ in range(500):
                QApplication.processEvents()
                if not window.callbacks: break
                QTest.qWait(10)
            self.assertFalse(window.callbacks)
            for dialog in window.dialogs: dialog.close()
            window.close(); QApplication.processEvents()

    def test_inline_memory_reference_opens_exact_note_without_approval(self):
        from quantlab.desktop.research_chat import ResearchChatDialog
        from quantlab.desktop.app import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            hid=ResearchMemory(tmp).save('hypothesis',str(uuid4()),hypothesis())['record']['memory_id']
            window=MainWindow(tmp); self.addCleanup(window.close)
            chat=ResearchChatDialog(window); self.addCleanup(chat.close)
            chat.receive('tool_result',{'name':'get_research_memory','result':{'ok':True,'evidence':[{'kind':'memory','memory_id':hid}]}})
            self.assertIn(hid,chat.evidence.item(0).text())
            chat.evidence.setCurrentRow(0); chat.open_reference()
            for _ in range(500):
                QApplication.processEvents()
                if not window.callbacks: break
                QTest.qWait(10)
            panel=next(d for d in window.dialogs if isinstance(d,ResearchMemoryDialog))
            self.assertEqual(panel.current['memory_id'],hid)
            self.assertFalse(list(Path(tmp).glob('_jobs/*.json')))
            for dialog in window.dialogs: dialog.close()
