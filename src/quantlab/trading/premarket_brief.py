"""Pre-market limit-board brief (research_only).

For a target session it gathers, from data known after the last close before that session: the close review's sentiment state and
key metrics, still-valid confirmed conclusions (MONITORING) with the stocks matching their conditions as an observation list,
decaying conclusions as warnings, top themes, forecasts recorded for the session with the scorecard, and versioned rule-based risk
flags with trailing percentiles. Facts and machine states only; it is never a trading instruction.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import hashlib
import json
import re

from quantlab.storage.codec import digest, encode

FORMAT = 'limit-premarket-brief-v1'
RISK_RULES_VERSION = 'premarket-risk-v1'
MAX_BASIS_GAP_DAYS = 14
MAX_CANDIDATES = 30
BRIEF = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
KEY_LIMIT = ('limit_up_count', 'limit_up_count_non_st', 'limit_down_count', 'limit_down_count_non_st', 'broken_rate', 'max_streak',
             'advance_rate_1to2', 'advance_rate_2plus', 'prev_limit_up_avg_return', 'prev_limit_up_win_rate', 'big_loss_count', 'high_board_broken')
KEY_MARKET = ('up_count', 'down_count', 'up_ratio', 'amount_total_yi', 'amount_change')
PHASE_RISKS = {'CLIMAX': '高潮次日容易分歧', 'DIVERGENCE': '分歧', 'EBB': '退潮', 'ICE': '冰点'}
# (code, metric, test, label, severity); thresholds sit near the 80th–90th percentile of the last 250 sessions when introduced.
RISK_RULES = (
    ('BROKEN_RATE_HIGH', 'broken_rate', lambda v: v >= 0.40, '炸板率 ≥ 40%', 'WARN'),
    ('LIMIT_DOWN_MANY', 'limit_down_count_non_st', lambda v: v >= 20, '非 ST 跌停 ≥ 20 家', 'WARN'),
    ('BIG_LOSS_MANY', 'big_loss_count', lambda v: v >= 15, '大面 ≥ 15 家', 'WARN'),
    ('PREV_LIMIT_UP_NEGATIVE', 'prev_limit_up_avg_return', lambda v: v < 0, '昨日涨停股今日平均收益为负', 'WARN'),
    ('AMOUNT_SHRINK', 'amount_change', lambda v: v <= -0.10, '成交额较前一日缩量 ≥ 10%', 'WARN'),
    ('HIGH_BOARD_BROKEN', 'high_board_broken', lambda v: v is True, '最高连板股断板（常见，仅提示）', 'INFO'),
)
LIMITATIONS = [
    '盘前简报只用目标交易日之前最后一个收盘后的数据；情绪周期、相似日与风险规则都是版本化工程规则，不是预测或交易信号。',
    '“仍有效的规律”只列宿主晋级确认、且前瞻监控为 MONITORING 的结论；符合条件的股票只是观察名单，不是买入建议，也不代表能成交。',
    '当日涨停价打板类结论依赖盘中信息，盘前无法列出符合条件的股票。',
    '预测部分只列已记录的概率与记分卡；样本不足时不能说明任何预测者有预测能力。',
]


class PremarketBriefError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def code_fingerprint():
    folder = Path(__file__).resolve().parent
    names = ('premarket_brief.py', 'daily_review.py', 'research_conclusions.py', 'limit_forecasts.py', 'event_study.py')
    files = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in names}
    return {'files': files, 'digest': digest(files)}


def _day(value, name='target_day'):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise PremarketBriefError('INVALID_ARGUMENT', name + ' 必须为 YYYY-MM-DD。')


def _pct(value, signed=False):
    if value is None:
        return '—'
    return f'{value * 100:+.1f}%' if signed else f'{value * 100:.1f}%'


class PremarketBriefLibrary:
    def __init__(self, output, *, now_fn=None, registry=None, conclusions=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise PremarketBriefError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._registry, self._conclusions = registry, conclusions
        self.root = self.output / '_limit_research' / 'premarket_brief'

    def registry(self):
        if self._registry is None:
            from quantlab.trading.event_study import EventStudyRegistry
            self._registry = EventStudyRegistry(self.output, now_fn=self.now_fn)
        return self._registry

    def conclusions(self):
        if self._conclusions is None:
            from quantlab.trading.research_conclusions import ConclusionLibrary
            self._conclusions = ConclusionLibrary(self.output, now_fn=self.now_fn)
        return self._conclusions

    # ---- inputs -----------------------------------------------------------------------------------------
    def resolve(self, target_day):
        from quantlab.trading.daily_review import DailyReviewLibrary
        from quantlab.trading.limit_forecasts import LimitForecastJournal
        target = _day(target_day)
        review = DailyReviewLibrary(self.output).latest_on_or_before(target - timedelta(days=1))
        if review is None:
            raise PremarketBriefError('REVIEW_MISSING', f'{target} 之前没有收盘复盘，不能生成盘前简报。')
        basis = date.fromisoformat(review['trading_day'])
        if (target - basis).days > MAX_BASIS_GAP_DAYS:
            raise PremarketBriefError('REVIEW_STALE', f'最近的收盘复盘是 {basis}，距离目标交易日超过 {MAX_BASIS_GAP_DAYS} 天。')
        conclusions = self.conclusions().list()
        forecasts = LimitForecastJournal(self.output).forecasts(target)
        inputs = {'review_id': review['review_id'], 'basis_day': basis.isoformat(), 'limit_event_build_id': review['inputs']['limit_event_build_id'],
                  'market_sentiment_build_id': review['inputs']['market_sentiment_build_id'],
                  'conclusions': sorted([c['conclusion_id'], c['status'], (c['latest_monitoring'] or {}).get('as_of_day')] for c in conclusions),
                  'forecasts': sorted(f['forecast_id'] for f in forecasts)}
        identity = {'format': FORMAT, 'code_fingerprint': code_fingerprint()['digest'], 'risk_rules_version': RISK_RULES_VERSION,
                    'target_day': target.isoformat(), 'inputs': inputs}
        return {'target': target, 'basis': basis, 'review': review, 'conclusions': conclusions, 'forecasts': forecasts, 'identity': identity,
                'brief_id': str(uuid5(NAMESPACE_URL, 'niuniu-premarket-brief:' + digest(identity)))}

    # ---- sections -----------------------------------------------------------------------------------------
    def _sentiment(self, review):
        facts, state = review['facts'], review['machine_state']
        previous = facts.get('previous_day') or {}
        neighbors = (state.get('similar_days') or {}).get('neighbors') or []
        analog = None
        if neighbors:
            counts = sorted(n['next_limit_up_count'] for n in neighbors if n.get('next_limit_up_count') is not None)
            returns = [n['next_prev_limit_up_avg_return'] for n in neighbors if n.get('next_prev_limit_up_avg_return') is not None]
            analog = {'days': len(neighbors), 'dates': [n['date'] for n in neighbors],
                      'next_limit_up_count_range': [counts[0], counts[-1]] if counts else None,
                      'next_prev_limit_up_avg_return_mean': sum(returns) / len(returns) if returns else None}
        return {'basis_day': review['trading_day'], 'phase': state['phase'], 'temperature': state['temperature'], 'previous_phase': state.get('previous_phase'),
                'rules_version': state['rules_version'], 'limit': {k: facts['limit'].get(k) for k in KEY_LIMIT},
                'market': {k: facts['market'].get(k) for k in KEY_MARKET},
                'previous_day': {k: previous.get(k) for k in ('date', 'limit_up_count_non_st', 'limit_down_count_non_st', 'broken_rate', 'max_streak')},
                'similar_days': analog}

    def _percentiles(self, build_id, basis):
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        daily, _ = MarketSentimentLibrary(self.output).read(build_id)
        daily = daily.sort('date')
        dates = daily['date'].to_list()
        if basis not in dates:
            return {}
        index = dates.index(basis)
        result = {}
        for _, metric, _, _, _ in RISK_RULES:
            if metric == 'high_board_broken' or metric not in daily.columns:
                continue
            history = [v for v in daily[metric].to_list()[max(0, index - 250):index] if v is not None]
            value = daily[metric][index]
            result[metric] = None if value is None or len(history) < 60 else sum(v <= value for v in history) / len(history)
        return result

    def _risks(self, sentiment, percentiles, decaying, gaps):
        values = {**sentiment['limit'], **sentiment['market']}
        flags = []
        for code, metric, test, label, severity in RISK_RULES:
            value = values.get(metric)
            if value is not None and test(value):
                flags.append({'code': code, 'severity': severity, 'label': label, 'metric': metric, 'value': value,
                              'percentile_250': percentiles.get(metric)})
        if sentiment['phase'] in PHASE_RISKS:
            flags.append({'code': 'PHASE_' + sentiment['phase'], 'severity': 'WARN', 'label': '情绪周期：' + PHASE_RISKS[sentiment['phase']],
                          'metric': 'phase', 'value': sentiment['phase'], 'percentile_250': None})
        if decaying:
            flags.append({'code': 'DECAYING_CONCLUSIONS', 'severity': 'WARN', 'label': '有已确认规律进入衰减，不应再当作有效', 'metric': 'conclusions',
                          'value': len(decaying), 'percentile_250': None})
        if gaps:
            flags.append({'code': 'DATA_GAPS', 'severity': 'WARN', 'label': '数据缺口：' + '、'.join(gaps), 'metric': 'coverage', 'value': len(gaps),
                          'percentile_250': None})
        return flags

    def _conclusion_section(self, resolved):
        from quantlab.data.public_evidence import PublicEvidenceArchive, PublicEvidenceError
        basis, inputs = resolved['basis'], resolved['identity']['inputs']
        names = {}
        try:
            pool, _ = PublicEvidenceArchive(self.output).read_table('em_limit_up_pool', basis)
            names = dict(zip(pool['symbol'].to_list(), pool['name'].to_list()))
        except PublicEvidenceError:
            pass
        valid, decaying, stale = [], [], []
        for summary in resolved['conclusions']:
            monitoring = summary['latest_monitoring'] or {}
            compact = {k: summary[k] for k in ('conclusion_id', 'hypothesis', 'expected_sign', 'condition', 'baseline_condition', 'outcome')}
            compact.update(entry=(summary['execution'] or {}).get('entry'), p_holm=summary['confirmation']['p_holm'],
                           family_size=summary['confirmation']['family_size'], confirmation_window=summary['confirmation']['window'],
                           monitoring_as_of=monitoring.get('as_of_day'), health=monitoring.get('health'), reasons=monitoring.get('reasons'),
                           recent=(monitoring.get('windows') or {}).get('recent'))
            if summary['status'] == 'DECAYING':
                decaying.append(compact)
                continue
            if summary['status'] != 'MONITORING':
                continue
            if summary['confirmation']['window']['end'] < basis.isoformat() and (monitoring.get('as_of_day') or '') < basis.isoformat():
                stale.append(summary['conclusion_id'])
            if compact['entry'] == 't0_limit_price':
                compact.update(candidates=None, candidate_count=None, candidate_note='当日涨停价打板依赖盘中信息，盘前无法列出')
            else:
                spec = self.conclusions().get(summary['conclusion_id'])['confirmation']['spec']
                spec = {**spec, 'library_build_id': inputs['limit_event_build_id'],
                        'sentiment_build_id': inputs['market_sentiment_build_id'] if spec['sentiment_build_id'] else None}
                try:
                    matched = self.registry().matching_events(spec, basis)
                    rows = matched.head(MAX_CANDIDATES).to_dicts()
                    compact.update(candidate_count=matched.height, candidate_note=None, candidates=[
                        {'code': r['code'], 'name': names.get(r['code']), 'board': r.get('board'), 'limit_up_streak': r.get('limit_up_streak'),
                         'close': r.get('close'), 'day_ret': r.get('day_ret'), 'is_st': r.get('is_st')} for r in rows])
                except ValueError as error:
                    compact.update(candidates=None, candidate_count=None, candidate_note='无法筛选：' + str(error)[:120])
            valid.append(compact)
        return {'monitoring': valid, 'decaying': decaying, 'stale_monitoring': stale}

    def _forecasts(self, forecasts):
        from quantlab.trading.limit_forecasts import LimitForecastJournal, question_catalog
        by_question = {}
        for record in forecasts:
            by_question.setdefault(record['question_id'], []).append({'forecaster': record['forecaster'], 'probability': record['probability']})
        questions = [{'question_id': q['question_id'], 'label': q['label'],
                      'forecasts': sorted(by_question.get(q['question_id'], []), key=lambda r: r['forecaster'])} for q in question_catalog()['questions']]
        scorecard = LimitForecastJournal(self.output).scorecard()
        return {'questions': questions, 'recorded': len(forecasts),
                'scorecard': [{k: row[k] for k in ('forecaster', 'resolved', 'sample_status', 'mean_brier', 'brier_skill_vs_climatology')}
                              for row in scorecard['forecasters']]}

    # ---- build & storage ----------------------------------------------------------------------------------
    def _dir(self, target):
        for path in (self.output / '_limit_research', self.root, self.root / target.isoformat()):
            if path.is_symlink():
                raise PremarketBriefError('INVALID_WORKSPACE', '盘前简报目录不能是符号链接。')
        return self.root / target.isoformat()

    def is_current(self, target_day):
        try:
            resolved = self.resolve(target_day)
        except PremarketBriefError:
            return False
        return (self._dir(resolved['target']) / f"{resolved['brief_id']}.json").is_file()

    def build(self, target_day):
        resolved = self.resolve(target_day)
        folder = self._dir(resolved['target'])
        path = folder / f"{resolved['brief_id']}.json"
        if path.exists():
            return {**self.get(resolved['target'], resolved['brief_id']), 'created': False}
        review = resolved['review']
        sentiment = self._sentiment(review)
        conclusions = self._conclusion_section(resolved)
        forecasts = self._forecasts(resolved['forecasts'])
        gaps = [name for name, present in review['facts']['coverage'].items() if not present]
        if not any(f['forecaster'].startswith('baseline:') for q in forecasts['questions'] for f in q['forecasts']):
            gaps.append('baseline_forecasts')
        if conclusions['stale_monitoring']:
            gaps.append('conclusion_monitoring')
        previous_weekday = resolved['target'] - timedelta(days=1)
        while previous_weekday.weekday() >= 5:
            previous_weekday -= timedelta(days=1)
        if resolved['basis'] < previous_weekday:
            gaps.append('review_before_previous_weekday')  # a missing close review, or a holiday in between
        percentiles = self._percentiles(resolved['identity']['inputs']['market_sentiment_build_id'], resolved['basis'])
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise PremarketBriefError('INVALID_CLOCK', '时钟必须带时区。')
        brief = {**resolved['identity'], 'brief_id': resolved['brief_id'], 'created_at': created.astimezone(timezone.utc).isoformat(),
                 'basis_day': resolved['basis'].isoformat(), 'sentiment': sentiment,
                 'ladder': [{'streak': level['streak'], 'count': level['count'], 'stocks': [s['name'] or s['code'] for s in level['stocks'][:5]]}
                            for level in review['facts']['ladder']['levels'][:3]],
                 'themes': [{k: t.get(k) for k in ('board_name', 'limit_up_count', 'max_streak', 'persistence_days', 'leaders')}
                            for t in ((review['facts'].get('themes') or {}).get('concept') or [])[:5]],
                 'pool_industries': ((review['facts'].get('themes') or {}).get('pool_industries') or [])[:5],
                 'conclusions': conclusions, 'forecasts': forecasts, 'gaps': gaps,
                 'risks': self._risks(sentiment, percentiles, conclusions['decaying'], gaps),
                 'qualification': 'research_only', 'limitations': LIMITATIONS}
        brief = json.loads(encode(brief))
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f".{resolved['brief_id']}.tmp"
        temporary.write_text(encode({**brief, 'checksum': digest(brief)}), encoding='utf-8')
        temporary.replace(path)
        return {**brief, 'created': True}

    def get(self, target_day, brief_id=None):
        target = _day(target_day)
        folder = self._dir(target)
        if brief_id is not None and (not isinstance(brief_id, str) or not BRIEF.fullmatch(brief_id)):
            raise PremarketBriefError('NOT_FOUND', '盘前简报不存在。')
        candidates = [folder / f'{brief_id}.json'] if brief_id else (sorted(folder.glob('*.json')) if folder.is_dir() else [])
        briefs = []
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            value = json.loads(path.read_bytes())
            core = {k: v for k, v in value.items() if k != 'checksum'}
            if value.get('checksum') != digest(core) or core.get('format') != FORMAT:
                raise PremarketBriefError('CORRUPT_ARCHIVE', path.name + ' 校验失败。')
            briefs.append(core)
        if not briefs:
            raise PremarketBriefError('NOT_FOUND', f'{target} 没有盘前简报。')
        return max(briefs, key=lambda b: (b['created_at'], b['brief_id']))


def render_markdown(brief):
    """Short Chinese pre-market summary; every number comes from the stored brief."""
    s, limit, market = brief['sentiment'], brief['sentiment']['limit'], brief['sentiment']['market']
    from quantlab.trading.daily_review import PHASE_LABELS
    lines = [f"## {brief['target_day']} 盘前简报（依据 {brief['basis_day']} 收盘，research_only）", '',
             f"- 情绪周期：{PHASE_LABELS.get(s['phase'], s['phase'])}（温度 {s['temperature'] if s['temperature'] is not None else '—'}）· 规则 {s['rules_version']}",
             f"- 非ST涨停 {limit['limit_up_count_non_st']}、非ST跌停 {limit['limit_down_count_non_st']}；炸板率 {_pct(limit['broken_rate'])}；最高 {limit['max_streak']} 板；"
             f"1进2 {_pct(limit['advance_rate_1to2'])}；昨日涨停今日均值 {_pct(limit['prev_limit_up_avg_return'], signed=True)}",
             f"- 成交额 {market.get('amount_total_yi', '—')} 亿元（{_pct(market['amount_change'], signed=True)}）；上涨 {market['up_count']} / 下跌 {market['down_count']}"]
    if brief['ladder']:
        lines.append('- 连板梯队：' + '；'.join(f"{level['streak']}板 {level['count']} 家（{'、'.join(level['stocks'][:3])}）" for level in brief['ladder']))
    if brief['themes']:
        lines.append('- 题材（按涨停家数）：' + '；'.join(f"{t['board_name']} {t['limit_up_count']}家" for t in brief['themes']))
    elif brief['pool_industries']:
        lines.append('- 股池行业分布（缺板块成分时的替代）：' + '；'.join(f"{t['industry']} {t['limit_up_count']}" for t in brief['pool_industries']))
    valid = brief['conclusions']['monitoring']
    lines.append(f"- 仍有效的已确认规律：{len(valid)} 条" + ('' if valid else '（暂无；未授权研究计划或尚无宿主晋级确认的结论）'))
    for item in valid[:5]:
        count = '盘中条件，盘前无法列出' if item['candidate_count'] is None else f"符合条件 {item['candidate_count']} 只（观察名单，不是买入建议）"
        lines.append(f"  - {item['hypothesis'][:60]}：{count}")
    for item in brief['conclusions']['decaying'][:3]:
        lines.append(f"  - 衰减中（不应再当作有效）：{item['hypothesis'][:60]}（{'、'.join(item['reasons'] or [])}）")
    recorded = [q for q in brief['forecasts']['questions'] if q['forecasts']]
    if recorded:
        lines.append('- 已记录预测：' + '；'.join(f"{q['label']} " + '/'.join(f"{f['forecaster'].split(':')[-1]} {f['probability']:.0%}" for f in q['forecasts'])
                                                for q in recorded[:6]))
    if brief['risks']:
        lines.append('- 风险提示：' + '；'.join(r['label'] for r in brief['risks']))
    return '\n'.join(lines)


__all__ = ['FORMAT', 'RISK_RULES_VERSION', 'LIMITATIONS', 'PremarketBriefError', 'PremarketBriefLibrary', 'render_markdown']
