import json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from quantlab.agent.market_snapshot_live_cli import main as live_cli
from quantlab.trading.market_snapshot import MarketSnapshotStore
from quantlab.trading.public_web_market_snapshot import PublicWebConsensusProvider

TENCENT='v_sh600000="1~浦发银行~600000~9.22~9.40~9.39~676431~263092~413339~9.22~1840~9.21~3828~9.20~10067~9.19~1090~9.18~5581~9.23~1494~9.24~425~9.25~1022~9.26~823~9.27~1823~~20260915093030~-0.18~-1.91~9.42~9.16~9.22/676431/624141587~676431~62414";'
SINA='var hq_str_sh600000="浦发银行,9.390,9.400,9.220,9.420,9.160,9.220,9.230,67643079,624141587.000,184000,9.220,382800,9.210,1006700,9.200,109000,9.190,558140,9.180,149400,9.230,42500,9.240,102200,9.250,82300,9.260,182300,9.270,2026-09-15,09:30:00,00,";'
EM=json.dumps({'data':{'f43':922,'f44':942,'f45':916,'f46':939,'f47':676431,'f48':624141587.0,
    'f57':'600000','f58':'浦发银行','f60':940,'f86':1789435830}},ensure_ascii=False)


def fixture_http(url,encoding,headers):
    if 'qt.gtimg.cn' in url:return TENCENT,'a'*64
    if 'hq.sinajs.cn' in url:return SINA,'b'*64
    if 'eastmoney.com' in url:return EM,'c'*64
    raise AssertionError(url)

class PublicWebMarketSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'artifacts';self.output.mkdir()

    def test_three_source_consensus_prefers_tencent_and_keeps_public_source_non_strict(self):
        value=PublicWebConsensusProvider(http_get=fixture_http).capture('2026-09-15','R1',['sh.600000'])
        self.assertEqual(value['completeness'],'FULL');self.assertFalse(value['strict_pit_source_verified'])
        row=value['instruments'][0]
        self.assertEqual(row['last'],9.22);self.assertEqual(row['previous_close'],9.4)
        self.assertEqual(row['execution_profile'],'STANDARD_ACCESS')
        self.assertEqual(row['metrics']['agreement_sources'],['tencent','eastmoney','sina'])
        self.assertEqual(value['market_metrics']['consensus_symbols'],1)

    def test_one_outlier_is_ignored_but_execution_access_becomes_unknown_without_two_sided_sources(self):
        bad_sina=SINA.replace(',9.220,9.420,9.160,',',9.000,9.420,9.160,',1)
        def http(url,encoding,headers):
            if 'hq.sinajs.cn' in url:return bad_sina,'d'*64
            return fixture_http(url,encoding,headers)
        value=PublicWebConsensusProvider(http_get=http).capture('2026-09-15','R1',['sh.600000'])
        row=value['instruments'][0]
        self.assertEqual(row['last'],9.22);self.assertEqual(row['metrics']['agreement_sources'],['tencent','eastmoney'])
        self.assertEqual(row['execution_profile'],'UNKNOWN')

    def test_only_one_source_fails_closed(self):
        def http(url,encoding,headers):
            if 'qt.gtimg.cn' in url:return TENCENT,'a'*64
            raise OSError('offline')
        with self.assertRaisesRegex(ValueError,'两源一致'):
            PublicWebConsensusProvider(http_get=http).capture('2026-09-15','R1',['sh.600000'])

    def test_wrong_day_source_is_rejected_before_consensus(self):
        stale=SINA.replace('2026-09-15,09:30:00','2026-09-14,09:30:00')
        def http(url,encoding,headers):
            if 'hq.sinajs.cn' in url:return stale,'e'*64
            return fixture_http(url,encoding,headers)
        value=PublicWebConsensusProvider(http_get=http,now_fn=lambda:datetime.fromisoformat('2026-09-15T09:31:00+08:00')).capture('2026-09-15','R1',['sh.600000'])
        row=value['instruments'][0]
        self.assertEqual(row['metrics']['agreement_sources'],['tencent','eastmoney'])
        self.assertEqual(value['market_metrics']['source_health']['sina']['responses'],1)

    def test_future_source_times_fail_closed_when_only_one_valid_source_remains(self):
        future_t=TENCENT.replace('20260915093030','20260915100000')
        future_s=SINA.replace('09:30:00','10:00:00')
        def http(url,encoding,headers):
            if 'qt.gtimg.cn' in url:return future_t,'f'*64
            if 'hq.sinajs.cn' in url:return future_s,'1'*64
            return EM,'c'*64
        with self.assertRaisesRegex(ValueError,'两源一致'):
            PublicWebConsensusProvider(http_get=http,now_fn=lambda:datetime.fromisoformat('2026-09-15T09:31:00+08:00')).capture('2026-09-15','R1',['sh.600000'])

    def test_live_full_public_snapshot_never_becomes_strict_pit(self):
        content=PublicWebConsensusProvider(http_get=fixture_http,now_fn=lambda:datetime.fromisoformat('2026-09-15T09:31:00+08:00')).capture('2026-09-15','R1',['sh.600000'])
        content['trading_day']='2026-09-14';content['as_of']='2026-09-14T09:35:30+08:00'
        store=MarketSnapshotStore(self.output,now_fn=lambda:datetime.fromisoformat('2026-09-14T09:36:00+08:00'))
        saved=store.create(str(uuid4()),content)
        self.assertEqual(saved['capture_status'],'LIVE_NEAR_REALTIME')
        self.assertEqual(saved['completeness'],'FULL');self.assertFalse(saved['strict_pit_eligible'])

    def test_host_cli_requires_explicit_network_confirmation(self):
        stream=StringIO()
        with patch('quantlab.agent.market_snapshot_live_cli.PublicWebConsensusProvider.capture',side_effect=AssertionError('must not network')):
            with redirect_stdout(stream):code=live_cli(['--output',str(self.output),'--trading-day','2026-09-15','--frame','R1','--symbols','sh.600000'])
        self.assertEqual(code,2);self.assertFalse(json.loads(stream.getvalue())['ok'])
        self.assertFalse((self.output/'_trading/market_snapshots.sqlite3').exists())

    def test_host_cli_confirmed_capture_can_freeze_through_market_snapshot_store(self):
        content=PublicWebConsensusProvider(http_get=fixture_http,now_fn=lambda:datetime.fromisoformat('2026-09-15T09:31:00+08:00')).capture('2026-09-15','R1',['sh.600000'])
        stream=StringIO()
        with patch('quantlab.agent.market_snapshot_live_cli.PublicWebConsensusProvider.capture',return_value=content):
            with redirect_stdout(stream):code=live_cli(['--output',str(self.output),'--trading-day','2026-09-15','--frame','R1','--symbols','sh.600000','--confirm-network','--store'])
        result=json.loads(stream.getvalue());self.assertEqual(code,0);self.assertTrue(result['ok'])
        self.assertEqual(result['data']['provider'],'public-web-consensus-v1');self.assertFalse(result['data']['strict_pit_eligible'])
        self.assertEqual(MarketSnapshotStore(self.output).overview()['snapshots'],1)


if __name__=='__main__':unittest.main()
