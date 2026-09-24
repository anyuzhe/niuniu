"""User-facing workbenches: each page answers one everyday question in plain language.

The research, governance and development tools stay available under 专业模式.
"""
from quantlab.trading.decision_store import DecisionStore
from .widgets import Card, button, kpis, label, row, table
from .market_pages import market_page, themes_page  # noqa: F401  (re-exported)
from .stock_pages import stock_page, mine_page  # noqa: F401  (re-exported)
from .market_pages import candidates_page  # noqa: F401  (re-exported)


def _coming(window, box, what, today):
    card = Card('即将上线')
    card.add(label(what, '', True))
    if today:
        card.add(label('现在可以先用：' + today, 'muted', True))
    box.addWidget(card)


def _pp(value):
    return '—' if value is None else f'{value * 100:+.1f}%'


def _rate(stats):
    return '—' if stats['hit_rate'] is None else f"{stats['hit_rate'] * 100:.0f}%"


def review_page(window):
    from PyQt6 import sip
    from quantlab.trading.judgments import (SOURCES, STANCES, VERDICTS, delete_judgment, judgments_prompt,
                                            review_judgments)
    box = window.page('复盘验证', '我过去的判断到底有没有用：在个股报告里保存的判断，按之后的真实走势自动核对。')
    holder = Card()
    box.addWidget(holder)
    status = label('正在核对…', 'muted', True)
    holder.add(status)

    def done(result, error):
        if holder is None or sip.isdeleted(holder):
            return
        if error:
            status.setText('核对失败：' + error.split(': ', 1)[-1])
            return
        rows, stats = result['rows'], result['stats']
        if not rows:
            status.setText('还没有保存过判断。打开“个股报告”，在“保存判断”里选看多/观望/看空和核对周期，'
                           '之后每天会按真实走势自动核对，这里统计准确率。')
            return
        o = stats['overall']
        pending = stats['pending']
        status.setText(f"数据截至 {result['trading_day'] or '—'} 收盘 · 共 {stats['total']} 条判断，"
                       f"已完成 {o['finished']} 条（不含观望），进行中 {pending['running']}，等待数据 {pending['waiting']}。")
        head = row(kpis([
            ('准确率', _rate(o), f"正确 {o['right']} / 错误 {o['wrong']} / 持平 {o['flat']}"),
            ('平均顺向收益', _pp(o['avg_aligned']), '看空按涨跌取反'),
            ('平均顺向超额', _pp(o['avg_aligned_excess']), '减去同期全市场等权平均'),
        ]), button('问 AI 复盘', lambda: window.ask_ai(judgments_prompt(result)), True))
        head.layout().setStretch(0, 1)
        holder.add(head)
        for note in stats['notes']:
            holder.add(label(note, 'muted', True))
        group_rows = [[g['label'], g['finished'], _rate(g), _pp(g['avg_aligned']), _pp(g['avg_aligned_excess'])]
                      for key in ('source', 'stance', 'horizon') for g in stats['groups'][key]]
        grid = table(['分组', '已完成', '准确率', '平均顺向收益', '平均顺向超额'], group_rows)
        grid.setMinimumHeight(min(60 + 39 * len(group_rows), 360))
        holder.add(grid)
        state = {'running': '进行中', 'waiting': '等待数据', 'unavailable': '无法核对'}

        def outcome(r):
            result = r['result'] or {}
            if result.get('verdict'):
                return VERDICTS[result['verdict']]
            text = state.get(result.get('status'), '—')
            return f"{text} {result['sessions_done']}/{result['horizon']}" if result.get('status') == 'running' else text

        def remark(r):
            trigger = (r['result'] or {}).get('trigger')
            parts = [f"{trigger['date'][5:]} 触及{'失效价' if trigger['kind'] == 'stop' else '目标价'}"] if trigger else []
            return '；'.join(parts + ([r['reason']] if r['reason'] else [])) or '—'

        detail = table(['判断日', '股票', '判断', '来源', '周期', '结果', '涨跌', '全市场', '超额', '备注'],
                       [[r['made_on'], r['name'] or r['code'], STANCES[r['stance']], SOURCES[r['source']],
                         f"{r['horizon']} 日", outcome(r), _pp((r['result'] or {}).get('return')),
                         _pp((r['result'] or {}).get('market')), _pp((r['result'] or {}).get('excess')), remark(r)]
                        for r in rows],
                       lambda i: window.open_stock_report(rows[i]['code']))
        for i, r in enumerate(rows):
            for column in range(detail.columnCount()):
                detail.item(i, column).setToolTip(f"{r['code']}：{(r['result'] or {}).get('text', '')}")
        detail.setMinimumHeight(min(60 + 39 * len(rows), 560))
        holder.add(detail)

        def remove():
            selected = detail.currentRow()
            if 0 <= selected < len(rows):
                delete_judgment(window.output, rows[selected]['id'])
                window.navigate_page('review')

        holder.add(row(label('双击一行打开个股报告。收益从判断日收盘算起（前复权），失效价/目标价按实际收盘价核对。', 'muted', True),
                       button('删除选中', remove)))

    window.async_call(lambda: review_judgments(window.output, getattr(window, 'data_catalog_path', None)), done)
    legacy = DecisionStore(window.output).list(include_superseded=True, limit=1)['records']
    if legacy:
        box.addWidget(label('交易台的决策记录在专业模式的“决策复盘”里查看。', 'muted', True))


def assistant_page(window):
    box = window.page('AI 助手', '用自然语言问市场、问个股、让牛牛帮你做研究。')
    card = Card('开始对话')
    card.add(label('可以这样问：“今天市场怎么样”“帮我看看 sh.600000”“最近哪些方向在走强”。'
                   '回答会注明数据截至时间和来源。', '', True))
    card.add(button('打开 AI 助手', window.research_chat, True))
    box.addWidget(card)
