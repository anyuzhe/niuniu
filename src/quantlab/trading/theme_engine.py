"""Daily machine theme facts from archived Eastmoney evidence (research_only).

For one trading day the engine joins the archived limit-up / broken-board / limit-down pools
with the latest board-membership snapshot taken on or before that day, and reports per board:
limit-up count and streak ladder, leader candidates, seal funds, broken and limit-down counts,
board quotes, and how many consecutive archived trading days the board has had limit-ups.
These are facts with a versioned ranking rule; no theme state or AI judgment is inferred.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import io
import json
import re

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'theme-daily-facts-v1'
RULES_VERSION = 'theme-facts-v1'
FAMILIES = {'concept': {'members': 'em_concept_board_members', 'quotes': 'em_concept_boards', 'label': '概念'},
            'industry': {'members': 'em_industry_board_members', 'quotes': 'em_industry_boards', 'label': '行业'}}
POOLS = {'limit_up': 'em_limit_up_pool', 'broken': 'em_broken_board_pool', 'limit_down': 'em_limit_down_pool'}
MEMBERSHIP_MAX_AGE_DAYS = 10
PERSISTENCE_LOOKBACK = 20
ACTIVE_MIN_LIMIT_UPS = 3
TWENTY_CM_PREFIXES = ('sz.300', 'sz.301', 'sz.302', 'sh.688', 'sh.689')
# Eastmoney "concept" lists also carry index, holder, style, report-forecast and yesterday-pool
# baskets. They are kept in the data but never ranked as themes.
GENERIC_NAME_PATTERNS = (
    '昨日', '最近多板', 'HS300', '上证50', '上证180', '上证380', '深成500', '中证500', '深证100', '央视50', 'MSCI', '富时罗素',
    '标准普尔', '创业成份', '创业板综', '融资融券', '沪股通', '深股通', 'AB股', 'AH股', 'B股', 'GDR', '重仓', '证金持股', '券商金股',
    '参股', '转债标的', 'ST股', '次新股', '破净', '破发', '破增发', '低价股', '百元股', '微盘', '小盘', '中盘', '大盘', '权重股',
    '行业龙头', '价值股', '周期股', '红利股', '微利股', '高成长股', '预增', '预减', '扭亏', '首亏', '新高', '超跌股', '近期摘帽',
    '股权集中', '股权分散', '密集调研', '风格', '趋势股', '反转股', '题材股', '市净率', '东方财富热股', '茅指数', '宁组合',
    '科创板做市', '举牌', 'IPO受益', '北交所概念')
GENERIC_EXACT_NAMES = ('养老金',)
LIMITATIONS = [
    '股池、板块成分与板块行情来自东方财富公开网页接口的收盘后归档，是供应商口径（涨停池、炸板池、跌停池均不含 ST），不是交易所官方数据；资格 research_only。',
    '板块成分取交易日当日或之前最近一次快照（最长 10 个自然日）；成分会被供应商事后调整，持续天数用当前成分回看历史股池，偏向当前热门成分。',
    '持续天数只统计已归档的连续交易日，遇到缺档即截断并标记。',
    '排序规则是工程设定（涨停家数、最高连板、封板资金、成分数），不是题材强弱判断；机器状态一律 UNKNOWN。',
]
BUILD = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
THEME_SCHEMA = {
    'family': pl.String, 'board_code': pl.String, 'board_name': pl.String, 'is_generic': pl.Boolean, 'membership_day': pl.String,
    'membership_age_days': pl.Int64, 'constituents': pl.Int64, 'limit_up_count': pl.Int64, 'twenty_cm_limit_up_count': pl.Int64,
    'first_board_count': pl.Int64, 'streak_2_count': pl.Int64, 'streak_3_count': pl.Int64, 'streak_4_count': pl.Int64,
    'streak_5plus_count': pl.Int64, 'max_streak': pl.Int64, 'broken_count': pl.Int64, 'limit_down_count': pl.Int64,
    'seal_fund_total': pl.Float64, 'earliest_first_seal_time': pl.String, 'leader_symbols': pl.List(pl.String), 'leaders': pl.String,
    'board_pct_change': pl.Float64, 'breadth_up': pl.Int64, 'breadth_down': pl.Int64, 'board_amount': pl.Float64,
    'limit_up_count_prev': pl.Int64, 'persistence_days': pl.Int64, 'persistence_days_3plus': pl.Int64,
    'persistence_history_days': pl.Int64, 'persistence_truncated': pl.Boolean, 'rank': pl.Int64,
}


class ThemeEngineError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def is_generic(name):
    name = name or ''
    return name in GENERIC_EXACT_NAMES or any(pattern in name for pattern in GENERIC_NAME_PATTERNS)


def code_fingerprint():
    payload = Path(__file__).resolve().read_bytes()
    return {'files': {'theme_engine.py': hashlib.sha256(payload).hexdigest()}, 'digest': hashlib.sha256(payload).hexdigest()}


def _counts_by_board(membership, symbols, alias):
    if not symbols:
        return pl.DataFrame(schema={'board_code': pl.String, alias: pl.Int64})
    return (membership.filter(pl.col('symbol').is_in(sorted(symbols))).group_by('board_code')
            .agg(pl.len().cast(pl.Int64).alias(alias)))


def compute_family(day, family, membership, membership_day, pools, quotes=None, history=(), truncated=False):
    """Per-board facts for one family.

    ``pools``: dict with polars frames for limit_up / broken / limit_down (archived table schemas).
    ``history``: previous archived trading days (most recent first) as ``(day, limit_up_symbols)``,
    stopping before the first missing day; ``truncated`` records that a missing day (not the lookback limit) ended it.
    """
    day = date.fromisoformat(day) if isinstance(day, str) else day
    members = membership.select('board_code', 'board_name', 'symbol').unique()
    boards = members.group_by('board_code').agg(pl.col('board_name').first(), pl.len().cast(pl.Int64).alias('constituents'))
    up = pools['limit_up'].select('symbol', 'name', 'pct_change', 'limit_up_streak', 'first_seal_time', 'seal_fund')
    joined = members.join(up, on='symbol', how='inner')
    streak = pl.col('limit_up_streak')
    ladder = joined.group_by('board_code').agg(
        pl.len().cast(pl.Int64).alias('limit_up_count'),
        pl.any_horizontal([pl.col('symbol').str.starts_with(prefix) for prefix in TWENTY_CM_PREFIXES]).sum().cast(pl.Int64)
        .alias('twenty_cm_limit_up_count'),
        (streak == 1).sum().cast(pl.Int64).alias('first_board_count'), (streak == 2).sum().cast(pl.Int64).alias('streak_2_count'),
        (streak == 3).sum().cast(pl.Int64).alias('streak_3_count'), (streak == 4).sum().cast(pl.Int64).alias('streak_4_count'),
        (streak >= 5).sum().cast(pl.Int64).alias('streak_5plus_count'), streak.max().cast(pl.Int64).alias('max_streak'),
        pl.col('seal_fund').sum().alias('seal_fund_total'), pl.col('first_seal_time').min().alias('earliest_first_seal_time'))
    ordered = joined.sort(['board_code', 'limit_up_streak', 'first_seal_time', 'seal_fund', 'symbol'],
                          descending=[False, True, False, True, False], nulls_last=True)
    leaders = ordered.group_by('board_code', maintain_order=True).head(3).group_by('board_code', maintain_order=True).agg(
        pl.col('symbol').alias('leader_symbols'),
        pl.concat_str([pl.col('symbol'), pl.col('name'), pl.col('limit_up_streak').cast(pl.String) + pl.lit('板'),
                       pl.col('first_seal_time').fill_null('?')], separator=' ').str.join('；').alias('leaders'))
    frame = (boards.join(ladder, on='board_code', how='left').join(leaders, on='board_code', how='left')
             .join(_counts_by_board(members, set(pools['broken']['symbol'].to_list()), 'broken_count'), on='board_code', how='left')
             .join(_counts_by_board(members, set(pools['limit_down']['symbol'].to_list()), 'limit_down_count'), on='board_code', how='left'))
    if quotes is not None and quotes.height:
        frame = frame.join(quotes.select('board_code', pl.col('pct_change').alias('board_pct_change'), pl.col('up_count').cast(pl.Int64).alias('breadth_up'),
                                         pl.col('down_count').cast(pl.Int64).alias('breadth_down'), pl.col('amount').alias('board_amount')),
                           on='board_code', how='left')
    else:
        frame = frame.with_columns(pl.lit(None, pl.Float64).alias('board_pct_change'), pl.lit(None, pl.Int64).alias('breadth_up'),
                                   pl.lit(None, pl.Int64).alias('breadth_down'), pl.lit(None, pl.Float64).alias('board_amount'))
    counts = ['limit_up_count', 'twenty_cm_limit_up_count', 'first_board_count', 'streak_2_count', 'streak_3_count', 'streak_4_count',
              'streak_5plus_count', 'broken_count', 'limit_down_count']
    frame = frame.with_columns([pl.col(c).fill_null(0) for c in counts] + [pl.col('max_streak').fill_null(0), pl.col('seal_fund_total').fill_null(0.0)])
    # Persistence: consecutive archived trading days (ending today) with >=1 and >=3 limit-ups, using today's membership.
    history_counts = []
    for past_day, symbols in history:
        history_counts.append(_counts_by_board(members, set(symbols), 'n').with_columns(pl.lit(past_day.isoformat()).alias('day')))
    persistence = frame.select('board_code', pl.col('limit_up_count').alias('n0'))
    run1 = (pl.col('n0') >= 1).cast(pl.Int64)
    run3 = (pl.col('n0') >= ACTIVE_MIN_LIMIT_UPS).cast(pl.Int64)
    alive1, alive3 = (pl.col('n0') >= 1), (pl.col('n0') >= ACTIVE_MIN_LIMIT_UPS)
    prev_count = pl.lit(None, pl.Int64)
    for index, counts_frame in enumerate(history_counts, start=1):
        name = f'n{index}'
        persistence = persistence.join(counts_frame.select('board_code', pl.col('n').alias(name)), on='board_code', how='left').with_columns(
            pl.col(name).fill_null(0))
        alive1 = alive1 & (pl.col(name) >= 1)
        alive3 = alive3 & (pl.col(name) >= ACTIVE_MIN_LIMIT_UPS)
        run1 = run1 + alive1.cast(pl.Int64)
        run3 = run3 + alive3.cast(pl.Int64)
        if index == 1:
            prev_count = pl.col(name)
    persistence = persistence.select('board_code', run1.alias('persistence_days'), run3.alias('persistence_days_3plus'),
                                     prev_count.cast(pl.Int64).alias('limit_up_count_prev'))
    frame = frame.join(persistence, on='board_code', how='left').with_columns(
        pl.lit(family).alias('family'),
        (pl.col('board_name').fill_null('').str.contains_any(list(GENERIC_NAME_PATTERNS)) | pl.col('board_name').is_in(list(GENERIC_EXACT_NAMES)))
        .alias('is_generic'),
        pl.lit(membership_day).alias('membership_day'),
        pl.lit((day - date.fromisoformat(membership_day)).days, pl.Int64).alias('membership_age_days'),
        pl.lit(len(history), pl.Int64).alias('persistence_history_days'))
    ranked = frame.filter(~pl.col('is_generic') & (pl.col('limit_up_count') > 0)).sort(
        ['limit_up_count', 'max_streak', 'seal_fund_total', 'constituents', 'board_code'], descending=[True, True, True, False, False]
    ).with_row_index('rank', offset=1).select('board_code', pl.col('rank').cast(pl.Int64))
    frame = frame.join(ranked, on='board_code', how='left').with_columns(pl.lit(bool(truncated)).alias('persistence_truncated'))
    return frame.select([pl.col(name).cast(dtype) for name, dtype in THEME_SCHEMA.items()]).sort(
        ['rank', 'board_code'], nulls_last=True)


def pool_industries(limit_up):
    """Limit-ups grouped by the pool's own (truncated) industry label; available without membership snapshots."""
    return limit_up.group_by('industry').agg(
        pl.len().cast(pl.Int64).alias('limit_up_count'), pl.col('limit_up_streak').max().cast(pl.Int64).alias('max_streak'),
        pl.col('seal_fund').sum().alias('seal_fund_total'),
        pl.col('symbol').sort_by('limit_up_streak', descending=True).head(3).alias('top_symbols')).sort(
        ['limit_up_count', 'max_streak', 'industry'], descending=[True, True, False])


class ThemeFactsLibrary:
    def __init__(self, output, *, now_fn=None, evidence=None, calendar_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise ThemeEngineError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._evidence = evidence
        self.calendar_fn = calendar_fn
        self.root = self.output / '_limit_research' / 'theme_daily'

    # ---- inputs ------------------------------------------------------------------------------------
    def evidence(self):
        if self._evidence is None:
            from quantlab.data.public_evidence import PublicEvidenceArchive
            self._evidence = PublicEvidenceArchive(self.output)
        return self._evidence

    def previous_trading_days(self, day, count):
        if self.calendar_fn is not None:
            return self.calendar_fn(day, count)
        from quantlab.data.forward_daily import ForwardDailyError, ForwardReferenceArchive
        try:
            archive = ForwardReferenceArchive(self.output)
            reference = archive.load(archive.latest_covering(day)['snapshot_id'])
        except ForwardDailyError:
            return None
        days = sorted((date.fromisoformat(d) for d, flag in reference['trade_calendar'] if flag == '1' and d < day.isoformat()), reverse=True)
        return days[:count]

    def _accepted(self, source, day):
        from quantlab.data.public_evidence import PublicEvidenceError
        try:
            return self.evidence().get(source, day)
        except PublicEvidenceError as error:
            if error.code == 'NOT_FOUND':
                return None
            raise ThemeEngineError(error.code, str(error)) from None

    def _table(self, source, day):
        frame, manifest = self.evidence().read_table(source, day)
        return frame, {'source_id': source, 'trading_day': manifest['trading_day'], 'capture_id': manifest['capture_id'],
                       'content_hash': manifest['content_hash'], 'finished_at': manifest['finished_at']}

    def _membership(self, family, day):
        source = FAMILIES[family]['members']
        for row in self.evidence().list_days(source, limit=40):
            if 'error' in row:
                continue
            captured = date.fromisoformat(row['trading_day'])
            if captured <= day:
                if (day - captured).days > MEMBERSHIP_MAX_AGE_DAYS:
                    return None
                return self._table(source, captured)
        return None

    def resolve(self, day):
        """Collect and identify every input for ``day`` without computing facts."""
        day = date.fromisoformat(day) if isinstance(day, str) else day
        inputs, pools = [], {}
        missing = [source for source in POOLS.values() if self._accepted(source, day) is None]
        if missing:
            raise ThemeEngineError('POOLS_MISSING', f'{day} 缺少已接受的股池归档：' + ', '.join(missing))
        for key, source in POOLS.items():
            pools[key], meta = self._table(source, day)
            inputs.append(meta)
        families, skipped = {}, {}
        for family, sources in FAMILIES.items():
            membership = self._membership(family, day)
            if membership is None:
                skipped[family] = 'MEMBERSHIP_UNAVAILABLE'
                continue
            quotes = None
            if self._accepted(sources['quotes'], day) is not None:
                quotes, quote_meta = self._table(sources['quotes'], day)
                inputs.append(quote_meta)
            inputs.append(membership[1])
            families[family] = {'membership': membership[0], 'membership_day': membership[1]['trading_day'], 'quotes': quotes}
        previous = self.previous_trading_days(day, PERSISTENCE_LOOKBACK)
        history, truncated = [], previous is None
        for past in previous or []:
            if self._accepted(POOLS['limit_up'], past) is None:
                truncated = True
                break
            frame, meta = self._table(POOLS['limit_up'], past)
            history.append((past, frame['symbol'].to_list()))
            inputs.append(meta)
        identity = {'format': FORMAT, 'rules_version': RULES_VERSION, 'code_fingerprint': code_fingerprint()['digest'],
                    'trading_day': day.isoformat(), 'inputs': [{k: v for k, v in meta.items() if k != 'finished_at'} for meta in inputs],
                    'skipped_families': skipped, 'history_days': [d.isoformat() for d, _ in history], 'history_truncated': truncated}
        return {'day': day, 'pools': pools, 'families': families, 'history': history, 'truncated': truncated, 'inputs': inputs,
                'identity': identity, 'build_id': str(uuid5(NAMESPACE_URL, 'niuniu-theme-facts:' + digest(identity)))}

    # ---- builds ------------------------------------------------------------------------------------
    def _day_dir(self, day):
        for path in (self.output / '_limit_research', self.root):
            if path.is_symlink():
                raise ThemeEngineError('INVALID_WORKSPACE', '题材事实目录不能是符号链接。')
        return self.root / (day.isoformat() if isinstance(day, date) else date.fromisoformat(day).isoformat())

    def is_current(self, day):
        """True when a build over exactly the currently accepted inputs already exists."""
        try:
            resolved = self.resolve(day)
        except ThemeEngineError:
            return False
        return (self._day_dir(resolved['day']) / resolved['build_id'] / 'manifest.json').is_file()

    def build(self, day):
        resolved = self.resolve(day)
        folder = self._day_dir(resolved['day']) / resolved['build_id']
        if folder.exists():
            return {**self.get(resolved['day'], resolved['build_id']), 'created': False}
        frames = []
        for family, item in resolved['families'].items():
            frames.append(compute_family(resolved['day'], family, item['membership'], item['membership_day'], resolved['pools'],
                                         item['quotes'], resolved['history'], resolved['truncated']))
        themes = pl.concat(frames, how='vertical') if frames else pl.DataFrame(schema=THEME_SCHEMA)
        industries = pool_industries(resolved['pools']['limit_up'])
        payloads = {}
        for name, frame in (('themes.parquet', themes), ('pool_industries.parquet', industries)):
            stream = io.BytesIO()
            frame.write_parquet(stream, compression='zstd')
            payloads[name] = stream.getvalue()
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise ThemeEngineError('INVALID_CLOCK', '时钟必须带时区。')
        facts_as_of = max(meta['finished_at'] for meta in resolved['inputs'])
        top = {family: themes.filter((pl.col('family') == family) & pl.col('rank').is_not_null()).sort('rank').head(10).select(
            'rank', 'board_code', 'board_name', 'limit_up_count', 'max_streak', 'persistence_days').to_dicts() for family in resolved['families']}
        manifest = {**resolved['identity'], 'build_id': resolved['build_id'], 'created_at': created.astimezone(timezone.utc).isoformat(),
                    'facts_as_of': facts_as_of, 'families': sorted(resolved['families']),
                    'rows': themes.height, 'pool_limit_ups': resolved['pools']['limit_up'].height, 'top': top,
                    'files': {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()},
                    'active_min_limit_ups': ACTIVE_MIN_LIMIT_UPS, 'generic_name_patterns': list(GENERIC_NAME_PATTERNS),
                    'generic_exact_names': list(GENERIC_EXACT_NAMES), 'qualification': 'research_only', 'limitations': LIMITATIONS}
        folder.parent.mkdir(parents=True, exist_ok=True)
        temporary = folder.parent / ('.tmp-' + str(uuid4()))
        temporary.mkdir()
        for name, payload in payloads.items():
            (temporary / name).write_bytes(payload)
        (temporary / 'manifest.json').write_text(encode({**manifest, 'checksum': digest(manifest)}), encoding='utf-8')
        temporary.replace(folder)
        return {**manifest, 'created': True}

    def get(self, day, build_id=None):
        folder = self._day_dir(day)
        if build_id is None:
            builds = [p for p in folder.iterdir() if p.is_dir() and BUILD.fullmatch(p.name)] if folder.is_dir() else []
            if not builds:
                raise ThemeEngineError('NOT_FOUND', f'{day} 没有题材事实 build。')
            manifests = [self.get(day, p.name) for p in builds]
            return max(manifests, key=lambda m: (m['created_at'], m['build_id']))
        if not BUILD.fullmatch(build_id or ''):
            raise ThemeEngineError('INVALID_ARGUMENT', 'build_id 无效。')
        path = folder / build_id / 'manifest.json'
        if path.is_symlink() or not path.is_file():
            raise ThemeEngineError('NOT_FOUND', '题材事实 build 不存在。')
        value = json.loads(path.read_bytes())
        core = {k: v for k, v in value.items() if k != 'checksum'}
        if value.get('checksum') != digest(core) or core.get('format') != FORMAT or core.get('build_id') != build_id:
            raise ThemeEngineError('CORRUPT_ARCHIVE', '题材事实 manifest 校验失败。')
        return core

    def read(self, day, build_id=None, table='themes'):
        manifest = self.get(day, build_id)
        name = table + '.parquet'
        if name not in manifest['files']:
            raise ThemeEngineError('INVALID_ARGUMENT', 'table 必须为 themes 或 pool_industries。')
        payload = (self._day_dir(day) / manifest['build_id'] / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['files'][name]:
            raise ThemeEngineError('CORRUPT_ARCHIVE', name + ' 哈希校验失败。')
        return pl.read_parquet(io.BytesIO(payload)), manifest

    def list_days(self, limit=60):
        if not self.root.is_dir():
            return []
        rows = []
        for folder in sorted((p for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name)), reverse=True)[:limit]:
            try:
                manifest = self.get(folder.name)
                rows.append({'trading_day': folder.name, 'build_id': manifest['build_id'], 'families': manifest['families'],
                             'skipped_families': manifest['skipped_families'], 'pool_limit_ups': manifest['pool_limit_ups'],
                             'history_days': len(manifest['history_days']), 'created_at': manifest['created_at']})
            except ThemeEngineError as error:
                rows.append({'trading_day': folder.name, 'error': error.code})
        return rows

    # ---- Theme Matrix ------------------------------------------------------------------------------
    def snapshot_contents(self, day, *, concept_limit=10, industry_limit=5, min_limit_ups=ACTIVE_MIN_LIMIT_UPS):
        """Theme Snapshot payloads (machine facts only, states UNKNOWN) for the top ranked boards of a build."""
        themes, manifest = self.read(day)
        limits = {'concept': concept_limit, 'industry': industry_limit}
        contents = []
        for family, limit in limits.items():
            if type(limit) is not int or not 0 <= limit <= 50:
                raise ThemeEngineError('INVALID_ARGUMENT', '每类发布数量必须为 0–50。')
            chosen = themes.filter((pl.col('family') == family) & pl.col('rank').is_not_null() & (pl.col('limit_up_count') >= min_limit_ups)).sort('rank').head(limit)
            for row in chosen.to_dicts():
                ladder = '/'.join(f'{label}{row[key]}' for label, key in (('5板+', 'streak_5plus_count'), ('4板', 'streak_4_count'), ('3板', 'streak_3_count'),
                                                                          ('2板', 'streak_2_count'), ('首板', 'first_board_count')) if row[key])
                note = f"{manifest['trading_day']} 收盘：梯队 {ladder}；龙头候选 {row['leaders'] or '无'}"
                facts = {'constituents': row['constituents'], 'limit_up_count': row['limit_up_count'], 'limit_down_count': row['limit_down_count'],
                         'twenty_cm_limit_up_count': row['twenty_cm_limit_up_count'], 'max_streak': row['max_streak'],
                         'broken_count': row['broken_count'], 'persistence_days': row['persistence_days'],
                         'seal_fund_billion': round(row['seal_fund_total'] / 1e8, 4), 'leader_symbol': (row['leader_symbols'] or [None])[0],
                         'breadth_up': row['breadth_up'], 'breadth_down': row['breadth_down'], 'board_pct_change': row['board_pct_change'],
                         'amount_billion': None if row['board_amount'] is None else round(row['board_amount'] / 1e8, 4), 'note': note[:400]}
                name = row['board_name'] if family == 'concept' else f"{row['board_name']}（行业）"
                contents.append({
                    'request_id': str(uuid5(NAMESPACE_URL, f"niuniu-theme-snapshot:{manifest['build_id']}:{family}:{row['board_code']}")),
                    'content': {'theme': name, 'trading_day': manifest['trading_day'], 'frame': 'R3', 'machine_state': 'UNKNOWN', 'ai_state': 'UNKNOWN',
                                'facts': {k: v for k, v in facts.items() if v is not None},
                                'facts_source': f"东方财富公开证据归档 · {RULES_VERSION} build {manifest['build_id']}",
                                'facts_as_of': manifest['facts_as_of'],
                                'machine_rule': f"收盘后题材事实：非通用板块按涨停家数、最高连板、封板资金、成分数排序，取涨停≥{min_limit_ups}家的前列；不判定题材状态。",
                                'machine_rule_version': RULES_VERSION, 'source': 'machine_theme_facts'}})
        return contents

    def publish(self, day, *, confirmed=False, store=None, **limits):
        if confirmed is not True:
            raise ThemeEngineError('CONFIRMATION_REQUIRED', '写入 Theme Matrix 需要宿主显式确认。')
        from quantlab.trading.theme_store import ThemeError, ThemeStore
        store = store or ThemeStore(self.output)
        written = []
        for item in self.snapshot_contents(day, **limits):
            try:
                snapshot = store.create(item['request_id'], item['content'])
            except ThemeError as error:
                raise ThemeEngineError(error.code, str(error)) from None
            written.append({'snapshot_id': snapshot['snapshot_id'], 'theme': snapshot['theme'], 'limit_up_count': snapshot['facts'].get('limit_up_count')})
        return {'trading_day': day if isinstance(day, str) else day.isoformat(), 'written': written}


__all__ = ['FORMAT', 'RULES_VERSION', 'FAMILIES', 'POOLS', 'THEME_SCHEMA', 'GENERIC_NAME_PATTERNS', 'LIMITATIONS', 'ThemeEngineError',
           'ThemeFactsLibrary', 'code_fingerprint', 'compute_family', 'is_generic', 'pool_industries']
