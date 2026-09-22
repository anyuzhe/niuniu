"""Synthetic-only tests for bounded TDX date-axis and coverage queries."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from quantlab.data.tdx_lake import FAMILIES, QUALIFICATION, TdxLake
from quantlab.data.tdx_query import FAMILY_DATE_AXIS, _catalog_fingerprint


EVENT = {'bars_daily', 'bars_5m', 'bars_1m', 'trades', 'opening_match', 'auction', 'capital_changes'}
OBSERVED = {'depth', 'finance', 'quotes', 'securities', 'topics'}


class TdxCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root / 'catalog').mkdir()
        self.catalog = self.root / 'catalog/mqc.duckdb'
        with duckdb.connect(str(self.catalog)) as con:
            for family in FAMILIES:
                date_type = 'DATE' if family == 'bars_1m' else 'VARCHAR'
                con.execute(f'''CREATE TABLE tdx_{family}(
                    date {date_type}, code VARCHAR, observed_at VARCHAR, source_id VARCHAR,
                    record_index BIGINT, record_json VARCHAR, qualification VARCHAR)''')
        self.lake = TdxLake(self.root)

    def insert(self, family, rows):
        with duckdb.connect(str(self.catalog)) as con:
            con.executemany(f'INSERT INTO tdx_{family} VALUES (?,?,?,?,?,?,?)', rows)

    def test_all_thirteen_families_have_explicit_date_axes_and_empty_statistics(self):
        self.assertEqual(set(FAMILIES), set(FAMILY_DATE_AXIS)); self.assertEqual(len(FAMILIES), 13)
        for family in FAMILIES:
            with self.subTest(family=family):
                value = self.lake.coverage(family)
                expected = 'event_date' if family in EVENT else 'observed_date' if family in OBSERVED else 'batch_date'
                self.assertEqual(value['date_axis'], expected)
                self.assertEqual((value['rows'], value['codes'], value['source_ids']), (0, 0, 0))
                self.assertIsNone(value['observed_at_min']); self.assertIsNone(value['observed_at_max'])
                self.assertEqual(value['per_symbol_event_days'], None if expected != 'event_date' else {
                    'min': None, 'p25': None, 'median': None, 'p75': None, 'max': None})
                self.assertEqual(value['per_symbol_dates'], None if expected == 'event_date' else {
                    'min': None, 'p25': None, 'median': None, 'p75': None, 'max': None})
                self.assertFalse(value['source_bytes_verified']); self.assertFalse(value['history_complete'])
                self.assertFalse(value['strict_pit']); self.assertTrue(value['catalog_rows_only'])
        ladder = self.lake.coverage('limit_ladder')
        self.assertIn('trading_date_value', ladder['date_axis_note'])
        self.assertIn('not uniform event-date certification', ladder['date_axis_note'])

    def test_event_global_dates_do_not_inflate_per_symbol_days_and_duplicates_remain(self):
        rows = [
            ('2026-09-01', 'sh.600000', '2026-09-02T00:00:00+08:00', 'source-a', 0, '{}', QUALIFICATION),
            ('2026-09-01', 'sh.600000', '2026-09-02T00:00:00+08:00', 'source-a', 1, '{}', QUALIFICATION),
            ('2026-09-02', 'sh.600000', '2026-09-02T01:00:00+08:00', 'source-a', 2, '{}', QUALIFICATION),
            ('2026-09-02', 'sz.000001', '2026-09-02T02:00:00+08:00', 'source-b', 0, '{}', QUALIFICATION),
            ('2026-09-03', 'sz.000001', '2026-09-03T02:00:00+08:00', 'source-b', 1, '{}', QUALIFICATION),
            ('2026-09-04', 'bj.920001', None, 'source-b', 2, '{}', QUALIFICATION),
            ('2026-09-05', '', 'bad-observation', 'source-b', 3, '{}', QUALIFICATION),
            (None, None, '2026-09-06T12:00:00', None, 4, '{}', QUALIFICATION),
            ('not-a-date', 'bj.920001', '2026-09-06T12:00:00Z', 'source-b', 5, '{}', QUALIFICATION),
        ]
        self.insert('bars_daily', rows)
        value = self.lake.coverage('bars_daily')
        self.assertEqual(value['rows'], 9)  # duplicate rows are catalog rows, not silently deduplicated
        self.assertEqual(value['source_ids'], 2); self.assertNotEqual(value['rows'], value['source_ids'])
        self.assertEqual(value['codes'], 4)  # COUNT(DISTINCT code): includes '', excludes NULL
        self.assertEqual((value['empty_code_rows'], value['null_code_rows']), (1, 1))
        self.assertEqual((value['event_date_min'], value['event_date_max'], value['event_dates']),
                         ('2026-09-01', '2026-09-05', 5))
        self.assertEqual(value['per_symbol_event_days'], {'min': 1, 'p25': 1, 'median': 1.5, 'p75': 2, 'max': 2})
        self.assertLess(value['per_symbol_event_days']['max'], value['event_dates'])
        self.assertEqual((value['null_date_rows'], value['invalid_date_rows']), (1, 1))
        selected = self.lake.coverage('bars_daily', 'sh.600000', '2026-09-01', '2026-09-01')
        self.assertEqual(selected['rows'], 2); self.assertEqual(selected['event_dates'], 1)
        self.assertEqual(selected['per_symbol_event_days']['max'], 1)

    def test_observation_times_use_utc_instants_and_disclose_bad_null_and_naive_values(self):
        self.insert('depth', [
            ('2026-01-02', 'sh.600000', '2026-01-02T00:00:00+08:00', 's1', 0, '{}', QUALIFICATION),
            ('2026-01-01', 'sh.600000', '2026-01-01T18:00:00Z', 's1', 1, '{}', QUALIFICATION),
            ('bad-date', 'sz.000001', 'definitely-bad', 's2', 0, '{}', QUALIFICATION),
            (None, 'sz.000001', None, 's2', 1, '{}', QUALIFICATION),
            ('2026-01-03', 'sz.000001', '2026-01-03T12:00:00', 's2', 2, '{}', QUALIFICATION),
        ])
        value = self.lake.coverage('depth')
        # Lexical order would put 2026-01-01T18:00Z first; UTC instant order does not.
        self.assertEqual(value['observed_at_min'], '2026-01-01T16:00:00Z')
        self.assertEqual(value['observed_at_max'], '2026-01-01T18:00:00Z')
        self.assertEqual((value['valid_observed_at_rows'], value['invalid_observed_at_rows'],
                          value['null_observed_at_rows'], value['timezone_missing_observed_at_rows']),
                         (2, 1, 1, 1))
        self.assertEqual((value['date_min'], value['date_max'], value['distinct_dates']),
                         ('2026-01-01', '2026-01-03', 3))
        self.assertEqual((value['null_date_rows'], value['invalid_date_rows']), (1, 1))
        self.assertIsNone(value['event_dates']); self.assertIsNone(value['per_symbol_event_days'])
        self.assertTrue(self.lake.read('depth')['date_filter_is_not_event_date'])
        self.assertIn('date_filter_is_not_event_date', self.lake.read('depth')['warnings'])

    def test_read_keeps_old_rows_order_qualification_and_adds_only_axis_contract(self):
        self.insert('bars_1m', [
            ('2026-09-02', 'sz.000001', '2026-09-02T01:00:00Z', 'b', 1, '{"v":2}', QUALIFICATION),
            ('2026-09-01', 'sh.600000', '2026-09-01T01:00:00Z', 'a', 0, '{"v":1}', QUALIFICATION),
        ])
        value = self.lake.read('bars_1m', limit=20)
        self.assertEqual([row['source_id'] for row in value['rows']], ['a', 'b'])
        self.assertEqual(value['rows'][0]['record_json'], '{"v":1}')
        self.assertEqual(value['qualification'], QUALIFICATION)
        self.assertEqual(value['date_axis'], 'event_date'); self.assertFalse(value['date_filter_is_not_event_date'])
        self.assertFalse(value['strict_pit']); self.assertFalse(value['observation_versions_complete'])

    def test_read_and_coverage_reject_sql_identity_bool_noncanonical_and_reverse_ranges(self):
        calls = (
            lambda: self.lake.read('bars_daily; DROP TABLE tdx_bars_daily'),
            lambda: self.lake.coverage('bars_daily; DROP TABLE tdx_bars_daily'),
            lambda: self.lake.read('bars_daily', True),
            lambda: self.lake.coverage('bars_daily', True),
            lambda: self.lake.read('bars_daily', start=True),
            lambda: self.lake.coverage('bars_daily', start=True),
            lambda: self.lake.read('bars_daily', start='20260901'),
            lambda: self.lake.coverage('bars_daily', start='2026-9-01'),
            lambda: self.lake.read('bars_daily', start='2026-02-30'),
            lambda: self.lake.coverage('bars_daily', start='2026-09-02', end='2026-09-01'),
            lambda: self.lake.read('bars_daily', start='2026-09-02', end='2026-09-01'),
            lambda: self.lake.read('bars_daily', offset=True),
            lambda: self.lake.read('bars_daily', limit=True),
        )
        for call in calls:
            with self.subTest(call=call), self.assertRaises(ValueError): call()
        self.assertEqual(self.lake.coverage('bars_daily')['rows'], 0)

    def test_catalog_is_not_modified_and_source_change_or_unreadable_source_fails(self):
        before_hash = hashlib.sha256(self.catalog.read_bytes()).hexdigest()
        before_mtime = self.catalog.stat().st_mtime_ns
        before_names = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        value = self.lake.coverage('quotes')
        self.assertEqual(value['query_budget'], {'threads': 2, 'memory_limit': '512MB',
                                                'timeout_seconds': 30, 'temporary_spill': False})
        self.assertEqual(hashlib.sha256(self.catalog.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(self.catalog.stat().st_mtime_ns, before_mtime)
        self.assertEqual(sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')), before_names)

        fingerprint = _catalog_fingerprint(self.catalog)
        changed = fingerprint[:-1] + (fingerprint[-1] + 1,)
        with patch('quantlab.data.tdx_query._catalog_fingerprint', side_effect=[fingerprint, changed]):
            with self.assertRaisesRegex(ValueError, 'changed during'): self.lake.coverage('quotes')

        broken_root = self.root / 'broken'; (broken_root / 'catalog').mkdir(parents=True)
        (broken_root / 'catalog/mqc.duckdb').write_bytes(b'not a DuckDB database')
        with self.assertRaises(ValueError): TdxLake(broken_root).coverage('quotes')

    def test_root_and_catalog_symlinks_are_rejected(self):
        root_link = self.root.parent / (self.root.name + '-link')
        try:
            root_link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        self.addCleanup(lambda: root_link.unlink(missing_ok=True))
        with self.assertRaises(ValueError): TdxLake(root_link)

        outside = self.root / 'outside.duckdb'
        with duckdb.connect(str(outside)) as con: con.execute('CREATE TABLE x(i INTEGER)')
        linked_root = self.root / 'linked-root'; (linked_root / 'catalog').mkdir(parents=True)
        catalog_link = linked_root / 'catalog/mqc.duckdb'; catalog_link.symlink_to(outside)
        with self.assertRaises(ValueError): TdxLake(linked_root)


if __name__ == '__main__':
    unittest.main()
