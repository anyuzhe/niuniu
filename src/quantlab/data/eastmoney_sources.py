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


BILLBOARD_LIMITATIONS = (
    '龙虎榜由交易所盘后公布，东方财富约在收盘后数小时内更新；尚未发布时不写入，等待重试。',
    '供应商的未来收益列（D1/D2/D5/D10/D20/D30_CLOSE_ADJCHRATE）一律丢弃，避免未来函数。',
    'EXPLAIN、席位上涨概率等为供应商统计或解读，不是事实，只能作为待验证特征。',
)
FUTURE_COLUMNS = frozenset({'D1_CLOSE_ADJCHRATE', 'D2_CLOSE_ADJCHRATE', 'D5_CLOSE_ADJCHRATE', 'D10_CLOSE_ADJCHRATE',
                            'D20_CLOSE_ADJCHRATE', 'D30_CLOSE_ADJCHRATE'})
SECUCODE = re.compile(r'^(\d{6})\.(SH|SZ|BJ)$')
A_SHARE_PREFIXES = ('sh.600', 'sh.601', 'sh.603', 'sh.605', 'sh.688', 'sh.689', 'sz.000', 'sz.001', 'sz.002', 'sz.003',
                    'sz.300', 'sz.301', 'sz.302', 'bj.4', 'bj.8', 'bj.92')


def secucode_symbol(value):
    match = SECUCODE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise PublicEvidenceError('DATA_SCHEMA', 'SECUCODE 无效：' + str(value))
    return match.group(2).lower() + '.' + match.group(1)


class EastmoneyDatacenterSource(Source):
    parser_version = 'em-datacenter-v1'
    PAGE_SIZE = 500
    MAX_PAGES = 40

    def __init__(self, source_id, report, sort_column, sort_type, fields, key_fields, description, ignored=()):
        self.source_id, self.report, self.sort_column, self.sort_type = source_id, report, sort_column, sort_type
        self.fields, self.key_fields, self.description = fields, key_fields, description
        self.ignored = frozenset(ignored)
        self.limitations = BILLBOARD_LIMITATIONS

    def _url(self, day, page):
        return ('https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=' + self.report + '&columns=ALL'
                + '&filter=' + quote(f"(TRADE_DATE='{day.isoformat()}')", safe='') + f'&pageNumber={page}&pageSize={self.PAGE_SIZE}'
                + f'&sortTypes={self.sort_type}&sortColumns={self.sort_column}&source=WEB&client=WEB')

    def requests(self, day):
        return [RequestSpec(self._url(day, 1))]

    @staticmethod
    def _load(response, source_id):
        try:
            value = json.loads(response.body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise PublicEvidenceError('DATA_SCHEMA', source_id + ' 响应不是 JSON。') from None
        if not isinstance(value, dict):
            raise PublicEvidenceError('DATA_SCHEMA', source_id + ' 响应结构无效。')
        if value.get('code') == 9201 or value.get('result') is None:
            raise PublicEvidenceError('NOT_READY', source_id + ' 数据尚未发布或为空：' + str(value.get('message'))[:80])
        result = value['result']
        if value.get('success') is not True or not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise PublicEvidenceError('PROVIDER_ERROR', source_id + ' 返回失败：' + str(value.get('message'))[:80])
        pages = result.get('pages')
        if type(pages) is not int or pages < 1:
            raise PublicEvidenceError('DATA_SCHEMA', source_id + ' 分页信息无效。')
        return result

    def follow_up(self, day, responses):
        if len(responses) != 1:
            return []
        pages = self._load(responses[0], self.source_id)['pages']
        if pages > self.MAX_PAGES:
            raise PublicEvidenceError('BUDGET_EXCEEDED', self.source_id + ' 分页数超过上限。')
        return [RequestSpec(self._url(day, page)) for page in range(2, pages + 1)]

    def schema(self):
        schema = {'symbol': pl.String, 'is_a_share': pl.Boolean}
        for _key, name, kind in self.fields:
            schema[name] = {'str': pl.String, 'float': pl.Float64, 'int': pl.Int64, 'nstr': pl.String}[kind]
        return schema

    def parse(self, day, responses):
        rows, extra = [], set()
        pages = None
        count = None
        required = {'SECUCODE', 'TRADE_DATE'} | {key for key, _name, kind in self.fields if kind != 'nstr'}
        for index, response in enumerate(responses):
            result = self._load(response, self.source_id)
            if pages is None:
                pages, count = result['pages'], result.get('count')
            elif result['pages'] != pages:
                raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 分页过程中页数变化。')
            for item in result['data']:
                if not isinstance(item, dict) or required - set(item):
                    raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 缺少字段：' + ', '.join(sorted(required - set(item or {}))))
                if item['TRADE_DATE'] != day.isoformat() + ' 00:00:00':
                    raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 返回了其他交易日：{item["TRADE_DATE"]}')
                known = required | {key for key, _n, _k in self.fields}
                extra |= set(item) - known - FUTURE_COLUMNS - self.ignored
                symbol = secucode_symbol(item['SECUCODE'])
                row = [symbol, symbol.startswith(A_SHARE_PREFIXES)]
                for key, name, kind in self.fields:
                    raw = item.get(key)
                    if kind in ('str', 'nstr'):
                        if raw is not None and not isinstance(raw, str):
                            raw = str(raw)
                        if kind == 'str' and raw is None:
                            raise PublicEvidenceError('DATA_SCHEMA', key + ' 不能为空。')
                        row.append(raw)
                    elif kind == 'float':
                        row.append(_number(raw, key))
                    elif kind == 'int':
                        if raw is None:
                            row.append(None)
                        else:
                            row.append(_integer(raw, key))
                rows.append(row)
        if pages is not None and len(responses) != pages:
            raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 分页未取全。')
        if type(count) is int and count != len(rows):
            raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} 行数与 count 不一致。')
        names = list(self.schema())
        key_index = [names.index(k) for k in self.key_fields]
        rows.sort(key=lambda r: tuple('' if r[i] is None else str(r[i]) for i in key_index))
        warnings = ['UNEXPECTED_FIELDS:' + ','.join(sorted(extra))] if extra else []
        return ParsedTable(rows, self.schema(), warnings)


def billboard_sources():
    seats = [('SECURITY_CODE', 'code', 'str'), ('OPERATEDEPT_CODE', 'seat_code', 'str'), ('OPERATEDEPT_NAME', 'seat_name', 'str'),
             ('EXPLANATION', 'reason', 'str'), ('CHANGE_RATE', 'pct_change', 'float'), ('CLOSE_PRICE', 'close', 'float'),
             ('ACCUM_AMOUNT', 'amount', 'float'), ('ACCUM_VOLUME', 'volume', 'float'), ('BUY', 'buy', 'float'),
             ('SELL', 'sell', 'float'), ('NET', 'net', 'float'), ('TOTAL_BUYRIO', 'buy_ratio', 'float'),
             ('TOTAL_SELLRIO', 'sell_ratio', 'float'), ('RISE_PROBABILITY_3DAY', 'em_seat_rise_probability_3d', 'float'),
             ('TOTAL_BUYER_SALESTIMES_3DAY', 'em_seat_times_3d', 'float'), ('CHANGE_TYPE', 'change_type', 'nstr'),
             ('OPERATEDEPT_CODE_OLD', 'seat_code_old', 'nstr'), ('TRADE_ID', 'trade_id', 'nstr')]
    return [
        EastmoneyDatacenterSource('em_billboard_daily', 'RPT_DAILYBILLBOARD_DETAILSNEW', 'SECURITY_CODE', 1, [
            ('SECURITY_CODE', 'code', 'str'), ('SECURITY_NAME_ABBR', 'name', 'str'), ('EXPLANATION', 'reason', 'str'),
            ('CLOSE_PRICE', 'close', 'float'), ('CHANGE_RATE', 'pct_change', 'float'), ('TURNOVERRATE', 'turnover_rate', 'float'),
            ('FREE_MARKET_CAP', 'free_market_cap', 'float'), ('ACCUM_AMOUNT', 'amount', 'float'),
            ('BILLBOARD_BUY_AMT', 'billboard_buy', 'float'), ('BILLBOARD_SELL_AMT', 'billboard_sell', 'float'),
            ('BILLBOARD_NET_AMT', 'billboard_net', 'float'), ('BILLBOARD_DEAL_AMT', 'billboard_deal', 'float'),
            ('DEAL_NET_RATIO', 'net_ratio', 'float'), ('DEAL_AMOUNT_RATIO', 'deal_ratio', 'float'),
            ('EXPLAIN', 'em_explain', 'nstr'), ('CHANGE_TYPE', 'change_type', 'nstr'), ('TRADE_ID', 'trade_id', 'nstr'),
            ('MARKET', 'market', 'nstr')], ('symbol', 'trade_id', 'reason'), '东方财富龙虎榜每日上榜明细（上榜原因、买卖总额、净额）',
            ignored=('BUY_RATIO', 'BUY_SEAT', 'BUY_SEAT_NEW', 'NET_BS_AMT', 'SECURITY_INNER_CODE', 'SECURITY_TYPE_CODE',
                     'SELL_RATIO', 'SELL_SEAT', 'SELL_SEAT_NEW', 'SUM_BUY_AMT', 'SUM_SELL_AMT', 'TRADE_MARKET', 'TRADE_MARKET_CODE')),
        EastmoneyDatacenterSource('em_billboard_buy_seats', 'RPT_BILLBOARD_DAILYDETAILSBUY', 'BUY', -1, seats,
                                  ('symbol', 'trade_id', 'seat_code', 'reason'), '东方财富龙虎榜买入营业部席位'),
        EastmoneyDatacenterSource('em_billboard_sell_seats', 'RPT_BILLBOARD_DAILYDETAILSSELL', 'SELL', -1, seats,
                                  ('symbol', 'trade_id', 'seat_code', 'reason'), '东方财富龙虎榜卖出营业部席位'),
    ]


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
    return pool_sources() + billboard_sources()


__all__ = ['POOL_UT', 'EastmoneyPoolSource', 'EastmoneyDatacenterSource', 'billboard_sources', 'default_sources',
           'em_symbol', 'pool_sources', 'secucode_symbol']
