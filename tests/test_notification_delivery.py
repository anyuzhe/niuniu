from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import tempfile
import unittest
from quantlab.agent.notification_delivery import DeliveryStore,notice_events,notification_text
from quantlab.agent.tracking_control_store import ControlStore,notify


def fixture_notices(output, stamp=None):
    stamp=stamp or datetime.now(timezone.utc)-timedelta(minutes=1)
    state={'watch_id':str(uuid4()),'grant_id':str(uuid4()),'notices':{},'enabled':False}
    notify(state,'data','snapshot_updated',{'private_note':'not for lock screen'},stamp)
    notify(state,'failure','blocked',{'detail':'confidential'},stamp)
    store=ControlStore(output)
    with store.locked(state['watch_id']):store.save(state)
    return state


class NotificationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=DeliveryStore(self.root)
    def test_absent_inbox_and_history_do_not_create_files(self):
        self.assertEqual(notice_events(self.root)['events'],[])
        self.assertEqual(self.store.reserve([]),[])
        self.assertEqual(self.store.history()['total'],0)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_reserve_then_restart_is_at_most_once_and_inbox_unchanged(self):
        state=fixture_notices(self.root);source=ControlStore(self.root).folder(state['watch_id'])/'state.json'
        before=source.read_bytes();events=notice_events(self.root)['events']
        claimed=self.store.reserve(events);self.assertEqual(len(claimed),2)
        self.assertEqual(DeliveryStore(self.root).reserve(events),[])
        self.store.finish(claimed,'handed_to_qt');history=self.store.history()
        self.assertEqual(history['total'],2);self.assertFalse(history['display_confirmed'])
        self.assertTrue(all(r['state']=='handed_to_qt' for r in history['deliveries']))
        self.assertEqual(before,source.read_bytes())
        title,body=notification_text(events)
        self.assertNotIn('confidential',body);self.assertNotIn(state['watch_id'],body)
    def test_competing_readers_reserve_only_once(self):
        fixture_notices(self.root);events=notice_events(self.root)['events']
        def reserve(_):return DeliveryStore(self.root).reserve(events)
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(reserve,range(4)))
        self.assertEqual(sum(map(len,results)),2);self.assertEqual(self.store.history()['total'],2)
    def test_unconfirmed_dispatch_is_not_replayed_in_another_process(self):
        fixture_notices(self.root);self.store.reserve(notice_events(self.root)['events'])
        script='from quantlab.agent.notification_delivery import *; import sys; print(len(DeliveryStore(sys.argv[1]).reserve(notice_events(sys.argv[1])["events"])))'
        result=subprocess.run([sys.executable,'-c',script,str(self.root)],capture_output=True,text=True,check=True,timeout=20)
        self.assertEqual(result.stdout.strip(),'0')
        self.assertTrue(all(r['state']=='reserved' for r in self.store.history()['deliveries']))
    def test_existing_cooldown_generates_a_new_event_only_when_due(self):
        t=datetime.now(timezone.utc)-timedelta(hours=12);state=fixture_notices(self.root,t)
        store=ControlStore(self.root);self.store.reserve(notice_events(self.root)['events'])
        store.acknowledge(state['watch_id'])
        with store.locked(state['watch_id']):
            current=store.get(state['watch_id']);notify(current,'data','snapshot_updated',{},t+timedelta(hours=1));store.save(current)
        self.assertEqual(notice_events(self.root)['events'],[])
        with store.locked(state['watch_id']):
            current=store.get(state['watch_id']);notify(current,'data','snapshot_updated',{},t+timedelta(hours=6));store.save(current)
        self.assertEqual(len(self.store.reserve(notice_events(self.root)['events'])),1)
    def test_future_and_read_notices_are_not_reserved(self):
        state=fixture_notices(self.root,datetime.now(timezone.utc)+timedelta(days=1))
        self.assertEqual(self.store.reserve(notice_events(self.root)['events']),[])
        ControlStore(self.root).acknowledge(state['watch_id'])
        self.assertEqual(notice_events(self.root)['events'],[])
    def test_failed_and_suppressed_dispatches_do_not_acknowledge_or_retry(self):
        state=fixture_notices(self.root);events=self.store.reserve(notice_events(self.root)['events'])
        self.store.finish(events[:1],'dispatch_failed');self.store.finish(events[1:],'suppressed')
        self.assertEqual(self.store.reserve(notice_events(self.root)['events']),[])
        self.assertEqual(len(notice_events(self.root)['events']),2)
        with self.assertRaises(ValueError):self.store.finish(events,'delivered')
    def test_tampered_identity_and_symlink_rejected(self):
        fixture_notices(self.root);events=notice_events(self.root)['events'];events[0]['event_id']='bad'
        with self.assertRaises(ValueError):self.store.reserve(events)
        self.assertEqual(self.store.history()['total'],0)
        target=self.root/'other';target.mkdir();workspace=self.root/'workspace';workspace.mkdir()
        (workspace/'_notification_delivery').symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):DeliveryStore(workspace).history()
