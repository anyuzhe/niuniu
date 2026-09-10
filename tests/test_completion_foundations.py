import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.factors.cache import FactorCache
from quantlab.multitimeframe.resample import resample_bars
from quantlab.regime.engine import RuleBasedRegimeEngine
from quantlab.regime.config import RegimeConfig
from quantlab.sequence.engine import EventSelector,SequenceDefinition,OrderedSequenceEngine
from quantlab.sequence.specification import normalize_steps
from test_sequences import event,T
from test_multitimeframe import bars,at
from test_regime import inputs

class CompletionFoundationsTests(unittest.TestCase):
    def test_cache_integrity_and_identity(self):
        frame=pl.DataFrame({'value':[1.,2.]})
        with tempfile.TemporaryDirectory() as tmp:
            cache=FactorCache(tmp,'revision-a');key=cache.key({'factor':'test','parameters':{}},frame)
            cache.put(key,frame,[{'id':'event'}]);saved=cache.get(key)
            assert_frame_equal(saved[0],frame);self.assertEqual(saved[1],[{'id':'event'}])
            self.assertNotEqual(key,cache.key({'factor':'test','parameters':{'n':2}},frame))
            self.assertNotEqual(key,cache.key({'factor':'test','parameters':{}},frame*2))
            self.assertNotEqual(key,FactorCache(tmp,'revision-b').key({'factor':'test','parameters':{}},frame))
            (Path(tmp)/key/'events.json').write_text('[]')
            self.assertIsNone(cache.get(key));cache.put(key,frame);assert_frame_equal(cache.get(key)[0],frame)

    def test_classic_shared_cache_and_verified_prefix(self):
        import math
        from test_technical import bars as daily_bars
        from quantlab.factors.chan_classic import ClassicChanFactor
        from quantlab.adapters.chan_classic import analyze_classic
        frame=daily_bars([20+math.sin(i/3)*2+i*.01 for i in range(100)])
        expected,events=analyze_classic(frame)
        with tempfile.TemporaryDirectory() as tmp:
            cache=FactorCache(tmp,'fixed-code')
            first=ClassicChanFactor('position');first._persistent_cache=cache;first.matrix(frame)
            second=ClassicChanFactor('buy1');second._persistent_cache=FactorCache(tmp,'fixed-code')
            with patch('quantlab.factors.chan_classic.analyze_classic',side_effect=AssertionError('Should reuse verified prefix')):
                values,earlier=second.matrix(frame.head(70))
            assert_frame_equal(values,expected.head(70));self.assertEqual(earlier,[e for e in events if e.available_at<=frame['available_at'][69]])
            revised=frame.with_columns((pl.col('turnover')+1).alias('turnover'))
            with patch.object(second._persistent_cache,'compute_classic',wraps=second._persistent_cache.compute_classic) as calculation:
                recalculated,revised_events=second.matrix(revised)
                self.assertEqual(calculation.call_count,1)
            self.assertEqual(second._persistent_cache.classic_resumed_bars,0)
            reference,reference_events=analyze_classic(revised)
            assert_frame_equal(recalculated,reference);self.assertEqual(revised_events,reference_events)

    def test_complete_intraday_sessions_and_delayed_availability(self):
        start=at(1,9).replace(minute=30)
        times=[start+timedelta(minutes=5*i) for i in range(1,25)]
        times += [at(1,13)+timedelta(minutes=5*i) for i in range(1,25)]
        source=bars(times,'5m',[float(10+i) for i in range(48)])
        for period,count in [('15m',16),('30m',8),('60m',4)]:
            result=resample_bars(source,period)
            self.assertEqual(result.height,count);self.assertEqual(result['volume'].sum(),4800.)
            self.assertEqual(result['datetime'][count//2-1].hour,11)
            self.assertEqual(result['datetime'][count//2-1].minute,30)
            prefix=source.filter(pl.col('datetime')<=result['datetime'][0])
            assert_frame_equal(resample_bars(prefix,period),result.head(1))
        delayed=source.with_columns((pl.col('available_at')+timedelta(minutes=1)).alias('available_at'))
        self.assertEqual(resample_bars(delayed,'15m')['available_at'][0],times[2]+timedelta(minutes=1))
        self.assertEqual(resample_bars(source.slice(1),'15m').height,15)
        with self.assertRaises(ValueError):resample_bars(source,'1m')

    def test_liquidity_past_threshold_and_prefix(self):
        source=inputs([.1]*6,[1.]*6).with_columns(pl.Series('amihud',[1.,2.,3.,100.,.1,3.]))
        engine=RuleBasedRegimeEngine(RegimeConfig(baseline_window=3));full=engine.frame(source)
        self.assertEqual(full['regime_liquidity'].to_list(),['Unknown']*3+['Low','High','Medium'])
        assert_frame_equal(engine.frame(source.head(4)),full.head(4))

    def test_resample_rejects_a_symbol_with_no_complete_bars(self):
        start=at(1,9).replace(minute=30)
        complete=bars([start+timedelta(minutes=5*i) for i in range(1,4)],'5m',[10.,11.,12.])
        incomplete=complete.head(1).with_columns(pl.lit('MISSING').alias('symbol'))
        with self.assertRaisesRegex(ValueError,'MISSING'):
            resample_bars(pl.concat([complete,incomplete]),'15m')

    def test_nested_optional_greedy_and_streaming(self):
        flat,optional=normalize_steps(['A',{'steps':[{'event':'B','optional':True},'C']},'D'],('A','B','C','D'))
        definition=SequenceDefinition('nested',tuple(EventSelector(s) for s in flat),timedelta(seconds=60),optional_steps=optional)
        events=[event('a','A',0),event('c','C',10),event('d','D',20)]
        whole=OrderedSequenceEngine(definition).advance(events,T+timedelta(seconds=20))
        engine=OrderedSequenceEngine(definition)
        streamed=engine.advance(events[:1],T)+engine.advance(events[1:],T+timedelta(seconds=20))
        self.assertEqual(whole,streamed);self.assertEqual(whole[-1].status,'completed');self.assertEqual(whole[-1].event_ids,('a','c','d'))
        included=OrderedSequenceEngine(definition).advance([events[0],event('b','B',5),*events[1:]],T+timedelta(seconds=20))
        self.assertEqual(included[-1].event_ids,('a','b','c','d'))
        for bad in ([{'event':'A','optional':True},'B'],['A',{'steps':[]} , 'D']):
            with self.assertRaises(ValueError):normalize_steps(bad,('A','B','D'))

if __name__=='__main__':unittest.main()
