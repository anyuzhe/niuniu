"""User-facing workbenches: each page answers one everyday question in plain language.

The research, governance and development tools stay available under 专业模式.
"""
from quantlab.trading.decision_store import DecisionStore
from .widgets import Card, button, label, row, table
from .market_pages import market_page, themes_page  # noqa: F401  (re-exported)
from .stock_pages import stock_page, mine_page  # noqa: F401  (re-exported)


def _coming(window, box, what, today):
    card = Card('即将上线')
    card.add(label(what, '', True))
    if today:
        card.add(label('现在可以先用：' + today, 'muted', True))
    box.addWidget(card)


def candidates_page(window):
    box = window.page('今日候选', '哪些股票值得重点研究，以及为什么；每条规则都标出历史验证结果。')
    _coming(window, box,
            '按已有扫描规则自动给出候选清单，每只股票写明入选理由；规则在全市场历史上验证过的，会直接显示验证结果。',
            '')


def review_page(window):
    box = window.page('复盘验证', '我过去的判断到底有没有用：按日期查看当时的判断和后来的结果。')
    records = DecisionStore(window.output).list(include_superseded=True, limit=200)['records']
    if not records:
        box.addWidget(label('还没有保存过判断。以后在个股报告里保存的结论会出现在这里，并自动核对后续走势。', 'note', True))
        return
    rows = [[d['trading_day'], d['symbol'], d['action'], d.get('ai_thesis', '')[:80], d.get('outcome', '')[:60] or '待核对']
            for d in records]
    box.addWidget(table(['日期', '股票', '当时判断', '理由', '后来结果'], rows,
                        lambda i: window.open_decision(records[i])), 1)


def assistant_page(window):
    box = window.page('AI 助手', '用自然语言问市场、问个股、让牛牛帮你做研究。')
    card = Card('开始对话')
    card.add(label('可以这样问：“今天市场怎么样”“帮我看看 sh.600000”“最近哪些方向在走强”。'
                   '回答会注明数据截至时间和来源。', '', True))
    card.add(button('打开 AI 助手', window.research_chat, True))
    box.addWidget(card)
