import tempfile
import unittest
from datetime import date,datetime,time,timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import polars as pl
from quantlab.execution.rules import MarketRules
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.qimo_paper import QimoPaperRunner,QimoMarketData,CONFIG,POLICY,TZ
from quantlab.trading.qimo_rules import portfolio_targets,assess


def dt(value):return datetime.fromisoformat(value).replace(tzinfo=TZ)


def bars(day,symbol,price=10.):
    stamps=[datetime.combine(day,t,TZ)+timedelta(minutes=i*5) for t in (time(9,30),time(13)) for i in range(1,25)]
    return pl.DataFrame([{'symbol':symbol,'datetime':s,'available_at':s,'timeframe':'5m',
        'open':price,'high':price+.1,'low':price-.1,'close':price,'volume':100000.,'turnover':1000000.} for s in stamps])


class Market:
    def __init__(self):self.block_buy=set();self.block_sell=set();self.missing=False;self.suspended=set()
    def sessions(self,now):return [date(2026,9,d) for d in (14,15,16,17,18,21)]
    def execution_rules(self,day,symbol):
        if self.missing:raise ValueError('OFFICIAL_EXECUTION_RULES_MISSING')
        return MarketRules([{'symbol':symbol,'effective_at':datetime.combine(day,time(),TZ),
            'available_at':datetime.combine(day,time(),TZ),'expires_at':datetime.combine(day,time(23,59),TZ),
            'suspended':symbol in self.suspended,'st':False,'limit_up':10. if symbol in self.block_buy else 11.,
            'limit_down':10. if symbol in self.block_sell else 9.,'commission_bps':3.,'minimum_commission':5.,
            'sell_tax_bps':5.,'transfer_bps':.1,'source':'synthetic-test-only'}])
    def bars(self,day,symbol,now):return bars(day,symbol)
    def check_corporate_action(self,*args):pass
    def prep_evidence(self,*args):return None,None,['pit_universe_not_certified']


class QimoPaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'out';self.data=self.root/'data'
        self.output.mkdir();self.data.mkdir();self.market=Market();self.now=dt('2026-09-15T09:36:00')
        self.runner=QimoPaperRunner(self.output,self.data,now_fn=lambda:self.now,market=self.market)
        store=PlaybookStore(self.output)
        self.evidence=store.create_source(str(uuid4()),{'expert_key':'qimofenshu','title':'fixture',
            'source_type':'PUBLIC_POST','locator':'local:synthetic','available_at':'2026-09-14T18:00:00+08:00',
            'content_hash':'a'*64,'completeness':'VERIFIED'})
        self.source=store.create_definition(str(uuid4()),{
            'playbook_key':'qimofenshu','name':'test','version':'test','state':'DRAFT','source_ids':[self.evidence['source_id']]})
        self.runner.enable(self.source['definition_id'],confirmed=True)
        self.journal=read_checked(self.runner.root/'journal.json')

    def event(self,at,weights):
        e={'id':str(uuid4()),'day':at[:10],'at':at+'+08:00','weights':weights,'selection_id':str(uuid4())}
        self.journal['events'].append(e);write_checked(self.runner.root/'journal.json',self.journal);return e

    def settle(self,stamp):return self.runner.settle(self.journal,self.market.sessions(self.now),dt(stamp))

    def test_million_multiple_positions_above_twenty_percent_hold_until_signal(self):
        self.assertEqual(CONFIG.initial_cash,1000000);self.assertIsNone(POLICY['max_positions'])
        self.event('2026-09-15T09:36:00',{'sh.600001':.6,'sz.000001':.4})
        self.settle('2026-09-15T18:31:00');entry=self.runner.account.read()
        self.assertEqual(len(entry['fills']),2)
        self.assertGreater(entry['fills'][0]['quantity']*entry['fills'][0]['price'],200000)
        self.settle('2026-09-16T18:31:00');held=self.runner.account.read()
        self.assertEqual(len(held['fills']),2);self.assertEqual(len(held['summary']['ending_positions']),2)
        self.event('2026-09-17T11:31:00',{})
        self.settle('2026-09-17T18:31:00');result=self.runner.account.read()
        self.assertEqual([f['side'] for f in result['fills']],['buy','buy','sell','sell'])
        self.assertEqual(result['summary']['ending_positions'],{})
        self.settle('2026-09-17T18:32:00');self.assertEqual(result,self.runner.account.read())

    def test_add_and_exit_keep_t_plus_one(self):
        self.event('2026-09-15T09:36:00',{'sh.600001':.3})
        self.event('2026-09-15T11:31:00',{'sh.600001':.8})
        self.event('2026-09-15T15:00:00',{})
        self.settle('2026-09-15T18:31:00');result=self.runner.account.read()
        self.assertEqual([f['side'] for f in result['fills']],['buy','buy'])
        self.settle('2026-09-16T18:31:00');result=self.runner.account.read()
        self.assertEqual([f['side'] for f in result['fills']],['buy','buy','sell'])
        self.assertEqual(datetime.fromisoformat(result['fills'][-1]['filled_at']).astimezone(TZ).date(),date(2026,9,16))

    def test_new_other_symbol_does_not_rebalance_unchanged_holding(self):
        self.event('2026-09-15T09:36:00',{'sh.600001':.3})
        self.event('2026-09-16T09:36:00',{'sh.600001':.3,'sz.000001':.7})
        self.settle('2026-09-16T18:31:00')
        self.assertEqual([(f['symbol'],f['side']) for f in self.runner.account.read()['fills']],
            [('sh.600001','buy'),('sz.000001','buy')])

    def test_limit_up_one_attempt_per_signal_and_limit_down_exit_retry(self):
        self.event('2026-09-15T09:36:00',{'sh.600001':.5,'sz.000001':.5});self.market.block_buy={'sh.600001'}
        self.settle('2026-09-15T18:31:00');state=self.runner.account.read()
        self.assertEqual(len(state['fills']),1)
        self.assertEqual(len([r for r in state['rejections'] if r['symbol']=='sh.600001']),1)
        self.event('2026-09-16T09:36:00',{});self.market.block_sell={'sz.000001'}
        self.settle('2026-09-16T18:31:00');self.assertTrue(self.runner.account.read()['summary']['ending_positions'])
        self.market.block_sell=set();self.settle('2026-09-17T18:31:00')
        self.assertEqual(self.runner.account.read()['summary']['ending_positions'],{})

    def test_suspension_keeps_real_previous_mark_and_exit_pending(self):
        self.event('2026-09-15T09:36:00',{'sh.600001':1.});self.settle('2026-09-15T18:31:00')
        self.event('2026-09-16T09:36:00',{});self.market.suspended={'sh.600001'}
        with patch.object(self.market,'bars',side_effect=AssertionError('No fake suspension bars')):
            self.settle('2026-09-16T18:31:00')
        self.market.suspended=set();self.settle('2026-09-17T18:31:00')
        self.assertEqual([f['side'] for f in self.runner.account.read()['fills']],['buy','sell'])

    def test_restart_after_account_commit_and_missing_rules(self):
        self.event('2026-09-15T09:36:00',{'sh.600001':1.});self.market.missing=True
        with self.assertRaisesRegex(ValueError,'RULES_MISSING'):self.settle('2026-09-15T18:31:00')
        self.assertFalse(self.runner.account.path.exists());self.market.missing=False
        self.settle('2026-09-15T18:31:00');state=self.runner.account.read()
        self.journal['settled_days']=[];self.settle('2026-09-15T18:32:00')
        self.assertEqual(state,self.runner.account.read())

    def test_no_history_backfill_missing_data_and_control_migration(self):
        self.assertEqual(self.runner.tick()['status'],'WAIT_FIRST_FORWARD_SESSION')
        self.now=dt('2026-09-16T08:30:00')
        self.assertEqual(self.runner.tick()['status'],'BLOCKED_PREP_EVIDENCE')
        control=read_checked(self.runner.root/'control.json');control['policy']={'version':'old'}
        control['account']='old';write_checked(self.runner.root/'control.json',control)
        self.runner.enable(self.source['definition_id'],confirmed=True)
        self.assertTrue((self.runner.root/'versions/old/control.json').exists())
        self.assertEqual(read_checked(self.runner.root/'control.json')['policy'],POLICY)

    def test_migration_refuses_to_discard_signals(self):
        control=read_checked(self.runner.root/'control.json');control['policy']={'version':'old'}
        write_checked(self.runner.root/'control.json',control);self.event('2026-09-15T09:36:00',{'sh.600001':1.})
        with self.assertRaisesRegex(ValueError,'旧版已有信号'):self.runner.enable(self.source['definition_id'],confirmed=True)

    def test_forward_multi_selection_admitted_once(self):
        definition=read_checked(self.runner.root/'control.json')['definition_id'];store=PlaybookStore(self.output,now_fn=lambda:self.now)
        case=store.create_case(str(uuid4()),{'definition_id':definition,'trading_day':'2026-09-15','frame':'R1',
            'as_of':'2026-09-15T09:35:00+08:00','source_ids':[self.evidence['source_id']],'summary':'synthetic'})
        syms=['sh.600001','sz.000001'];candidate=store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],
            'definition_id':definition,'trading_day':'2026-09-15','frame':'R1','as_of':'2026-09-15T09:35:00+08:00',
            'completeness':'FULL','pit_status':'UNKNOWN','universe_source':'fixture','generation_method':'fixture',
            'candidates':[{'symbol':s,'eligibility_reasons':['fixture'],'features':{'qimo_assessment':{'action':'BUY','score':1.}},'evidence_ids':['fixture']} for s in syms],'evidence_ids':['fixture']})
        selection=store.create_selection(str(uuid4()),{'candidate_set_id':candidate['candidate_set_id'],'kind':'SYSTEM_PREDICTION',
            'selected_symbols':syms,'ranked_symbols':syms,'reasons':{s:['fixture'] for s in syms},'evidence_ids':['fixture'],
            'as_of':'2026-09-15T09:35:00+08:00'})
        plan={'trading_day':'2026-09-15','definition_id':definition,'r1':{'status':'FROZEN','prediction_id':selection['selection_id']}}
        for _ in range(2):self.runner.admit(plan,self.journal,self.market.sessions(self.now),self.now)
        self.assertEqual(len(self.journal['events']),1);self.assertEqual(len(self.journal['events'][0]['weights']),2)
        self.settle('2026-09-15T18:31:00');self.assertEqual(len(self.runner.account.read()['fills']),2)

    def test_raw_bar_contract(self):
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):QimoMarketData._bars({'rows':[]},date(2026,9,15),'sh.600001')
        with self.assertRaisesRegex(ValueError,'IDENTITY'):
            QimoMarketData._bars({'rows':[{'date':'2026-09-15','code':'sh.600001','adjustflag':'2'}]},date(2026,9,15),'sh.600001')


class SourceRuleTests(unittest.TestCase):
    def theme(self,up,down,count,ret):return {'snapshot_id':str(uuid4()),'facts':{'leader_symbol':'sh.600001',
        'breadth_up':up,'breadth_down':down,'limit_up_count':count,'leader_return':ret}}
    def test_joint_rule_hold_and_conditional_exit(self):
        prior={'symbol':'sh.600001','previous_close':10.,'last':10.3}
        item={**prior,'last':10.6,'high':10.8,'low':10.2,'open':10.3,'tradable':True,'execution_profile':'STANDARD_ACCESS'}
        old={'sector':self.theme(5,2,1,2)};strong={'sector':self.theme(7,1,2,5)}
        self.assertEqual(assess(item,prior,strong,old)['action'],'BUY')
        self.assertEqual(assess(item,prior,{},old)['action'],'WAIT_CONTEXT')
        self.assertEqual(assess({**item,'last':10.2},prior,strong,old)['action'],'HOLD')
        weak={'sector':self.theme(2,7,0,-2)}
        self.assertEqual(assess({**item,'last':9.7},{**prior,'last':9.9},weak,strong)['action'],'EXIT')
        self.assertEqual(assess({**item,'high':11.,'last':10.5,'limit_up_price':11.},prior,weak,strong)['action'],'EXIT')
        self.assertEqual(assess({**item,'high':11.,'last':10.5,'limit_up_price':11.},
            {**prior,'last':None,'auction_price':10.3},weak,strong)['action'],'EXIT')
    def test_full_cash_multiple_and_single_signal_not_artificial_cap(self):
        a={s:{'action':'BUY','score':v} for s,v in [('sh.600001',3.),('sz.000001',1.)]}
        self.assertEqual(portfolio_targets({},a),{'sh.600001':.75,'sz.000001':.25})
        self.assertEqual(portfolio_targets({}, {'sh.600001':a['sh.600001']}),{'sh.600001':1.})
        self.assertEqual(portfolio_targets({'sh.600001':1.},{'sh.600001':{'action':'HOLD'}}),{'sh.600001':1.})
        self.assertEqual(portfolio_targets({},a,allow_entries=False),{})


if __name__=='__main__':unittest.main()
