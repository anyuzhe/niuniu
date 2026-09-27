import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

import test_alpha_factory as fixtures
from quantlab.desktop.app import MainWindow
from quantlab.desktop.factory_builder import FactoryPlanDialog
from quantlab.desktop.alpha_factory import AlphaFactoryDialog
from quantlab.trading.research_evidence import archive_research_reference,find_research_archives


class ArchiveDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def header(self,kind='factor',status='completed',name='test'):
        rid=str(uuid4());folder=self.root/rid;folder.mkdir()
        record={'run_id':rid,'kind':kind,'status':status,'created_at':'2025-01-01','manifest':{
            'config':{'research_question':name,'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{},'horizons':[1,5],
                      'data':{'symbols':['A'],'start':'2025-01-01','end':'2025-01-10','timeframe':'1d'}},
            'parameters':{'lookback':20},'data_snapshot':{'adjustment':'raw'}}}
        (folder/'experiment.json').write_text(json.dumps(record));return rid
    def test_kind_scope_actual_parameters_and_failed_visibility(self):
        factor=self.header(name='精确动量');failed=self.header(status='failed');execution=self.header(kind='execution')
        value=find_research_archives(self.root,kind='factor');self.assertEqual({r['source']['run_id'] for r in value['matches']},{factor,failed})
        self.assertTrue(all(r['metadata_only'] for r in value['matches']))
        filtered=find_research_archives(self.root,query='精确动量',kind='factor')['matches']
        self.assertEqual(len(filtered),1);self.assertEqual(filtered[0]['horizons'],[1,5]);self.assertEqual(filtered[0]['adjustment'],'raw')
        self.assertEqual(filtered[0]['rule_identity']['resolved_parameters'],{'lookback':20})
        self.assertEqual(find_research_archives(self.root,kind='execution')['matches'][0]['source']['run_id'],execution)
    def test_real_pagination_preserves_matches_and_bad_entries(self):
        ids={self.header() for _ in range(9)};bad=str(uuid4());(self.root/bad).mkdir();(self.root/bad/'experiment.json').write_text('{bad')
        offset=0;seen=set();errors=set();pages=0
        while True:
            result=find_research_archives(self.root,offset=offset,limit=2,scan_budget=3);pages+=1
            seen.update(r['source']['run_id'] for r in result['matches']);errors.update(r['run_id'] for r in result['errors'])
            if result['next_offset'] is None:break
            self.assertGreater(result['next_offset'],offset);offset=result['next_offset']
            self.assertLess(pages,20)
        self.assertEqual(seen,ids);self.assertEqual(errors,{bad});self.assertGreater(pages,1)
    def test_inventory_change_and_bad_inputs_remain_explicit(self):
        self.header();before=find_research_archives(self.root)['inventory_digest'];self.header()
        self.assertNotEqual(before,find_research_archives(self.root)['inventory_digest'])
        for kwargs in ({'offset':True},{'limit':0},{'kind':'unknown'},{'query':'a'*501}):
            with self.assertRaises(ValueError):find_research_archives(self.root,**kwargs)
        alias=self.root/'alias';alias.symlink_to(self.root)
        with self.assertRaises(ValueError):find_research_archives(alias)


class FactoryVisualFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.fx=fixtures.AlphaFactoryTests();self.fx.setUp()
        self.window=MainWindow(self.fx.output);self.window.data_root=self.fx.fx.root
        self.dialog=FactoryPlanDialog(self.window);self.window.show_dialog(self.dialog)
        self.wait(lambda:not self.window.callbacks)
    def wait(self,predicate):
        end=time.monotonic()+20
        while time.monotonic()<end:
            QApplication.processEvents()
            if predicate():return
            QTest.qWait(10)
        self.fail('Qt callback did not settle')
    def tearDown(self):
        self.wait(lambda:not self.window.callbacks)
        for dialog in self.window.dialogs:dialog.close()
        if self.window.queue:self.window.queue.close()
        self.window.close();QApplication.processEvents();self.fx.doCleanups()
    def configure(self):
        d=self.dialog;ref=archive_research_reference(self.fx.output,self.fx.baseline.run_id)
        d.use_archive('baseline',ref);d.use_archive('control',ref)
        definition=next(v for v in self.window.factors if v['definition']['factor_id']=='BASE.MOMENTUM')
        d.set_factor(definition);d.parameters={'lookback':3};d.candidate_name.setText('动量3');d.add_candidate()
        d.name.setText('可视化固定计划');d.train_end.setText('2025-01-06');d.evaluation_start.setText('2025-01-07')
        d.horizon.setCurrentIndex(d.horizon.findData(1));return d
    def preview(self):
        self.dialog.preview_plan();self.wait(lambda:not self.dialog.busy)
        self.assertIsNotNone(self.dialog.prepared,self.dialog.status.text())
    def test_empty_form_does_not_create_research_or_proposals(self):
        d=self.dialog;d.preview_plan();d.save_plan()
        self.assertIsNone(d.prepared);self.assertEqual(d.service.list()['factories'],[])
        self.assertFalse((self.fx.output/'_jobs').exists())
        self.assertEqual(d.train_end.text(),'');self.assertIsNone(d.horizon.currentData())
    def test_preview_save_pending_and_existing_manual_execution_end_to_end(self):
        d=self.configure();self.preview()
        self.assertEqual(d.prepared['planned_test_count'],1)
        d.save_plan();self.assertIsNone(d.saved)
        d.review.setChecked(True);d.save_plan();self.wait(lambda:not d.busy)
        self.assertEqual(d.saved['status'],'pending',d.status.text());self.assertFalse((self.fx.output/'_jobs').exists())
        saved_id=d.saved['proposal_id'];d.save_plan();self.assertEqual(len(d.service.list()['factories']),1)
        d.open_approval();approval=self.window.dialogs[-1];self.assertIsInstance(approval,AlphaFactoryDialog)
        self.wait(lambda:not approval.busy and approval.current is not None)
        self.assertFalse(approval.confirm.isChecked());approval.submit();self.assertFalse((self.fx.output/'_jobs').exists())
        approval.confirm.setChecked(True);approval.submit();self.wait(lambda:not approval.busy)
        self.assertEqual(approval.current['status'],'submitted',approval.status.text())
        self.window.queue.close();approval.sync();self.wait(lambda:not approval.busy)
        result=d.service.get(saved_id);self.assertEqual(result['status'],'completed')
        self.assertTrue((self.fx.output/result['result_run_id']/'experiment.json').is_file())
        self.assertEqual(result['promotions'],[])
        self.assertEqual(approval.test_table.rowCount(),result['prepared']['planned_test_count'])
        self.assertEqual(approval.test_rows[0]['estimate'],result['tests'][0].get('estimate'))
        self.assertEqual(approval.test_rows[0]['p_holm'],result['tests'][0].get('p_holm'))
    def test_pending_plan_survives_window_reopen_and_is_not_auto_submitted(self):
        d=self.configure();self.preview();d.review.setChecked(True);d.save_plan();self.wait(lambda:not d.busy)
        proposal=d.saved['proposal_id'];d.close()
        self.window.open_alpha_factory();approval=self.window.dialogs[-1];self.wait(lambda:not approval.busy)
        self.assertEqual(approval.current['proposal_id'],proposal);self.assertEqual(approval.current['status'],'pending')
        self.assertFalse(approval.confirm.isChecked());self.assertEqual(approval.test_table.rowCount(),1)
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_plan_change_invalidates_preview_and_confirmation(self):
        d=self.configure();self.preview();d.review.setChecked(True)
        d.alpha.setValue(.04)
        self.assertIsNone(d.prepared);self.assertFalse(d.review.isChecked());self.assertFalse(d.save_button.isEnabled())
        d.save_plan();self.assertEqual(d.service.list()['factories'],[])
    def test_duplicate_candidate_identity_rejected_and_added_parameters_frozen(self):
        d=self.configure();self.assertEqual(len(d.candidate_refs),1)
        d.candidate_name.setText('同参数不同名字');d.add_candidate();self.assertEqual(len(d.candidate_refs),1)
        self.assertIn('不可',d.status.text())
        d.parameters['lookback']=4
        self.assertEqual(d.candidate_refs[0]['parameters'],{'lookback':3})
    def test_changed_archive_after_selection_or_preview_cannot_be_saved(self):
        d=self.configure();self.preview();d.review.setChecked(True)
        p=self.fx.baseline.artifact_path/'experiment.json';value=json.loads(p.read_text());value['manifest']['config']['research_question']='changed';p.write_text(json.dumps(value))
        d.save_plan();self.wait(lambda:not d.busy)
        self.assertIsNone(d.saved);self.assertEqual(d.service.list()['factories'],[])
        self.assertFalse((self.fx.output/'_jobs').exists());self.assertRegex(d.status.text(),'变化|Archive identity mismatch')
    def test_backend_expected_preview_guard_checks_before_any_proposal_write(self):
        preview=self.fx.service.preview(self.fx.plan())
        with self.assertRaisesRegex(ValueError,'预览已变化'):
            self.fx.service.propose(str(uuid4()),self.fx.plan(),expected_digest='0'*64)
        self.assertEqual(self.fx.service.list()['factories'],[])
        result=self.fx.service.propose(str(uuid4()),self.fx.plan(),expected_digest=preview['prepared_digest'])
        self.assertEqual(result['status'],'pending');self.assertFalse((self.fx.output/'_jobs').exists())
    def test_old_workspace_cannot_preview_or_save_and_late_callback_ignored(self):
        d=self.configure();captured=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,**kwargs:captured.append((fn,done))):d.preview_plan()
        self.assertEqual(len(captured),1)
        fn,done=captured[0];preview=fn();old=self.window.output;self.window.output=old/'different'
        try:
            done(preview,None);self.assertIsNone(d.prepared)
            d.review.setChecked(True);d.save_plan();self.assertEqual(d.service.list()['factories'],[])
        finally:self.window.output=old;d.busy=False
    def test_real_pickers_and_parameter_editor_fill_form_without_manual_ids_or_json(self):
        from quantlab.desktop.research_picker import FactorPickerDialog,ArchivePickerDialog
        d=self.dialog
        d.baseline_button.click();picker=self.window.dialogs[-1];self.assertIsInstance(picker,ArchivePickerDialog)
        self.assertIsNone(picker.results);picker.search_button.click();self.wait(lambda:not self.window.callbacks)
        index=next(i for i,r in enumerate(picker.rows) if r['source']['run_id']==self.fx.baseline.run_id)
        picker.results.selectRow(index);picker.use_button.click();self.wait(lambda:not self.window.callbacks)
        self.assertEqual(d.baseline['source']['run_id'],self.fx.baseline.run_id)
        d.control_button.click();picker=self.window.dialogs[-1];picker.search_button.click();self.wait(lambda:not self.window.callbacks)
        index=next(i for i,r in enumerate(picker.rows) if r['source']['run_id']==self.fx.baseline.run_id)
        picker.results.selectRow(index);picker.use_button.click();self.wait(lambda:not self.window.callbacks)
        d.factor_button.click();factor=self.window.dialogs[-1];self.assertIsInstance(factor,FactorPickerDialog)
        factor.search.setText('BASE.MOMENTUM');factor.versions.setCurrentRow(0);factor.use_button.click()
        self.assertEqual(d.definition['definition']['factor_id'],'BASE.MOMENTUM')
        d.params_button.click();parameters=self.window.dialogs[-1];parameters.controls['lookback'].setValue(3);parameters.finish()
        self.assertEqual(d.parameters,{'lookback':3});d.add_button.click()
        d.name.setText('完整表单入口');d.train_end.setText('2025-01-06');d.evaluation_start.setText('2025-01-07');d.horizon.setCurrentIndex(0)
        self.preview();d.review.setChecked(True);d.save_button.click();self.wait(lambda:not d.busy)
        self.assertEqual(d.saved['status'],'pending',d.status.text());self.assertFalse((self.fx.output/'_jobs').exists())
    def test_optional_cost_after_slots_preserve_execution_configuration(self):
        d=self.configure();account=self.fx.baseline_execution()
        d.require_net.setChecked(True)
        d.use_archive('execution',archive_research_reference(self.fx.output,account.run_id));self.preview()
        self.assertEqual(d.prepared['planned_test_count'],2)
        self.assertTrue(d.prepared['plan']['require_net_return'])
        spec=d.prepared['candidates'][0]['execution_spec']
        self.assertEqual(spec['parameters'],{'lookback':3});self.assertEqual(spec['execution']['top_n'],1)
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_existing_approval_cannot_submit_after_workspace_switch(self):
        d=self.configure();self.preview();d.review.setChecked(True);d.save_plan();self.wait(lambda:not d.busy)
        d.open_approval();approval=self.window.dialogs[-1];self.wait(lambda:not approval.busy)
        approval.confirm.setChecked(True);old=self.window.output;self.window.output=old/'other'
        try:
            with patch.object(approval.service,'submit',side_effect=AssertionError('stale submit')) as submit:
                approval.submit();submit.assert_not_called()
            self.assertFalse(approval.submit_button.isEnabled())
        finally:self.window.output=old
    def test_factor_evidence_prefill_retains_exact_version_without_auto_query(self):
        from quantlab.desktop.factor_evidence import FactorEvidenceDialog
        entry=next(v for v in self.window.factors if v['definition']['factor_id']=='BASE.MOMENTUM')
        before=len(self.window.callbacks);d=FactorEvidenceDialog(self.window,definition=entry);self.window.show_dialog(d)
        self.assertEqual(d.factor.text(),'BASE.MOMENTUM');self.assertEqual(d.version.text(),'1.0.0')
        self.assertEqual(d.params.toPlainText(),'');self.assertEqual(before,len(self.window.callbacks))


if __name__=='__main__':unittest.main()
