import json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime,timezone
from io import StringIO
from pathlib import Path
from quantlab.agent.broker_shadow_cli import main as cli_main
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.agent.system_health import SystemHealthService
from quantlab.broker import BrokerShadowReconciler,BrokerSnapshotError,BrokerSnapshotStore,JsonBrokerExportAdapter,normalize_broker_snapshot
from quantlab.experiments.campaign_state import write_checked

class BrokerShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.output.mkdir();self.data.mkdir()
    def snapshot(self,**updates):
        value={'provider':'fixture-broker','account_alias':'main','captured_at':'2026-09-15T09:30:00+08:00',
            'currency':'CNY','cash':50000.0,'equity':60000.0,
            'positions':[{'symbol':'sh.600000','quantity':1000,'available_quantity':1000,'market_value':10000.0}],
            'source_ref':'fixture-export'}
        value.update(updates);return value
    def files(self):return sorted(str(p.relative_to(self.output)) for p in self.output.rglob('*'))

    def test_contract_rejects_sensitive_fields_and_normalizes(self):
        value=normalize_broker_snapshot(self.snapshot())
        self.assertTrue(value['read_only']);self.assertFalse(value['order_submission']);self.assertFalse(value['contains_credentials'])
        self.assertEqual(value['positions'][0]['symbol'],'sh.600000')
        bad=self.snapshot();bad['api_key']='secret'
        with self.assertRaises(BrokerSnapshotError) as error:normalize_broker_snapshot(bad)
        self.assertEqual(error.exception.code,'SENSITIVE_FIELD')
        account=self.snapshot(account_alias='123456789')
        with self.assertRaises(BrokerSnapshotError) as error:normalize_broker_snapshot(account)
        self.assertEqual(error.exception.code,'SENSITIVE_FIELD')

    def test_store_requires_confirmation_is_idempotent_and_detects_tamper(self):
        store=BrokerSnapshotStore(self.output)
        with self.assertRaises(BrokerSnapshotError) as error:store.import_snapshot(self.snapshot())
        self.assertEqual(error.exception.code,'CONFIRM_REQUIRED')
        first=store.import_snapshot(self.snapshot(),confirmed=True);same=store.import_snapshot(self.snapshot(),confirmed=True)
        self.assertEqual(first['snapshot_id'],same['snapshot_id']);self.assertEqual(store.latest('main')['snapshot_id'],first['snapshot_id'])
        with self.assertRaises(BrokerSnapshotError) as escape:store.get('../outside')
        self.assertEqual(escape.exception.code,'INVALID_ARGUMENT')
        path=self.output/'_broker_shadow'/'snapshots'/(first['snapshot_id']+'.json');path.write_text('{}')
        with self.assertRaises(BrokerSnapshotError):store.get(first['snapshot_id'])

    def test_json_adapter_is_read_only(self):
        path=self.root/'broker.json';path.write_text(json.dumps(self.snapshot()))
        value=JsonBrokerExportAdapter(path).snapshot();self.assertEqual(value['account_alias'],'main')
        link=self.root/'broker-link.json';link.symlink_to(path)
        with self.assertRaises(BrokerSnapshotError) as error:JsonBrokerExportAdapter(link).snapshot()
        self.assertEqual(error.exception.code,'INVALID_SOURCE')
        self.assertFalse((self.output/'_broker_shadow').exists())

    def paper(self,quantity=1000,cash=50000.0,equity=60000.0):
        folder=self.output/'paper_dynamic';folder.mkdir(exist_ok=True);path=folder/'main.json'
        write_checked(path,{'format':'dynamic-paper-v1','revision':3,'watermark':'2026-09-15T15:00:00+08:00',
            'summary':{'ending_positions':{'sh.600000':quantity}},'nav':[{'cash':cash,'equity':equity}]})
        return path

    def test_shadow_match_diff_and_read_only(self):
        store=BrokerSnapshotStore(self.output);match=store.import_snapshot(self.snapshot(),confirmed=True);self.paper()
        before=self.files();result=BrokerShadowReconciler(self.output).reconcile(snapshot_id=match['snapshot_id'],paper_account='main');after=self.files()
        self.assertEqual(before,after);self.assertEqual(result['status'],'MATCH');self.assertTrue(result['position_match']);self.assertTrue(result['cash_match'])
        self.assertFalse(result['real_order_submission']);self.assertFalse(result['automatic_execution'])
        later=self.snapshot(captured_at='2026-09-15T10:00:00+08:00',cash=45000.0,
            positions=[{'symbol':'sh.600000','quantity':800,'available_quantity':800,'market_value':8000.0}])
        second=store.import_snapshot(later,confirmed=True);diff=BrokerShadowReconciler(self.output).reconcile(snapshot_id=second['snapshot_id'],paper_account='main')
        self.assertEqual(diff['status'],'DIFF');self.assertFalse(diff['position_match']);self.assertEqual(diff['position_deltas'][0]['delta'],-200)

    def test_empty_shadow_is_side_effect_free(self):
        before=self.files();value=BrokerShadowReconciler(self.output).reconcile();after=self.files()
        self.assertEqual(before,after);self.assertEqual(value['status'],'NOT_CONFIGURED')

    def test_model_tool_is_read_only_and_has_no_broker_write_actions(self):
        api=MarketDataResearchAPI(self.output,self.data);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_broker_shadow',names)
        self.assertFalse({'import_broker_snapshot','connect_broker','place_order','cancel_order','transfer_funds'} & names)
        before=self.files();reply=api.call('get_broker_shadow',{'snapshot_id':'','account_alias':'','paper_account':''});after=self.files()
        self.assertTrue(reply['ok']);self.assertEqual(reply['data']['status'],'NOT_CONFIGURED');self.assertEqual(before,after)

    def test_cli_import_requires_confirm_and_health_never_claims_connection(self):
        export=self.root/'broker.json';export.write_text(json.dumps(self.snapshot()))
        stream=StringIO()
        with redirect_stdout(stream):code=cli_main(['--output',str(self.output),'--import-json',str(export)])
        self.assertEqual(code,2);self.assertFalse((self.output/'_broker_shadow').exists())
        with redirect_stdout(StringIO()):code=cli_main(['--output',str(self.output),'--import-json',str(export),'--confirm'])
        self.assertEqual(code,0)
        health=SystemHealthService(self.output,self.data,now_fn=lambda:datetime(2026,9,15,2,0,tzinfo=timezone.utc)).build()
        self.assertEqual(health['components']['broker_shadow']['status'],'OK')
        self.assertFalse(health['components']['broker_shadow']['evidence']['real_broker_connected'])
        self.assertFalse(health['summary']['real_broker_connected'])

if __name__=='__main__':unittest.main()
