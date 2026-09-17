"""Model tools over the limit-board research datasets (research_only, no builds, no network).

Reads only, plus two journal writes that never execute anything: verifiable forecasts and proposals into the host-authorized
autonomous research queue. ``allow_forecast_write=False`` (AI Team reviewers) removes both writes.
"""
from __future__ import annotations

from datetime import date
import json
import re

import polars as pl

from quantlab.agent.catalog import schema, TEXT, LIMIT, OFFSET, compact
from quantlab.storage.codec import encode

DAY = {'type': 'string', 'maxLength': 10}
NAME = {'type': 'string', 'maxLength': 40}
DAYS = {'type': 'integer', 'minimum': 1, 'maximum': 30}
TOP_K = {'type': 'integer', 'minimum': 1, 'maximum': 20}
TOOLS = [
    schema('get_limit_research_status',
           '只读查看打板研究数据底座：回溯日线、事件库、情绪指标、题材事实、前瞻明细、公开证据归档、事件研究与收盘后调度的最新构建和覆盖日期；不构建、不联网。',
           {}),
    schema('get_market_sentiment',
           '读取日度打板情绪指标（涨跌停/炸板/连板/晋级率/昨日涨停收益/成交额等）与机器情绪周期（温度与阶段，规则版本化，不是交易信号）。trading_day 留空取最新；days 为向前取的交易日数。',
           {'trading_day': DAY, 'days': DAYS}),
    schema('find_similar_sentiment_days',
           '在严格早于目标日的历史中找情绪分位最相近的交易日，并给出它们下一个交易日的涨停数、最高连板、昨日涨停收益、1进2晋级率与炸板率；只是历史类比，不是预测。',
           {'trading_day': DAY, 'k': TOP_K}),
    schema('get_limit_ladder',
           '读取某交易日涨停梯队：按连板高度分组的收盘涨停股（区分 ST）、炸板与跌停家数；有前瞻明细时附名称、首次封板时间、封单、开板次数、龙虎榜与人气名次。limit 为每个高度最多列出的股票数。',
           {'trading_day': DAY, 'limit': LIMIT}),
    schema('query_limit_events',
           '用白名单条件表达式筛选日期区间内的涨停/跌停相关事件（比较、and/or/not、in 常量列表）。可引用事件库 T 日特征、mkt_ 情绪列与 em_ 前瞻明细列；返回特征与已经发生的 T+1/T+2 结果——结果列只用于复盘，不能当作当时已知信息。区间最长 250 个交易日。',
           {'start': DAY, 'end': DAY, 'condition': TEXT, 'offset': OFFSET, 'limit': LIMIT}),
    schema('get_theme_facts',
           '读取某交易日的机器题材事实：非通用板块按涨停家数、最高连板、封单资金排序，含梯队、龙头候选、持续天数和板块行情；另含股池行业分布。family 为 concept 或 industry；机器状态一律 UNKNOWN，不是题材强弱判断。',
           {'trading_day': DAY, 'family': NAME, 'limit': LIMIT}),
    schema('get_billboard',
           '读取某交易日龙虎榜上榜股票（理由、买卖与净买入、成交占比）；symbol 非空时附该股买入/卖出前五席位（含“机构专用”）。供应商统计与解读字段不是事实。',
           {'trading_day': DAY, 'symbol': TEXT, 'limit': LIMIT}),
    schema('get_daily_review',
           '读取某交易日的打板情绪收盘复盘：事实层（涨跌停、连板梯队、题材、龙虎榜、数据缺口，含前一日对比）、机器状态层（情绪周期与相似日类比）和单独追加的评论层，并附简短中文摘要。trading_day 留空取最新。',
           {'trading_day': DAY}),
    schema('list_limit_forecast_questions',
           '读取可验证打板预测的问题目录（二元问题、判定指标、09:15 截止规则、机器基准），以及目标交易日已记录的预测和判定结果。target_day 留空只返回目录。',
           {'target_day': DAY}),
    schema('get_limit_forecast_scorecard',
           '读取打板预测记分卡：各预测者（AI、宿主、机器基准）的已判定数量、平均 Brier 分数、相对 250 日气候基准的技能分、分问题成绩与校准分箱。',
           {}),
    schema('list_event_studies',
           '只读列出预登记事件研究：family 留空列出全部研究族；给出 family 时返回该族 Holm 校正报告（检验量、样本内外取值、是否符合预登记方向、成交率与结论）。',
           {'family': NAME}),
    schema('get_event_study',
           '读取一个预登记事件研究的冻结规格与结果：全样本/样本内/样本外统计与检验、成交模型统计、分年、分组和局限说明。',
           {'family': NAME, 'study_id': TEXT}),
    schema('get_auto_research_status',
           '只读查看宿主授权的自主研究计划：研究族前缀、样本内区间、允许的结果列与成交模型、每周/每晚预算、隔离期与锁定样本外起点、确认族与质疑清单阈值；以及本周已用预算、队列计数和最近提案的筛选状态与未通过的质疑项。没有有效计划时不能提案。',
           {}),
]
WRITE_TOOLS = [
    schema('record_limit_forecast',
           '记录一条可验证的概率预测（不是交易指令）。forecast_json 须含 question_id（来自 list_limit_forecast_questions）、target_day（YYYY-MM-DD，须在该日 09:15 前记录、7 天内）、probability（0–1）、rationale（≤2000 字，说明依据）与 evidence（至多 20 条工具证据引用文本）。同一问题同一目标日只能记录一次，不可修改；request_id 须为 UUID，重试幂等。',
           {'request_id': TEXT, 'forecast_json': {'type': 'string', 'maxLength': 8000}}),
    schema('propose_auto_study',
           '在宿主授权的自主研究计划内提交一项事件研究提案：只进入队列，不直接登记或运行，也不是结论或交易指令。proposal_json 须恰好含 family（计划前缀本身或以“前缀-”开头，≤33 字符）、hypothesis（5–500 字）、expected_sign（positive/negative，必须预登记方向）、condition（白名单条件表达式）、baseline_condition（对照条件或 null；布尔结果与 t1_high_ret/t1_low_ret 必须给对照）、outcome（计划允许的结果列）、execution（计划授权的成交模型规格或 null；net_return/gross_return 必须给）、group_by（board/streak_bucket/year/mkt_phase/is_st 或 null）、use_sentiment（布尔）。夜间任务只在样本内区间运行并按质疑清单筛选；同一检验只运行一次，改族名、假设文字或方向不能重跑；失败同样消耗预算。request_id 须为 UUID，重试幂等。',
           {'request_id': TEXT, 'proposal_json': {'type': 'string', 'maxLength': 4000}}),
]
TOOL_NAMES = tuple(tool['name'] for tool in TOOLS)
WRITE_TOOL_NAMES = tuple(tool['name'] for tool in WRITE_TOOLS)
SENTIMENT_FIELDS = ('limit_up_count', 'limit_up_count_non_st', 'limit_down_count', 'touched_limit_up_count', 'broken_board_count',
                    'broken_rate', 'one_word_limit_up_count', 'first_board_count', 'consecutive_board_count', 'max_streak',
                    'advance_rate_1to2', 'advance_rate_2plus', 'prev_limit_up_avg_return', 'prev_limit_up_win_rate', 'big_loss_count',
                    'up_count', 'down_count', 'amount_total', 'amount_change', 'high_board_broken')
EVENT_FIELDS = ('date', 'code', 'board', 'is_st', 'limit_rate', 'close', 'day_ret', 'amount_rank_pct', 'limit_up_streak', 'is_limit_up_close',
                'touched_limit_up', 'is_broken_board', 'is_one_word_limit_up', 'is_limit_down_close', 'is_first_board',
                't1_open_ret', 't1_close_ret', 't1_is_limit_up_close', 't1_is_broken_board', 'ret_t1open_to_t2open')
WARNING = '打板研究数据为 research_only：涨跌停由研究制度表推算，东方财富股池/龙虎榜为供应商口径（股池不含 ST），情绪周期与题材排序是工程规则；任何结果都不是买卖建议。'


def _day(value, name):
    if value == '':
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value or ''):
        raise ValueError(name + ' 必须为 YYYY-MM-DD 或留空。')
    return date.fromisoformat(value)


def _round(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


class LimitResearchAPI:
    """Compose limit-research reads with an existing agent API without adding writes."""

    def __init__(self, inner, *, forecaster='ai:chat', allow_forecast_write=True, now_fn=None):
        self.inner = inner
        self.now_fn = now_fn
        self.output = getattr(inner, 'output', None)
        self.forecaster = forecaster
        self.allow_forecast_write = allow_forecast_write

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _tools(self):
        return TOOLS + (WRITE_TOOLS if self.allow_forecast_write else [])

    def schemas(self):
        return self.inner.schemas() + json.loads(json.dumps(self._tools(), ensure_ascii=False))

    @staticmethod
    def _validate(definition, arguments):
        props = definition['parameters']['properties']
        if not isinstance(arguments, dict) or set(arguments) != set(props):
            raise ValueError('打板研究工具字段必须与 Schema 完全一致。')
        for key, spec in props.items():
            value = arguments[key]
            valid = (isinstance(value, str) and len(value) <= spec['maxLength']) if spec['type'] == 'string' else (
                type(value) is int and spec['minimum'] <= value <= spec['maximum'])
            if not valid:
                raise ValueError('打板研究工具参数无效：' + key)

    # ---- libraries -----------------------------------------------------------------------------------
    def _events(self):
        from quantlab.trading.limit_events import LimitEventLibrary
        return LimitEventLibrary(self.output)

    def _sentiment(self):
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        return MarketSentimentLibrary(self.output)

    def _evidence(self):
        from quantlab.data.public_evidence import PublicEvidenceArchive
        return PublicEvidenceArchive(self.output)

    def _event_build(self, day):
        library = self._events()
        if day is not None:
            manifest = library.latest_covering(day)
        else:
            rows = [r for r in library.list() if 'error' not in r]
            manifest = library.get(max(rows, key=lambda r: (r['calendar']['last'], r['created_at']))['build_id']) if rows else None
        if manifest is None:
            raise LookupError('没有覆盖该交易日的涨停事件库 build。')
        return manifest

    def _sentiment_build(self, day):
        library = self._sentiment()
        if day is not None:
            manifest = library.latest_covering(day)
        else:
            rows = [r for r in library.list() if 'error' not in r]
            manifest = library.get(max(rows, key=lambda r: (r['last_date'], r['created_at']))['build_id']) if rows else None
        if manifest is None:
            raise LookupError('没有覆盖该交易日的情绪指标 build。')
        return manifest

    def _latest_evidence_day(self, source):
        root = self.output / '_market_data' / 'public_evidence' / source
        if not root.is_dir():
            return None
        days = sorted((p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name) and (p / 'accepted.json').is_file()),
                      reverse=True)
        return date.fromisoformat(days[0]) if days else None

    # ---- tools ---------------------------------------------------------------------------------------
    def _status(self):
        from quantlab.data.retro_daily import RetroDailyStore
        from quantlab.trading.event_details import EventDetailLibrary
        from quantlab.trading.theme_engine import ThemeFactsLibrary
        from quantlab.agent.evidence_scheduler import EvidenceScheduler
        retro = [{k: p.get(k) for k in ('capture_id', 'start', 'end', 'symbol_count', 'created_at', 'error')} for p in RetroDailyStore(self.output).list()]
        events = sorted(self._events().list(), key=lambda r: r.get('created_at', ''), reverse=True)[:5]
        sentiment = sorted(self._sentiment().list(), key=lambda r: r.get('created_at', ''), reverse=True)[:5]
        evidence = {}
        root = self.output / '_market_data' / 'public_evidence'
        if root.is_dir():
            for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith('_')):
                days = sorted(p.name for p in folder.iterdir() if (p / 'accepted.json').is_file())
                evidence[folder.name] = {'accepted_days': len(days), 'first_day': days[0] if days else None, 'last_day': days[-1] if days else None}
        studies = self.output / '_limit_research' / 'event_studies'
        families = {p.name: sum(1 for c in p.iterdir() if c.is_dir() and not c.name.startswith('.')) for p in sorted(studies.iterdir()) if p.is_dir()} if studies.is_dir() else {}
        try:
            scheduler = EvidenceScheduler(self.output).status()
            scheduler = {k: scheduler.get(k) for k in ('enabled', 'last_tick_at', 'last_action_at', 'schedule_version')}
        except (OSError, ValueError) as error:
            scheduler = {'error': str(error)[:120]}
        try:
            auto = self._auto().status(limit=0)
            auto = {'active': auto['active'], 'plan_status': (auto['plan'] or {}).get('status'), 'queue_counts': auto['queue_counts']}
        except (OSError, ValueError) as error:
            auto = {'error': str(error)[:120]}
        return {'retro_daily_captures': retro, 'limit_event_builds': events, 'market_sentiment_builds': sentiment, 'auto_research': auto,
                'theme_facts_days': ThemeFactsLibrary(self.output).list_days(limit=5), 'event_detail_days': EventDetailLibrary(self.output).list_days(limit=5),
                'public_evidence': evidence, 'public_evidence_verified': False, 'event_study_families': families, 'evidence_scheduler': scheduler}, []

    def _market_sentiment(self, arguments):
        from quantlab.trading.sentiment_cycle import compute_cycle
        day = _day(arguments['trading_day'], 'trading_day')
        manifest = self._sentiment_build(day)
        daily, _ = self._sentiment().read(manifest['build_id'])
        cycle = compute_cycle(daily).select('date', 'temperature', 'phase')
        frame = daily.join(cycle, on='date', how='left')
        if day is not None:
            frame = frame.filter(pl.col('date') <= day)
        rows = frame.tail(arguments['days']).select(['date', *SENTIMENT_FIELDS, 'temperature', 'phase']).with_columns(
            (pl.col('amount_total') / 1e8).round(1).alias('amount_total')).to_dicts()
        data = {'build_id': manifest['build_id'], 'available_policy': manifest['available_policy'], 'amount_unit': '亿元',
                'rows': _round(rows), 'cycle_note': '温度=8个指标在此前250个交易日中的分位数平均；阶段阈值是工程规则（sentiment-cycle-rules-v1），不是专家规则或交易信号。'}
        return data, [{'kind': 'market_sentiment_build', 'build_id': manifest['build_id']}]

    def _similar(self, arguments):
        from quantlab.trading.sentiment_cycle import similar_days
        day = _day(arguments['trading_day'], 'trading_day')
        manifest = self._sentiment_build(day)
        daily, _ = self._sentiment().read(manifest['build_id'])
        target = day or daily['date'].max()
        result = similar_days(daily, target, k=arguments['k'])
        return {'build_id': manifest['build_id'], **_round(result)}, [{'kind': 'market_sentiment_build', 'build_id': manifest['build_id']}]

    def _ladder(self, arguments):
        from quantlab.data.public_evidence import PublicEvidenceError
        from quantlab.trading.event_details import EventDetailError, EventDetailLibrary
        day = _day(arguments['trading_day'], 'trading_day')
        manifest = self._event_build(day)
        day = day or date.fromisoformat(manifest['calendar']['last'])
        events, _ = self._events().read_events(manifest['build_id'], start=day, end=day)
        refs = [{'kind': 'limit_event_build', 'build_id': manifest['build_id']}]
        detail_note = '该日没有核对一致的前瞻明细。'
        try:
            details, detail_manifest = EventDetailLibrary(self.output).read(day)
            if detail_manifest['reconciliation'] == 'CONSISTENT':
                events = events.join(details.select('code', 'em_first_seal_time', 'em_seal_fund', 'em_broken_times', 'em_on_billboard',
                                                    'em_popularity_rank'), on='code', how='left')
                detail_note = '附东方财富前瞻明细（已与日线核对一致）。'
                refs.append({'kind': 'event_details', 'trading_day': day.isoformat(), 'build_id': detail_manifest['build_id']})
        except EventDetailError:
            pass
        names = {}
        try:
            pool, pool_manifest = self._evidence().read_table('em_limit_up_pool', day)
            names = dict(zip(pool['symbol'].to_list(), pool['name'].to_list()))
            refs.append({'kind': 'public_evidence', 'source_id': 'em_limit_up_pool', 'trading_day': day.isoformat(), 'capture_id': pool_manifest['capture_id']})
        except PublicEvidenceError:
            pass
        ups = events.filter(pl.col('is_limit_up_close'))
        ladder = []
        for streak in sorted(set(ups['limit_up_streak'].to_list()), reverse=True):
            group = ups.filter(pl.col('limit_up_streak') == streak).sort('code')
            stocks = []
            for row in group.head(arguments['limit']).to_dicts():
                item = {'code': row['code'], 'name': names.get(row['code']), 'board': row['board'], 'is_st': row['is_st']}
                for key in ('em_first_seal_time', 'em_broken_times', 'em_on_billboard', 'em_popularity_rank'):
                    if key in row:
                        item[key] = row[key]
                if row.get('em_seal_fund') is not None:
                    item['em_seal_fund_yi'] = round(row['em_seal_fund'] / 1e8, 3)
                stocks.append(item)
            ladder.append({'streak': streak, 'count': group.height, 'st_count': int(group['is_st'].sum()), 'stocks': stocks,
                           'omitted': max(0, group.height - arguments['limit'])})
        data = {'trading_day': day.isoformat(), 'build_id': manifest['build_id'], 'limit_up_close': ups.height,
                'limit_up_close_non_st': ups.filter(~pl.col('is_st')).height, 'broken_board': events.filter(pl.col('is_broken_board')).height,
                'limit_down_close': events.filter(pl.col('is_limit_down_close')).height, 'ladder': ladder, 'details': detail_note}
        return data, refs

    def _query(self, arguments):
        from quantlab.trading.event_details import DETAIL_COLUMNS, EventDetailLibrary
        from quantlab.trading.event_study import CONTEXT_COLUMNS, compile_condition
        start, end = _day(arguments['start'], 'start'), _day(arguments['end'], 'end')
        manifest = self._event_build(end)
        end = end or date.fromisoformat(manifest['calendar']['last'])
        start = start or end
        if start > end:
            raise ValueError('start 不能晚于 end。')
        condition = arguments['condition'].strip()
        expression, used = compile_condition(condition) if condition else (pl.lit(True), [])
        events, _ = self._events().read_events(manifest['build_id'], start=start, end=end)
        if events.select(pl.col('date').n_unique()).item() > 250:
            raise ValueError('区间最长 250 个交易日。')
        refs = [{'kind': 'limit_event_build', 'build_id': manifest['build_id']}]
        if any(c in CONTEXT_COLUMNS for c in used):
            from quantlab.trading.market_sentiment import METRICS
            from quantlab.trading.sentiment_cycle import compute_cycle
            sentiment = self._sentiment_build(end)
            daily, _ = self._sentiment().read(sentiment['build_id'])
            cycle = compute_cycle(daily).select('date', pl.col('temperature').alias('mkt_temperature'), pl.col('phase').alias('mkt_phase'))
            events = events.join(daily.rename({name: 'mkt_' + name for name in METRICS}).join(cycle, on='date', how='left'), on='date', how='left')
            refs.append({'kind': 'market_sentiment_build', 'build_id': sentiment['build_id']})
        detail_columns = [c for c in used if c in DETAIL_COLUMNS]
        if detail_columns:
            events, used_builds = EventDetailLibrary(self.output).attach(events, start, end)
            refs.extend({'kind': 'event_details', 'trading_day': b['trading_day'], 'build_id': b['build_id']} for b in used_builds)
        selected = events.filter(expression).sort(['date', 'code'])
        columns = list(EVENT_FIELDS) + [c for c in dict.fromkeys(used) if c not in EVENT_FIELDS]
        rows = selected.slice(arguments['offset'], arguments['limit']).select(columns).to_dicts()
        return {'build_id': manifest['build_id'], 'start': start.isoformat(), 'end': end.isoformat(), 'condition': condition,
                'total': selected.height, 'offset': arguments['offset'], 'rows': _round(rows),
                'label_note': 't1_/ret_ 列是事件之后已经发生的结果，只用于复盘；筛选条件不能引用它们。'}, refs

    def _theme(self, arguments):
        from quantlab.trading.theme_engine import ThemeFactsLibrary
        if arguments['family'] not in ('concept', 'industry'):
            raise ValueError('family 必须为 concept 或 industry。')
        library = ThemeFactsLibrary(self.output)
        day = _day(arguments['trading_day'], 'trading_day')
        if day is None:
            days = library.list_days(limit=1)
            if not days:
                raise LookupError('还没有题材事实 build。')
            day = date.fromisoformat(days[0]['trading_day'])
        themes, manifest = library.read(day)
        industries, _ = library.read(day, manifest['build_id'], table='pool_industries')
        rows = themes.filter((pl.col('family') == arguments['family']) & pl.col('rank').is_not_null()).sort('rank').head(arguments['limit']).select(
            'rank', 'board_code', 'board_name', 'constituents', 'limit_up_count', 'twenty_cm_limit_up_count', 'first_board_count', 'streak_2_count',
            'streak_3_count', 'streak_4_count', 'streak_5plus_count', 'max_streak', 'broken_count', 'limit_down_count', 'seal_fund_total', 'leaders',
            'board_pct_change', 'limit_up_count_prev', 'persistence_days', 'persistence_days_3plus', 'persistence_truncated', 'membership_day').to_dicts()
        data = {'trading_day': manifest['trading_day'], 'build_id': manifest['build_id'], 'facts_as_of': manifest['facts_as_of'],
                'skipped_families': manifest['skipped_families'], 'rows': _round(rows),
                'pool_industries': _round(industries.head(10).to_dicts()), 'machine_state': 'UNKNOWN', 'limitations': manifest['limitations']}
        return data, [{'kind': 'theme_facts', 'trading_day': manifest['trading_day'], 'build_id': manifest['build_id']}]

    def _billboard(self, arguments):
        day = _day(arguments['trading_day'], 'trading_day') or self._latest_evidence_day('em_billboard_daily')
        if day is None:
            raise LookupError('还没有龙虎榜归档。')
        archive = self._evidence()
        board, manifest = archive.read_table('em_billboard_daily', day)
        board = board.filter(pl.col('is_a_share'))
        symbol = arguments['symbol'].strip()
        if symbol:
            board = board.filter(pl.col('symbol') == symbol)
        rows = board.sort(pl.col('billboard_net').abs(), descending=True, nulls_last=True).head(arguments['limit']).select(
            'symbol', 'name', 'reason', 'close', 'pct_change', 'turnover_rate', 'billboard_buy', 'billboard_sell', 'billboard_net', 'deal_ratio',
            'em_explain').to_dicts()
        refs = [{'kind': 'public_evidence', 'source_id': 'em_billboard_daily', 'trading_day': day.isoformat(), 'capture_id': manifest['capture_id']}]
        seats = None
        if symbol:
            seats = {}
            for key, source in (('buy', 'em_billboard_buy_seats'), ('sell', 'em_billboard_sell_seats')):
                frame, seat_manifest = archive.read_table(source, day)
                seats[key] = frame.filter(pl.col('symbol') == symbol).select('seat_name', 'reason', 'buy', 'sell', 'net').head(20).to_dicts()
                refs.append({'kind': 'public_evidence', 'source_id': source, 'trading_day': day.isoformat(), 'capture_id': seat_manifest['capture_id']})
        return {'trading_day': day.isoformat(), 'listed': board.height, 'rows': _round(rows), 'seats': _round(seats),
                'note': 'em_ 开头的供应商解读与席位胜率只是统计，不是事实；龙虎榜只含上榜理由对应的前五席位。'}, refs

    def _review(self, arguments):
        from quantlab.trading.daily_review import DailyReviewLibrary, render_markdown
        library = DailyReviewLibrary(self.output)
        day = _day(arguments['trading_day'], 'trading_day')
        if day is None:
            days = library.list_days(limit=1)
            if not days or 'error' in days[0]:
                raise LookupError('还没有收盘复盘。')
            day = date.fromisoformat(days[0]['trading_day'])
        review = library.get(day)
        facts = review['facts']
        data = {'trading_day': review['trading_day'], 'review_id': review['review_id'], 'markdown': render_markdown(review),
                'facts': {**facts, 'previous_day': facts.get('previous_day')}, 'machine_state': review['machine_state'],
                'commentary': review['commentary'][-5:], 'inputs': review['inputs'], 'limitations': review['limitations']}
        return _round(data), [{'kind': 'daily_review', 'trading_day': review['trading_day'], 'review_id': review['review_id']}]

    def _forecast_questions(self, arguments):
        from quantlab.trading.limit_forecasts import LimitForecastJournal, question_catalog
        data = question_catalog()
        day = _day(arguments['target_day'], 'target_day')
        if day is not None:
            journal = LimitForecastJournal(self.output)
            data['target_day'] = day.isoformat()
            data['forecasts'] = [{k: r[k] for k in ('forecast_id', 'forecaster', 'question_id', 'probability', 'recorded_at')} for r in journal.forecasts(day)][:60]
            resolution = journal.resolution(day)
            data['resolution'] = None if resolution is None else {k: resolution[k] for k in ('sentiment_build_id', 'trading_day', 'outcomes', 'resolved_at')}
        return data, []

    def _forecast_scorecard(self, arguments):
        from quantlab.trading.limit_forecasts import LimitForecastJournal
        return _round(LimitForecastJournal(self.output).scorecard()), []

    def _record_forecast(self, arguments):
        from quantlab.trading.limit_forecasts import LimitForecastJournal
        try:
            value = json.loads(arguments['forecast_json'])
        except json.JSONDecodeError:
            raise ValueError('forecast_json 不是合法 JSON。') from None
        if not isinstance(value, dict) or set(value) != {'question_id', 'target_day', 'probability', 'rationale', 'evidence'}:
            raise ValueError('forecast_json 字段必须是 question_id、target_day、probability、rationale、evidence。')
        record = LimitForecastJournal(self.output, now_fn=self.now_fn).record(request_id=arguments['request_id'], forecaster=self.forecaster, **value)
        return {k: record[k] for k in ('forecast_id', 'forecaster', 'question_id', 'question', 'target_day', 'probability', 'recorded_at', 'deadline', 'created')}, [
            {'kind': 'limit_forecast', 'forecast_id': record['forecast_id'], 'target_day': record['target_day']}]

    def _auto(self):
        from quantlab.trading.auto_research import AutoResearch
        return AutoResearch(self.output, now_fn=self.now_fn)

    def _auto_status(self, arguments):
        return _round(self._auto().status()), []

    def _propose_auto(self, arguments):
        from quantlab.trading.auto_research import AutoResearch
        try:
            proposal = json.loads(arguments['proposal_json'])
        except json.JSONDecodeError:
            raise ValueError('proposal_json 不是合法 JSON。') from None
        item = self._auto().propose(arguments['request_id'], proposal, proposer=self.forecaster)
        return {**AutoResearch.summary(item), 'created': item['created'], 'duplicate_of': item['duplicate_of']}, [
            {'kind': 'auto_research_item', 'item_id': item['item_id']}]

    def _studies(self, arguments):
        from quantlab.trading.event_study import EventStudyRegistry
        registry = EventStudyRegistry(self.output)
        family = arguments['family'].strip()
        if not family:
            root = self.output / '_limit_research' / 'event_studies'
            families = [{'family': p.name, 'studies': sum(1 for c in p.iterdir() if c.is_dir() and not c.name.startswith('.'))}
                        for p in sorted(root.iterdir()) if p.is_dir()] if root.is_dir() else []
            return {'families': families}, []
        report = registry.family_report(family)
        refs = [{'kind': 'event_study', 'family': family, 'study_id': row['study_id']} for row in report['studies']]
        return _round(report), refs

    def _study(self, arguments):
        from quantlab.trading.event_study import EventStudyRegistry
        record = EventStudyRegistry(self.output).get(arguments['family'], arguments['study_id'])
        result = record['result']
        if result is not None:
            result = {**result, 'by_group': (result.get('by_group') or [])[:20], 'by_year': result.get('by_year')}
        return {'study_id': record['study_id'], 'spec': record['spec'], 'registered_at': record['registered_at'], 'result': _round(result)}, [
            {'kind': 'event_study', 'family': arguments['family'], 'study_id': arguments['study_id']}]

    def call(self, name, arguments):
        definition = next((tool for tool in self._tools() if tool['name'] == name), None)
        if definition is None:
            result = self.inner.call(name, arguments)
            if name == 'get_capabilities' and result.get('ok'):
                result['data'].update(limit_research_tools_available=True, limit_research_write_tool=False, limit_research_build_tool=False,
                                      limit_research_network_tool=False, limit_forecast_record_tool=self.allow_forecast_write,
                                      auto_study_proposal_tool=self.allow_forecast_write,
                                      tools=[tool['name'] for tool in self.schemas()])
                result['data'].setdefault('limitations', []).append(WARNING)
            return result
        handlers = {'get_limit_research_status': lambda a: self._status(), 'get_daily_review': self._review,
                    'list_limit_forecast_questions': self._forecast_questions, 'get_limit_forecast_scorecard': self._forecast_scorecard,
                    'record_limit_forecast': self._record_forecast, 'get_market_sentiment': self._market_sentiment,
                    'find_similar_sentiment_days': self._similar, 'get_limit_ladder': self._ladder, 'query_limit_events': self._query,
                    'get_theme_facts': self._theme, 'get_billboard': self._billboard, 'list_event_studies': self._studies,
                    'get_event_study': self._study, 'get_auto_research_status': self._auto_status, 'propose_auto_study': self._propose_auto}
        try:
            self._validate(definition, arguments)
            data, refs = handlers[name](arguments)
            reply = {'ok': True, 'tool': name, 'data': compact(data), 'evidence': refs[:50], 'warnings': [WARNING], 'error': None}
            if len(encode(reply)) > 24000:
                reply['data'] = {'omitted': True, 'reason': 'result_size_limit', 'hint': '缩小 limit、days 或日期区间后重试。'}
            return json.loads(encode(reply))
        except (LookupError, ValueError, OSError, TypeError, KeyError) as error:
            code = getattr(error, 'code', None) or ('NOT_FOUND' if isinstance(error, LookupError) else 'LIMIT_RESEARCH_READ_FAILED')
            return {'ok': False, 'tool': name, 'data': None, 'evidence': [], 'warnings': [], 'error': {'code': code, 'message': str(error)[:240]}}


__all__ = ['TOOLS', 'TOOL_NAMES', 'WRITE_TOOLS', 'WRITE_TOOL_NAMES', 'LimitResearchAPI']
