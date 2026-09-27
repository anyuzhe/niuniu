import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from uuid import uuid4
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtTest import QTest
from quantlab.desktop.alpha_factory import AlphaFactoryDialog,factory_test_rows
from quantlab.desktop.app import MainWindow


def state():
    cid=str(uuid4());rid=str(uuid4())
    return {'status':'completed','prepared':{'plan':{'name':'fixed'},'candidates':[{'candidate_id':cid,'name':'候选A'}],
        'planned_test_count':2,'planned_tests':[{'candidate_id':cid,'id':'residual_ic'},{'candidate_id':cid,'id':'net_return_increment'}]},
        'tests':[{'candidate_id':cid,'id':'residual_ic','status':'completed','estimate':-0.03,'p_value':0.04,'p_holm':0.08,'run_id':rid},
                 {'candidate_id':cid,'id':'net_return_increment','status':'failed','estimate':None,'p_value':None,'p_holm':None,'error':'fixture missing data'}],
        'decisions':[{'candidate_id':cid,'recommended_for_watchlist':False,'checks':{'common_finite_ratio':True,'residual_increment':False,'net_return_increment':False}}]}


class FactorySummaryTests(unittest.TestCase):
    def test_stored_negative_values_and_failed_slots_are_retained_without_recalculation(self):
        value=state();before=deepcopy(value);rows=factory_test_rows(value)
        self.assertEqual(value,before);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['estimate'],-.03);self.assertEqual(rows[0]['p_holm'],.08)
        self.assertEqual(rows[1]['status'],'failed');self.assertIsNone(rows[1]['estimate'])
        self.assertIn('净收益增量',rows[0]['blockers']);self.assertEqual(rows[0]['recommendation'],'不建议晋级')
    def test_pending_missing_duplicate_results_never_infer_zero_or_success(self):
        value=state();value['tests']=[];value['decisions']=[];rows=factory_test_rows(value)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['estimate'] is None and r['recommendation']=='未评估' for r in rows))
        value=state();value['tests'].append(deepcopy(value['tests'][0]));rows=factory_test_rows(value)
        self.assertIn('重复',rows[0]['status']);self.assertIsNone(rows[0]['p_value']);self.assertIsNone(rows[0]['run_id'])
    def test_zero_is_not_misreported_as_missing(self):
        value=state();value['tests'][0].update(estimate=0.0,p_value=0.0,p_holm=0.0)
        self.assertEqual(factory_test_rows(value)[0]['p_holm'],0.0)


class FactorySummaryDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.window=MainWindow(self.root);self.window.open_alpha_factory();self.dialog=self.window.dialogs[-1]
        self.wait(lambda:not self.window.callbacks)
    def wait(self,predicate):
        end=time.monotonic()+10
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('callback did not settle')
    def tearDown(self):
        for dialog in self.window.dialogs:dialog.close()
        self.wait(lambda:not self.window.callbacks);self.window.close();QApplication.processEvents();self.tmp.cleanup()
    def test_summary_open_uses_selected_evidence_and_never_starts_queue(self):
        d=self.dialog;value=state();d.current=value;d.render_summary(value);d.buttons()
        self.assertEqual(d.test_table.rowCount(),2);self.assertIn('预设检验 2',d.summary_text.text())
        self.assertEqual(d.test_table.item(1,3).text(),'—');self.assertEqual(d.test_table.item(0,3).text(),'-0.03')
        d.test_table.selectRow(0);self.assertTrue(d.evidence_button.isEnabled())
        rid=value['tests'][0]['run_id']
        with patch.object(self.window.catalog,'file') as file,patch.object(self.window,'open_run') as open_run:
            d.evidence_button.click();file.assert_called_once_with(rid,'experiment.json');open_run.assert_called_once_with(rid)
        d.test_table.selectRow(1);self.assertFalse(d.evidence_button.isEnabled())
        self.assertIsNone(self.window.queue);self.assertFalse((self.root/'_jobs').exists())
    def test_generic_research_lab_creation_entry_does_not_depend_on_data_extension(self):
        self.window.navigate_page('lab')
        buttons=[b for b in self.window.findChildren(QPushButton) if b.text()=='新建可视化Factory计划']
        self.assertTrue(buttons)
        buttons[-1].click()
        from quantlab.desktop.factory_builder import FactoryPlanDialog
        self.assertIsInstance(self.window.dialogs[-1],FactoryPlanDialog)
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()
