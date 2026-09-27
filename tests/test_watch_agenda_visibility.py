import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_agenda import ResearchAgendaDialog
import test_watchlist as fixtures


class WatchAgendaVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixtures.WatchlistTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.created=self.fx.create();self.wid=self.created['watch_id'];self.windows=[]
        self.agenda=ResearchAgendaService(self.fx.output,self.fx.root)
    def wait(self,predicate):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def tearDown(self):
        for window in self.windows:
            for dialog in window.dialogs:dialog.close()
            self.wait(lambda:not window.callbacks);window.close()
        QApplication.processEvents()
    def corrupt_snapshot(self):
        sid=self.created['snapshot']['snapshot_id']
        path=self.fx.service.store.folder(self.wid)/'snapshots'/(sid+'.json')
        row=json.loads(path.read_text());row['preview']['bars']=999;path.write_text(json.dumps(row))
    def open_dialog(self):
        window=MainWindow(self.fx.output);window.data_root=self.fx.root;self.windows.append(window)
        dialog=ResearchAgendaDialog(window);window.show_dialog(dialog);self.wait(lambda:not dialog.busy)
        return window,dialog
    def test_unreadable_snapshot_survives_as_actionable_error_in_agenda(self):
        self.corrupt_snapshot();items=self.agenda._watch_items()
        error=next(r for r in items if r['kind']=='watch_snapshot_error')
        self.assertEqual(error['evidence'],[{'kind':'watch','watch_id':self.wid}])
        self.assertIn('失败',error['reason']);self.assertIn('不删除',error['action'])
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_scan_budget_is_reported_instead_of_healthy_complete_claim(self):
        rows=[{'watch_id':str(uuid4()),'name':'fixture'} for _ in range(101)]
        class Store:
            def list(inner):return {'watches':rows,'unreadable':0}
        class Service:
            store=Store()
            def __init__(inner):inner.calls=[]
            def get(inner,wid):
                inner.calls.append(wid);return {'source_integrity':'verified','latest':{'alerts':[]}}
        service=Service()
        with patch('quantlab.agent.research_agenda.WatchService',return_value=service):
            items=self.agenda._watch_items()
        self.assertEqual(len(service.calls),100)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['kind'],'watch_scan_limited')
        self.assertIn('1 个未核对',items[0]['reason'])
    def test_agenda_native_selected_watch_opens_only_exact_read_target(self):
        self.corrupt_snapshot()
        window,dialog=self.open_dialog()
        index=next(i for i,r in enumerate(dialog.items) if any(v.get('watch_id')==self.wid for v in r.get('evidence',[])))
        self.assertFalse(dialog.open_watch_button.isEnabled());dialog.listing.selectRow(index)
        self.assertTrue(dialog.open_watch_button.isEnabled())
        with patch.object(window,'factor_watches') as target:
            dialog.open_watch_button.click();target.assert_called_once_with(self.wid)
        self.assertIn('不是全工作空间',dialog.status.text())
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_refresh_error_clears_previous_actions_and_no_stale_workspace_navigation(self):
        self.corrupt_snapshot()
        window,dialog=self.open_dialog();dialog.listing.selectRow(0)
        with patch.object(dialog.service,'build',side_effect=ValueError('fixture read failure')):
            dialog.reload();self.wait(lambda:not dialog.busy)
        self.assertEqual(dialog.items,[]);self.assertEqual(dialog.listing.rowCount(),0)
        self.assertFalse(dialog.open_watch_button.isEnabled());self.assertIn('未完成',dialog.status.text())
        output=window.output;window.output=self.fx.root/'other'
        try:
            with patch.object(window,'factor_watches') as target,patch.object(dialog.service,'build') as reader:
                dialog.open_watch();dialog.reload();target.assert_not_called();reader.assert_not_called()
        finally:window.output=output
    def test_closed_dialog_does_not_accept_late_reply(self):
        window,dialog=self.open_dialog();pending=[]
        with patch.object(window,'async_call',side_effect=lambda fn,cb,**kwargs:pending.append((fn,cb))):
            dialog.reload()
        dialog.close();value={'items':[{'title':'late'}],'total':1}
        pending[0][1](value,None)
        self.assertEqual(dialog.items,[]);self.assertFalse(dialog.open_watch_button.isEnabled())


if __name__=='__main__':unittest.main()
