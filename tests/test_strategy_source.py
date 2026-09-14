import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from quantlab.trading.playbook_store import PlaybookError,PlaybookStore


class StrategySourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.clock=datetime.fromisoformat('2026-09-14T17:40:00+08:00')
        self.store=PlaybookStore(self.root,now_fn=lambda:self.clock)
    def tearDown(self):self.temp.cleanup()

    def expert(self):
        return {'expert_key':'qimofenshu','title':'期末50分原始记录','source_type':'LIVE_RECORD',
            'locator':'local:expert','available_at':'2026-09-13T20:00:00+08:00',
            'content_hash':'a'*64,'archive_ref':'local:expert','completeness':'VERIFIED','notes':'legacy'}

    def strategy(self,**updates):
        value={'source_key':'user-breakout-notes','source_kind':'USER_EXPERIENCE','title':'用户突破经验',
            'locator':'local:user-notes','published_at':None,'available_at':'2026-09-14T16:00:00+08:00',
            'content_hash':'b'*64,'archive_ref':'local:user-notes','completeness':'VERIFIED',
            'notes':'人工确认经验，只是来源，不自动成为规则。','evidence_ids':['decision:example']}
        value.update(updates);return value

    def draft_definition(self):
        return {'playbook_key':'high_low_switch','name':'高低切','version':'draft-1','state':'DRAFT',
            'source_ids':[],'market_context':{},'eligibility':{},'selection':{},'veto':{},'entry':{},
            'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':'P8.6 generic source test'}

    def test_legacy_expert_is_projected_as_trader_strategy_source(self):
        expert=self.store.create_source(str(uuid4()),self.expert())
        projected=self.store.get_strategy_source(expert['source_id'])
        self.assertEqual(projected['strategy_source_id'],expert['source_id'])
        self.assertEqual(projected['source_kind'],'TRADER');self.assertEqual(projected['source_key'],'qimofenshu')
        self.assertEqual(projected['legacy_expert_source_id'],expert['source_id'])
        listing=self.store.list_strategy_sources(source_kind='TRADER',query='期末',limit=20)
        self.assertEqual(listing['total'],1);self.assertEqual(listing['records'][0]['compatibility'],'EXPERT_SOURCE_PROJECTION')

    def test_generic_source_and_many_to_many_link_are_append_only(self):
        request=str(uuid4());source=self.store.create_strategy_source(request,self.strategy())
        self.assertEqual(self.store.create_strategy_source(request,self.strategy())['strategy_source_id'],source['strategy_source_id'])
        definition=self.store.create_definition(str(uuid4()),self.draft_definition())
        content={'definition_id':definition['definition_id'],'strategy_source_id':source['strategy_source_id'],
            'relation':'SUPPORT','notes':'支持高低切假设，但不是正式验证。','evidence_ids':['memo:1']}
        link=self.store.create_source_link(str(uuid4()),content)
        self.assertEqual(link['relation'],'SUPPORT');self.assertEqual(link['definition_hash'],definition['definition_hash'])
        bundle=self.store.definition_source_bundle(definition['definition_id'])
        self.assertEqual(len(bundle['strategy_source_links']),1)
        self.assertEqual(bundle['strategy_source_links'][0]['source']['source_kind'],'USER_EXPERIENCE')
        with self.assertRaises(PlaybookError) as duplicate:
            self.store.create_source_link(str(uuid4()),content)
        self.assertEqual(duplicate.exception.code,'LINK_EXISTS')

    def test_generic_source_does_not_bypass_legacy_formal_source_contract(self):
        generic=self.store.create_strategy_source(str(uuid4()),self.strategy(source_kind='STATISTICAL_DISCOVERY',source_key='stat-1'))
        bad={**self.draft_definition(),'version':'v1','state':'FROZEN','source_ids':[generic['strategy_source_id']],
            'eligibility':{'rule':'x'},'selection':{'rule':'y'}}
        with self.assertRaises(PlaybookError) as error:self.store.create_definition(str(uuid4()),bad)
        self.assertEqual(error.exception.code,'NOT_FOUND')
        draft=self.store.create_definition(str(uuid4()),self.draft_definition())
        self.store.create_source_link(str(uuid4()),{'definition_id':draft['definition_id'],
            'strategy_source_id':generic['strategy_source_id'],'relation':'ORIGIN','notes':'','evidence_ids':[]})
        self.assertEqual(self.store.get_definition(draft['definition_id'])['state'],'DRAFT')

    def test_source_links_are_actually_many_to_many(self):
        first=self.store.create_strategy_source(str(uuid4()),self.strategy())
        second=self.store.create_strategy_source(str(uuid4()),self.strategy(
            source_key='public-method-1',source_kind='PUBLIC_METHOD',title='公开方法',
            locator='https://example.invalid/method',content_hash='c'*64,evidence_ids=[]))
        d1=self.store.create_definition(str(uuid4()),self.draft_definition())
        d2=self.store.create_definition(str(uuid4()),{**self.draft_definition(),
            'playbook_key':'leader_reentry','name':'龙头重入','version':'draft-1'})
        for definition,source,relation in ((d1,first,'ORIGIN'),(d2,first,'SUPPORT'),(d1,second,'CONTRADICT')):
            self.store.create_source_link(str(uuid4()),{'definition_id':definition['definition_id'],
                'strategy_source_id':source['strategy_source_id'],'relation':relation,'notes':'','evidence_ids':[]})
        self.assertEqual(self.store.list_source_links(strategy_source_id=first['strategy_source_id'])['total'],2)
        self.assertEqual(self.store.list_source_links(definition_id=d1['definition_id'])['total'],2)
        overview=self.store.overview();self.assertEqual(overview['native_strategy_sources'],2);self.assertEqual(overview['source_links'],3)

    def test_invalid_kind_and_unverified_verified_source_are_rejected(self):
        with self.assertRaises(PlaybookError):
            self.store.create_strategy_source(str(uuid4()),self.strategy(source_kind='UNKNOWN_KIND'))
        with self.assertRaises(PlaybookError):
            self.store.create_strategy_source(str(uuid4()),self.strategy(content_hash='',completeness='VERIFIED'))

    def test_v1_database_remains_readable_and_projects_experts(self):
        expert=self.store.create_source(str(uuid4()),self.expert())
        db=sqlite3.connect(self.store.path)
        db.execute('DROP TABLE strategy_sources');db.execute('DROP TABLE source_links');db.execute('PRAGMA user_version=1')
        db.commit();db.close()
        listing=self.store.list_strategy_sources(limit=20)
        self.assertEqual(listing['total'],1);self.assertEqual(listing['records'][0]['strategy_source_id'],expert['source_id'])
        overview=self.store.overview();self.assertEqual(overview['strategy_sources'],1);self.assertEqual(overview['source_links'],0)
        self.assertEqual(self.store.get_source(expert['source_id'])['expert_key'],'qimofenshu')

    def test_new_record_corruption_is_detected(self):
        source=self.store.create_strategy_source(str(uuid4()),self.strategy())
        db=sqlite3.connect(self.store.path);db.execute("UPDATE strategy_sources SET payload='{}' WHERE id=?",(source['strategy_source_id'],));db.commit();db.close()
        with self.assertRaises(PlaybookError) as error:self.store.get_strategy_source(source['strategy_source_id'])
        self.assertEqual(error.exception.code,'CORRUPT_RECORD')


if __name__=='__main__':unittest.main()
