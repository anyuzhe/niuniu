import json
import random
import tempfile
import unittest
from pathlib import Path
import polars as pl
from test_technical import bars
from quantlab.adapters.chan_classic import ClassicChanState,analyze_classic,PROFILE
from quantlab.adapters.chan_state import dump_state,load_state
from quantlab.factors.cache import FactorCache
from quantlab._vendor.chanpy.Common.CEnum import KL_TYPE


class ChanContinuationTest(unittest.TestCase):
    def frame(self):
        rng=random.Random(42);prices=[100.]
        for _ in range(650):prices.append(prices[-1]+rng.uniform(-3,3))
        return bars(prices)

    def test_recursive_state_roundtrip_preserves_events_and_timezone(self):
        frame=self.frame();state=ClassicChanState('A','1d');state.extend(frame.head(400))
        restored=load_state(json.loads(json.dumps(dump_state(state))))
        actual,events=restored.extend(frame.slice(400));expected,reference=analyze_classic(frame)
        self.assertTrue(actual.equals(expected));self.assertEqual(events,reference)
        self.assertEqual(ClassicChanState('A','30m').engine.kl_type,KL_TYPE.K_30M)
        self.assertEqual(ClassicChanState('A','60m').engine.kl_type,KL_TYPE.K_60M)
        with self.assertRaisesRegex(ValueError,'strictly later'):restored.append(frame.row(-1,named=True))

    def test_persisted_append_and_historical_revision_invalidation(self):
        frame=self.frame()
        with tempfile.TemporaryDirectory() as tmp:
            FactorCache(Path(tmp),'v1').compute_classic(PROFILE,frame.head(400))
            resumed=FactorCache(Path(tmp),'v1');actual,events=resumed.compute_classic(PROFILE,frame)
            expected,reference=analyze_classic(frame)
            self.assertEqual(resumed.classic_resumed_bars,400);self.assertTrue(actual.equals(expected));self.assertEqual(events,reference)
            changed=frame.with_columns((pl.col('volume')+1).alias('volume'))
            reset=FactorCache(Path(tmp),'v1');value,_=reset.compute_classic(PROFILE,changed)
            self.assertEqual(reset.classic_resumed_bars,0);self.assertTrue(value.equals(analyze_classic(changed)[0]))

    def test_unexpected_state_classes_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            load_state({'version':1,'root':{'ref':0},'nodes':[{'kind':'object','class':'subprocess.Popen','fields':{}}]})

    def test_interruption_resumes_only_fully_persisted_chunk(self):
        from unittest.mock import patch
        from quantlab.progress import ResearchCancelled
        frame=self.frame();append=ClassicChanState.append
        def interrupted(state,row):
            if len(state.rows)==550:raise ResearchCancelled('simulated interruption')
            return append(state,row)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ClassicChanState,'append',interrupted):
                with self.assertRaises(ResearchCancelled):FactorCache(tmp,'v1').compute_classic(PROFILE,frame)
            resumed=FactorCache(tmp,'v1');actual,events=resumed.compute_classic(PROFILE,frame)
            expected,reference=analyze_classic(frame)
            self.assertEqual(resumed.classic_resumed_bars,512)
            self.assertTrue(actual.equals(expected));self.assertEqual(events,reference)
