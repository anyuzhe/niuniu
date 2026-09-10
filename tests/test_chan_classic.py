import math
import random
import unittest
from types import SimpleNamespace
from test_technical import bars
from quantlab.adapters.chan_classic import analyze_classic,PROFILE
from quantlab.factors.chan_classic import ClassicChanFactor
from quantlab.factors.chan_classic import classic_transitions
from quantlab.domain import Event,Timeframe
from quantlab._vendor.chanpy.Seg.Seg import CSeg
from quantlab._vendor.chanpy.Common.CEnum import MACD_ALGO


class ClassicChanTests(unittest.TestCase):
    def test_streaming_prefix_and_withdrawn_snapshot(self):
        rng=random.Random(42);prices=[100.]
        for _ in range(400):prices.append(prices[-1]+rng.uniform(-3,3))
        frame=bars(prices)
        values,events=analyze_classic(frame)
        self.assertTrue(any(e.factor_id=='CHAN.CLASSIC_BI_UP' for e in events))
        self.assertTrue(any(e.metadata['status']=='removed' for e in events))
        for n in (1,9,37,100,211,319):
            prefix,earlier=analyze_classic(frame.head(n))
            self.assertTrue(prefix.equals(values.head(n)))
            self.assertEqual(earlier,[e for e in events if e.available_at<=frame[n-1,'available_at']])
        self.assertTrue(all(e.occurred_at<=e.available_at for e in events))
        self.assertEqual(len({e.event_id for e in events}),len(events))

    def test_segment_area_uses_observed_matching_sign_and_end_boundary(self):
        units=[SimpleNamespace(idx=i,macd=SimpleNamespace(macd=v),next=None) for i,v in enumerate([1.,-2.,3.,-4.,999.])]
        for a,b in zip(units,units[1:]):a.next=b
        line=SimpleNamespace(get_begin_klu=lambda:units[0],get_end_klu=lambda:units[3],is_up=lambda:True,is_down=lambda:False)
        self.assertAlmostEqual(CSeg.cal_macd_metric(line,MACD_ALGO.FULL_AREA,False),4.+1e-7)
        line.is_up=lambda:False;line.is_down=lambda:True
        self.assertAlmostEqual(CSeg.cal_macd_metric(line,MACD_ALGO.FULL_AREA,False),6.+1e-7)

    def test_frozen_profile_and_factor_cache_change(self):
        self.assertEqual(PROFILE['seg_algo'],'chan');self.assertEqual(PROFILE['macd_algo-seg'],'full_area')
        factor=ClassicChanFactor('position');frame=bars([10+math.sin(i/3) for i in range(60)])
        self.assertEqual(factor.compute(frame,{}).height,60)
        self.assertEqual(factor.compute(frame.head(15),{}).height,15)
        with self.assertRaises(ValueError):factor.parameters({'seg_algo':'break'})

    def test_related_sequence_respects_withdrawal_and_information_order(self):
        frame=bars([10.,11.,12.]);times=frame['available_at'].to_list();symbol=frame['symbol'][0]
        first=Event('one','CHAN.CLASSIC_BUY1',symbol,Timeframe.DAILY,times[0],times[0],metadata={'status':'added','end_index':0})
        second=Event('two','CHAN.CLASSIC_BUY2',symbol,Timeframe.DAILY,times[1],times[2],metadata={'status':'added','end_index':1,'related_buy_sell_1_index':0})
        self.assertEqual([t.status for t in classic_transitions([first,second])],['active','completed'])
        removed=Event('withdraw','CHAN.CLASSIC_BUY1',symbol,Timeframe.DAILY,times[0],times[2],metadata={'status':'removed','end_index':0})
        self.assertEqual([t.status for t in classic_transitions([first,second,removed])],['active','invalidated'])

    def test_classic_replay_applies_only_known_object_revisions(self):
        from quantlab.sequence.replay import replay_page
        frame=bars([10.,11.,12.]);times=frame['available_at'].to_list();symbol=frame['symbol'][0]
        events=[{'event_id':str(i),'factor_id':'CHAN.CLASSIC_PIVOT_LOW','symbol':symbol,'timeframe':'1d',
            'available_at':times[i].isoformat(),'occurred_at':times[0].isoformat(),
            'metadata':{'object_key':'fx:0','kind':'pivot_low','status':status,'price':9.,'end_index':0}}
            for i,status in enumerate(['added','removed'])]
        record={'replay':{'version':'classic_snapshots_v1'},'sequence_audit':{'sequences':[{'events':events}]}}
        self.assertEqual(len(replay_page(frame,record,symbol,0)['structures']),1)
        self.assertEqual(replay_page(frame,record,symbol,1)['structures'],[])
