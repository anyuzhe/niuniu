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


SNAPSHOT_LIMITATIONS = (
    '板块与人气数据是抓取时刻的快照，不能按日期回查；只允许当日收盘后或下一交易日开盘前抓取。',
    '板块划分、成分与领涨股为东方财富口径，成分变动时间未知，不是官方行业分类。',
    '板块数据取自东方财富延时行情主机 push2delay；收盘后与收盘值一致，盘中不可用作实时数据。',
)
CLIST_PAGE = 100
BOARD_FIELDS = 'f12,f13,f14,f2,f3,f5,f6,f8,f104,f105,f128,f140,f141,f136'
MEMBER_FIELDS = 'f12,f13,f14,f2,f3,f6'
BOARD_FAMILIES = {'concept': 'm:90+t:3+f:!50', 'industry': 'm:90+t:2+f:!50'}
BOARD_CODE = re.compile(r'^BK\d{4}$')


def _clist_url(fs, page, fields, sort='f12'):
    return ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=' + str(page) + f'&pz={CLIST_PAGE}&po=0&np=1&fltt=2&invt=2&fid={sort}'
            + '&fs=' + quote(fs, safe='') + '&fields=' + quote(fields, safe=''))


def _clist_page(response, source_id):
    try:
        value = json.loads(response.body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise PublicEvidenceError('DATA_SCHEMA', source_id + ' 响应不是 JSON。') from None
    if not isinstance(value, dict) or value.get('rc') != 0:
        raise PublicEvidenceError('PROVIDER_ERROR', source_id + ' 返回错误码。')
    data = value.get('data')
    if data is None:
        return 0, []
    total, diff = data.get('total'), data.get('diff')
    if type(total) is not int or total < 0 or not isinstance(diff, list):
        raise PublicEvidenceError('DATA_SCHEMA', source_id + ' 列表结构无效。')
    return total, diff


def _pages(total):
    return max(1, -(-total // CLIST_PAGE))


def _fs_of(url):
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(url).query).get('fs', [''])[0]


def _page_of(url):
    from urllib.parse import parse_qs, urlparse
    return int(parse_qs(urlparse(url).query).get('pn', ['0'])[0])


def _nullable_number(value, key):
    return None if value in ('-', None, '') else _number(value, key)


def _member_symbol(code, market):
    if not isinstance(code, str) or not CODE.fullmatch(code) or market not in (0, 1):
        raise PublicEvidenceError('DATA_SCHEMA', f'成分证券代码无效：{code}/{market}')
    return em_symbol(code, market)


class EastmoneyBoardListSource(Source):
    parser_version = 'em-board-list-v1'
    snapshot_only = True

    def __init__(self, family):
        self.family = family
        self.fs = BOARD_FAMILIES[family]
        self.source_id = f'em_{family}_boards'
        self.description = f'东方财富{"概念" if family == "concept" else "行业"}板块列表与收盘快照（涨跌幅、成交额、涨跌家数、领涨股）'
        self.limitations = SNAPSHOT_LIMITATIONS

    def requests(self, day):
        return [RequestSpec(_clist_url(self.fs, 1, BOARD_FIELDS))]

    def follow_up(self, day, responses):
        if len(responses) != 1:
            return []
        total, _ = _clist_page(responses[0], self.source_id)
        return [RequestSpec(_clist_url(self.fs, page, BOARD_FIELDS)) for page in range(2, _pages(total) + 1)]

    SCHEMA = {'board_code': pl.String, 'board_name': pl.String, 'index_price': pl.Float64, 'pct_change': pl.Float64,
              'volume': pl.Float64, 'amount': pl.Float64, 'turnover_rate': pl.Float64, 'up_count': pl.Int64,
              'down_count': pl.Int64, 'leader_name': pl.String, 'leader_symbol': pl.String, 'leader_pct_change': pl.Float64}

    def parse(self, day, responses):
        rows, totals = {}, set()
        for response in responses:
            total, diff = _clist_page(response, self.source_id)
            totals.add(total)
            for item in diff:
                if not isinstance(item, dict) or not BOARD_CODE.fullmatch(str(item.get('f12'))):
                    raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 板块代码无效。')
                code = item['f12']
                if code in rows:
                    raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 板块重复：' + code)
                leader = None
                if item.get('f140') not in (None, '', '-') and item.get('f141') in (0, 1):
                    leader = _member_symbol(item['f140'], item['f141'])
                up, down = item.get('f104'), item.get('f105')
                rows[code] = [code, str(item.get('f14') or ''), _nullable_number(item.get('f2'), 'f2'), _nullable_number(item.get('f3'), 'f3'),
                              _nullable_number(item.get('f5'), 'f5'), _nullable_number(item.get('f6'), 'f6'), _nullable_number(item.get('f8'), 'f8'),
                              up if type(up) is int else None, down if type(down) is int else None,
                              item.get('f128') if isinstance(item.get('f128'), str) else None, leader, _nullable_number(item.get('f136'), 'f136')]
        if len(totals) != 1 or len(rows) != totals.pop():
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 板块总数与分页结果不一致。')
        return ParsedTable([rows[k] for k in sorted(rows)], dict(self.SCHEMA), [])


class EastmoneyBoardMembersSource(Source):
    parser_version = 'em-board-members-v1'
    snapshot_only = True
    resumable = True
    max_requests = 3000

    def __init__(self, family, board_limit=None):
        self.family = family
        self.fs = BOARD_FAMILIES[family]
        self.board_limit = board_limit
        self.source_id = f'em_{family}_board_members'
        self.description = f'东方财富{"概念" if family == "concept" else "行业"}板块成分快照'
        self.limitations = SNAPSHOT_LIMITATIONS

    def requests(self, day):
        return [RequestSpec(_clist_url(self.fs, 1, 'f12,f14'))]

    def _boards(self, responses):
        lists = [r for r in responses if _fs_of(r.request.url) == self.fs]
        boards = []
        for response in lists:
            _total, diff = _clist_page(response, self.source_id)
            boards.extend((item['f12'], item.get('f14')) for item in diff)
        return lists, boards

    def follow_up(self, day, responses):
        lists, boards = self._boards(responses)
        total, _ = _clist_page(lists[0], self.source_id)
        pages = _pages(total)
        if len(lists) < pages:
            return [RequestSpec(_clist_url(self.fs, page, 'f12,f14')) for page in range(2, pages + 1)]
        if self.board_limit is not None:
            boards = sorted(boards)[:self.board_limit]
        members = [r for r in responses if _fs_of(r.request.url).startswith('b:')]
        if not members:
            return [RequestSpec(_clist_url(f'b:{code}+f:!50', 1, MEMBER_FIELDS)) for code, _name in sorted(boards)]
        if any(_page_of(r.request.url) > 1 for r in members):
            return []
        extra = []
        for response in members:
            total, _ = _clist_page(response, self.source_id)
            board = _fs_of(response.request.url)
            extra.extend(RequestSpec(_clist_url(board, page, MEMBER_FIELDS)) for page in range(2, _pages(total) + 1))
        return extra

    SCHEMA = {'board_code': pl.String, 'board_name': pl.String, 'symbol': pl.String, 'code': pl.String, 'name': pl.String,
              'price': pl.Float64, 'pct_change': pl.Float64, 'amount': pl.Float64}

    def parse(self, day, responses):
        lists, boards = self._boards(responses)
        names = dict(boards)
        if len(set(names)) != len(boards) or not lists:
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 板块列表重复或缺失。')
        total_boards, _ = _clist_page(lists[0], self.source_id)
        if len(boards) != total_boards:
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 板块列表未取全。')
        expected = set(sorted(names)[:self.board_limit] if self.board_limit is not None else names)
        per_board, totals = {}, {}
        for response in responses:
            fs = _fs_of(response.request.url)
            if not fs.startswith('b:'):
                continue
            board = fs[2:].split('+')[0]
            total, diff = _clist_page(response, self.source_id)
            totals.setdefault(board, set()).add(total)
            for item in diff:
                symbol = _member_symbol(item.get('f12'), item.get('f13'))
                per_board.setdefault(board, {})
                if symbol in per_board[board]:
                    raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} {board} 成分重复。')
                per_board[board][symbol] = [board, names.get(board), symbol, item['f12'], str(item.get('f14') or ''),
                                            _nullable_number(item.get('f2'), 'f2'), _nullable_number(item.get('f3'), 'f3'),
                                            _nullable_number(item.get('f6'), 'f6')]
        if set(totals) != expected:
            raise PublicEvidenceError('DATA_SCHEMA', self.source_id + ' 成分请求与板块列表不一致。')
        rows = []
        for board in sorted(expected):
            if len(totals[board]) != 1 or len(per_board.get(board, {})) != next(iter(totals[board])):
                raise PublicEvidenceError('DATA_SCHEMA', f'{self.source_id} {board} 成分数量与总数不一致。')
            rows.extend(per_board.get(board, {})[s] for s in sorted(per_board.get(board, {})))
        warnings = [f'BOARD_LIMIT:{self.board_limit}'] if self.board_limit is not None else []
        return ParsedTable(rows, dict(self.SCHEMA), warnings)


class EastmoneyPopularitySource(Source):
    source_id = 'em_popularity_rank'
    parser_version = 'em-popularity-v1'
    description = '东方财富个股人气榜前 100 名快照'
    snapshot_only = True
    limitations = SNAPSHOT_LIMITATIONS + ('人气榜为供应商基于访问与关注的排名，只提供前 100 名。',)
    BODY = json.dumps({'appId': 'appId01', 'globalId': '786e4c21-70dc-435a-93bb-38', 'marketType': '', 'pageNo': 1, 'pageSize': 100}).encode()

    def requests(self, day):
        return [RequestSpec('https://emappdata.eastmoney.com/stockrank/getAllCurrentList', method='POST', body=self.BODY,
                            headers=(('Content-Type', 'application/json'),))]

    SCHEMA = {'rank': pl.Int64, 'symbol': pl.String, 'code': pl.String, 'rank_change': pl.Int64, 'em_his_rank_change': pl.Int64}

    def parse(self, day, responses):
        try:
            value = json.loads(responses[0].body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise PublicEvidenceError('DATA_SCHEMA', '人气榜响应不是 JSON。') from None
        if not isinstance(value, dict) or value.get('status') != 0 or not isinstance(value.get('data'), list):
            raise PublicEvidenceError('PROVIDER_ERROR', '人气榜返回失败。')
        rows = []
        for item in value['data']:
            sc = item.get('sc') if isinstance(item, dict) else None
            match = re.fullmatch(r'(SH|SZ|BJ)(\d{6})', sc or '')
            if not match or type(item.get('rk')) is not int:
                raise PublicEvidenceError('DATA_SCHEMA', '人气榜条目无效。')
            rows.append([item['rk'], match.group(1).lower() + '.' + match.group(2), match.group(2),
                         item.get('rc') if type(item.get('rc')) is int else None,
                         item.get('hisRc') if type(item.get('hisRc')) is int else None])
        ranks = sorted(r[0] for r in rows)
        if ranks != list(range(1, len(rows) + 1)) or len({r[1] for r in rows}) != len(rows):
            raise PublicEvidenceError('DATA_SCHEMA', '人气榜排名不连续或证券重复。')
        rows.sort(key=lambda r: r[0])
        return ParsedTable(rows, dict(self.SCHEMA), [])


def snapshot_sources():
    return [EastmoneyBoardListSource('concept'), EastmoneyBoardListSource('industry'),
            EastmoneyBoardMembersSource('concept'), EastmoneyBoardMembersSource('industry'), EastmoneyPopularitySource()]


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
    return pool_sources() + billboard_sources() + snapshot_sources()


__all__ = ['POOL_UT', 'EastmoneyPoolSource', 'EastmoneyDatacenterSource', 'EastmoneyBoardListSource', 'EastmoneyBoardMembersSource',
           'EastmoneyPopularitySource', 'billboard_sources', 'default_sources', 'em_symbol', 'pool_sources', 'secucode_symbol',
           'snapshot_sources']
