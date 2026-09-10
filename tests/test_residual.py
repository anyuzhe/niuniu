import unittest
from datetime import datetime, timedelta, timezone
import polars as pl
from quantlab.statistics.residual import residual_alpha

class ResidualTests(unittest.TestCase):
    def test_train_projection_and_heldout_independent_component(self):
        rows=[]
        for day in range(24):
            for symbol in range(7):
                control=symbol-3.; novelty=((symbol*3+day)%7)-3.
                dt=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=day)
                rows.append({'symbol':str(symbol),'datetime':dt,'available_at':dt,'value':2*control+novelty,'control':control,'forward_1':novelty/100})
        frame=pl.DataFrame(rows);control=frame.with_columns(pl.col('control').alias('value'))
        cutoff=datetime(2025,1,12).date();obs,result=residual_alpha(frame,[control],cutoff)
        self.assertGreater(result['test_residual_ic'],.9)
        altered=frame.with_columns(pl.when(pl.col('datetime').dt.date()>cutoff).then(pl.col('value')*100).otherwise(pl.col('value')).alias('value'))
        self.assertEqual(residual_alpha(altered,[control],cutoff)[1]['model'],result['model'])
        redundant=frame.with_columns((pl.col('control')*2).alias('value'))
        empty,zero=residual_alpha(redundant,[control],cutoff)
        self.assertEqual(empty['value'].abs().max(),0.)
        self.assertIsNone(zero['test_residual_ic'])
        with self.assertRaisesRegex(ValueError,'Collinear'):residual_alpha(frame,[control,control],cutoff)
