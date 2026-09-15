import json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.agent.market_snapshot_provider_cli import main as provider_cli
from quantlab.trading.market_snapshot_provider import MarketSnapshotProviderReadiness,MarketSnapshotProviderRegistry
from quantlab.trading.playbook_forward import FORWARD_FRAMES,forward_frame_status


class MarketSnapshotProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data'
        self.output.mkdir();self.data.mkdir()

    def test_registry_is_explicitly_offline_and_fail_closed(self):
        registry=MarketSnapshotProviderRegistry();rows=registry.list()
        self.assertEqual([row['provider_id'] for row in rows],['manual-import-v1'])
        self.assertFalse(rows[0]['live_channel']);self.assertFalse(rows[0]['automatic_capture'])
        value=MarketSnapshotProviderReadiness(registry).build()
        self.assertEqual(value['status'],'BLOCKED');self.assertEqual(value['missing_live_frames'],['AUCTION','R1','R2','R3'])

    def test_forward_frames_include_midday_and_close_review_times(self):
        self.assertEqual(FORWARD_FRAMES,('PREP','AUCTION','R1','R2','R3'))
        r2=forward_frame_status(self.output,'2026-09-14','R2',lambda:datetime.fromisoformat('2026-09-14T11:29:59+08:00'))
        self.assertEqual(r2['forward_status'],'WAIT_DATA')
        r2_ready=forward_frame_status(self.output,'2026-09-14','R2',lambda:datetime.fromisoformat('2026-09-14T11:30:00+08:00'))
        self.assertTrue(r2_ready['can_freeze']);self.assertIn('11:30:00',r2_ready['data_ready_at'])
        r3=forward_frame_status(self.output,'2026-09-14','R3',lambda:datetime.fromisoformat('2026-09-14T15:00:00+08:00'))
        self.assertTrue(r3['can_freeze']);self.assertIn('15:00:00',r3['data_ready_at'])

    def test_cli_and_mcp_status_are_read_only(self):
        before=list(self.output.rglob('*'));stream=StringIO()
        with redirect_stdout(stream):code=provider_cli([])
        self.assertEqual(code,0);self.assertEqual(before,list(self.output.rglob('*')))
        self.assertEqual(json.loads(stream.getvalue())['data']['status'],'BLOCKED')
        api=MarketDataResearchAPI(self.output,self.data);names={row['name'] for row in api.schemas()}
        self.assertIn('get_market_snapshot_provider_status',names)
        self.assertFalse({'capture_market_snapshot','connect_market_provider','set_market_provider_credentials'} & names)
        reply=api.call('get_market_snapshot_provider_status',{});self.assertTrue(reply['ok']);self.assertEqual(reply['data']['status'],'BLOCKED')


    def test_system_health_surfaces_provider_gap_without_marking_research_broken(self):
        from datetime import timezone
        from quantlab.agent.system_health import SystemHealthService
        health=SystemHealthService(self.output,self.data,now_fn=lambda:datetime(2026,9,15,0,0,tzinfo=timezone.utc)).build()
        provider=health['components']['market_snapshot_provider']
        self.assertEqual(provider['status'],'NOT_CONFIGURED');self.assertFalse(provider['evidence']['live_provider_available'])
        self.assertNotEqual(health['summary']['research_readiness_status'],'BLOCKED')


if __name__=='__main__':unittest.main()
