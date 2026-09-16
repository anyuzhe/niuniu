import contextlib
import io
import json
import hashlib
import tempfile
import unittest
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import polars as pl

from quantlab.data.daily_market_archive import DailyMarketArchive,EXPECTED_FIELDS
from quantlab.data.pit_universe import archive_pit_universe
from quantlab.trading.daily_orchestrator import DailyOrchestratorError,DailyPlaybookOrchestrator
from quantlab.trading.market_snapshot import MarketSnapshotStore
from quantlab.trading.playbook_store import PlaybookError,PlaybookStore
from quantlab.agent.playbook_tools import PlaybookResearchAPI
from quantlab.agent.daily_orchestrator_cli import main as orchestrator_cli


class Response:
    error_code='0';error_msg='success'
    def __init__(self,rows,fields=EXPECTED_FIELDS):self.rows=rows;self.fields=list(fields);self.index=-1
    def next(self):self.index+=1;return self.index<len(self.rows)
    def get_row_data(self):return [self.rows[self.index][k] for k in self.fields]


class SDK:
    __version__='0.9.3'
    def __init__(self,rows):self.rows=rows;self.calls=0
    def login(self):return Response([{'ok':'1'}],['ok'])
    def logout(self):pass
    def query_daily_history_k_AStock(self,date=''):self.calls+=1;return Response(self.rows)


def daily_row(day,code,close,preclose):
    row={key:'1' for key in EXPECTED_FIELDS}
    row.update(date=day,code=code,open=str(close),high=str(close),low=str(close),close=str(close),
        preclose=str(preclose),volume='1000',amount='10000',adjustflag='3',turn='2',tradestatus='1',
        pctChg=str((close/preclose-1)*100),peTTM='12',pbMRQ='1',psTTM='2',pcfNcfTTM='3',isST='0')
    return row


class DailyOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'artifacts';self.data=self.root/'data'
        self.output.mkdir();directory=self.data/'lake/bronze/provider=baostock/stock_kline_daily';directory.mkdir(parents=True)
        pl.DataFrame([
            {'date':date(2026,9,9),'code':'sh.600001','open':10.0,'high':10.0,'low':10.0,'close':10.0,'volume':1000.0,'amount':10000.0,'adjustflag':'3'},
            {'date':date(2026,9,10),'code':'sh.600001','open':11.0,'high':11.0,'low':11.0,'close':11.0,'volume':1000.0,'amount':11000.0,'adjustflag':'3'},
        ]).write_parquet(directory/'sh_600001.parquet')
        self.playbooks=PlaybookStore(self.output,now_fn=lambda:datetime.fromisoformat('2026-09-13T18:00:00+08:00'))
        source=self.playbooks.create_source(str(uuid4()),{'expert_key':'pilot','title':'前瞻来源','source_type':'PUBLIC_POST',
            'locator':'local:pilot','available_at':'2026-09-13T12:00:00+08:00','content_hash':'a'*64,
            'archive_ref':'','completeness':'VERIFIED','notes':''})
        self.definition=self.playbooks.create_definition(str(uuid4()),{'playbook_key':'daily-pilot','name':'Daily Pilot',
            'version':'draft-1','state':'DRAFT','source_ids':[source['source_id']],'market_context':{},
            'eligibility':{'target':'2_to_3'},'selection':{'rule':'active'},'veto':{},'entry':{},'confirm':{},
            'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        self.market_rows=[daily_row('2026-09-11','sh.600001',12.1,11.0)]

    def service(self,now):return DailyPlaybookOrchestrator(self.output,self.data,now_fn=lambda:now)

    def init(self,now,allow=False,bridge=False,market=False):
        return self.service(now).create_plan('2026-09-14','2026-09-11',self.definition['definition_id'],
            target_streak=2,allow_daily_market_capture=allow,allow_market_snapshot_capture=market,
            bridge_to_trading_desk=bridge)

    def accept_daily(self):
        return DailyMarketArchive(self.output,now_fn=lambda:datetime.fromisoformat('2026-09-13T18:31:00+08:00')).capture(
            '2026-09-11',sdk=SDK(self.market_rows))

    def prep_frozen(self):
        self.accept_daily();now=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(now)
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['prep']['status'],'FROZEN');return state

    def auction_snapshot(self,as_of='2026-09-14T09:25:30+08:00',captured='2026-09-14T09:26:00+08:00'):
        content={'trading_day':'2026-09-14','frame':'AUCTION','as_of':as_of,'provider':'fixture',
            'provider_ref':'fixture:auction','source_hash':'b'*64,'completeness':'FULL','instruments':[
                {'symbol':'sh.600001','previous_close':12.1,'auction_price':12.2,'tradable':True,
                    'execution_profile':'STANDARD_ACCESS','metrics':{}}], 'market_metrics':{},'notes':''}
        return MarketSnapshotStore(self.output,now_fn=lambda:datetime.fromisoformat(captured)).create(str(uuid4()),content)

    def r1_snapshot(self,as_of='2026-09-14T09:35:30+08:00',captured='2026-09-14T09:36:00+08:00'):
        content={'trading_day':'2026-09-14','frame':'R1','as_of':as_of,'provider':'fixture',
            'provider_ref':'fixture:r1','source_hash':'c'*64,'completeness':'FULL','instruments':[
                {'symbol':'sh.600001','previous_close':12.1,'open':12.2,'high':12.5,'low':12.1,'last':12.5,
                    'volume':1000,'amount':12400,'tradable':True,'execution_profile':'STANDARD_ACCESS','metrics':{}}],
            'market_metrics':{},'notes':''}
        return MarketSnapshotStore(self.output,now_fn=lambda:datetime.fromisoformat(captured)).create(str(uuid4()),content)

    def later_snapshot(self,frame,as_of,captured,last=12.6,source='d'):
        content={'trading_day':'2026-09-14','frame':frame,'as_of':as_of,'provider':'fixture',
            'provider_ref':'fixture:'+frame.lower(),'source_hash':source*64,'completeness':'FULL','instruments':[
                {'symbol':'sh.600001','previous_close':12.1,'open':12.2,'high':max(last,12.5),'low':12.1,'last':last,
                    'volume':2000,'amount':25000,'tradable':True,'execution_profile':'STANDARD_ACCESS','metrics':{}}],
            'market_metrics':{},'notes':''}
        return MarketSnapshotStore(self.output,now_fn=lambda:datetime.fromisoformat(captured)).create(str(uuid4()),content)

    def test_plan_binds_only_verified_exact_trading_day_universe_snapshot(self):
        document=self.root/'universe.json';document.write_text('{"symbols":["sh.600001"]}')
        plan={'format':'niuniu-pit-universe-plan-v1','effective_session':'2026-09-14',
            'cutoff_at':'2026-09-14T09:15:00+08:00','scope':{'market':'CN_A_SHARE','exchanges':['SSE'],
                'instrument_types':['A_SHARE'],'completeness':'FULL_OFFICIAL_LIST'},
            'sources':[{'source_id':'sse-list','exchange':'SSE','url':'https://www.sse.com.cn/test/list',
                'published_at':'2026-09-13T14:00:00+08:00','available_at':'2026-09-13T15:00:00+08:00',
                'document':str(document),'sha256':hashlib.sha256(document.read_bytes()).hexdigest()}],
            'members':[{'symbol':'sh.600001','source_id':'sse-list'}]}
        snapshot=archive_pit_universe(self.data,plan,confirm_publication_times=True,
            confirm_semantic_mapping=True,confirm_complete_official_universe=True,
            now_fn=lambda:datetime.fromisoformat('2026-09-13T16:00:00+08:00'))['universe_snapshot']
        now=datetime.fromisoformat('2026-09-13T18:00:00+08:00')
        state=self.service(now).create_plan('2026-09-14','2026-09-11',self.definition['definition_id'],
            target_streak=2,universe_snapshot=snapshot)
        self.assertEqual(state['universe_snapshot'],snapshot)
        with self.assertRaises(DailyOrchestratorError) as ctx:
            self.service(now).create_plan('2026-09-15','2026-09-14',self.definition['definition_id'],
                target_streak=2,universe_snapshot=snapshot)
        self.assertEqual(ctx.exception.code,'PIT_UNIVERSE_INVALID')

    def test_plan_defaults_to_no_network_and_waits_for_daily_market(self):
        now=datetime.fromisoformat('2026-09-13T19:00:00+08:00');state=self.init(now,allow=False)
        with patch.object(DailyMarketArchive,'capture',side_effect=AssertionError('must not network')):
            state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['status'],'WAIT_DAILY_MARKET');self.assertEqual(state['daily_market']['attempts'],0)

    def test_authorized_capture_waits_until_1830_then_freezes_prep_once(self):
        early=datetime.fromisoformat('2026-09-11T18:00:00+08:00');self.init(early,allow=True)
        sdk=SDK(self.market_rows);state=self.service(early).tick('2026-09-14',now=early,daily_market_sdk=sdk)
        self.assertEqual(state['status'],'WAIT_DAILY_MARKET_READY');self.assertEqual(sdk.calls,0)
        ready=datetime.fromisoformat('2026-09-13T18:31:00+08:00')
        state=self.service(ready).tick('2026-09-14',now=ready,daily_market_sdk=sdk)
        self.assertEqual(sdk.calls,1);self.assertEqual(state['prep']['status'],'FROZEN')
        before=PlaybookStore(self.output).overview();state2=self.service(ready).tick('2026-09-14',now=ready,daily_market_sdk=sdk)
        after=PlaybookStore(self.output).overview();self.assertEqual(before,after);self.assertEqual(sdk.calls,1)
        self.assertEqual(state2['status'],'WAIT_AUCTION_DATA_READY')

    def test_empty_prep_candidate_set_completes_no_trade_without_live_capture(self):
        self.accept_daily();now=datetime.fromisoformat('2026-09-13T18:31:00+08:00')
        self.service(now).create_plan('2026-09-14','2026-09-11',self.definition['definition_id'],
            target_streak=3,allow_market_snapshot_capture=True,bridge_to_trading_desk=True)
        with patch('quantlab.trading.public_web_market_snapshot.PublicWebConsensusProvider.capture',
                side_effect=AssertionError('empty PREP must not request live quotes')):
            state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['status'],'COMPLETE_NO_TRADE');self.assertEqual(state['prep']['status'],'FROZEN')
        self.assertEqual(state['prep']['scan']['candidate_count'],0)
        self.assertTrue(state['prep']['decision_bridge']['no_trade']);self.assertEqual(state['prep']['decision_bridge']['decisions'],[])
        self.assertFalse((self.output/'_trading/decision_ledger.sqlite3').exists())
        for name in ('auction','r1','r2','r3'):
            self.assertEqual(state[name]['status'],'SKIPPED_NO_TRADE')
            self.assertEqual(state[name]['reason'],'EMPTY_PREP_CANDIDATE_SET')
        overview=PlaybookStore(self.output).overview();bridges=len(list((self.output/'_trading/playbook_bridge').glob('*.json')))
        again=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(again,state);self.assertEqual(PlaybookStore(self.output).overview(),overview)
        self.assertEqual(len(list((self.output/'_trading/playbook_bridge').glob('*.json'))),bridges)

    def test_capture_failure_uses_cooldown_before_retry(self):
        class FailingSDK(SDK):
            def login(self):
                response=Response([{'ok':'1'}],['ok']);response.error_code='9';response.error_msg='offline';return response
        start=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(start,allow=True)
        failed=FailingSDK(self.market_rows);state=self.service(start).tick('2026-09-14',now=start,daily_market_sdk=failed)
        self.assertEqual(state['status'],'DAILY_MARKET_CAPTURE_FAILED');self.assertEqual(state['daily_market']['attempts'],1)
        good=SDK(self.market_rows);minute=datetime.fromisoformat('2026-09-13T18:32:00+08:00')
        state=self.service(minute).tick('2026-09-14',now=minute,daily_market_sdk=good)
        self.assertEqual(state['status'],'WAIT_DAILY_MARKET_COOLDOWN');self.assertEqual(good.calls,0)
        retry=datetime.fromisoformat('2026-09-13T18:47:00+08:00')
        state=self.service(retry).tick('2026-09-14',now=retry,daily_market_sdk=good)
        self.assertEqual(good.calls,1);self.assertEqual(state['daily_market']['attempts'],2);self.assertEqual(state['prep']['status'],'FROZEN')

    def test_pending_daily_revision_blocks_but_can_resume_after_host_accepts(self):
        first=self.accept_daily();changed=[daily_row('2026-09-11','sh.600001',12.2,11.0)]
        archive=DailyMarketArchive(self.output,now_fn=lambda:datetime.fromisoformat('2026-09-13T18:32:00+08:00'))
        revision=archive.capture('2026-09-11',sdk=SDK(changed));self.assertTrue(revision['revision_detected'])
        now=datetime.fromisoformat('2026-09-13T18:33:00+08:00');self.init(now)
        blocked=self.service(now).tick('2026-09-14',now=now);self.assertEqual(blocked['status'],'BLOCKED_REVISION_REVIEW')
        archive.accept_revision('2026-09-11',revision['snapshot_id'],confirmed=True)
        resumed=self.service(now).tick('2026-09-14',now=now)
        self.assertNotEqual(resumed['status'],'BLOCKED_REVISION_REVIEW')
        self.assertEqual(resumed['daily_market']['snapshot_id'],revision['snapshot_id'])
        self.assertNotEqual(first['snapshot_id'],revision['snapshot_id'])

    def test_missed_prep_cannot_be_backfilled(self):
        self.accept_daily();now=datetime.fromisoformat('2026-09-14T09:16:00+08:00');self.init(now)
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['status'],'BLOCKED_PREP_MISSED');self.assertEqual(state['prep']['status'],'MISSED')
        self.assertEqual(PlaybookStore(self.output).overview()['selections'],0)

    def test_auction_waits_for_live_snapshot_and_ignores_backfill(self):
        self.prep_frozen()
        # Same auction data recorded too late is BACKFILL and must not be consumed.
        backfill=self.auction_snapshot(captured='2026-09-14T09:36:00+08:00')
        self.assertEqual(backfill['capture_status'],'BACKFILL')
        now=datetime.fromisoformat('2026-09-14T09:26:00+08:00')
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['status'],'WAIT_AUCTION_MARKET_SNAPSHOT');self.assertEqual(state['auction']['status'],'PENDING')
        late=datetime.fromisoformat('2026-09-14T09:31:00+08:00');state=self.service(late).tick('2026-09-14',now=late)
        self.assertEqual(state['auction']['status'],'MISSED');self.assertEqual(state['status'],'WAIT_R1_DATA_READY')

    def test_prep_interrupted_after_reservation_resumes_without_duplicate_snapshot(self):
        self.accept_daily();now=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(now)
        with patch('quantlab.trading.daily_orchestrator.freeze_forward_snapshot',
                side_effect=PlaybookError('FIXTURE','simulated lost freeze acknowledgement')):
            blocked=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(blocked['status'],'BLOCKED_PREP_FREEZE');self.assertEqual(blocked['prep']['status'],'RESERVED')
        self.assertEqual(MarketSnapshotStore(self.output).overview()['snapshots'],1)
        resumed=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(resumed['prep']['status'],'FROZEN');self.assertEqual(MarketSnapshotStore(self.output).overview()['snapshots'],1)
        overview=PlaybookStore(self.output).overview();self.assertEqual(overview['cases'],1);self.assertEqual(overview['selections'],1)

    def test_live_auction_freezes_idempotently(self):
        self.prep_frozen();self.auction_snapshot();now=datetime.fromisoformat('2026-09-14T09:26:30+08:00')
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['auction']['status'],'FROZEN');self.assertEqual(state['auction']['selected_symbols'],[])
        prediction=state['auction']['prediction_id'];again=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(again['auction']['prediction_id'],prediction);self.assertEqual(again['status'],'WAIT_R1_DATA_READY')

    def test_explicit_trading_desk_bridge_keeps_partial_r1_as_no_trade(self):
        self.accept_daily();prep_time=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(prep_time,bridge=True)
        state=self.service(prep_time).tick('2026-09-14',now=prep_time);self.assertEqual(state['prep']['status'],'FROZEN')
        self.auction_snapshot();self.r1_snapshot();now=datetime.fromisoformat('2026-09-14T09:36:30+08:00')
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['r1']['status'],'FROZEN');self.assertTrue(state['r1']['decision_bridge']['no_trade'])
        self.assertEqual(state['r1']['decision_bridge']['decisions'],[])
        self.assertFalse((self.output/'_trading/decision_ledger.sqlite3').exists())

    def test_r1_can_run_after_auction_prediction_missed_if_live_auction_fact_exists(self):
        self.prep_frozen();self.auction_snapshot();self.r1_snapshot();now=datetime.fromisoformat('2026-09-14T09:36:30+08:00')
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['auction']['status'],'MISSED')
        self.assertEqual(state['r1']['status'],'FROZEN')
        # Current automatic PREP remains PARTIAL without certified PIT universe/official rules, so R1 must fail closed to NO_TRADE.
        self.assertEqual(state['r1']['selected_symbols'],[])
        self.assertEqual(state['status'],'WAIT_R2_DATA_READY')

    def test_r1_without_first_window_snapshot_is_missed_not_backfilled(self):
        self.prep_frozen();self.auction_snapshot();now=datetime.fromisoformat('2026-09-14T09:41:00+08:00')
        state=self.service(now).tick('2026-09-14',now=now)
        self.assertEqual(state['auction']['status'],'MISSED');self.assertEqual(state['r1']['status'],'MISSED')
        self.assertEqual(state['status'],'WAIT_R2_DATA_READY')

    def test_r2_and_r3_freeze_at_midday_and_close_then_complete(self):
        self.prep_frozen();self.auction_snapshot();self.r1_snapshot()
        morning=datetime.fromisoformat('2026-09-14T09:36:30+08:00');state=self.service(morning).tick('2026-09-14',now=morning)
        self.assertEqual(state['r1']['status'],'FROZEN');self.assertEqual(state['status'],'WAIT_R2_DATA_READY')
        self.later_snapshot('R2','2026-09-14T11:30:30+08:00','2026-09-14T11:31:00+08:00',12.7,'d')
        midday=datetime.fromisoformat('2026-09-14T11:31:30+08:00');state=self.service(midday).tick('2026-09-14',now=midday)
        self.assertEqual(state['r2']['status'],'FROZEN');self.assertEqual(state['status'],'WAIT_R3_DATA_READY')
        self.later_snapshot('R3','2026-09-14T15:00:30+08:00','2026-09-14T15:01:00+08:00',12.8,'e')
        close=datetime.fromisoformat('2026-09-14T15:01:30+08:00');state=self.service(close).tick('2026-09-14',now=close)
        self.assertEqual(state['r3']['status'],'FROZEN');self.assertEqual(state['status'],'COMPLETE_WITH_MISSED')
        self.assertEqual(state['supported_frames'],['PREP','AUCTION','R1','R2','R3'])

    def test_explicit_public_web_capture_populates_auction_and_r1_through_shared_store(self):
        self.accept_daily();prep=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(prep,market=True)
        state=self.service(prep).tick('2026-09-14',now=prep);self.assertEqual(state['prep']['status'],'FROZEN')
        calls=[]
        def capture(_provider,day,frame,symbols):
            calls.append((day,frame,tuple(symbols)))
            base={'trading_day':day,'frame':frame,'provider':'public-web-consensus-v1','provider_ref':'fixture:web',
                'source_hash':'f'*64,'completeness':'FULL','strict_pit_source_verified':False,'market_metrics':{},'notes':'fixture'}
            if frame=='AUCTION':
                return {**base,'as_of':'2026-09-14T09:25:30+08:00','instruments':[{'symbol':'sh.600001','name':'fixture','previous_close':12.1,
                    'auction_price':12.2,'tradable':True,'execution_profile':'STANDARD_ACCESS','metrics':{}}]}
            return {**base,'as_of':'2026-09-14T09:35:30+08:00','instruments':[{'symbol':'sh.600001','name':'fixture','previous_close':12.1,
                'open':12.2,'high':12.5,'low':12.1,'last':12.5,'volume':1000,'amount':12400,
                'tradable':True,'execution_profile':'STANDARD_ACCESS','metrics':{}}]}
        with patch('quantlab.trading.public_web_market_snapshot.PublicWebConsensusProvider.capture',new=capture):
            auction=self.service(datetime.fromisoformat('2026-09-14T09:26:00+08:00')).tick('2026-09-14',now=datetime.fromisoformat('2026-09-14T09:26:00+08:00'))
            self.assertEqual(auction['auction']['status'],'FROZEN')
            r1=self.service(datetime.fromisoformat('2026-09-14T09:36:00+08:00')).tick('2026-09-14',now=datetime.fromisoformat('2026-09-14T09:36:00+08:00'))
        self.assertEqual(r1['r1']['status'],'FROZEN');self.assertEqual([c[1] for c in calls],['AUCTION','R1'])
        snapshots=MarketSnapshotStore(self.output).list(provider='public-web-consensus-v1',limit=10)['records']
        self.assertEqual(len(snapshots),2);self.assertTrue(all(not row['strict_pit_eligible'] for row in snapshots))

    def test_public_web_capture_uses_cooldown_after_failure(self):
        self.accept_daily();prep=datetime.fromisoformat('2026-09-13T18:31:00+08:00');self.init(prep,market=True);self.service(prep).tick('2026-09-14',now=prep)
        with patch('quantlab.trading.public_web_market_snapshot.PublicWebConsensusProvider.capture',side_effect=OSError('fixture offline')) as capture:
            first=self.service(datetime.fromisoformat('2026-09-14T09:26:00+08:00')).tick('2026-09-14',now=datetime.fromisoformat('2026-09-14T09:26:00+08:00'))
            second=self.service(datetime.fromisoformat('2026-09-14T09:26:10+08:00')).tick('2026-09-14',now=datetime.fromisoformat('2026-09-14T09:26:10+08:00'))
            third=self.service(datetime.fromisoformat('2026-09-14T09:26:31+08:00')).tick('2026-09-14',now=datetime.fromisoformat('2026-09-14T09:26:31+08:00'))
        self.assertEqual(capture.call_count,2);self.assertEqual(first['auction']['market_capture']['attempts'],1)
        self.assertEqual(second['auction']['market_capture']['attempts'],1);self.assertEqual(third['auction']['market_capture']['attempts'],2)
        self.assertIn('fixture offline',third['auction']['market_capture']['last_error'])

    def test_cli_init_status_and_model_has_no_orchestrator_write_tool(self):
        out=io.StringIO()
        args=['--output',str(self.output),'--data-root',str(self.data),'--trading-day','2026-09-14',
            '--init','--as-of-session','2026-09-11','--definition-id',self.definition['definition_id'],'--target-streak','2']
        with contextlib.redirect_stdout(out):code=orchestrator_cli(args)
        self.assertEqual(code,0);self.assertTrue(json.loads(out.getvalue())['ok'])
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=orchestrator_cli([
            '--output',str(self.output),'--data-root',str(self.data),'--trading-day','2026-09-14','--status'])
        value=json.loads(out.getvalue());self.assertEqual(code,0);self.assertEqual(value['data']['status'],'CREATED')
        names={item['name'] for item in PlaybookResearchAPI(self.output,self.data).schemas()}
        self.assertFalse(any('orchestrator' in name or 'daily_market_capture' in name for name in names))

    def test_state_corruption_and_plan_conflict_are_rejected(self):
        now=datetime.fromisoformat('2026-09-13T18:00:00+08:00');state=self.init(now)
        with self.assertRaises(DailyOrchestratorError) as conflict:
            self.service(now).create_plan('2026-09-14','2026-09-11',self.definition['definition_id'],target_streak=3)
        self.assertEqual(conflict.exception.code,'PLAN_CONFLICT')
        path=self.output/'_daily_orchestrator/2026-09-14.json';value=json.loads(path.read_text());value['status']='CORRUPT';path.write_text(json.dumps(value))
        with self.assertRaises(DailyOrchestratorError) as corrupt:self.service(now).get('2026-09-14')
        self.assertEqual(corrupt.exception.code,'CORRUPT_STATE')


if __name__=='__main__':unittest.main()
