"""Layered daily close review for limit-board research (research_only).

A review freezes, for one trading day, three separated layers:
- facts: market breadth, limit-board statistics with the previous day, the streak ladder, theme facts,
  billboard highlights and data coverage, each traced to a build or capture id;
- machine_state: the versioned sentiment-cycle phase and historical analog days (not predictions);
- commentary: optional appended AI or host judgments, stored separately and never merged into facts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import json
import re

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'limit-daily-review-v1'
COMMENTARY_FORMAT = 'limit-daily-review-commentary-v1'
BUILD = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
MARKET_FIELDS = ('tradable_count', 'up_count', 'down_count', 'flat_count', 'up_ratio', 'amount_total', 'amount_change')
LIMIT_FIELDS = ('limit_up_count', 'limit_up_count_non_st', 'limit_down_count', 'limit_down_count_non_st', 'touched_limit_up_count',
                'broken_board_count', 'broken_rate', 'one_word_limit_up_count', 'first_board_count', 'consecutive_board_count', 'max_streak',
                'streak_2_count', 'streak_3_count', 'streak_4_count', 'streak_5plus_count', 'advance_rate_1to2', 'advance_rate_2plus',
                'prev_limit_up_avg_return', 'prev_limit_up_median_return', 'prev_limit_up_win_rate', 'prev_broken_avg_return', 'big_loss_count',
                'limit_up_to_down_count', 'limit_down_to_up_count', 'high_board_broken')
PHASE_LABELS = {'ICE': '冰点', 'CLIMAX': '高潮', 'REPAIR': '修复', 'FERMENT': '发酵', 'DIVERGENCE': '分歧', 'EBB': '退潮',
                'RANGE_WARM': '偏暖震荡', 'RANGE_COOL': '偏冷震荡', 'UNKNOWN': '未知'}
LIMITATIONS = [
    '事实层来自研究数据集（research_only）：涨跌停由研究制度表推算，东方财富股池、板块与龙虎榜为供应商口径（股池不含 ST）。',
    '机器状态层是版本化工程规则（情绪周期）与历史类比（相似日），不是专家判断、预测或交易信号。',
    '评论层是 AI 或宿主的判断，单独追加保存，不回写事实，也不构成买卖建议。',
]


class DailyReviewError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def code_fingerprint():
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def _clean(value):
    if isinstance(value, float):
        return None if value != value else round(value, 6)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _pct(value, signed=False):
    if value is None:
        return '—'
    return f'{value * 100:+.1f}%' if signed else f'{value * 100:.1f}%'


class DailyReviewLibrary:
    def __init__(self, output, *, now_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise DailyReviewError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.root = self.output / '_limit_research' / 'daily_review'

    # ---- inputs ---------------------------------------------------------------------------------------
    def resolve(self, day):
        from quantlab.trading.event_details import EventDetailError, EventDetailLibrary
        from quantlab.trading.limit_events import LimitEventLibrary
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        from quantlab.trading.theme_engine import ThemeEngineError, ThemeFactsLibrary
        day = date.fromisoformat(day) if isinstance(day, str) else day
        sentiment = MarketSentimentLibrary(self.output).latest_covering(day)
        events = LimitEventLibrary(self.output).latest_covering(day)
        if sentiment is None or events is None:
            raise DailyReviewError('RESEARCH_BUILD_MISSING', f'{day} 缺少覆盖该日的情绪指标或事件库 build。')
        inputs = {'market_sentiment_build_id': sentiment['build_id'], 'limit_event_build_id': events['build_id'],
                  'theme_facts_build_id': None, 'event_details_build_id': None, 'billboard_capture_id': None}
        try:
            inputs['theme_facts_build_id'] = ThemeFactsLibrary(self.output).get(day)['build_id']
        except ThemeEngineError:
            pass
        try:
            inputs['event_details_build_id'] = EventDetailLibrary(self.output).get(day)['build_id']
        except EventDetailError:
            pass
        from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError
        try:
            inputs['billboard_capture_id'] = PublicEvidenceArchive(self.output).get('em_billboard_daily', day)['capture_id']
        except PublicEvidenceError:
            pass
        identity = {'format': FORMAT, 'code_fingerprint': code_fingerprint(), 'trading_day': day.isoformat(), 'inputs': inputs}
        return {'day': day, 'inputs': inputs, 'identity': identity, 'review_id': str(uuid5(NAMESPACE_URL, 'niuniu-daily-review:' + digest(identity)))}

    # ---- assembly -------------------------------------------------------------------------------------
    def _facts_and_state(self, day, inputs):
        from quantlab.trading.limit_events import LimitEventLibrary
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        from quantlab.trading.sentiment_cycle import CYCLE_RULES_VERSION, compute_cycle, similar_days
        daily, _ = MarketSentimentLibrary(self.output).read(inputs['market_sentiment_build_id'])
        cycle = compute_cycle(daily)
        dates = daily['date'].to_list()
        if day not in dates:
            raise DailyReviewError('DAY_NOT_IN_BUILD', f'{day} 不在情绪指标 build 中。')
        index = dates.index(day)
        today = daily.row(index, named=True)
        previous = daily.row(index - 1, named=True) if index else None
        facts = {'market': {k: today[k] for k in MARKET_FIELDS}, 'limit': {k: today[k] for k in LIMIT_FIELDS},
                 'previous_day': None if previous is None else {'date': previous['date'], **{k: previous[k] for k in LIMIT_FIELDS + MARKET_FIELDS}}}
        facts['market']['amount_total_yi'] = None if today['amount_total'] is None else round(today['amount_total'] / 1e8, 1)
        events, _ = LimitEventLibrary(self.output).read_events(inputs['limit_event_build_id'], start=day, end=day)
        names, details = {}, None
        from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError
        try:
            pool, _ = PublicEvidenceArchive(self.output).read_table('em_limit_up_pool', day)
            names = dict(zip(pool['symbol'].to_list(), pool['name'].to_list()))
        except PublicEvidenceError:
            pass
        if inputs['event_details_build_id']:
            from quantlab.trading.event_details import EventDetailLibrary
            details, detail_manifest = EventDetailLibrary(self.output).read(day, inputs['event_details_build_id'])
            facts['details'] = {'reconciliation': detail_manifest['reconciliation'], 'checks': detail_manifest['checks']}
            if detail_manifest['reconciliation'] == 'CONSISTENT':
                events = events.join(details.drop('date'), on='code', how='left')
                labels = ['集合竞价', '开盘30分钟内', '30分钟至2小时', '2至3小时', '3小时以后']
                seal = details.filter(pl.col('em_in_limit_up_pool')).select(
                    pl.col('em_first_seal_minute').cut([0, 30, 120, 180], labels=labels).cast(pl.String).alias('bucket')).group_by('bucket').len()
                counts = {row['bucket']: row['len'] for row in seal.to_dicts()}
                # A list keeps the time order; JSON objects are written with sorted keys.
                facts['details']['first_seal_distribution'] = [{'bucket': label, 'count': counts[label]} for label in labels if label in counts]
        ups = events.filter(pl.col('is_limit_up_close'))
        ladder = []
        for streak in sorted({s for s in ups['limit_up_streak'].to_list() if s >= 2}, reverse=True):
            group = ups.filter(pl.col('limit_up_streak') == streak).sort('code')
            ladder.append({'streak': streak, 'stocks': [
                {'code': r['code'], 'name': names.get(r['code']), 'is_st': r['is_st'],
                 'first_seal_time': r.get('em_first_seal_time'), 'broken_times': r.get('em_broken_times'),
                 'seal_fund_yi': None if r.get('em_seal_fund') is None else round(r['em_seal_fund'] / 1e8, 3),
                 'on_billboard': r.get('em_on_billboard')} for r in group.head(10).to_dicts()], 'count': group.height})
        facts['ladder'] = {'levels': ladder, 'first_board_count': ups.filter(pl.col('limit_up_streak') == 1).height}
        if inputs['theme_facts_build_id']:
            from quantlab.trading.theme_engine import ThemeFactsLibrary
            library = ThemeFactsLibrary(self.output)
            themes, theme_manifest = library.read(day, inputs['theme_facts_build_id'])
            industries, _ = library.read(day, inputs['theme_facts_build_id'], table='pool_industries')
            columns = ['rank', 'board_name', 'limit_up_count', 'max_streak', 'first_board_count', 'broken_count', 'persistence_days', 'leaders']
            facts['themes'] = {'skipped_families': theme_manifest['skipped_families'],
                               'concept': themes.filter((pl.col('family') == 'concept') & pl.col('rank').is_not_null()).sort('rank').head(10).select(columns).to_dicts(),
                               'industry': themes.filter((pl.col('family') == 'industry') & pl.col('rank').is_not_null()).sort('rank').head(5).select(columns).to_dicts(),
                               'pool_industries': industries.head(10).select('industry', 'limit_up_count', 'max_streak').to_dicts()}
        if inputs['billboard_capture_id']:
            board, _ = PublicEvidenceArchive(self.output).read_table('em_billboard_daily', day)
            board = board.filter(pl.col('is_a_share')).sort(['symbol', 'billboard_deal'], descending=[False, True]).unique('symbol', keep='first')
            pick = ['symbol', 'name', 'pct_change', 'billboard_net', 'reason']
            facts['billboard'] = {'listed': board.height,
                                  'top_net_buy': board.sort('billboard_net', descending=True, nulls_last=True).head(5).select(pick).to_dicts(),
                                  'top_net_sell': board.sort('billboard_net', nulls_last=True).head(5).select(pick).to_dicts()}
        facts['coverage'] = {'theme_facts': bool(inputs['theme_facts_build_id']), 'event_details': bool(inputs['event_details_build_id']),
                             'billboard': bool(inputs['billboard_capture_id'])}
        state = {'rules_version': CYCLE_RULES_VERSION, 'temperature': cycle['temperature'][index], 'phase': cycle['phase'][index],
                 'previous_phase': cycle['phase'][index - 1] if index else None,
                 'previous_temperature': cycle['temperature'][index - 1] if index else None}
        try:
            state['similar_days'] = similar_days(daily, day, k=5)
        except ValueError as error:
            state['similar_days'] = {'error': str(error)[:200]}
        return _clean(facts), _clean(state)

    def build(self, day):
        resolved = self.resolve(day)
        folder = self._day_dir(resolved['day']) / resolved['review_id']
        if folder.exists():
            return {**self.get(resolved['day'], resolved['review_id']), 'created': False}
        facts, state = self._facts_and_state(resolved['day'], resolved['inputs'])
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise DailyReviewError('INVALID_CLOCK', '时钟必须带时区。')
        review = {**resolved['identity'], 'review_id': resolved['review_id'], 'created_at': created.astimezone(timezone.utc).isoformat(),
                  'facts': facts, 'machine_state': state, 'qualification': 'research_only', 'limitations': LIMITATIONS}
        folder.parent.mkdir(parents=True, exist_ok=True)
        temporary = folder.parent / ('.tmp-' + str(uuid4()))
        (temporary / 'commentary').mkdir(parents=True)
        (temporary / 'review.json').write_text(encode({**review, 'checksum': digest(review)}), encoding='utf-8')
        temporary.replace(folder)
        return {**review, 'created': True}

    # ---- storage ----------------------------------------------------------------------------------------
    def _day_dir(self, day):
        for path in (self.output / '_limit_research', self.root):
            if path.is_symlink():
                raise DailyReviewError('INVALID_WORKSPACE', '复盘目录不能是符号链接。')
        return self.root / (day.isoformat() if isinstance(day, date) else date.fromisoformat(day).isoformat())

    def is_current(self, day):
        try:
            resolved = self.resolve(day)
        except DailyReviewError:
            return False
        return (self._day_dir(resolved['day']) / resolved['review_id'] / 'review.json').is_file()

    def get(self, day, review_id=None):
        folder = self._day_dir(day)
        if review_id is None:
            ids = [p.name for p in folder.iterdir() if p.is_dir() and BUILD.fullmatch(p.name)] if folder.is_dir() else []
            if not ids:
                raise DailyReviewError('NOT_FOUND', f'{day} 没有收盘复盘。')
            return max((self.get(day, i) for i in ids), key=lambda r: (r['created_at'], r['review_id']))
        if not BUILD.fullmatch(review_id or ''):
            raise DailyReviewError('INVALID_ARGUMENT', 'review_id 无效。')
        path = folder / review_id / 'review.json'
        if path.is_symlink() or not path.is_file():
            raise DailyReviewError('NOT_FOUND', '收盘复盘不存在。')
        value = json.loads(path.read_bytes())
        core = {k: v for k, v in value.items() if k != 'checksum'}
        if value.get('checksum') != digest(core) or core.get('format') != FORMAT or core.get('review_id') != review_id:
            raise DailyReviewError('CORRUPT_ARCHIVE', '收盘复盘校验失败。')
        return {**core, 'commentary': self.commentary(day, review_id)}

    def commentary(self, day, review_id):
        folder = self._day_dir(day) / review_id / 'commentary'
        if not folder.is_dir():
            return []
        rows = []
        for path in sorted(folder.glob('*.json')):
            value = json.loads(path.read_bytes())
            core = {k: v for k, v in value.items() if k != 'checksum'}
            if value.get('checksum') != digest(core) or core.get('format') != COMMENTARY_FORMAT:
                raise DailyReviewError('CORRUPT_ARCHIVE', '复盘评论校验失败。')
            rows.append(core)
        return sorted(rows, key=lambda r: r['created_at'])

    def annotate(self, day, review_id, *, text, author, kind):
        """Append one judgment to a review; facts are never modified."""
        if kind not in ('ai', 'host'):
            raise DailyReviewError('INVALID_ARGUMENT', 'kind 必须为 ai 或 host。')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
            raise DailyReviewError('INVALID_ARGUMENT', '评论必须为 1–8000 字。')
        if not isinstance(author, str) or not 1 <= len(author.strip()) <= 80:
            raise DailyReviewError('INVALID_ARGUMENT', 'author 必须为 1–80 字。')
        review = self.get(day, review_id)
        created = self.now_fn()
        value = {'format': COMMENTARY_FORMAT, 'review_id': review['review_id'], 'trading_day': review['trading_day'], 'kind': kind,
                 'author': author.strip(), 'text': text.strip(), 'created_at': created.astimezone(timezone.utc).isoformat(),
                 'layer': 'judgment_not_fact'}
        value['commentary_id'] = str(uuid5(NAMESPACE_URL, 'niuniu-review-commentary:' + digest(value)))
        path = self._day_dir(day) / review['review_id'] / 'commentary' / f"{value['created_at'].replace(':', '').replace('+', '_')}-{value['commentary_id'][:8]}.json"
        if path.exists():
            raise DailyReviewError('CONFLICT', '同一时刻的评论已存在。')
        temporary = path.with_name('.' + path.name + '.tmp')
        temporary.write_text(encode({**value, 'checksum': digest(value)}), encoding='utf-8')
        temporary.replace(path)
        return value

    def list_days(self, limit=60):
        if not self.root.is_dir():
            return []
        rows = []
        for folder in sorted((p for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name)), reverse=True)[:limit]:
            try:
                review = self.get(folder.name)
                rows.append({'trading_day': folder.name, 'review_id': review['review_id'], 'phase': review['machine_state']['phase'],
                             'limit_up_count': review['facts']['limit']['limit_up_count'], 'commentary': len(review['commentary']),
                             'created_at': review['created_at']})
            except DailyReviewError as error:
                rows.append({'trading_day': folder.name, 'error': error.code})
        return rows

    def latest_on_or_before(self, day):
        day = day.isoformat() if isinstance(day, date) else day
        for row in self.list_days(limit=400):
            if 'error' not in row and row['trading_day'] <= day:
                return self.get(row['trading_day'], row['review_id'])
        return None


def render_markdown(review):
    """Short Chinese summary for phones and chat; numbers come only from the review's facts and machine state."""
    facts, state, limit, market = review['facts'], review['machine_state'], review['facts']['limit'], review['facts']['market']
    previous = facts.get('previous_day') or {}
    lines = [f"## {review['trading_day']} 打板情绪复盘（research_only）", '',
             f"- 情绪周期：{PHASE_LABELS.get(state['phase'], state['phase'])}（温度 {state['temperature'] if state['temperature'] is not None else '—'}；"
             f"前一日 {PHASE_LABELS.get(state.get('previous_phase'), state.get('previous_phase') or '—')}）· 规则 {state['rules_version']}",
             f"- 涨停 {limit['limit_up_count']}（非ST {limit['limit_up_count_non_st']}，前一日 {previous.get('limit_up_count', '—')}）；"
             f"跌停 {limit['limit_down_count']}；炸板率 {_pct(limit['broken_rate'])}；最高 {limit['max_streak']} 板",
             f"- 1进2 晋级率 {_pct(limit['advance_rate_1to2'])}；昨日涨停今日均值 {_pct(limit['prev_limit_up_avg_return'], signed=True)}、胜率 {_pct(limit['prev_limit_up_win_rate'])}；大面 {limit['big_loss_count']} 家",
             f"- 上涨 {market['up_count']} / 下跌 {market['down_count']}；成交额 {market.get('amount_total_yi', '—')} 亿元（{_pct(market['amount_change'], signed=True)}）"]
    levels = facts['ladder']['levels']
    if levels:
        top = '；'.join(f"{level['streak']}板：" + '、'.join((s['name'] or s['code']) for s in level['stocks'][:4]) for level in levels[:4])
        lines.append(f"- 连板梯队：{top}；首板 {facts['ladder']['first_board_count']} 家")
    themes = (facts.get('themes') or {}).get('concept') or []
    if themes:
        lines.append('- 概念题材（按涨停家数）：' + '；'.join(f"{t['board_name']} {t['limit_up_count']}家（持续{t['persistence_days']}天）" for t in themes[:5]))
    elif (facts.get('themes') or {}).get('pool_industries'):
        lines.append('- 股池行业分布：' + '；'.join(f"{t['industry']} {t['limit_up_count']}" for t in facts['themes']['pool_industries'][:5]))
    if facts.get('details', {}).get('first_seal_distribution'):
        lines.append('- 首次封板时间：' + '；'.join(f"{item['bucket']} {item['count']}" for item in facts['details']['first_seal_distribution']))
    similar = state.get('similar_days') or {}
    if similar.get('neighbors'):
        outcomes = [n['next_limit_up_count'] for n in similar['neighbors']]
        lines.append(f"- 历史相似日（类比，非预测）：{len(outcomes)} 天，次日涨停 {min(outcomes)}～{max(outcomes)} 家")
    missing = [name for name, present in facts['coverage'].items() if not present]
    if missing:
        lines.append('- 数据缺口：' + '、'.join(missing))
    for item in review.get('commentary', [])[-2:]:
        lines.append(f"- {'AI' if item['kind'] == 'ai' else '宿主'}评论（{item['author']}，判断不是事实）：{item['text'][:200]}")
    return '\n'.join(lines)


__all__ = ['FORMAT', 'LIMITATIONS', 'DailyReviewError', 'DailyReviewLibrary', 'render_markdown']
