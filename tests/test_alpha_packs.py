import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import math
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.factors.alpha import alpha_packs
from quantlab.factors.engine import compute_factor

class AlphaPackTests(unittest.TestCase):
    def test_frozen_formulas_prefix_and_no_future_labels(self):
        rows=[]
        for symbol in ('A','B','C'):
            for i in range(85):
                t=datetime(2020,1,1,15,tzinfo=ZoneInfo('Asia/Shanghai'))+timedelta(days=i)
                price=20+i*.03+math.sin(i*.7+ord(symbol))
                rows.append(dict(symbol=symbol,datetime=t,available_at=t,timeframe='1d',open=price-.1,close=price,
                    high=price+.5,low=price-.6,volume=1000.+i*3,turnover=(1000.+i*3)*price*2,adj_factor=.5))
        bars=pl.DataFrame(rows);cut=bars['datetime'][69];prefix=bars.filter(pl.col('datetime')<=cut)
        packs=alpha_packs();self.assertEqual([len(p.factors) for p in packs],[82,158])
        for pack in packs:
            for factor in pack.factors:
                with self.subTest(factor=factor.definition.factor_id):
                    full=compute_factor(factor,bars,{})
                    short=compute_factor(factor,prefix,{})
                    assert_frame_equal(short,full.filter(pl.col('datetime')<=cut),check_exact=False,abs_tol=1e-10)
                    self.assertFalse(full.filter(pl.col('value').is_not_null()&~pl.col('value').is_finite()).height)
        vwap=next(f for f in packs[1].factors if f.name=='vwap_0')
        self.assertTrue(all(abs(v-1)<1e-12 for v in compute_factor(vwap,bars,{})['value']))

if __name__=='__main__':unittest.main()
