"""F10 real workbench/input-switch integration, isolated fixtures and offscreen Qt only."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QCheckBox
import test_archived_dataset_lifecycle as fixture
from quantlab.desktop.data_workbench import DataConnectedWorkbench, DataResearchChatDialog, DataWorkbenchReadAPI
from quantlab.data.archived_daily_dataset import MARKER


class ArchivedDatasetWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if condition():
                return
            QTest.qWait(5)
        self.fail('Workbench callbacks did not settle')

    def setUp(self):
        self.fx = fixture.ArchivedDatasetLifecycleTests(); self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.exported = self.fx.export()
        self.window = DataConnectedWorkbench(self.fx.output, self.fx.source)
        self.window.tracking_controller.timer.stop()
        self.addCleanup(self.cleanup_window)
        self.wait(lambda: not self.window.callbacks)
        self.old_root = self.window.data_root

    def cleanup_window(self):
        self.wait(lambda: not self.window.callbacks)
        for dialog in list(self.window.dialogs):
            dialog.close()
        self.window.close(); QApplication.processEvents()

    def switch(self, expected=None, keep=None):
        completed = []
        self.window.select_archived_daily_dataset(self.fx.destination,
            expected or self.exported['dataset_id'], lambda value, error: completed.append((value,error)), keep)
        self.wait(lambda: bool(completed) and not self.window.callbacks)
        return completed[0]

    def test_real_selection_closes_old_consent_and_does_not_run_or_authorize(self):
        old = QDialog(self.window); old.consent = QCheckBox(old); old.consent.setChecked(True)
        self.window.dialogs.append(old)
        source_before = fixture.files(self.fx.source); input_before = fixture.files(self.fx.destination)
        result, error = self.switch()
        self.assertFalse(error, error); self.assertEqual(result['dataset_id'], self.exported['dataset_id'])
        self.assertEqual(self.window.data_root, self.fx.destination); self.assertFalse(old.consent.isChecked())
        self.assertIsNone(self.window.queue); self.assertIsNone(getattr(self.window,'_research_chat_dialog',None))
        self.assertFalse((self.fx.output/'_jobs').exists())
        self.assertFalse((self.fx.output/'_research_session_grants').exists())
        self.assertEqual(source_before,fixture.files(self.fx.source))
        self.assertEqual(input_before,fixture.files(self.fx.destination))

    def test_new_chat_keeps_full_runtime_archive_and_data_readers(self):
        self.assertFalse(self.switch()[1])
        chat = DataResearchChatDialog(self.window); self.window.dialogs.append(chat)
        from quantlab.agent.chat_runtime import ChatRuntime
        canonical = ChatRuntime(self.fx.output,self.fx.destination).api
        names = [tool['name'] for tool in chat.runtime.api.schemas()]
        self.assertEqual(len(names),len(set(names)))
        self.assertTrue({t['name'] for t in canonical.schemas()} <= set(names))
        for name in ('get_archived_daily_dataset','read_tdx_data','list_baostock_imports',
                     'get_research_session_grant','list_strategy_runs','preview_peer_review'):
            self.assertIn(name,names)
        value = chat.runtime.api.call('get_archived_daily_dataset',{})
        self.assertTrue(value['ok'],value)
        self.assertEqual(value['data']['dataset_id'],self.exported['dataset_id'])
        capabilities = chat.runtime.api.call('get_capabilities',{})
        self.assertTrue(capabilities['ok'],capabilities)
        self.assertEqual(set(capabilities['data']['tools']),set(names))
        for name in ('export_archived_daily_dataset','approve_proposal','authorize_grant'):
            self.assertNotIn(name,names)
        self.assertFalse(chat.consent.isChecked())

    def test_wrong_id_or_corrupt_package_leaves_root_and_queue_untouched(self):
        self.assertTrue(self.switch('0'*64)[1]); self.assertEqual(self.window.data_root,self.old_root)
        payload = self.fx.destination/'normalized/bars.parquet'; payload.write_bytes(b'broken')
        self.assertTrue(self.switch()[1]); self.assertEqual(self.window.data_root,self.old_root)
        self.assertFalse(self.window._archived_selection_pending); self.assertIsNone(self.window.queue)

    def test_inflight_callback_and_running_queue_prevent_switch(self):
        self.window.callbacks[999] = (None,lambda *_:None)
        try:
            with self.assertRaises(ValueError):self.switch()
        finally:self.window.callbacks.pop(999)
        self.window.queue = SimpleNamespace(list=lambda:[{'status':'running'}])
        try:
            with self.assertRaises(ValueError):self.switch()
        finally:self.window.queue = None
        self.assertEqual(self.window.data_root,self.old_root)

    def test_effective_session_grant_is_not_inherited_or_revoked(self):
        from quantlab.agent.research_session_grant import preview_grant,authorize_grant,SessionGrantStore
        from quantlab.storage.codec import digest
        scope = {'symbols':self.fx.symbols,'start':self.fx.start,'end':self.fx.end,'timeframe':'1d',
                 'adjustment':'raw','qualification':'research_only','allowed_modes':['single'],
                 'allowed_factors':['BASE.MOMENTUM@1.0.0']}
        plan = preview_grant(self.fx.output,self.old_root,scope,
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        authorize_grant(self.fx.output,self.old_root,plan,digest(plan),confirmed=True)
        record = SessionGrantStore(self.fx.output).current; before = record.read_bytes()
        _,error = self.switch(); self.assertIn('授权',error)
        self.assertEqual(self.window.data_root,self.old_root); self.assertEqual(record.read_bytes(),before)

    def test_tracking_authorization_and_corrupt_jobs_block_without_repair(self):
        from quantlab.agent.tracking_control_store import ControlStore
        store = ControlStore(self.fx.output); identifier = str(uuid4())
        with store.locked(identifier):
            store.save({'watch_id':identifier,'enabled':True,'cycles':[]})
        _,error = self.switch(); self.assertIn('跟踪',error)
        with store.locked(identifier):
            store.save({'watch_id':identifier,'enabled':False,'cycles':[]})
        jobs = self.fx.output/'_jobs'; jobs.mkdir(); bad = jobs/(str(uuid4())+'.json'); bad.write_text('broken')
        _,error = self.switch(); self.assertTrue(error)
        self.assertEqual(bad.read_text(),'broken'); self.assertEqual(self.window.data_root,self.old_root)

    def test_revoked_tracking_with_synced_cycles_allows_switch(self):
        from quantlab.agent.tracking_control_store import ControlStore
        store=ControlStore(self.fx.output); identifier=str(uuid4())
        with store.locked(identifier):
            store.save({'watch_id':identifier,'enabled':False,'cycles':[{'status':'synced'}]})
        result,error=self.switch()
        self.assertFalse(error,error); self.assertEqual(result['dataset_id'],self.exported['dataset_id'])

    def test_data_wrapper_preserves_locked_spec_tool_boundary(self):
        from test_research_spec_fidelity import synthetic_pair
        from quantlab.agent.research_specs import ResearchSpecStore
        from quantlab.agent.chat_runtime import ChatRuntime
        md,js=synthetic_pair(self.fx.root)
        spec=ResearchSpecStore(self.fx.output).import_pair(md,js,confirmed=True)
        inner=ChatRuntime(self.fx.output,self.fx.destination,local_data_only=True,research_spec=spec['spec_id']).api
        wrapped=DataWorkbenchReadAPI(inner,self.fx.output,self.fx.destination)
        self.assertEqual(wrapped.schemas(),inner.schemas())
        self.assertEqual(wrapped.call('get_capabilities',{}),inner.call('get_capabilities',{}))
        self.assertFalse(wrapped.call('list_baostock_imports',{'offset':0,'limit':1})['ok'])

    def test_persisted_running_job_is_checked_without_constructing_queue(self):
        jobs=self.fx.output/'_jobs';jobs.mkdir();(jobs/(str(uuid4())+'.json')).write_text(json.dumps({'status':'running'}))
        _,error=self.switch();self.assertTrue(error);self.assertIsNone(self.window.queue)
        self.assertEqual(self.window.data_root,self.old_root)

    def delayed_selection(self, keep=None):
        calls=[];completed=[]
        with patch.object(self.window,'async_call',side_effect=lambda function,callback,guarded=False:calls.append((function,callback))):
            self.window.select_archived_daily_dataset(self.fx.destination,self.exported['dataset_id'],
                lambda value,error:completed.append((value,error)),keep)
        self.assertTrue(self.window._archived_selection_pending)
        with self.assertRaises(ValueError):self.window.get_research_queue()
        return calls[0],completed

    def test_close_or_context_change_discards_late_selection(self):
        keep=QDialog(self.window);self.window.dialogs.append(keep);keep.closing=False
        (work,done),completed=self.delayed_selection(keep);value=work();keep.closing=True;done(value,'')
        self.assertTrue(completed[0][1]);self.assertEqual(self.window.data_root,self.old_root)
        (work,done),completed=self.delayed_selection();value=work()
        self.window.data_root=self.fx.root;done(value,'')
        self.assertIn('变化',completed[0][1]);self.assertEqual(self.window.data_root,self.fx.root)

    def test_marker_change_between_background_check_and_application_is_rejected(self):
        (work,done),completed=self.delayed_selection();value=work()
        (self.fx.destination/MARKER).write_text('{}');done(value,'')
        self.assertTrue(completed[0][1]);self.assertEqual(self.window.data_root,self.old_root)
        self.assertFalse(self.window._archived_selection_pending)

    def test_payload_change_after_background_inspect_is_rejected(self):
        (work,done),completed=self.delayed_selection();value=work()
        (self.fx.destination/'normalized/bars.parquet').write_bytes(b'changed')
        done(value,'')
        self.assertTrue(completed[0][1]);self.assertEqual(self.window.data_root,self.old_root)

    def test_unfrozen_resumable_old_jobs_block_root_change(self):
        jobs=self.fx.output/'_jobs';jobs.mkdir();identifier=str(uuid4());path=jobs/(identifier+'.json')
        for status in ('failed','cancelled','interrupted'):
            with self.subTest(status=status):
                record={'job_id':identifier,'status':status,'spec':self.fx.spec,'execution_guard':None}
                path.write_text(json.dumps(record));before=path.read_bytes()
                _,error=self.switch();self.assertTrue(error,'resumable job must stay on its original input')
                self.assertEqual(self.window.data_root,self.old_root);self.assertEqual(path.read_bytes(),before)

    def test_dispatch_exception_restores_selection_guard(self):
        with patch.object(self.window,'async_call',side_effect=RuntimeError('dispatcher unavailable')):
            with self.assertRaises(RuntimeError):self.switch()
        self.assertFalse(self.window._archived_selection_pending)
        self.assertFalse(self.switch()[1])

    def test_data_center_has_explicit_archived_input_entry(self):
        from PyQt6.QtWidgets import QPushButton
        with patch.object(self.window,'open_archived_daily_dataset') as open_dialog:
            self.window.data_page()
            controls=[b for b in self.window.findChildren(QPushButton)
                      if b.text()=='归档日线研究输入：预检 / 生成 / 选择']
            self.assertEqual(len(controls),1);controls[0].click();open_dialog.assert_called_once()
        self.wait(lambda:not self.window.callbacks)

    def test_real_dialog_previews_exports_inspects_and_explicitly_selects(self):
        import shutil
        from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
        shutil.copytree(self.fx.source/'_market_data',self.fx.output/'_market_data')
        source_before=fixture.files(self.fx.output/'_market_data')
        dialog=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(dialog)
        for field,value in ((dialog.capture_id,self.fx.capture),(dialog.symbols,' '.join(self.fx.symbols)),
                            (dialog.start,self.fx.start),(dialog.end,self.fx.end),
                            (dialog.destination,str(self.fx.root/'ui-created'))):field.setText(value)
        dialog.preview();self.wait(lambda:not dialog.busy and not self.window.callbacks)
        self.assertIsNotNone(dialog.preview_hash,dialog.status.text())
        dialog.confirm.setChecked(True);dialog.export()
        self.wait(lambda:not dialog.busy and not self.window.callbacks)
        target=self.fx.root/'ui-created';self.assertTrue((target/MARKER).is_file(),dialog.status.text())
        self.assertEqual(self.window.data_root,self.old_root);self.assertIsNone(self.window.queue)
        dialog.package_path.setText(str(target));dialog.inspect_package()
        self.wait(lambda:not dialog.busy and not self.window.callbacks)
        identity=dialog.inspected_dataset_id;self.assertIsNotNone(identity,dialog.status.text())
        dialog.use_package();self.wait(lambda:not dialog.busy and not self.window.callbacks)
        self.assertEqual(self.window.data_root,target,dialog.status.text())
        self.assertIn('显式切换',dialog.status.text());self.assertIsNone(self.window.queue)
        self.assertEqual(source_before,fixture.files(self.fx.output/'_market_data'))
        self.assertFalse((self.fx.output/'_jobs').exists())
        self.assertFalse((self.fx.output/'_research_session_grants').exists())

    def test_real_dialog_close_during_selection_does_not_switch_root(self):
        from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
        dialog=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(dialog)
        dialog.package_path.setText(str(self.fx.destination));dialog.inspect_package()
        self.wait(lambda:not dialog.busy and not self.window.callbacks)
        calls=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,guarded=False:calls.append((fn,done))):
            dialog.use_package()
        self.assertTrue(dialog.busy);work,done=calls[0];value=work();dialog.reject()
        self.assertTrue(dialog.closing);done(value,'')
        self.wait(lambda:not self.window._archived_selection_pending and not dialog.busy)
        self.assertEqual(self.window.data_root,self.old_root)

    def test_missing_host_completion_is_not_presented_as_selection_success(self):
        from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
        dialog=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(dialog)
        dialog.package_path.setText(str(self.fx.destination));dialog.inspect_package()
        self.wait(lambda:not dialog.busy and not self.window.callbacks)
        with patch.object(self.window,'select_archived_daily_dataset',
                side_effect=lambda path,identity,done,keep_dialog=None:done(None,'')):
            dialog.use_package()
        self.assertIn('未切换',dialog.status.text())
        self.assertEqual(self.window.data_root,self.old_root)

    def test_export_close_request_keeps_actions_disabled_after_completion(self):
        import shutil
        from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
        shutil.copytree(self.fx.source/'_market_data',self.fx.output/'_market_data')
        dialog=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(dialog)
        for field,value in ((dialog.capture_id,self.fx.capture),(dialog.symbols,' '.join(self.fx.symbols)),
                            (dialog.start,self.fx.start),(dialog.end,self.fx.end),
                            (dialog.destination,str(self.fx.root/'closing-ui'))):field.setText(value)
        dialog.preview();self.wait(lambda:not dialog.busy and not self.window.callbacks)
        dialog.confirm.setChecked(True);calls=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,guarded=False:calls.append((fn,done))):
            dialog.export();dialog.reject();self.assertTrue(dialog.closing)
            work,done=calls[0];value=work();done(value,'')
            self.assertFalse(dialog.export_button.isEnabled())
            dialog.export();self.assertEqual(len(calls),1)
        self.assertTrue((self.fx.root/'closing-ui'/MARKER).is_file())
        self.assertEqual(self.window.data_root,self.old_root)

    def test_closed_read_dialog_does_not_leave_permanent_busy_blocker(self):
        from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog
        dialog=ArchivedDailyDatasetDialog(self.window);self.window.dialogs.append(dialog)
        for field,value in ((dialog.capture_id,self.fx.capture),(dialog.symbols,' '.join(self.fx.symbols)),
                            (dialog.start,self.fx.start),(dialog.end,self.fx.end)):field.setText(value)
        calls=[]
        with patch.object(self.window,'async_call',side_effect=lambda fn,done,guarded=False:calls.append((fn,done))):
            dialog.preview();self.assertTrue(dialog.busy);dialog.reject()
        self.assertTrue(dialog.closed);self.assertFalse(dialog.busy)
        calls[0][1](None,'late failure')
        self.assertFalse(self.switch()[1])

    def test_full_proposal_flow_after_ui_selection_uses_selected_package(self):
        self.assertFalse(self.switch()[1])
        from quantlab.agent.proposals import ProposalService
        service=ProposalService(self.fx.output,self.window.data_root)
        proposal=service.propose(str(uuid4()),self.fx.spec)
        self.assertIsNone(self.window.queue)
        job=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.window.get_research_queue)['job']
        self.wait(lambda:all(j['status'] not in ('queued','running') for j in self.window.queue.list()))
        saved=self.window.queue.list()[0];self.assertEqual(saved['status'],'completed',saved)
        record=json.loads((self.fx.output/saved['run_id']/'experiment.json').read_text())
        self.assertEqual(record['manifest']['data_snapshot']['source'],'archived_retro_daily_dataset')
        self.assertIn(self.exported['dataset_id'],json.dumps(record['manifest']['data_snapshot']))


if __name__ == '__main__':unittest.main()
