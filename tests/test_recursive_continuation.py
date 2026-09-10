import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from datetime import timedelta
import polars as pl
from test_wyckoff_classic import fixture, P
from quantlab.factors.wyckoff_classic import ClassicWyckoffFactor
from quantlab.factors.cache import FactorCache
from quantlab.factors.continuation import pack_state, unpack_state
from quantlab.progress import research_progress, ResearchCancelled


def cached_factor(root, code='continuation-test'):
    factor=ClassicWyckoffFactor('position');factor._persistent_cache=FactorCache(root,code)
    return factor


class RecursiveContinuationTests(unittest.TestCase):
    def test_process_restart_matches_every_component_event_and_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache';project=Path(__file__).resolve().parents[1]
            env={**os.environ,'PYTHONPATH':str(project/'src')+os.pathsep+str(project/'tests')}
            script='from test_recursive_continuation import cached_factor, fixture, P; cached_factor('+repr(str(path))+').matrix(fixture().head(8),P)'
            subprocess.run([sys.executable,'-c',script],env=env,check=True,timeout=30)
            resumed=cached_factor(path);actual=resumed.matrix(fixture(),P)
            expected=ClassicWyckoffFactor('position').matrix(fixture(),P)
            self.assertEqual(resumed._persistent_cache.recursive_resumed_bars,8)
            self.assertEqual(resumed._persistent_cache.recursive_processed_bars,8)
            self.assertTrue(actual[0].equals(expected[0]))
            self.assertEqual(actual[1:],expected[1:])

    def test_history_revision_corruption_and_code_changes_do_not_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);cached_factor(path).matrix(fixture().head(8),P)
            changed=fixture().with_columns(pl.when(pl.col('datetime')==fixture()['datetime'][0]).then(pl.col('close')+.1).otherwise(pl.col('close')).alias('close'))
            factor=cached_factor(path);factor.matrix(changed,P)
            self.assertEqual(factor._persistent_cache.recursive_resumed_bars,0)
            pointer=next(p for p in path.glob('recursive-*') if p.is_file())
            state=path/('recursive-state-'+pointer.read_text())/'state.json'
            state.write_text('{}')
            factor=cached_factor(path);actual=factor.matrix(changed,P)
            self.assertEqual(factor._persistent_cache.recursive_resumed_bars,0)
            self.assertTrue(actual[0].equals(ClassicWyckoffFactor('position').matrix(changed,P)[0]))
            factor=cached_factor(path,'new-code');factor.matrix(changed,P)
            self.assertEqual(factor._persistent_cache.recursive_resumed_bars,0)

    def test_cancel_after_committed_chunk_then_resume(self):
        source=fixture();start=source['datetime'][0];rows=[]
        for i in range(800):
            row=source.row(i%source.height,named=True)
            row.update(datetime=start+timedelta(days=i),available_at=start+timedelta(days=i));rows.append(row)
        frame=pl.DataFrame(rows).cast(source.schema)
        with tempfile.TemporaryDirectory() as tmp:
            checks=0
            def cancel(stage=None,completed=None,total=None):
                nonlocal checks
                if stage is None:
                    checks+=1
                    if checks==6: raise ResearchCancelled('fixture cancellation')
            with research_progress(cancel),self.assertRaises(ResearchCancelled):
                cached_factor(Path(tmp)).matrix(frame,P)
            resumed=cached_factor(Path(tmp));actual=resumed.matrix(frame,P)
            expected=ClassicWyckoffFactor('position').matrix(frame,P)
            self.assertEqual(resumed._persistent_cache.recursive_resumed_bars,512)
            self.assertEqual(resumed._persistent_cache.recursive_processed_bars,288)
            self.assertTrue(actual[0].equals(expected[0]))
            self.assertEqual(actual[1:],expected[1:])

    def test_state_codec_has_no_arbitrary_type_loader(self):
        with self.assertRaises(ValueError):unpack_state(['record','UnknownClass',{}])
        with self.assertRaises(ValueError):pack_state(float('nan'))
        with self.assertRaises(ValueError):pack_state(object())
        value={'a':(True,None,1.2),'when':fixture()['datetime'][0]}
        self.assertEqual(unpack_state(pack_state(value)),value)
