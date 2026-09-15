import json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime,timezone
from io import StringIO
from pathlib import Path

from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.agent.real_trade_readiness_cli import main as cli_main
from quantlab.agent.system_health import SystemHealthService
from quantlab.broker import (BrokerCapabilityRegistry,BrokerSnapshotError,BrokerSnapshotStore,
    JsonBrokerExportAdapter,RealTradeReadinessService,normalize_real_trade_policy)
from quantlab.experiments.campaign_state import write_checked


class RealTradeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.output.mkdir();self.data.mkdir()
        self.now=datetime(2026,9,15,2,0,tzinfo=timezone.utc)
    def files(self):return sorted(str(p.relative_to(self.output)) for p in self.output.rglob('*'))

    def policy(self,**updates):
        value={'policy_name':'reviewed-disabled','enabled':False,'broker_adapter_id':'json-export-v1','account_alias':'main',
            'paper_account':'main','manual_confirmation_required':True,'kill_switch_required':True,'shadow_required':True,
            'strict_pit_required':True,'system_health_required':True,'snapshot_max_age_seconds':300,
            'max_order_notional':10000.0,'max_single_position_ratio':0.1,'max_gross_exposure':0.5,
            'max_daily_loss':1000.0,'max_orders_per_day':10,'allowed_order_types':['LIMIT'],'source_ref':'fixture policy'}
        value.update(updates);return value

    def snapshot(self):
        return {'provider':'fixture-broker','account_alias':'main','captured_at':'2026-09-15T10:00:00+08:00','currency':'CNY',
            'cash':50000.0,'equity':60000.0,'positions':[{'symbol':'sh.600000','quantity':1000,
            'available_quantity':1000,'market_value':10000.0}],'source_ref':'fixture'}

    def paper(self):
        folder=self.output/'paper_dynamic';folder.mkdir(exist_ok=True)
        write_checked(folder/'main.json',{'format':'dynamic-paper-v1','revision':1,'watermark':'2026-09-15T10:00:00+08:00',
            'summary':{'ending_positions':{'sh.600000':1000}},'nav':[{'cash':50000.0,'equity':60000.0}]})

    def test_registry_and_json_adapter_are_offline_only(self):
        profile=BrokerCapabilityRegistry().get('json-export-v1')
        self.assertTrue(profile['implemented']);self.assertFalse(profile['live_channel']);self.assertFalse(profile['order_submit'])
        path=self.root/'broker.json';path.write_text(json.dumps(self.snapshot()))
        self.assertEqual(JsonBrokerExportAdapter(path).capabilities(),profile)

    def test_policy_is_safe_incomplete_and_cannot_enable_trading(self):
        example=json.loads((Path(__file__).parents[1]/'examples'/'real_trade_policy.example.json').read_text())
        value=normalize_real_trade_policy(example);self.assertFalse(value['complete']);self.assertIn('broker_adapter_id',value['missing_fields'])
        with self.assertRaises(BrokerSnapshotError) as enabled:normalize_real_trade_policy(self.policy(enabled=True))
        self.assertEqual(enabled.exception.code,'UNSUPPORTED_POLICY')
        with self.assertRaises(BrokerSnapshotError) as unsafe:normalize_real_trade_policy(self.policy(kill_switch_required=False))
        self.assertEqual(unsafe.exception.code,'UNSAFE_POLICY')

    def test_empty_workspace_is_fail_closed_and_side_effect_free(self):
        before=self.files();value=RealTradeReadinessService(self.output,self.data,now_fn=lambda:self.now).build();after=self.files()
        self.assertEqual(before,after);self.assertEqual(value['status'],'BLOCKED');self.assertFalse(value['ready_for_real_orders'])
        codes={row['code'] for row in value['blockers']}
        self.assertIn('NO_LIVE_BROKER_CHANNEL',codes);self.assertIn('REAL_TRADE_POLICY_MISSING',codes)
        self.assertIn('KILL_SWITCH_NOT_IMPLEMENTED',codes);self.assertIn('ORDER_GATEWAY_NOT_IMPLEMENTED',codes)

    def test_complete_policy_and_shadow_match_still_cannot_bypass_offline_adapter(self):
        BrokerSnapshotStore(self.output).import_snapshot(self.snapshot(),confirmed=True);self.paper()
        policy_path=self.root/'policy.json';policy_path.write_text(json.dumps(self.policy()))
        value=RealTradeReadinessService(self.output,self.data,policy_path,now_fn=lambda:self.now).build()
        self.assertEqual(value['shadow']['status'],'MATCH');self.assertFalse(value['ready_for_live_connection'])
        codes={row['code'] for row in value['blockers']}
        self.assertIn('NO_LIVE_BROKER_CHANNEL',codes);self.assertIn('BROKER_ADAPTER_OFFLINE_ONLY',codes)
        self.assertIn('ORDER_SUBMISSION_CAPABILITY_UNAVAILABLE',codes);self.assertNotIn('REAL_TRADE_POLICY_INCOMPLETE',codes)
        self.assertNotIn('SHADOW_RECONCILIATION_NOT_MATCHED',codes)

    def test_sensitive_policy_fields_are_rejected(self):
        raw=self.policy();raw['api_key']='secret'
        with self.assertRaises(BrokerSnapshotError) as error:normalize_real_trade_policy(raw)
        self.assertEqual(error.exception.code,'SENSITIVE_FIELD')

    def test_future_broker_snapshot_is_fail_closed(self):
        future=self.snapshot();future['captured_at']='2026-09-15T10:05:00+08:00'
        BrokerSnapshotStore(self.output).import_snapshot(future,confirmed=True);self.paper()
        policy_path=self.root/'policy.json';policy_path.write_text(json.dumps(self.policy()))
        value=RealTradeReadinessService(self.output,self.data,policy_path,now_fn=lambda:self.now).build()
        codes={row['code'] for row in value['blockers']};self.assertIn('BROKER_SNAPSHOT_IN_FUTURE',codes)
        self.assertIn('BROKER_AUTH_RUNTIME_NOT_IMPLEMENTED',codes);self.assertIn('ORDER_RISK_GATE_NOT_IMPLEMENTED',codes)

    def test_cli_and_mcp_are_read_only_and_have_no_order_tools(self):
        before=self.files();stream=StringIO()
        with redirect_stdout(stream):code=cli_main(['--output',str(self.output),'--data-root',str(self.data)])
        after=self.files();self.assertEqual(code,0);self.assertEqual(before,after)
        payload=json.loads(stream.getvalue());self.assertEqual(payload['data']['status'],'BLOCKED')
        api=MarketDataResearchAPI(self.output,self.data);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_real_trade_readiness',names)
        self.assertFalse({'set_real_trade_policy','connect_broker','place_order','cancel_order','transfer_funds'} & names)
        reply=api.call('get_real_trade_readiness',{});self.assertTrue(reply['ok']);self.assertFalse(reply['data']['ready_for_real_orders'])

    def test_system_health_surfaces_readiness_without_making_research_unhealthy(self):
        health=SystemHealthService(self.output,self.data,now_fn=lambda:self.now).build()
        component=health['components']['real_trade_readiness']
        self.assertEqual(component['status'],'NOT_CONFIGURED');self.assertEqual(component['evidence']['status'],'BLOCKED')
        self.assertFalse(health['summary']['real_broker_connected'])
        self.assertNotIn('real_trade_readiness', {row['component'] for row in health['blockers']})


if __name__=='__main__':unittest.main()
