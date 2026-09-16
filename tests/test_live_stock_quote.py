import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

import polars as pl

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.live_stock_quote import FORMAT,LiveStockQuoteService
from quantlab.agent.model_config import ModelConfig

TZ=ZoneInfo('Asia/Shanghai')


class QuoteProvider:
    def __init__(self,failures=0):self.calls=[];self.failures=failures
    def capture(self,trading_day,frame,symbols):
        self.calls.append((trading_day,frame,list(symbols)))
        if len(self.calls)<=self.failures:raise ValueError('fixture unavailable')
        return {'trading_day':trading_day,'frame':frame,'as_of':trading_day+'T10:00:00+08:00',
            'provider':'public-web-consensus-v1','provider_ref':'three-source-fixture','source_hash':'a'*64,
            'completeness':'FULL','strict_pit_source_verified':False,
            'instruments':[{'symbol':symbol,'name':'宏景科技' if symbol=='sz.301396' else symbol,
                'previous_close':30.0,'last':31.5,'open':30.2,'high':32.0,'low':29.9,
                'volume':120000.0,'amount':3720000.0,'tradable':True,
                'metrics':{'bid1':31.49,'ask1':31.5,'agreement_sources':['tencent','sina'],
                    'source_times':{'tencent':trading_day+'T10:00:01+08:00','sina':trading_day+'T10:00:00+08:00'}}}
                for symbol in symbols],
            'market_metrics':{'source_health':{'tencent':{'accepted':len(symbols)},'sina':{'accepted':len(symbols)}},
                'consensus_issues':[]}}


class CapturingModel:
    def __init__(self):self.system='';self.messages=[]
    def run(self,system,messages,tools,dispatch,emit,stop):
        self.system=system;self.messages=messages
        return {'text':'fixture answer','model':'fixture','provider':'fixture','tool_calls':0,'usage':{}}


class LiveQuoteStub:
    def __init__(self,value):self.value=value;self.queries=[]
    def query(self,text,*,context_texts=()):self.queries.append((text,list(context_texts)));return self.value
    def tool_result(self,value):return LiveStockQuoteService.tool_result(value)


class LiveStockQuoteTests(unittest.TestCase):
    def data_root(self,tmp):
        root=Path(tmp);path=root/'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet'
        path.parent.mkdir(parents=True)
        pl.DataFrame([{'code':'sz.301396','code_name':'宏景科技','ipoDate':'2022-11-11',
            'outDate':'','type':'1','status':'1'},
            {'code':'sh.600519','code_name':'贵州茅台','ipoDate':'2001-08-27',
            'outDate':'','type':'1','status':'1'}]).write_parquet(path)
        return root

    def test_official_name_and_code_resolve_to_one_bounded_read_only_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.data_root(tmp);provider=QuoteProvider()
            service=LiveStockQuoteService(root,provider=provider,
                now_fn=lambda:datetime(2026,9,16,10,0,30,tzinfo=TZ))
            value=service.query('帮我看看宏景科技 301396 现在怎么样？')
            self.assertEqual(value['format'],FORMAT);self.assertEqual(value['status'],'OK')
            self.assertEqual(value['requested_symbols'],['sz.301396'])
            self.assertEqual(provider.calls,[('2026-09-16','R1',['sz.301396'])])
            quote=value['quotes'][0]
            self.assertEqual(quote['last'],31.5);self.assertAlmostEqual(quote['change_pct'],5.0)
            self.assertEqual(quote['agreement_sources'],['tencent','sina'])
            self.assertFalse(value['stored_as_market_snapshot']);self.assertFalse(value['creates_decision'])
            self.assertFalse(value['strict_pit_source_verified'])

    def test_non_stock_question_does_not_touch_network_and_previous_session_can_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.data_root(tmp);provider=QuoteProvider(failures=1)
            service=LiveStockQuoteService(root,provider=provider,
                now_fn=lambda:datetime(2026,9,17,8,0,0,tzinfo=TZ))
            self.assertIsNone(service.query('解释一下Rank IC'));self.assertEqual(provider.calls,[])
            value=service.query('贵州茅台现在什么情况')
            self.assertEqual(value['status'],'OK');self.assertEqual(len(provider.calls),2)
            self.assertEqual(value['trading_day'],'2026-09-16')
            self.assertEqual(value['market_status'],'LAST_AVAILABLE_SESSION')

    def test_chat_host_prefetches_and_injects_quote_without_creating_snapshot(self):
        value={'format':FORMAT,'status':'OK','query_mode':'EXPLICIT_USER_STOCK_QUESTION_READ_ONLY',
            'requested_at':'2026-09-16T10:00:30+08:00','requested_symbols':['sz.301396'],
            'stored_as_market_snapshot':False,'creates_decision':False,'strict_pit_source_verified':False,
            'trading_day':'2026-09-16','as_of':'2026-09-16T10:00:00+08:00',
            'captured_at':'2026-09-16T10:00:30+08:00','market_status':'TRADING',
            'provider':'public-web-consensus-v1','source_hash':'a'*64,'completeness':'FULL',
            'quotes':[{'symbol':'sz.301396','name':'宏景科技','last':31.5,'change_pct':5.0,
                'agreement_sources':['tencent','sina']}],
            'limitations':['not stored']}
        with tempfile.TemporaryDirectory() as tmp:
            stub=LiveQuoteStub(value);runtime=ChatRuntime(tmp,tmp,live_quote_service=stub)
            cid=runtime.store.create();model=CapturingModel();events=[]
            result=runtime.send(cid,'宏景科技现在怎么样？',ModelConfig(),allow_send=True,
                provider=model,emit=lambda kind,payload:events.append((kind,payload)))
            self.assertEqual(stub.queries,[('宏景科技现在怎么样？',[])])
            self.assertEqual(result['host_live_quote_queries'],1);self.assertEqual(result['tool_calls'],0)
            self.assertEqual(result['evidence'][0]['kind'],'live_stock_quote')
            wire=model.messages[-1]['content']
            self.assertIn('HOST_LIVE_QUOTE_CONTEXT',wire);self.assertIn('31.5',wire)
            self.assertIn('不能因为没有已冻结MarketSnapshot就跳过实时查询',model.system)
            self.assertTrue(any(kind=='tool_result' and payload['name']=='get_live_stock_quote' for kind,payload in events))
            self.assertFalse((Path(tmp)/'_trading/market_snapshots.sqlite3').exists())
            persisted=json.dumps(runtime.store.events(cid),ensure_ascii=False)
            self.assertIn('get_live_stock_quote',persisted);self.assertIn('sz.301396',persisted)

    def test_single_stock_followup_reuses_conversation_scope_but_ambiguous_scope_does_not_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.data_root(tmp);provider=QuoteProvider()
            service=LiveStockQuoteService(root,provider=provider,
                now_fn=lambda:datetime(2026,9,16,10,0,30,tzinfo=TZ))
            value=service.query('这只股票现在能买吗？',context_texts=['先看看宏景科技'])
            self.assertEqual(value['query_mode'],'CONTEXTUAL_USER_STOCK_FOLLOWUP_READ_ONLY')
            self.assertEqual(value['requested_symbols'],['sz.301396']);self.assertEqual(len(provider.calls),1)
            value=service.query('这只股票呢？',context_texts=['比较宏景科技和贵州茅台'])
            self.assertEqual(value['status'],'AMBIGUOUS_REFERENCE');self.assertEqual(len(provider.calls),1)


if __name__=='__main__':unittest.main()
