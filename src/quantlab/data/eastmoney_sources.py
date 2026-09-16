"""Eastmoney public webpage sources for after-close limit-board evidence (research_only)."""
from __future__ import annotations

from datetime import date
from urllib.parse import quote
import json
import math
import re

import polars as pl

from .public_evidence import ParsedTable, PublicEvidenceError, RequestSpec, Source

POOL_UT = '7eea3edcaed734bea9cbfc24409ed989'
CODE = re.compile(r'^\d{6}$')
POOL_LIMITATIONS = (
    '东方财富网页股池接口只保留近期数据，必须按日前瞻归档，不能补历史。',
    '涨停统计、封板资金、首次/最后封板时间等为供应商口径，未经交易所核验。',
)


def em_symbol(code, market):
    if not isinstance(code, str) or not CODE.fullmatch(code) or market not in (0, 1):
        raise PublicEvidenceError('DATA_SCHEMA', f'证券代码或市场标记无效：{code}/{market}')
    if market == 1:
        return 'sh.' + code
    if code.startswith(('4', '8', '92')):
        return 'bj.' + code
    return 'sz.' + code


def _number(value, key, *, positive=False, nullable=True):
    if value is None or value == '' or value == '-':
        if nullable:
            return None
        raise PublicEvidenceError('DATA_SCHEMA', key + ' 不能为空。')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicEvidenceError('DATA_SCHEMA', key + ' 必须为数值。')
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise PublicEvidenceError('DATA_SCHEMA', key + ' 数值无效。')
    return number


def _integer(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicEvidenceError('DATA_SCHEMA', key + ' 必须为整数。')
    return value


def _hhmmss(value, key):
    value = _integer(value, key)
    hours, rest = divmod(value, 10000)
    minutes, seconds = divmod(rest, 100)
    if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
        raise PublicEvidenceError('DATA_SCHEMA', key + ' 时间格式无效。')
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


KINDS = {
    'price1000': pl.Float64, 'float': pl.Float64, 'int': pl.Int64, 'hhmmss': pl.String, 'str': pl.String,
}


class EastmoneyPoolSource(Source):
    parser_version = 'em-pool-v1'

    def __init__(self, source_id, api, sort, fields, description):
        self.source_id, self.api, self.sort, self.fields, self.description = source_id, api, sort, fields, description
        self.limitations = POOL_LIMITATIONS

    def requests(self, day):
        url = (f'https://push2ex.eastmoney.com/{self.api}?ut={POOL_UT}&dpt=wz.ztzt&Pageindex=0&pagesize=10000'
               f'&sort={quote(self.sort, safe="")}&date={day:%Y%m%d}')
        return [RequestSpec(url)]

    def schema(self):
        schema = {'symbol': pl.String, 'code': pl.String, 'name': pl.String}
        for _key, name, kind in self.fields:
            if kind == 'zttj':
                schema['stat_days'] = pl.Int64
                schema['stat_limit_ups'] = pl.Int64
            else:
                schema[name] = KINDS[kind]
        return schema

    def parse(self, day, responses):
        if len(responses) != 1:
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 应只有一个响应。')
        try:
            value = json.loads(responses[0].body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 响应不是 JSON。') from None
        if not isinstance(value, dict) or value.get('rc') != 0:
            raise PublicEvidenceError('PROVIDER_ERROR', self.source_id + ' 返回错误码：' + str(value.get('rc') if isinstance(value, dict) else None))
        data = value.get('data')
        warnings = []
        if data is None:
            return ParsedTable([], self.schema(), ['NO_DATA_OBJECT'])
        pool = data.get('pool') if isinstance(data, dict) else None
        if not isinstance(pool, list) or data.get('tc') != len(pool):
            raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 股池数量与 tc 不一致或结构无效。')
        required = {'c', 'm', 'n'} | {key for key, _name, _kind in self.fields}
        extra = set()
        rows = []
        for item in pool:
            if not isinstance(item, dict) or required - set(item):
                raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 缺少字段：' + ', '.join(sorted(required - set(item or {}))))
            extra |= set(item) - required
            if not isinstance(item['n'], str):
                raise PublicEvidenceError('DATA_SCHEMA', 'name 必须为字符串。')
            row = [em_symbol(item['c'], item['m']), item['c'], item['n']]
            for key, name, kind in self.fields:
                raw = item[key]
                if kind == 'price1000':
                    number = _number(raw, key, positive=True, nullable=False)
                    row.append(round(number / 1000, 4))
                elif kind == 'float':
                    row.append(_number(raw, key))
                elif kind == 'int':
                    row.append(_integer(raw, key))
                elif kind == 'hhmmss':
                    row.append(_hhmmss(raw, key))
                elif kind == 'str':
                    if raw is not None and not isinstance(raw, str):
                        raise PublicEvidenceError('DATA_SCHEMA', key + ' 必须为字符串。')
                    row.append(raw)
                elif kind == 'zttj':
                    if not isinstance(raw, dict) or set(raw) != {'days', 'ct'}:
                        raise PublicEvidenceError('DATA_SCHEMA', 'zttj 结构无效。')
                    row.extend([_integer(raw['days'], 'zttj.days'), _integer(raw['ct'], 'zttj.ct')])
            rows.append(row)
        if len({r[0] for r in rows}) != len(rows):
            raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 证券重复。')
        if extra:
            warnings.append('UNEXPECTED_FIELDS:' + ','.join(sorted(extra)))
        rows.sort(key=lambda r: r[0])
        return ParsedTable(rows, self.schema(), warnings)


COMMON = [('p', 'price', 'price1000'), ('zdp', 'pct_change', 'float'), ('amount', 'amount', 'float'),
          ('ltsz', 'float_market_cap', 'float'), ('tshare', 'total_market_cap', 'float')]


def pool_sources():
    return [
        EastmoneyPoolSource('em_limit_up_pool', 'getTopicZTPool', 'fbt:asc', COMMON + [
            ('hs', 'turnover_rate', 'float'), ('lbc', 'limit_up_streak', 'int'), ('fbt', 'first_seal_time', 'hhmmss'),
            ('lbt', 'last_seal_time', 'hhmmss'), ('fund', 'seal_fund', 'float'), ('zbc', 'broken_times', 'int'),
            ('hybk', 'industry', 'str'), ('zttj', 'zttj', 'zttj')], '东方财富涨停股池（首次/最后封板时间、封板资金、炸板次数、连板数）'),
        EastmoneyPoolSource('em_prev_limit_up_pool', 'getYesterdayZTPool', 'zs:desc', COMMON + [
            ('ztp', 'limit_up_price', 'price1000'), ('hs', 'turnover_rate', 'float'), ('zf', 'amplitude', 'float'),
            ('zs', 'speed', 'float'), ('yfbt', 'prev_first_seal_time', 'hhmmss'), ('ylbc', 'prev_limit_up_streak', 'int'),
            ('hybk', 'industry', 'str'), ('zttj', 'zttj', 'zttj')], '东方财富昨日涨停股池（今日表现）'),
        EastmoneyPoolSource('em_broken_board_pool', 'getTopicZBPool', 'fbt:asc', COMMON + [
            ('ztp', 'limit_up_price', 'price1000'), ('hs', 'turnover_rate', 'float'), ('fbt', 'first_seal_time', 'hhmmss'),
            ('zbc', 'broken_times', 'int'), ('zf', 'amplitude', 'float'), ('zs', 'speed', 'float'),
            ('hybk', 'industry', 'str'), ('zttj', 'zttj', 'zttj')], '东方财富炸板股池'),
        EastmoneyPoolSource('em_limit_down_pool', 'getTopicDTPool', 'fund:asc', COMMON + [
            ('pe', 'pe_dynamic', 'float'), ('hs', 'turnover_rate', 'float'), ('fund', 'seal_fund', 'float'),
            ('lbt', 'last_seal_time', 'hhmmss'), ('fba', 'amount_at_limit', 'float'), ('days', 'limit_down_streak', 'int'),
            ('oc', 'open_times', 'int'), ('hybk', 'industry', 'str')], '东方财富跌停股池'),
        EastmoneyPoolSource('em_strong_pool', 'getTopicQSPool', 'zdp:desc', COMMON + [
            ('ztp', 'limit_up_price', 'price1000'), ('ztf', 'em_ztf', 'str'), ('hs', 'turnover_rate', 'float'),
            ('nh', 'em_new_high_flag', 'int'), ('cc', 'em_selection_code', 'int'), ('lb', 'volume_ratio', 'float'),
            ('zs', 'speed', 'float'), ('hybk', 'industry', 'str'), ('zttj', 'zttj', 'zttj')], '东方财富强势股池（入选代码语义未公开）'),
    ]


def default_sources():
    return pool_sources()


__all__ = ['POOL_UT', 'EastmoneyPoolSource', 'default_sources', 'em_symbol', 'pool_sources']
