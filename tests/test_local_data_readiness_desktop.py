import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path
import hashlib,time,unittest
from unittest.mock import patch
import polars as pl
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import test_local_data_tools as fixture
from quantlab.desktop.app import MainWindow
from quantlab.desktop.experiment import ExperimentDialog
from quantlab.desktop.local_data_readiness import LocalDataReadinessDialog
from quantlab.agent.local_data_tools import LocalMarketDataTools


class LocalDataReadinessDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixture.LocalDataToolsTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root;self.output=self.root/'readiness-output';self.output.mkdir()
        self.window=MainWindow(self.output);self.window.data_root=self.root
        self.addCleanup(self.cleanup);QTest.qWait(30);self.wait(lambda:not self.window.callbacks)
        self.scope=deepcopy(self.fx.profile)
    def wait(self,predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def cleanup(self):
        for d in self.window.dialogs:d.close()
        self.wait(lambda:not self.window.callbacks)
        self.window.close();QApplication.processEvents()
    def hashes(self):return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.parquet')}
    def open(self,scope=None):
        d=LocalDataReadinessDialog(self.window,scope or self.scope);self.window.show_dialog(d);self.wait(lambda:not d.busy);return d
    def form(self):
        d=ExperimentDialog(self.window,draft_only=True);self.window.show_dialog(d)
        d.symbols.setText(self.scope['symbols']);d.start.setDate(QDate(2025,1,1));d.end.setDate(QDate(2025,1,10))
        d.adjustment.setCurrentIndex(d.adjustment.findData('qfq'));return d
    def test_complete_scope_loads_original_provider_without_jobs_or_qualification(self):
        before=self.hashes()
        with patch.object(self.window,'get_research_queue',side_effect=AssertionError('queue')),patch('quantlab.data.qualification.qualify_spec',side_effect=AssertionError('qualification')):
            d=self.open()
        self.assertTrue(d.report['data']['request_loadable']);self.assertEqual(d.listing.rowCount(),5)
        self.assertIn('不是数据完整性',d.status.text());self.assertEqual(before,self.hashes())
        self.assertFalse((self.output/'_jobs').exists());self.assertIsNone(self.window.queue)
    def test_real_null_flow_fields_block_and_remain_unchanged(self):
        p=self.root/'lake/silver/qfq_kline_daily/sh_600000.parquet'
        frame=pl.read_parquet(p).with_columns(pl.when(pl.col('date')==self.fx.fixture.start).then(None).otherwise(pl.col('volume')).alias('volume'))
        frame.write_parquet(p);before=self.hashes();d=self.open()
        self.assertFalse(d.report['data']['request_loadable']);self.assertEqual(d.listing.item(0,1).text(),'阻塞')
        self.assertIn('volume: 1',d.listing.item(0,3).text());self.assertIn('Null in required',d.listing.item(0,4).text())
        self.assertEqual(before,self.hashes());self.assertEqual(d.report['data']['records'][0]['rows'],10)
    def test_explicit_form_button_needs_no_factor_and_never_reads_on_form_open(self):
        with patch.object(LocalMarketDataTools,'call',wraps=self.fx.tools.call) as reader:
            form=self.form();reader.assert_not_called();self.assertEqual(form.target.currentIndex(),-1)
            form.data_check_button.click();self.wait(lambda:not self.window.callbacks)
            self.assertEqual(reader.call_count,1)
        d=next(d for d in self.window.dialogs if isinstance(d,LocalDataReadinessDialog))
        self.assertTrue(d.report['data']['request_loadable']);self.assertIsNone(form.result_spec)
        self.assertFalse((self.output/'_proposals').exists());self.assertFalse((self.output/'_jobs').exists())
    def test_over_twenty_and_unsupported_timeframe_do_not_truncate_or_load(self):
        for scope in ({**self.scope,'symbols':' '.join(f'sh.{600100+i}' for i in range(21))},{**self.scope,'timeframe':'15m'}):
            with patch('quantlab.agent.local_data_tools.local_data_provider',side_effect=AssertionError('must not load')) as provider:
                d=self.open(scope);provider.assert_not_called()
            self.assertIsNone(d.report);self.assertEqual(d.listing.rowCount(),0);self.assertIn('未完成检查',d.status.text());d.close()
    def test_managed_marker_refuses_raw_fallback(self):
        (self.root/'archived-daily-dataset.json').write_text('{bad managed marker')
        with patch('quantlab.agent.local_data_tools.local_data_provider',side_effect=AssertionError('must not fall back')):
            d=self.open()
        self.assertIsNone(d.report);self.assertIn('MANAGED_DISCOVERY_UNSUPPORTED',d.status.text())
    def test_late_result_discarded_after_form_changes(self):
        form=self.form();pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,**kw:pending.append((fn,done))):d=form.inspect_data()
        value=pending[0][0]();form.end.setDate(QDate(2025,1,9));pending[0][1](value,None)
        self.assertIsNone(d.report);self.assertEqual(d.listing.rowCount(),0);self.assertFalse(d.refresh_button.isEnabled())
        self.assertIn('过期',d.status.text());self.assertFalse(d.busy)
    def test_closed_dialog_discards_late_response(self):
        pending=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,**kw:pending.append((fn,done))):
            d=LocalDataReadinessDialog(self.window,self.scope);self.window.show_dialog(d)
        d.close();pending[0][1](pending[0][0](),None)
        self.assertIsNone(d.report);self.assertEqual(d.listing.rowCount(),0)
    def test_worker_error_clears_old_result_and_can_retry(self):
        d=self.open();self.assertIsNotNone(d.report)
        with patch.object(LocalMarketDataTools,'call',side_effect=OSError('fixture failed read')):
            d.reload();self.wait(lambda:not d.busy)
        self.assertIsNone(d.report);self.assertEqual(d.listing.rowCount(),0);self.assertTrue(d.refresh_button.isEnabled())
        d.reload();self.wait(lambda:not d.busy);self.assertTrue(d.report['data']['request_loadable'])
    def test_wrong_scope_reply_never_becomes_current_result(self):
        value=self.fx.tools.call('inspect_local_market_data',self.scope);value['data']['records'][0]['symbol']='sh.699999'
        with patch.object(LocalMarketDataTools,'call',return_value=value):d=self.open()
        self.assertIsNone(d.report);self.assertIn('不一致',d.status.text());self.assertEqual(d.listing.rowCount(),0)
    def test_changed_root_or_replaced_directory_refuses_recheck(self):
        d=self.open();self.window.data_root=self.root/'other'
        with patch.object(LocalMarketDataTools,'call',side_effect=AssertionError('old context')) as reader:d.reload();reader.assert_not_called()
        self.assertIsNone(d.report);self.assertFalse(d.refresh_button.isEnabled())
    def test_missing_root_is_explicit_not_a_fabricated_empty_success(self):
        self.window.data_root=None;d=self.open()
        self.assertIsNone(d.report);self.assertIn('LOCAL_DATA_NOT_CONFIGURED',d.status.text());self.assertEqual(d.listing.rowCount(),0)


if __name__=='__main__':unittest.main()
