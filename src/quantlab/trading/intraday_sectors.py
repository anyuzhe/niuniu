"""盘中板块: product-side helpers over DATA's SectorIntradayProvider.

DATA owns the provider (quantlab.data.sector_intraday): sources, refresh limits,
cross-checks and price-limit status. This module only
- checks the DATA catalog before anything is called (sector_board_snapshot /
  sector_board_members must be READY);
- keeps the one shared provider instance per process, as the catalog asks;
- turns results into short plain-language summaries for the page and the assistant.
"""
from __future__ import annotations

import threading

from quantlab.data.dataset_catalog import DataCatalogError, get_data_catalog_entry

DATASETS = ('sector_board_snapshot', 'sector_board_members')
LIVE_STATUSES = {'OPENING_AUCTION', 'TRADING', 'CLOSING_AUCTION'}
MARKET_STATUS = {
    'PREOPEN': '盘前', 'OPENING_AUCTION': '集合竞价', 'TRADING': '交易中', 'MIDDAY_BREAK': '午间休市',
    'CLOSING_AUCTION': '收盘集合竞价', 'CLOSED': '已收盘', 'NON_TRADING_DAY': '非交易日',
}
MEMBER_STATUS = {
    'limit_up': '涨停', 'limit_down': '跌停', 'limit_break': '炸板', 'no_limit_new_listing': '新股无涨跌幅限制',
}
TYPE_NAMES = {'concept': '概念', 'industry': '行业'}

# Boards DATA classifies as market_label (margin trading, Stock Connect, vendor indices,
# listing status, earnings seasons...) are not themes; the page hides them by default,
# together with boards that have fewer than MIN_MEMBERS constituents.
LABEL_REASONS = {
    'trading_access': '交易资格', 'holder_label': '持股名单', 'index_selection': '精选指数',
    'status_label': '风险状态', 'listing_age': '次新股', 'earnings_label': '业绩标签',
}
MIN_MEMBERS = 10

_lock = threading.Lock()
_provider = None


def catalog_status(catalog_path=None) -> dict:
    """DATA status of the two interfaces, e.g. {'sector_board_snapshot': 'READY', ...}."""
    result = {}
    for dataset in DATASETS:
        try:
            result[dataset] = get_data_catalog_entry(catalog_path, dataset_id=dataset)['status']
        except DataCatalogError:
            result[dataset] = 'NOT_LISTED'
    return result


def is_ready(catalog_path=None) -> bool:
    return all(status == 'READY' for status in catalog_status(catalog_path).values())


def not_ready_text(catalog_path=None) -> str:
    status = catalog_status(catalog_path)
    detail = '、'.join(f'{k} 为 {v}' for k, v in status.items())
    return f'数据侧尚未开放盘中板块接口（{detail}）。数据侧盘中实测通过、在数据清单里改为 READY 后，这里自动可用。'


def shared_provider(data_root=None, factory=None):
    """One provider per process: its caches enforce DATA's refresh limits across pages and tools."""
    global _provider
    with _lock:
        if _provider is None:
            if factory is None:
                from quantlab.data.sector_intraday import SectorIntradayProvider
                factory = lambda: SectorIntradayProvider(data_root=data_root)
            _provider = factory()
        return _provider


def reset_shared_provider():
    global _provider
    with _lock:
        _provider = None


def error_text(error) -> str:
    text = str(error)
    if 'FUYAO_NOT_CONFIGURED' in text:
        return '没有配置扶摇密钥（HITHINK_FINANCE_API_KEY），请用启动脚本打开牛牛。'
    if isinstance(error, str):
        return '盘中板块数据暂时取不到：' + error.split(': ', 1)[-1][:160]
    if 'InvalidRequest' in type(error).__name__:
        return '板块代码无效。'
    return '盘中板块数据暂时取不到：' + text[:160]


def freshness(value: dict) -> str:
    parts = [MARKET_STATUS.get(value.get('market_status'), value.get('market_status') or '')]
    if value.get('as_of'):
        parts.append('数据时间 ' + value['as_of'][11:19])
    age = value.get('age_seconds')
    if age is not None:
        parts.append(f'{age:.0f} 秒前' if age < 600 else '较早的数据')
    if value.get('stale'):
        parts.append('刷新失败，显示上一次结果')
    if value.get('completeness') and value['completeness'] != 'FULL':
        missing = len(value.get('missing') or [])
        parts.append(f'部分缺失（{missing} 项）' if missing else '部分股票暂不显示')
    return ' · '.join(p for p in parts if p)


def is_market_label(board: dict) -> bool:
    """DATA's classification (board_class); CODE keeps no name list of its own."""
    return board.get('board_class') == 'market_label'


def _hidden(board: dict) -> str | None:
    if is_market_label(board):
        return 'label'
    count = board.get('constituent_count')  # None means unknown, never zero
    if count is not None and count < MIN_MEMBERS:
        return 'small'
    return None


def pick_boards(snapshot: dict, kind='all', order='up', limit=60, filtered=True) -> list[dict]:
    boards = [b for b in snapshot.get('boards', []) if (kind == 'all' or b['type'] == kind)
              and not (filtered and _hidden(b))]
    if order == 'amount':
        boards = sorted(boards, key=lambda b: -(b.get('amount') or 0))
    elif order == 'down':
        boards = sorted(boards, key=lambda b: (b.get('change_pct') is None, b.get('change_pct') or 0))
    return boards[:limit]


def filter_note(snapshot: dict) -> str:
    boards = snapshot.get('boards', [])
    labels = [b for b in boards if _hidden(b) == 'label']
    small = sum(_hidden(b) == 'small' for b in boards)
    if not any('board_class' in b for b in boards):
        text = '数据侧的板块榜没有提供板块分类，全市场标签暂不能隐藏'
    else:
        reasons = sorted({LABEL_REASONS.get(b.get('label_reason'), '其他') for b in labels})
        text = (f"已隐藏 {len(labels)} 个全市场标签（{'、'.join(reasons)}，如"
                f"{'、'.join(b['name'] for b in labels[:4])}）" if labels else '没有需要隐藏的全市场标签')
    if any(b.get('constituent_count') is not None for b in boards):
        day = snapshot.get('constituent_counts_date')
        text += f"，以及 {small} 个成分股少于 {MIN_MEMBERS} 只的板块" + (f"（成分按 {day} 统计）" if day else '')
    else:
        text += f"；成分股数量暂缺，少于 {MIN_MEMBERS} 只的板块暂不能隐藏"
    return text + '。分类和成分数由数据侧提供；取消勾选可显示全部。'


def member_state(row: dict) -> str:
    if row.get('status') == 'no_trade_today':
        return '停牌/未成交'
    if row.get('status') == 'withheld_source_mismatch':
        return '来源不一致'
    return MEMBER_STATUS.get(row.get('limit_status'), '')


def _pct(value):
    return '—' if value is None else f'{value:+.2f}%'


def boards_summary(snapshot: dict, top=10) -> dict:
    up = pick_boards(snapshot, 'all', 'up', top)
    down = pick_boards(snapshot, 'all', 'down', 5)  # market-wide tags and tiny boards are left out
    return {'as_of': snapshot.get('as_of'), 'market_status': MARKET_STATUS.get(snapshot.get('market_status')),
            'stale': bool(snapshot.get('stale')), 'completeness': snapshot.get('completeness'),
            'strongest': [{'code': b['code'], 'name': b['name'], 'type': TYPE_NAMES[b['type']],
                           'change_pct': b['change_pct'], 'amount_yi': round((b['amount'] or 0) / 1e8, 1)} for b in up],
            'weakest': [{'code': b['code'], 'name': b['name'], 'type': TYPE_NAMES[b['type']],
                         'change_pct': b['change_pct']} for b in down]}


def members_summary(members: dict, top=15) -> dict:
    rows = members.get('members', [])
    quoted = [r for r in rows if r.get('change_pct') is not None]
    up = sum(r['change_pct'] > 0 for r in quoted)
    return {'as_of': members.get('as_of'), 'counts': members.get('counts'), 'stale': bool(members.get('stale')),
            'rising': up, 'falling': sum(r['change_pct'] < 0 for r in quoted), 'quoted': len(quoted),
            'leaders': [{'symbol': r['symbol'], 'name': r['name'], 'change_pct': r['change_pct'],
                         'amount_yi': round((r['amount'] or 0) / 1e8, 2), 'state': member_state(r)}
                        for r in quoted[:top]],
            'note': '成分为当前成分，不代表历史。'}


def sector_prompt(snapshot: dict, board: dict | None = None, members: dict | None = None) -> str:
    s = boards_summary(snapshot)
    lines = [f"请帮我解读现在的盘中板块（{s['market_status']}，数据时间 {(s['as_of'] or '')[11:19]}，来源扶摇/同花顺板块指数）。",
             '涨幅前列：' + '、'.join(f"{b['name']}{_pct(b['change_pct'])}" for b in s['strongest']),
             '跌幅前列：' + '、'.join(f"{b['name']}{_pct(b['change_pct'])}" for b in s['weakest'])]
    if board and members:
        m = members_summary(members)
        c = m['counts'] or {}
        lines.append(f"我正在看“{board['name']}”（{_pct(board.get('change_pct'))}）：{m['quoted']} 只有行情，上涨 {m['rising']}、下跌 {m['falling']}，"
                     f"涨停 {c.get('limit_up', 0)}、炸板 {c.get('limit_break', 0)}、跌停 {c.get('limit_down', 0)}。领涨："
                     + '、'.join(f"{r['name']}{_pct(r['change_pct'])}" for r in m['leaders'][:8]))
    lines.append('请说明哪些方向在走强、是否有持续性的迹象、需要观察什么；这是盘中行情，不要给出确定的买卖指令。')
    return '\n'.join(lines)


__all__ = ['is_market_label', 'filter_note', 'LABEL_REASONS', 'MIN_MEMBERS', 'catalog_status', 'is_ready', 'not_ready_text', 'shared_provider', 'reset_shared_provider', 'error_text',
           'freshness', 'pick_boards', 'member_state', 'boards_summary', 'members_summary', 'sector_prompt',
           'LIVE_STATUSES', 'MARKET_STATUS', 'TYPE_NAMES']
