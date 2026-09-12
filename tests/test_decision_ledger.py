import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.trading.decision_store import DecisionError, DecisionStore


def decision(**updates):
    value = {
        'symbol':'sh.600000','trading_day':'2026-09-12','frame':'PREP','action':'WATCH',
        'role_id':'human','theme':'银行','theme_role':'观察','ai_thesis':'等待确认',
        'market_snapshot_id':'market-1','rule_snapshot_id':'rules-1',
        'research_evidence_ids':['run-1'],'risk_flags':['data_not_live'],
    }
    value.update(updates)
    return value


class DecisionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); self.root.mkdir(exist_ok=True)
        self.store = DecisionStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_get_idempotency_and_append_only_revision(self):
        request = str(uuid4()); first = self.store.create(request,decision())
        self.assertEqual(self.store.create(request,decision())['decision_id'],first['decision_id'])
        self.assertEqual(self.store.get(first['decision_id'])['symbol'],'sh.600000')
        second = self.store.create(str(uuid4()),decision(action='READY',revision_of=first['decision_id']))
        self.assertEqual(second['revision_of'],first['decision_id'])
        self.assertEqual(self.store.get(first['decision_id'])['superseded_by'],second['decision_id'])
        current = self.store.list()['records']
        self.assertEqual([row['decision_id'] for row in current],[second['decision_id']])
        self.assertEqual(len(self.store.list(include_superseded=True)['records']),2)

    def test_request_conflict_and_stale_revision_are_rejected(self):
        request = str(uuid4()); first = self.store.create(request,decision())
        with self.assertRaises(DecisionError) as conflict:
            self.store.create(request,decision(theme='证券'))
        self.assertEqual(conflict.exception.code,'CONFLICT')
        second = self.store.create(str(uuid4()),decision(action='READY',revision_of=first['decision_id']))
        self.assertEqual(second['action'],'READY')
        with self.assertRaises(DecisionError) as stale:
            self.store.create(str(uuid4()),decision(action='WATCH',revision_of=first['decision_id']))
        self.assertEqual(stale.exception.code,'STALE_REVISION')

    def test_revision_identity_and_action_evidence_are_enforced(self):
        first = self.store.create(str(uuid4()),decision())
        with self.assertRaises(DecisionError) as wrong_symbol:
            self.store.create(str(uuid4()),decision(symbol='sz.000001',revision_of=first['decision_id']))
        self.assertEqual(wrong_symbol.exception.code,'INVALID_REVISION')
        with self.assertRaises(DecisionError) as missing_reason:
            self.store.create(str(uuid4()),decision(action='EXIT',ai_thesis='',exit_condition='',invalidation=''))
        self.assertEqual(missing_reason.exception.code,'INVALID_ARGUMENT')
        with self.assertRaises(DecisionError):
            self.store.create(str(uuid4()),decision(action='OPEN',buy_zone='',confirm_trigger=''))

    def test_search_timeline_and_latest_by_symbol(self):
        self.store.create(str(uuid4()),decision(symbol='sh.600000',trading_day='2026-09-11'))
        self.store.create(str(uuid4()),decision(symbol='sz.000001',trading_day='2026-09-12',theme='银行'))
        self.store.create(str(uuid4()),decision(symbol='sh.600000',trading_day='2026-09-12',frame='R1',theme='银行'))
        self.assertEqual(self.store.list(query='银行')['total'],3)
        self.assertEqual(self.store.timeline('sh.600000')['total'],2)
        latest = {row['symbol']:row for row in self.store.latest_by_symbol()}
        self.assertEqual(latest['sh.600000']['trading_day'],'2026-09-12')
        self.assertEqual(latest['sz.000001']['trading_day'],'2026-09-12')

    def test_tamper_is_detected(self):
        value = self.store.create(str(uuid4()),decision())
        import sqlite3
        db = sqlite3.connect(self.store.path)
        db.execute("UPDATE decisions SET payload='{}' WHERE id=?",(value['decision_id'],));db.commit();db.close()
        with self.assertRaises(DecisionError) as error:
            self.store.get(value['decision_id'])
        self.assertEqual(error.exception.code,'CORRUPT_DECISION')


if __name__ == '__main__':
    unittest.main()
