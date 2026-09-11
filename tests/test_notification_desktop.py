from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication,QMainWindow,QLabel
from quantlab.desktop.notification_controller import NotificationController
from quantlab.agent.notification_delivery import DeliveryStore,notice_events
from test_notification_delivery import fixture_notices


class Tray:
    def __init__(self):self.calls=[];self.available=True;self.enabled=False;self.fail=False
    def supported(self):return self.available
    def set_enabled(self,value):self.enabled=value
    def send(self,title,body):
        if self.fail:raise RuntimeError('fixture transport failure')
        self.calls.append((title,body))


class Window(QMainWindow):
    def __init__(self,output):
        super().__init__();self.output=output;self.closing=False;self.callbacks={}
        self.status=QLabel();self.pending=[];self.defer=False;self.dialogs=[]
    def async_call(self,fn,done,guarded=False):
        if self.defer:self.pending.append((fn,done));return
        try:value=fn()
        except Exception as error:done(None,str(error))
        else:done(value,None)
    def show_dialog(self,dialog):self.dialogs.append(dialog)
    def open_tracking_control(self):pass


class NotificationDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.workspace=self.root/'workspace';self.workspace.mkdir()
        fixture_notices(self.workspace)
        self.settings=QSettings(str(self.root/'prefs.ini'),QSettings.Format.IniFormat)
        self.window=Window(self.workspace);self.addCleanup(self.window.deleteLater)
        self.tray=Tray();self.hour=12
        self.controller=NotificationController(self.window,self.window.menuBar().addMenu('测试'),
            settings=self.settings,transport=self.tray,clock=lambda:datetime(2026,9,11,self.hour).astimezone())
        self.controller.timer.stop()
    def test_default_is_disabled_and_reads_do_not_create_store(self):
        self.controller.check();self.assertFalse(self.tray.enabled)
        self.assertEqual(self.tray.calls,[])
        self.assertFalse((self.workspace/'_notification_delivery').exists())
    def test_opt_in_dispatch_and_reopened_controller_does_not_repeat(self):
        self.controller.enabled_action.setChecked(True);self.controller.check()
        self.assertEqual(len(self.tray.calls),1)
        fresh=Tray();second=NotificationController(self.window,self.window.menuBar().addMenu('新'),
            settings=self.settings,transport=fresh,clock=self.controller.clock)
        second.timer.stop();second.check();self.assertEqual(fresh.calls,[])
        self.assertFalse(DeliveryStore(self.workspace).history()['display_confirmed'])
        self.assertEqual(len(notice_events(self.workspace)['events']),2)
    def test_quiet_hours_defer_without_consuming_dispatch_ids(self):
        self.controller.enabled_action.setChecked(True);self.hour=23;self.controller.check()
        self.assertFalse((self.workspace/'_notification_delivery').exists())
        self.hour=8;self.controller.check();self.assertEqual(len(self.tray.calls),1)
    def test_unsupported_system_defers_and_inbox_remains_unread(self):
        self.controller.enabled_action.setChecked(True);self.tray.available=False;self.controller.check()
        self.assertEqual(len(notice_events(self.workspace)['events']),2)
        self.assertFalse((self.workspace/'_notification_delivery').exists())
        self.tray.available=True;self.controller.check();self.assertEqual(len(self.tray.calls),1)
    def test_disabling_during_read_suppresses_callback(self):
        self.controller.enabled_action.setChecked(True);self.window.defer=True;self.controller.check()
        fn,done=self.window.pending.pop();value=fn()
        self.controller.enabled_action.setChecked(False);done(value,None)
        self.assertEqual(self.tray.calls,[])
        self.assertTrue(all(r['state']=='suppressed' for r in DeliveryStore(self.workspace).history()['deliveries']))
    def test_workspace_switch_cannot_send_old_workspace_notice(self):
        self.controller.enabled_action.setChecked(True);self.window.defer=True;self.controller.check()
        fn,done=self.window.pending.pop();value=fn()
        other=self.root/'other';other.mkdir();self.window.output=other;done(value,None)
        self.assertFalse(self.controller.enabled_action.isChecked());self.assertEqual(self.tray.calls,[])
        self.assertFalse((other/'_notification_delivery').exists())
    def test_failed_transport_records_failure_not_delivery_and_no_retry(self):
        self.controller.enabled_action.setChecked(True);self.tray.fail=True;self.controller.check()
        self.assertTrue(all(r['state']=='dispatch_failed' for r in DeliveryStore(self.workspace).history()['deliveries']))
        self.tray.fail=False;self.controller.check();self.assertEqual(self.tray.calls,[])
    def test_toggle_after_switch_does_not_change_previous_preferences(self):
        oldkey=self.controller.key;self.controller.enabled_action.setChecked(True)
        other=self.root/'other';other.mkdir();self.window.output=other
        self.controller.enabled_action.setChecked(False)
        self.assertTrue(self.settings.value(oldkey+'enabled',False,type=bool))
