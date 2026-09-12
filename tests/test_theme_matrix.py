import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.trading.theme_store import ThemeError,ThemeStore
from quantlab.agent.theme_tools import ThemeResearchAPI


def snapshot(**updates):
    value={'theme':'软件AI','trading_day':'2026-09-11','frame':'R1','machine_state':'UNKNOWN','ai_state':'PREHEAT','ai_thesis':'等待确认','risk_review':'数据不足','source':'host_manual'}
    value.update(updates);return value


class ThemeMatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=ThemeStore(self.root)
    def tearDown(self):self.temp.cleanup()

    def test_unknown_is_valid_and_missing_cells_stay_unknown(self):
        first=self.store.create(str(uuid4()),snapshot())
        second=self.store.create(str(uuid4()),snapshot(theme='农业',trading_day='2026-09-10',frame='R2',machine_state='START',ai_state='UNKNOWN'))
        matrix=self.store.matrix();self.assertEqual(set(matrix['themes']),{'软件AI','农业'})
        self.assertIs(matrix['lookup'].get(('软件AI','2026-09-10','R2')),None)
        self.assertEqual(first['machine_state'],'UNKNOWN');self.assertEqual(second['ai_state'],'UNKNOWN')
        self.assertIn('UNKNOWN',matrix['policy'])

    def test_market_facts_require_provenance_and_timezone(self):
        with self.assertRaises(ThemeError):self.store.create(str(uuid4()),snapshot(facts={'limit_up_count':3}))
        saved=self.store.create(str(uuid4()),snapshot(facts={'limit_up_count':3,'amount_billion':123.4,'leader_symbol':'sz.300001'},facts_source='host-import:test',facts_as_of='2026-09-11T14:50:00+08:00'))
        self.assertEqual(saved['facts']['limit_up_count'],3);self.assertEqual(saved['facts']['amount_billion'],123.4)

    def test_revision_idempotency_and_tamper_detection(self):
        request=str(uuid4());first=self.store.create(request,snapshot())
        self.assertEqual(self.store.create(request,snapshot())['snapshot_id'],first['snapshot_id'])
        revised=self.store.create(str(uuid4()),snapshot(machine_state='START',revision_of=first['snapshot_id']))
        self.assertEqual(self.store.get(first['snapshot_id'])['superseded_by'],revised['snapshot_id'])
        self.assertEqual(self.store.list()['records'][0]['machine_state'],'START')
        with self.assertRaises(ThemeError) as stale:self.store.create(str(uuid4()),snapshot(machine_state='REPAIR',revision_of=first['snapshot_id']))
        self.assertEqual(stale.exception.code,'STALE_REVISION')
        db=sqlite3.connect(self.store.path);db.execute("UPDATE theme_snapshots SET payload='{}' WHERE id=?",(revised['snapshot_id'],));db.commit();db.close()
        with self.assertRaises(ThemeError) as corrupt:self.store.get(revised['snapshot_id'])
        self.assertEqual(corrupt.exception.code,'CORRUPT_SNAPSHOT')

    def test_revision_cannot_move_theme_day_or_frame(self):
        first=self.store.create(str(uuid4()),snapshot())
        for changed in (snapshot(theme='农业',revision_of=first['snapshot_id']),snapshot(trading_day='2026-09-10',revision_of=first['snapshot_id']),snapshot(frame='R2',revision_of=first['snapshot_id'])):
            with self.assertRaises(ThemeError) as error:self.store.create(str(uuid4()),changed)
            self.assertEqual(error.exception.code,'INVALID_REVISION')

    def test_score_is_not_an_allowed_market_fact_or_probability(self):
        with self.assertRaises(ThemeError):self.store.create(str(uuid4()),snapshot(facts={'score':85},facts_source='manual',facts_as_of='2026-09-11T15:00:00+08:00'))

    def test_model_theme_tools_are_read_only(self):
        saved=self.store.create(str(uuid4()),snapshot())
        api=ThemeResearchAPI(self.root);names={tool['name'] for tool in api.schemas()}
        self.assertIn('list_theme_snapshots',names);self.assertIn('get_theme_snapshot',names)
        self.assertFalse(any(word in name for name in names for word in ('create_theme','write_theme','revise_theme','save_theme')))
        listed=api.call('list_theme_snapshots',{'query':'软件AI','start':'','end':'','frame':'','offset':0,'limit':20})
        self.assertTrue(listed['ok']);self.assertEqual(listed['data']['total'],1)
        got=api.call('get_theme_snapshot',{'snapshot_id':saved['snapshot_id']})
        self.assertTrue(got['ok']);self.assertEqual(got['data']['theme'],'软件AI')
        denied=api.call('create_theme_snapshot',{})
        self.assertFalse(denied['ok'])


if __name__=='__main__':unittest.main()
