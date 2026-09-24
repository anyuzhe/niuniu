import json,tempfile,unittest
from unittest import mock
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
        self.ready_catalog=self.catalog('READY');self.review_catalog=self.catalog('REVIEW_REQUIRED')

    def catalog(self,status):
        path=self.root/('data-catalog-'+status+'.md')
        path.write_text('# DATA → CODE 数据清单\n\n## 3. 可供 CODE 使用的数据（READY）\n\n'
            '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |\n'
            '|---|---|---|---|---|---|---|---|\n'
            f'| `market_snapshot` | API | snapshot | `Provider` | call | research_only | `{status}` | gated |\n',encoding='utf-8')
        return path

    def test_registry_exposes_public_web_consensus_but_keeps_manual_offline(self):
        registry=MarketSnapshotProviderRegistry(data_catalog_path=self.ready_catalog);rows=registry.list()
        self.assertEqual([row['provider_id'] for row in rows],['manual-import-v1','public-web-consensus-v1'])
        manual=registry.get('manual-import-v1');live=registry.get('public-web-consensus-v1')
        self.assertFalse(manual['live_channel']);self.assertFalse(manual['automatic_capture'])
        self.assertTrue(live['live_channel']);self.assertTrue(live['automatic_capture']);self.assertFalse(live['strict_pit_source_verified'])
        value=MarketSnapshotProviderReadiness(registry).build()
        self.assertEqual(value['status'],'READY');self.assertEqual(value['missing_live_frames'],[])
        self.assertEqual(value['data_catalog_status'],'READY')
        blocked=MarketSnapshotProviderReadiness(
            MarketSnapshotProviderRegistry(data_catalog_path=self.review_catalog)).build()
        self.assertEqual(blocked['status'],'BLOCKED');self.assertFalse(blocked['live_provider_available'])
        self.assertEqual(blocked['data_catalog_status'],'REVIEW_REQUIRED');self.assertFalse(blocked['automatic_capture_available'])

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
        with redirect_stdout(stream):code=provider_cli(['--data-catalog-path',str(self.ready_catalog)])
        self.assertEqual(code,0);self.assertEqual(before,list(self.output.rglob('*')))
        self.assertEqual(json.loads(stream.getvalue())['data']['status'],'READY')
        api=MarketDataResearchAPI(self.output,self.data);names={row['name'] for row in api.schemas()}
        self.assertIn('get_market_snapshot_provider_status',names)
        self.assertFalse({'capture_market_snapshot','connect_market_provider','set_market_provider_credentials'} & names)
        # The agent reads the repository catalog; pin it so the test does not follow DATA's live status.
        with mock.patch('quantlab.data.dataset_catalog.default_data_catalog_path',return_value=self.review_catalog):
            reply=api.call('get_market_snapshot_provider_status',{})
        self.assertTrue(reply['ok'])
        self.assertEqual(reply['data']['status'],'BLOCKED');self.assertFalse(reply['data']['live_provider_available'])


    def test_system_health_surfaces_provider_gap_without_marking_research_broken(self):
        from datetime import timezone
        from quantlab.agent.system_health import SystemHealthService
        with mock.patch('quantlab.data.dataset_catalog.default_data_catalog_path',return_value=self.review_catalog):
            health=SystemHealthService(self.output,self.data,now_fn=lambda:datetime(2026,9,15,0,0,tzinfo=timezone.utc)).build()
        provider=health['components']['market_snapshot_provider']
        self.assertEqual(provider['status'],'NOT_CONFIGURED');self.assertFalse(provider['evidence']['live_provider_available'])
        self.assertEqual(provider['evidence']['data_catalog_status'],'REVIEW_REQUIRED')
        self.assertNotEqual(health['summary']['research_readiness_status'],'BLOCKED')


if __name__=='__main__':unittest.main()
