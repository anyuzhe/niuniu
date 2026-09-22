"""Bounded, read-only query helpers for the TDX catalog.

Family names are mapped to static identifiers here.  Callers can bind values, but
cannot supply SQL or an identifier.  The catalog is retrospective personal-
research inventory: none of these helpers certifies PIT, continuity, deduplication,
source bytes, or complete observation-version history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import threading

import duckdb

EVENT_DATE_FAMILIES = frozenset({
    'bars_daily', 'bars_5m', 'bars_1m', 'trades', 'opening_match', 'auction',
    'capital_changes',
})
OBSERVED_DATE_FAMILIES = frozenset({'depth', 'finance', 'quotes', 'securities', 'topics'})
FAMILY_DATE_AXIS = {
    **{family: 'event_date' for family in EVENT_DATE_FAMILIES},
    **{family: 'observed_date' for family in OBSERVED_DATE_FAMILIES},
    'limit_ladder': 'batch_date',
}
FAMILY_TABLE = {family: 'tdx_' + family for family in FAMILY_DATE_AXIS}
QUERY_TIMEOUT_SECONDS = 30
QUERY_MEMORY_LIMIT = '512MB'
QUERY_THREADS = 2


def family_table(family: str) -> str:
    """Return only a predeclared SQL identifier; never interpolate caller SQL."""
    if type(family) is not str or family not in FAMILY_TABLE:
        raise ValueError('Invalid TDX family')
    return FAMILY_TABLE[family]


def validate_text_filters(symbol='', start='', end=''):
    if type(symbol) is not str or (symbol and not re.fullmatch(r'(?:sh|sz|bj)\.\d{6}', symbol)):
        raise ValueError('Invalid symbol')
    parsed = []
    for value in (start, end):
        if type(value) is not str or (value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise ValueError('Invalid canonical date')
        try:
            parsed.append(datetime.strptime(value, '%Y-%m-%d').date() if value else None)
        except ValueError as error:
            raise ValueError('Invalid canonical date') from error
    if parsed[0] and parsed[1] and parsed[0] > parsed[1]:
        raise ValueError('start must be <= end')
    return parsed


def read_contract(family: str) -> dict:
    axis = FAMILY_DATE_AXIS[family]
    warning = axis != 'event_date'
    if axis == 'observed_date':
        note = ('date is the Asia/Shanghai observation date derived from observed_at; it is not an '
                'event date and stored snapshots do not prove complete observation-version history')
    elif axis == 'batch_date':
        note = ('date is a batch/date axis; some limit_ladder rows derive it from trading_date_value '
                'while others use the request day, so it is not uniform event-date certification')
    else:
        note = ('date is the stored vendor event-date axis; rows remain non-PIT observations and do '
                'not prove continuous or complete event history')
    return {
        'date_axis': axis,
        'date_filter_is_not_event_date': warning,
        'warnings': ['date_filter_is_not_event_date'] if warning else [],
        'strict_pit': False,
        'observation_versions_complete': False,
        'version_semantics': note,
    }


def _catalog_fingerprint(path: Path) -> tuple[int, int, int, int]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('TDX catalog must be a readable regular file')
    try:
        with path.open('rb') as stream:
            stream.read(1)
        stat = path.stat()
    except OSError as error:
        raise ValueError('TDX catalog is not readable') from error
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _utc_iso(epoch_seconds):
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(float(epoch_seconds), timezone.utc).isoformat().replace('+00:00', 'Z')


def _number(value):
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _distribution(row: dict) -> dict:
    return {key: _number(row[key]) for key in ('min', 'p25', 'median', 'p75', 'max')}


def _coverage_sql(table: str, terms: list[str]) -> str:
    where = ' WHERE ' + ' AND '.join(terms) if terms else ''
    # observed_at is accepted as timezone-aware only when its text has an explicit
    # ISO offset/Z suffix.  Naive values are counted separately and never converted
    # using the host/session timezone.
    return f"""
      WITH selected AS MATERIALIZED (
        SELECT * FROM {table}{where}
      ), typed AS MATERIALIZED (
        SELECT *, try_cast(date AS DATE) AS typed_date,
          trim(cast(observed_at AS VARCHAR)) AS observed_text
        FROM selected
      ), classified AS MATERIALIZED (
        SELECT *,
          (observed_at IS NOT NULL AND
           regexp_matches(observed_text, '[T ][0-9]{{2}}:[0-9]{{2}}.*([zZ]|[+-][0-9]{{2}}(:?[0-9]{{2}})?)$') AND
           try_cast(observed_at AS TIMESTAMPTZ) IS NOT NULL) AS aware_valid,
          (observed_at IS NOT NULL AND NOT regexp_matches(
             observed_text, '[T ][0-9]{{2}}:[0-9]{{2}}.*([zZ]|[+-][0-9]{{2}}(:?[0-9]{{2}})?)$') AND
           try_cast(observed_at AS TIMESTAMP) IS NOT NULL) AS naive_valid
        FROM typed
      ), per_code AS MATERIALIZED (
        SELECT code, count(DISTINCT typed_date)::BIGINT AS date_count
        FROM classified WHERE code IS NOT NULL GROUP BY code
      ), totals AS (
        SELECT count(*)::BIGINT AS row_count,
          count(DISTINCT code)::BIGINT AS code_count,
          count(DISTINCT source_id)::BIGINT AS source_count,
          count(*) FILTER (WHERE code IS NULL)::BIGINT AS null_code_rows,
          count(*) FILTER (WHERE code = '')::BIGINT AS empty_code_rows,
          count(*) FILTER (WHERE source_id IS NULL)::BIGINT AS null_source_id_rows,
          count(*) FILTER (WHERE source_id = '')::BIGINT AS empty_source_id_rows,
          min(typed_date) AS date_min, max(typed_date) AS date_max,
          count(DISTINCT typed_date)::BIGINT AS distinct_dates,
          count(*) FILTER (WHERE date IS NULL)::BIGINT AS null_date_rows,
          count(*) FILTER (WHERE date IS NOT NULL AND typed_date IS NULL)::BIGINT AS invalid_date_rows,
          count(*) FILTER (WHERE observed_at IS NULL)::BIGINT AS null_observed_at_rows,
          count(*) FILTER (WHERE aware_valid)::BIGINT AS valid_observed_at_rows,
          count(*) FILTER (WHERE naive_valid)::BIGINT AS timezone_missing_observed_at_rows,
          count(*) FILTER (WHERE observed_at IS NOT NULL AND NOT aware_valid AND NOT naive_valid)::BIGINT
            AS invalid_observed_at_rows,
          min(CASE WHEN aware_valid THEN epoch(try_cast(observed_at AS TIMESTAMPTZ)) END) AS observed_min_epoch,
          max(CASE WHEN aware_valid THEN epoch(try_cast(observed_at AS TIMESTAMPTZ)) END) AS observed_max_epoch
        FROM classified
      ), percentiles AS (
        SELECT min(date_count) AS min,
          quantile_cont(date_count, 0.25) AS p25,
          median(date_count) AS median,
          quantile_cont(date_count, 0.75) AS p75,
          max(date_count) AS max
        FROM per_code
      )
      SELECT totals.*, percentiles.* FROM totals CROSS JOIN percentiles
    """


def catalog_coverage(catalog, family, symbol='', start='', end='') -> dict:
    """Aggregate every selected catalog row in one bounded read-only transaction."""
    table = family_table(family)
    validate_text_filters(symbol, start, end)
    path = Path(catalog)
    before = _catalog_fingerprint(path)
    terms = []
    args = []
    if symbol:
        terms.append('code = ?'); args.append(symbol)
    if start:
        terms.append('try_cast(date AS DATE) >= ?::DATE'); args.append(start)
    if end:
        terms.append('try_cast(date AS DATE) <= ?::DATE'); args.append(end)
    sql = _coverage_sql('tdx_catalog.' + table, terms)
    try:
        # An isolated in-memory coordinator permits hard per-query resources even
        # when another reader already has the catalog open with different settings.
        # The only attached source is explicitly READ_ONLY; no catalog/temp write is allowed.
        with duckdb.connect(':memory:', config={
                'threads': QUERY_THREADS, 'memory_limit': QUERY_MEMORY_LIMIT,
                'temp_directory': ''}) as con:
            con.execute("SET max_temp_directory_size='0B'")
            con.execute("SET TimeZone='UTC'")
            escaped = str(path).replace("'", "''")
            con.execute("ATTACH '" + escaped + "' AS tdx_catalog (READ_ONLY)")
            con.execute('BEGIN TRANSACTION')
            timer = threading.Timer(QUERY_TIMEOUT_SECONDS, con.interrupt)
            timer.daemon = True; timer.start()
            try:
                values = con.execute(sql, args).fetchone()
                columns = [item[0] for item in con.description]
                con.execute('COMMIT')
            except Exception:
                try: con.execute('ROLLBACK')
                except duckdb.Error: pass
                raise
            finally:
                timer.cancel(); timer.join()
    except duckdb.InterruptException as error:
        raise ValueError('TDX coverage query exceeded the 30-second CPU/wall budget') from error
    except duckdb.Error as error:
        raise ValueError('TDX coverage could not read the selected catalog family') from error
    after = _catalog_fingerprint(path)
    if before != after:
        raise ValueError('TDX catalog changed during coverage query')
    row = dict(zip(columns, values))
    axis = FAMILY_DATE_AXIS[family]
    distribution = _distribution(row)
    event = axis == 'event_date'
    date_min = row['date_min'].isoformat() if row['date_min'] is not None else None
    date_max = row['date_max'].isoformat() if row['date_max'] is not None else None
    contract = read_contract(family)
    return {
        'family': family,
        'date_axis': axis,
        'date_filter_is_not_event_date': contract['date_filter_is_not_event_date'],
        'warnings': list(contract['warnings']),
        'filter': {'symbol': symbol, 'start': start, 'end': end, 'date_column': 'date'},
        'rows': int(row['row_count']),
        'codes': int(row['code_count']),
        'source_ids': int(row['source_count']),
        'null_code_rows': int(row['null_code_rows']),
        'empty_code_rows': int(row['empty_code_rows']),
        'null_source_id_rows': int(row['null_source_id_rows']),
        'empty_source_id_rows': int(row['empty_source_id_rows']),
        'null_date_rows': int(row['null_date_rows']),
        'invalid_date_rows': int(row['invalid_date_rows']),
        'event_date_min': date_min if event else None,
        'event_date_max': date_max if event else None,
        'event_dates': int(row['distinct_dates']) if event else None,
        'per_symbol_event_days': distribution if event else None,
        'date_min': None if event else date_min,
        'date_max': None if event else date_max,
        'distinct_dates': None if event else int(row['distinct_dates']),
        'per_symbol_dates': None if event else distribution,
        'observed_at_min': _utc_iso(row['observed_min_epoch']),
        'observed_at_max': _utc_iso(row['observed_max_epoch']),
        'valid_observed_at_rows': int(row['valid_observed_at_rows']),
        'null_observed_at_rows': int(row['null_observed_at_rows']),
        'timezone_missing_observed_at_rows': int(row['timezone_missing_observed_at_rows']),
        'invalid_observed_at_rows': int(row['invalid_observed_at_rows']),
        'catalog_rows_only': True,
        'source_bytes_verified': False,
        'history_complete': False,
        'strict_pit': False,
        'observation_versions_complete': False,
        'date_axis_note': contract['version_semantics'],
        'per_symbol_date_semantics': ('distinct valid dates for every non-null code in the selected rows; '
                                      "the empty-string code is included, NULL code is disclosed but excluded; "
                                      'no global-range completeness is inferred'),
        'limitations': [
            'Catalog row aggregation only; duplicates are retained in rows and are not certified away.',
            'No PIT, continuity, completeness, deduplication, or source-byte certification.',
            'Per-symbol date counts describe selected rows only and do not infer single-security coverage from a global range.',
        ],
        'query_budget': {'threads': QUERY_THREADS, 'memory_limit': QUERY_MEMORY_LIMIT,
                         'timeout_seconds': QUERY_TIMEOUT_SECONDS, 'temporary_spill': False},
    }
