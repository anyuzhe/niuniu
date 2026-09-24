"""数据中心 page: every dataset DATA lists, and the DATA services for status, preview and updates."""
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QComboBox, QLineEdit

from quantlab.workbench.data_center import (DELIVERY_NAMES, SERVICE_PURPOSE, SERVICES, STATUS_NAMES, catalog_rows, end_text,
                                            filter_rows, service_status)
from .widgets import Card, button, kpis, label, row, table

STATUS_COLORS = {'READY': QColor('#22d787'), 'REVIEW_REQUIRED': QColor('#f6b72f'),
                 'NOT_READY': QColor('#8fa4b7'), 'DEPRECATED': QColor('#f35f62')}


def data_center_page(window):
    box = window.page('数据中心', '牛牛能用哪些数据：数据侧交付的文件、数据库和查询接口，各自覆盖到哪天、能不能用、怎么用。')
    catalog = getattr(window, 'data_catalog_path', None)
    try:
        data = catalog_rows(catalog)
    except Exception as exc:  # unreadable catalog is a technical error, reported as such
        box.addWidget(label('读不了数据清单：' + str(exc)[:200], 'note', True))
        return
    counts = data['counts']
    box.addWidget(kpis([
        ('可用', str(counts.get('READY', 0)), '数据侧确认可以给牛牛用'),
        ('待审查', str(counts.get('REVIEW_REQUIRED', 0)), '接口已写好、数据侧还在核对'),
        ('未就绪', str(counts.get('NOT_READY', 0)), '规划中或只供数据侧内部'),
        ('已停用', str(counts.get('DEPRECATED', 0)), '不要再用'),
    ]))
    if data['review']:
        box.addWidget(label('数据清单最近一次审查：' + data['review'], 'muted', True))

    status = QComboBox()
    for key, text in (('ALL', '全部状态'), *STATUS_NAMES.items()):
        status.addItem(text, key)
    status.setAccessibleName('状态')
    delivery = QComboBox()
    for key, text in (('ALL', '全部类型'), *((k, v) for k, v in DELIVERY_NAMES.items() if k != 'LEGACY')):
        delivery.addItem(text, key)
    delivery.setAccessibleName('类型')
    search = QLineEdit()
    search.setPlaceholderText('搜索数据名称、内容或说明，例如 日K、涨停、研报')
    search.setAccessibleName('搜索数据')
    box.addWidget(row(search, status, delivery))

    listing = Card('数据目录（单击看详情）')
    shown = label('', 'muted')
    listing.add(shown)
    grid = table(['数据', '类型', '内容', '覆盖', '状态'], [])
    grid.setMinimumHeight(460)
    listing.add(grid)
    listing.add(label('“覆盖”是从数据清单的文字里读出的截止/观察日期，实际更新情况以数据侧的更新状态为准。', 'muted', True))
    detail = Card('详情')
    detail_text = label('在上面选一项数据。', 'muted', True)
    detail.add(detail_text)
    box.addWidget(listing)
    box.addWidget(detail)
    state = {'rows': []}

    def show():
        rows = filter_rows(data['rows'], status=status.currentData(), delivery=delivery.currentData(),
                           text=search.text())
        state['rows'] = rows
        grid.setRowCount(0)
        from PyQt6.QtWidgets import QTableWidgetItem
        grid.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [r['dataset_id'], DELIVERY_NAMES.get(r['delivery'], r['delivery']), r['content'], end_text(r),
                      STATUS_NAMES.get(r['status'], r['status'])]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(r['coverage'] if j == 3 else value)
                if j == 4:
                    item.setForeground(STATUS_COLORS.get(r['status'], QColor('#edf4fb')))
                grid.setItem(i, j, item)
        shown.setText(f'显示 {len(rows)} 项，共 {len(data["rows"])} 项。')

    def select(r, _c=None):
        if not 0 <= r < len(state['rows']):
            return
        d = state['rows'][r]
        detail_text.setObjectName('')
        detail_text.setStyleSheet('')
        detail_text.setText('\n'.join([
            f"{d['dataset_id']} · {DELIVERY_NAMES.get(d['delivery'], d['delivery'])} · {STATUS_NAMES.get(d['status'], d['status'])}",
            f"内容：{d['content']}",
            f"位置 / 接口：{d['address']}",
            f"格式 / 粒度：{d['format']}",
            f"覆盖 / 用途：{d['coverage']}",
            f"牛牛怎么用：{d['code_use']}",
        ]))

    grid.cellClicked.connect(select)
    search.textChanged.connect(lambda _: show())
    status.currentIndexChanged.connect(lambda _: show())
    delivery.currentIndexChanged.connect(lambda _: show())
    show()

    services = service_status(catalog)
    card = Card('更新状态 · 预览 · 更新与归档')
    for dataset_id, name in SERVICES.items():
        value = services[dataset_id]
        if value == 'READY':
            text = f'{name}：数据侧接口已开放，页面接入中。'
        elif value == 'NOT_LISTED':
            text = f'{name}：数据侧尚未提供接口（需求已提）。用途：{SERVICE_PURPOSE[dataset_id]}。'
        else:
            text = f'{name}：数据侧接口状态为 {STATUS_NAMES.get(value, value)}，开放后可用。'
        card.add(label(text, '', True))
    card.add(label('数据的采集、校验、写入和归档都由数据侧负责；这里只调用数据侧公开的接口，执行更新前会先显示计划并请你确认。',
                   'muted', True))
    box.addWidget(card)
    box.addWidget(row(label('研究实验用过的行情和股票池版本，在专业模式“研究实验室”的旧数据中心里查看。', 'muted', True),
                      button('打开旧数据中心', lambda: window.navigate(1))))


__all__ = ['data_center_page']
