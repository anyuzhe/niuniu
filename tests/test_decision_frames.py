import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

from quantlab.trading.decision_store import DecisionError,DecisionStore
from quantlab.trading.decision_frames import compare_intraday,followup_chain
from quantlab.trading.frame_policy import FramePolicyStore,assess_submission,default_policy


def base(**updates):
    value={'symbol':'sh.600000','trading_day':'2026-09-11','frame':'R1','action':'WATCH','role_id':'human','theme':'银行','ai_thesis':'观察','source':'test'}
    value.update(updates);return value


class DecisionFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def store_at(self,iso):
        moment=datetime.fromisoformat(iso)
        return DecisionStore(self.root,now_fn=lambda:moment)

    def test_default_policy_classifies_on_time_early_late_and_backfill(self):
        policy=default_policy()
        self.assertEqual(assess_submission('2026-09-11','R1','2026-09-11T10:00:00+08:00',policy)['submission_status'],'ON_TIME')
        self.assertEqual(assess_submission('2026-09-11','R1','2026-09-11T09:00:00+08:00',policy)['submission_status'],'EARLY')
        self.assertEqual(assess_submission('2026-09-11','R1','2026-09-11T11:00:00+08:00',policy)['submission_status'],'LATE')
        self.assertEqual(assess_submission('2026-09-11','R1','2026-09-12T09:00:00+08:00',policy)['submission_status'],'BACKFILL')
        self.assertEqual(assess_submission('2026-09-12','PREP','2026-09-11T20:00:00+08:00',policy)['submission_status'],'ON_TIME')

    def test_policy_store_checksum_and_custom_window(self):
        store=FramePolicyStore(self.root);policy=store.load();self.assertEqual(policy['version'],'a-share-default-v1')
        policy['windows']['R1']['end']='10:45'
        with self.assertRaises(ValueError):store.save(policy)
        policy['version']='custom-v1';store.save(policy)
        self.assertEqual(store.load()['windows']['R1']['end'],'10:45')
        store.path.write_text('{"policy":{},"checksum":"bad"}')
        with self.assertRaises(ValueError):store.load()

    def test_decision_persists_submission_assessment(self):
        store=self.store_at('2026-09-11T02:00:00+00:00')
        saved=store.create(str(uuid4()),base())
        self.assertEqual(saved['submission_status'],'ON_TIME')
        self.assertEqual(saved['frame_policy_version'],'a-share-default-v1')
        self.assertIn('+08:00',saved['submitted_local'])
        self.assertTrue(saved['frame_open_at'].endswith('+08:00'))
        self.assertTrue(saved['frame_close_at'].endswith('+08:00'))

    def test_historical_submission_is_backfill_and_future_effective_at_rejected(self):
        store=self.store_at('2026-09-12T02:00:00+00:00')
        saved=store.create(str(uuid4()),base())
        self.assertEqual(saved['submission_status'],'BACKFILL')
        with self.assertRaises(DecisionError) as error:
            store.create(str(uuid4()),base(effective_at='2026-09-12T10:01:00+08:00'))
        self.assertEqual(error.exception.code,'FUTURE_EFFECTIVE_AT')

    def test_followup_frames_require_valid_earlier_reference(self):
        source_store=self.store_at('2026-09-11T02:00:00+00:00')
        source=source_store.create(str(uuid4()),base())
        follow_store=self.store_at('2026-09-12T02:00:00+00:00')
        with self.assertRaises(DecisionError) as missing:
            follow_store.create(str(uuid4()),base(trading_day='2026-09-12',frame='D1'))
        self.assertEqual(missing.exception.code,'MISSING_REFERENCE')
        follow=follow_store.create(str(uuid4()),base(trading_day='2026-09-12',frame='D1',reference_decision_id=source['decision_id']))
        self.assertEqual(follow['reference_decision_id'],source['decision_id'])
        self.assertEqual(follow['submission_status'],'UNBOUNDED')
        chain=followup_chain(follow_store,source['decision_id'])
        self.assertEqual([r['decision_id'] for r in chain['followups']],[follow['decision_id']])
        later=self.store_at('2026-09-13T02:00:00+00:00')
        with self.assertRaises(DecisionError) as chained:
            later.create(str(uuid4()),base(trading_day='2026-09-13',frame='D2',reference_decision_id=follow['decision_id']))
        self.assertEqual(chained.exception.code,'INVALID_REFERENCE')

    def test_legacy_decision_without_frame_assessment_stays_readable(self):
        import json,sqlite3
        from quantlab.storage.codec import digest,encode
        store=self.store_at('2026-09-11T02:00:00+00:00');saved=store.create(str(uuid4()),base())
        legacy=dict(saved)
        for key in ('frame_policy_version','frame_timezone','submitted_local','submission_status','frame_open_at','frame_close_at','submission_lag_seconds','reference_decision_id'):
            legacy.pop(key,None)
        db=sqlite3.connect(store.path);db.execute('UPDATE decisions SET payload=?,checksum=? WHERE id=?',(encode(legacy),digest(legacy),saved['decision_id']));db.commit();db.close()
        loaded=store.get(saved['decision_id']);self.assertNotIn('submission_status',loaded);self.assertEqual(loaded['symbol'],'sh.600000')

    def test_intraday_comparison_preserves_missing_frames_and_changes(self):
        store=self.store_at('2026-09-11T01:00:00+00:00')
        prep=store.create(str(uuid4()),base(frame='PREP',action='WATCH',ai_thesis='盘前观察'))
        r1store=self.store_at('2026-09-11T02:00:00+00:00')
        r1=r1store.create(str(uuid4()),base(frame='R1',action='READY',ai_thesis='早盘确认'))
        report=compare_intraday(r1store,'sh.600000','2026-09-11')
        lookup={row['frame']:row for row in report['rows']}
        self.assertEqual(lookup['AUCTION']['status'],'missing')
        self.assertTrue(lookup['R1']['changes']['action']['changed'])
        self.assertEqual(lookup['R1']['changes']['action']['from'],'WATCH')
        self.assertEqual(lookup['R1']['changes']['action']['to'],'READY')
        self.assertEqual(prep['decision_id'],lookup['PREP']['decision']['decision_id'])
        self.assertEqual(r1['decision_id'],lookup['R1']['decision']['decision_id'])


if __name__=='__main__':unittest.main()
