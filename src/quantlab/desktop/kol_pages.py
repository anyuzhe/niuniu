"""大V复盘 page: saved review posts, their extracted views, and each author's track record."""
from datetime import datetime, timedelta, timezone

from PyQt6 import sip
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QComboBox, QDateEdit, QLineEdit, QPlainTextEdit

from quantlab.trading.judgments import HORIZONS, STANCES, review_judgments
from quantlab.trading.kol import (KINDS, PLATFORMS, add_post, confirm_views, delete_post, digest_prompt,
                                  extract_views, get_post, list_posts, set_views)
from quantlab.trading.market_overview import latest_overview
from .widgets import Card, button, label, row, table


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def _pp(value):
    return '—' if value is None else f'{value * 100:+.1f}%'


def _combo(items, name):
    box = QComboBox()
    for key, text in items:
        box.addItem(text, key)
    box.setAccessibleName(name)
    return box


def _import_card(window):
    card = Card('添加复盘文章')
    card.add(label('把雪球、淘股吧、公众号等复盘文章的正文粘贴进来（自动订阅和抓取属于数据侧，这里不联网抓取）。', 'muted', True))
    author = QLineEdit()
    author.setPlaceholderText('作者')
    author.setAccessibleName('作者')
    platform = _combo([(p, p) for p in PLATFORMS], '平台')
    day = QDateEdit(QDate.fromString(datetime.now(timezone(timedelta(hours=8))).date().isoformat(), 'yyyy-MM-dd'))
    day.setDisplayFormat('yyyy-MM-dd')
    day.setCalendarPopup(True)
    day.setAccessibleName('发布日期')
    title = QLineEdit()
    title.setPlaceholderText('标题（可不填）')
    title.setAccessibleName('标题')
    url = QLineEdit()
    url.setPlaceholderText('原文链接（可不填）')
    url.setAccessibleName('原文链接')
    text = QPlainTextEdit()
    text.setPlaceholderText('粘贴正文')
    text.setAccessibleName('文章正文')
    text.setMinimumHeight(120)
    status = label('', 'muted', True)

    def save():
        try:
            post = add_post(window.output, author=author.text(), platform=platform.currentData(),
                            published_on=day.date().toString('yyyy-MM-dd'), title=title.text(), url=url.text(),
                            text=text.toPlainText())
        except (ValueError, OSError) as exc:
            status.setText('没有保存：' + str(exc))
            return
        window.kol_selected = post['id']
        window.navigate_page('kol')

    card.add(row(author, platform, day, title, url))
    card.add(text)
    card.add(row(status, button('保存文章', save, True)))
    card.import_controls = {'author': author, 'platform': platform, 'day': day, 'title': title, 'url': url,
                            'text': text, 'status': status, 'save': save}
    return card


def _detail_card(window, post):
    card = Card(f"{post['author']} · {post['published_on']} · {post['title']}")
    status = label('', 'muted', True)
    body = QPlainTextEdit(post['text'])
    body.setReadOnly(True)
    body.setAccessibleName('文章正文')
    body.setMaximumHeight(180)
    card.add(body)
    if post.get('url'):
        card.add(label('原文：' + post['url'], 'muted', True))
    if post.get('summary'):
        card.add(label('AI 概括：' + post['summary'], '', True))
    views = list(post['views'])
    if post.get('extracted_by'):
        by = post['extracted_by']
        card.add(label(f"观点由 {by.get('model') or by.get('provider')} 提取"
                       + (f"，{by['dropped']} 条格式不对已丢弃" if by.get('dropped') else '')
                       + '；请核对后再保存。原话找不到的标为“未在原文找到”。', 'muted', True))
    grid = table(['类型', '对象', '方向', '周期', '原话'],
                 [[KINDS[v['kind']], v['target'], STANCES[v['stance']], f"{v['horizon']} 日",
                   (v['quote'] or '—') + ('' if v['quote_found'] else '（未在原文找到）')] for v in views])
    grid.setMinimumHeight(min(60 + 39 * max(len(views), 1), 420))
    card.add(grid if views else label('还没有观点。点“AI 提炼观点”，或在下面手动添加。', 'muted', True))

    def extract():
        status.setText('正在请求模型提炼观点（通常 20–90 秒）…')

        def done(result, error):
            if not _alive(status):
                return
            if error:
                status.setText('提炼失败：' + error.split(': ', 1)[-1])
                return
            window.navigate_page('kol')

        window.async_call(lambda: extract_views(window.output, post['id']), done)

    def remove_view():
        selected = grid.currentRow() if views else -1
        if 0 <= selected < len(views):
            set_views(window.output, post['id'], views[:selected] + views[selected + 1:])
            window.navigate_page('kol')

    kind = _combo(list(KINDS.items()), '观点类型')
    target = QLineEdit()
    target.setPlaceholderText('对象：股票名称/代码，或方向名称')
    target.setAccessibleName('观点对象')
    stance = _combo(list(STANCES.items()), '观点方向')
    horizon = _combo([(h, f'{h} 个交易日') for h in HORIZONS], '观点周期')
    quote = QLineEdit()
    quote.setPlaceholderText('原话（可不填）')
    quote.setAccessibleName('原话')

    def add_view():
        try:
            set_views(window.output, post['id'], views + [{
                'kind': kind.currentData(), 'target': target.text() or ('大盘' if kind.currentData() == 'market' else ''),
                'stance': stance.currentData(), 'horizon': horizon.currentData(), 'quote': quote.text()}])
        except ValueError as exc:
            status.setText('没有添加：' + str(exc))
            return
        window.navigate_page('kol')

    def confirm():
        try:
            result = confirm_views(window.output, post['id'], getattr(window, 'data_catalog_path', None))
        except (ValueError, OSError) as exc:
            status.setText('没有保存：' + str(exc))
            return
        text = f"已保存 {result['saved']} 条待核对观点，结果在下方“作者表现”和“复盘验证”里。"
        if result['skipped']:
            text += ' 未保存：' + '；'.join(result['skipped'])
        status.setText(text)

    def remove_post():
        delete_post(window.output, post['id'])
        window.kol_selected = None
        window.navigate_page('kol')

    card.add(row(kind, target, stance, horizon, quote, button('添加观点', add_view)))
    card.add(row(button('AI 提炼观点', extract, True), button('删除选中观点', remove_view),
                 button('保存为待核对', confirm, True), button('删除文章', remove_post)))
    card.add(status)
    card.detail_controls = {'grid': grid, 'status': status, 'extract': extract, 'confirm': confirm,
                            'add_view': add_view, 'kind': kind, 'target': target, 'stance': stance,
                            'horizon': horizon, 'quote': quote, 'remove_view': remove_view}
    return card


def _authors_card(window):
    card = Card('作者表现（按之后的真实走势核对）')
    status = label('正在核对…', 'muted', True)
    card.add(status)

    def done(result, error):
        if not _alive(status):
            return
        if error:
            status.setText('核对失败：' + error.split(': ', 1)[-1])
            return
        groups = result['stats']['groups'].get('author', [])
        kol = [r for r in result['rows'] if r['source'] == 'kol']
        if not groups:
            status.setText('还没有保存大V观点。提炼后点“保存为待核对”，之后这里按作者统计准确率。')
            return
        status.setText(f"数据截至 {result['trading_day'] or '—'} 收盘 · 大V观点 {len(kol)} 条。"
                       '大盘观点按全市场等权平均涨跌核对；个股观点从发布日收盘算起。样本少于10条时准确率参考意义有限。')
        grid = table(['作者', '已完成', '准确率', '平均顺向收益', '平均顺向超额'],
                     [[g['label'], g['finished'], '—' if g['hit_rate'] is None else f"{g['hit_rate'] * 100:.0f}%",
                       _pp(g['avg_aligned']), _pp(g['avg_aligned_excess'])] for g in groups])
        grid.setMinimumHeight(min(60 + 39 * len(groups), 360))
        card.add(grid)

    window.async_call(lambda: review_judgments(window.output, getattr(window, 'data_catalog_path', None)), done)
    return card


def kol_page(window):
    box = window.page('大V复盘', '保存看过的大V复盘，提炼出能核对的观点，之后按真实走势统计每位作者说得准不准。')
    posts = list_posts(window.output)
    head = row(label(f'已保存 {len(posts)} 篇文章。观点来自原作者，不代表牛牛的结论。', 'muted', True),
               button('问 AI 汇总最新观点', lambda: window.ask_ai(digest_prompt(posts, latest_overview(window.output))), True))
    head.layout().setStretch(0, 1)
    box.addWidget(head)
    box.addWidget(_import_card(window))
    if posts:
        card = Card('文章')
        grid = table(['发布日期', '作者', '平台', '标题', '状态'],
                     [[p['published_on'], p['author'], p['platform'], p['title'], p['status']] for p in posts],
                     lambda i: (setattr(window, 'kol_selected', posts[i]['id']), window.navigate_page('kol')))
        grid.setMinimumHeight(min(60 + 39 * len(posts), 400))
        card.add(grid)
        card.add(label('双击一篇文章查看正文和观点。', 'muted'))
        box.addWidget(card)
        selected = getattr(window, 'kol_selected', None)
        try:
            post = get_post(window.output, selected) if selected else None
        except ValueError:
            post = None
        box.addWidget(_detail_card(window, post or posts[0]))
    box.addWidget(_authors_card(window))


__all__ = ['kol_page']
