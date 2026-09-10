import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from quantlab.domain import Event,Timeframe
from quantlab.sequence.engine import SequenceDefinition,SequenceScope,EventSelector,OrderedSequenceEngine
from quantlab.sequence.specification import normalize_steps,sequence_scopes


class FinalSequenceTests(unittest.TestCase):
    def test_cross_timeframe_prefix_without_completed_higher_bar(self):
        from test_multitimeframe import bars,at
        from quantlab.factors.sequences import CustomOrderedSequence
        from polars.testing import assert_frame_equal
        start=at(1,9).replace(minute=30)
        source=bars([start+timedelta(minutes=5*i) for i in range(1,13)],'5m',[float(10+i) for i in range(12)])
        factor=CustomOrderedSequence();params={'lookback':1,'step_timeframes':['5m','15m']}
        full=factor.trace(source,params)[0]
        for count in (1,2,3,7):
            assert_frame_equal(factor.trace(source.head(count),params)[0],full.head(count))

    def test_nested_clock_does_not_reset_with_each_step(self):
        at=datetime(2020,1,1,tzinfo=ZoneInfo('Asia/Shanghai'))
        definition=SequenceDefinition('test',tuple(EventSelector(v) for v in ('A','B','C','D')),timedelta(seconds=100),scopes=(SequenceScope(1,3,timedelta(seconds=10)),))
        events=[Event(str(i),v,'A',Timeframe.MIN5,at+timedelta(seconds=t),at+timedelta(seconds=t)) for i,(v,t) in enumerate([('A',0),('B',1),('C',9),('D',11)])]
        results=OrderedSequenceEngine(definition).advance(events,at+timedelta(seconds=20))
        self.assertEqual([r.status for r in results],['active','active','active','timeout'])
        self.assertEqual(results[-1].available_at,at+timedelta(seconds=11))

    def test_cross_timeframe_requires_correct_availability_and_period(self):
        at=datetime(2020,1,1,tzinfo=ZoneInfo('Asia/Shanghai'))
        definition=SequenceDefinition('test',(EventSelector('A'),EventSelector('B')),timedelta(seconds=100),step_timeframes=(Timeframe.DAILY,Timeframe.MIN5))
        events=[Event('a','A','S',Timeframe.DAILY,at,at),Event('wrong','B','S',Timeframe.DAILY,at+timedelta(seconds=1),at+timedelta(seconds=1)),Event('b','B','S',Timeframe.MIN5,at+timedelta(seconds=2),at+timedelta(seconds=2))]
        results=OrderedSequenceEngine(definition).advance(events,at+timedelta(seconds=3))
        self.assertEqual(results[-1].event_ids,('a','b'))
        self.assertEqual(results[-1].status,'completed')

    def test_scoped_invalidation_precedes_completion(self):
        at=datetime(2020,1,1,tzinfo=ZoneInfo('Asia/Shanghai'))
        steps=['A',{'steps':['B','C'],'timeout_seconds':10,'invalidators':['X']},'D']
        flat,optional=normalize_steps(steps,['A','B','C','D','X'])
        definition=SequenceDefinition('test',tuple(EventSelector(v) for v in flat),timedelta(seconds=100),scopes=sequence_scopes(steps))
        events=[Event(str(i),v,'S',Timeframe.MIN5,at+timedelta(seconds=t),at+timedelta(seconds=t)) for i,(v,t) in enumerate([('X',0),('A',1),('B',2),('C',3),('X',3)])]
        results=OrderedSequenceEngine(definition).advance(events,at+timedelta(seconds=4))
        self.assertEqual(results[-1].status,'invalidated')
