"""Offline tests for the collection envelope in scripts/collect/.

Every test injects a fake fetcher, so the suite never touches a vendor endpoint
and never writes outside a temp directory. What is being pinned down here is the
part the receipt alone has to prove: that a non-empty target is refused, that a
dry run makes zero fetches, that resume adds without overwriting, and that
failed / empty / schema_issue stay three distinct states.
"""
import argparse
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from collect.envelope import CollectionRefused, Envelope, empty_marker_path, symbol_filename


def make_args(dest, **over):
    base = dict(dest=str(dest), receipt=None, universe=None, limit=None, throttle=0.0,
                retries=2, request_timeout=60.0, resume=False, dry_run=False,
                apply=True, fail_fast=False)
    base.update(over)
    return argparse.Namespace(**base)


def frame(code, rows=2):
    return pd.DataFrame({'证券代码': [code[3:]] * rows, '配股价格': [2.5] * rows,
                         '配股比例': [3.0] * rows, 'extra': [None] * rows})


class RecordingFetcher:
    """Fake vendor client. Records every call so 'no request was made' is testable."""

    def __init__(self, behaviour=None):
        self.calls = []
        self.behaviour = behaviour or {}

    def __call__(self, code):
        self.calls.append(code)
        what = self.behaviour.get(code, 'ok')
        if what == 'raise':
            raise RuntimeError('vendor said no')
        if what == 'empty':
            return pd.DataFrame()
        if what == 'short-schema':
            return pd.DataFrame({'证券代码': [code[3:]]})
        return frame(code)


class EnvelopeTests(unittest.TestCase):
    REQUIRED = ['证券代码', '配股价格', '配股比例']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / 'bronze'

    def env(self, args):
        return Envelope(args, name='t', source='fake', required_columns=self.REQUIRED, pandas=pd)

    def receipt(self, env):
        return json.loads(Path(env.receipt_path).read_text(encoding='utf-8'))

    # -- the gate -------------------------------------------------------------

    def test_non_empty_destination_is_refused_without_resume(self):
        self.dest.mkdir(parents=True)
        (self.dest / 'sh_600000.parquet').write_bytes(b'x')
        env = self.env(make_args(self.dest))
        with self.assertRaises(CollectionRefused):
            env.plan(['sh.600001'])

    def test_refusal_happens_before_any_fetch(self):
        self.dest.mkdir(parents=True)
        (self.dest / 'sh_600000.parquet').write_bytes(b'x')
        fetcher = RecordingFetcher()
        env = self.env(make_args(self.dest))
        with self.assertRaises(CollectionRefused):
            env.run(['sh.600001'], fetcher)
        self.assertEqual(fetcher.calls, [])

    # -- dry run --------------------------------------------------------------

    def test_request_timeout_interrupts_stalled_fetcher(self):
        env = self.env(make_args(self.dest, request_timeout=0.02))
        with self.assertRaises(TimeoutError):
            env._fetch_with_timeout(lambda _code: time.sleep(1), 'sh.600000')

    def test_dry_run_makes_no_request_and_writes_nothing(self):
        fetcher = RecordingFetcher()
        env = self.env(make_args(self.dest, dry_run=True))
        self.assertEqual(env.run(['sh.600000', 'sh.600001'], fetcher), 0)
        self.assertEqual(fetcher.calls, [])
        self.assertFalse(self.dest.exists())

    def test_apply_is_required_for_every_real_run(self):
        fetcher = RecordingFetcher()
        env = self.env(make_args(self.dest, apply=False))
        self.assertEqual(env.run(['sh.600000'], fetcher), 0)
        self.assertEqual(fetcher.calls, [])
        self.assertFalse(self.dest.exists())

    # -- the three outcome states --------------------------------------------

    def test_ok_empty_failed_and_schema_issue_stay_distinct(self):
        codes = ['sh.600000', 'sh.600001', 'sh.600002', 'sh.600003']
        fetcher = RecordingFetcher({'sh.600001': 'empty', 'sh.600002': 'raise',
                                    'sh.600003': 'short-schema'})
        env = self.env(make_args(self.dest))
        rc = env.run(codes, fetcher)
        rec = self.receipt(env)
        self.assertEqual(rc, 1)                                  # failures surface in the exit code
        self.assertEqual(rec['summary'],
                         {'ok': 1, 'empty': 1, 'failed': 1, 'schema_issue': 1, 'skipped_verified': 0})
        self.assertEqual([e['code'] for e in rec['ok']], ['sh.600000'])
        self.assertEqual([e['code'] for e in rec['failed']], ['sh.600002'])
        self.assertEqual(rec['schema_issue'][0]['missing'], ['配股价格', '配股比例'])
        # A failure leaves no file, so 'absent' is never ambiguous against 'never tried'.
        self.assertFalse((self.dest / symbol_filename('sh.600002')).exists())
        # Empty is a typed marker, never a schema-breaking zero-row parquet.
        self.assertFalse((self.dest / symbol_filename('sh.600001')).exists())
        self.assertTrue(empty_marker_path(self.dest, 'sh.600001').is_file())
        # A schema issue leaves no half-understood file either.
        self.assertFalse((self.dest / symbol_filename('sh.600003')).exists())

    def test_empty_marker_preserves_fetcher_evidence(self):
        def fetcher(_code):
            frame = pd.DataFrame()
            frame.attrs["http_status"] = 200
            frame.attrs["response_sha256"] = "a" * 64
            return frame
        env = self.env(make_args(self.dest))
        self.assertEqual(env.run(["sh.600000"], fetcher), 0)
        marker = json.loads(empty_marker_path(self.dest, "sh.600000").read_text())
        self.assertEqual(marker["evidence"]["http_status"], 200)
        self.assertEqual(marker["evidence"]["response_sha256"], "a" * 64)

    def test_failure_is_retried_up_to_the_limit(self):
        fetcher = RecordingFetcher({'sh.600000': 'raise'})
        env = self.env(make_args(self.dest, retries=3))
        env.run(['sh.600000'], fetcher)
        self.assertEqual(fetcher.calls, ['sh.600000'] * 3)

    # -- columns --------------------------------------------------------------

    def test_all_vendor_columns_are_preserved(self):
        env = self.env(make_args(self.dest))
        env.run(['sh.600000'], RecordingFetcher())
        back = pd.read_parquet(self.dest / symbol_filename('sh.600000'))
        self.assertEqual(list(back.columns), ['证券代码', '配股价格', '配股比例', 'extra'])
        self.assertEqual(self.receipt(env)['ok'][0]['columns'], list(back.columns))

    def test_numeric_columns_keep_their_dtype(self):
        env = self.env(make_args(self.dest))
        env.run(['sh.600000'], RecordingFetcher())
        back = pd.read_parquet(self.dest / symbol_filename('sh.600000'))
        self.assertEqual(back['配股价格'].dtype.kind, 'f')
        self.assertEqual(self.receipt(env)['ok'][0]['coerced_to_string'], [])

    # -- resume ---------------------------------------------------------------

    def test_resume_skips_verified_files_and_fetches_only_the_rest(self):
        first = RecordingFetcher({'sh.600002': 'raise'})
        env1 = self.env(make_args(self.dest))
        env1.run(['sh.600000', 'sh.600001', 'sh.600002'], first)
        sha_before = self.receipt(env1)['ok'][0]['sha256']

        second = RecordingFetcher()
        env2 = self.env(make_args(self.dest, resume=True))
        rc = env2.run(['sh.600000', 'sh.600001', 'sh.600002'], second)
        rec = self.receipt(env2)
        self.assertEqual(rc, 0)
        self.assertEqual(second.calls, ['sh.600002'])            # only the gap is re-requested
        self.assertEqual(sorted(rec['skipped_verified']), ['sh.600000', 'sh.600001'])
        # The already-good file is byte-identical: resume adds, it never rewrites.
        self.assertEqual(env1.receipt_path.parent.exists(), True)
        again = pd.read_parquet(self.dest / symbol_filename('sh.600000'))
        self.assertEqual(len(again), 2)
        from collect.envelope import sha256_file
        self.assertEqual(sha256_file(self.dest / symbol_filename('sh.600000')), sha_before)

    def test_resume_skips_verified_empty_marker(self):
        first = RecordingFetcher({'sh.600000': 'empty'})
        self.env(make_args(self.dest)).run(['sh.600000'], first)
        second = RecordingFetcher()
        self.env(make_args(self.dest, resume=True)).run(['sh.600000'], second)
        self.assertEqual(second.calls, [])

    def test_resume_re_fetches_a_corrupt_existing_file(self):
        self.dest.mkdir(parents=True)
        (self.dest / symbol_filename('sh.600000')).write_bytes(b'not parquet')
        fetcher = RecordingFetcher()
        env = self.env(make_args(self.dest, resume=True))
        env.run(['sh.600000'], fetcher)
        self.assertEqual(fetcher.calls, ['sh.600000'])
        self.assertEqual(len(pd.read_parquet(self.dest / symbol_filename('sh.600000'))), 2)

    # -- schema uniformity ----------------------------------------------------

    def test_uniform_destination_reports_a_single_signature(self):
        env = self.env(make_args(self.dest))
        env.run(['sh.600000', 'sh.600001'], RecordingFetcher())
        rec = self.receipt(env)
        self.assertTrue(rec['schema_is_uniform'])
        self.assertEqual(len(rec['column_signatures']), 1)
        self.assertEqual(rec['column_signatures'][0]['n_files'], 2)

    def test_resume_over_a_truncated_predecessor_is_flagged_not_hidden(self):
        # Reproduces the real hazard: the old cninfo collector wrote a 16-column
        # projection, so topping it up at full vendor width silently mixes schemas.
        self.dest.mkdir(parents=True)
        frame('sh.600000')[['证券代码', '配股价格', '配股比例']].to_parquet(
            self.dest / symbol_filename('sh.600000'), index=False)
        env = self.env(make_args(self.dest, resume=True))
        env.run(['sh.600000', 'sh.600001'], RecordingFetcher())
        rec = self.receipt(env)
        self.assertFalse(rec['schema_is_uniform'])
        self.assertEqual(sorted(s['n_columns'] for s in rec['column_signatures']), [3, 4])

    # -- misc -----------------------------------------------------------------

    def test_fail_fast_stops_and_records_it(self):
        fetcher = RecordingFetcher({'sh.600001': 'raise'})
        env = self.env(make_args(self.dest, fail_fast=True, retries=1))
        env.run(['sh.600000', 'sh.600001', 'sh.600002'], fetcher)
        rec = self.receipt(env)
        self.assertTrue(rec['stopped_early'])
        self.assertNotIn('sh.600002', fetcher.calls)

    def test_limit_truncates_the_plan(self):
        fetcher = RecordingFetcher()
        env = self.env(make_args(self.dest, limit=1))
        env.run(['sh.600000', 'sh.600001'], fetcher)
        self.assertEqual(fetcher.calls, ['sh.600000'])

    def test_non_positive_limit_is_refused(self):
        env = self.env(make_args(self.dest, limit=0))
        with self.assertRaises(CollectionRefused):
            env.plan(['sh.600000'])

    def test_symbol_filename_rejects_path_separators(self):
        self.assertEqual(symbol_filename('sh.600000'), 'sh_600000.parquet')
        with self.assertRaises(ValueError):
            symbol_filename('../etc/passwd')


if __name__ == '__main__':
    unittest.main()
