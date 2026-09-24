"""数据中心: a plain-language view of DATA's catalog, plus the slots for DATA's services.

Everything shown comes from docs/reference/data-catalog.md (DATA-owned). The coverage
end date is read from the catalog's own coverage text and labelled as such; real
update status, previews and update jobs come from DATA services once the catalog
lists them as READY (data_status_service, data_preview_service, data_update_jobs).
CODE never scans the data root to find out.
"""
from __future__ import annotations

import re

from quantlab.data.dataset_catalog import (DataCatalogError, _path, get_data_catalog_entry,
                                           read_data_catalog)

STATUS_NAMES = {'READY': '可用', 'REVIEW_REQUIRED': '待审查', 'NOT_READY': '未就绪', 'DEPRECATED': '已停用'}
DELIVERY_NAMES = {'FILE': '文件', 'DATABASE': '数据库', 'API': '查询接口', 'STREAM': '推送', 'LEGACY': '旧格式'}
SERVICES = {
    'data_status_service': '更新状态',
    'data_preview_service': '预览与试查询',
    'data_update_jobs': '更新与归档',
}
SERVICE_PURPOSE = {
    'data_status_service': '每个数据集最近一次更新、最新日期、行数和健康状况，今天该更新的有没有更新',
    'data_preview_service': '文件和数据库数据看前几行，查询接口在页面上填参数试查一次',
    'data_update_jobs': '在页面上发起收盘后更新、盘中板块记录器、补某天数据和归档，先看计划再执行',
}
FULL_DATE = r'(\d{4}-\d{2}-\d{2})'


def _plain(text: str) -> str:
    return re.sub(r'[`*]', '', text or '').strip()


def coverage_end(text: str) -> tuple[str | None, str]:
    """(date, kind) read from the catalog's coverage text: kind is 'until', 'observed' or ''.

    Handles “2026-09-01 至 09-22”, “1990-12-19 至 **2026-09-23**”, “2026-09-23 观察”,
    “观察日 2026-09-23”. Anything else gives (None, '').
    """
    plain = _plain(text)
    match = re.search(r'(?:至|截止)\s*(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})', plain)
    if match:
        value = match.group(1)
        if len(value) == 5:
            year = re.search(r'(\d{4})-\d{2}-\d{2}', plain[:match.start()])
            if not year:
                return None, ''
            value = f'{year.group(1)}-{value}'
        return value, 'until'
    match = (re.search(FULL_DATE + r'\s*观察', plain) or re.search(r'观察日\s*' + FULL_DATE, plain)
             or re.match(FULL_DATE + r'\s*[，,；;]', plain))
    if match:
        return match.group(1), 'observed'
    match = re.search(FULL_DATE + r'\s*起', plain)
    if match:
        return match.group(1), 'since'
    return None, ''


def review_line(catalog_path=None) -> str:
    """The catalog's “最近一次 DATA 审查” sentence, shortened."""
    try:
        text = _path(catalog_path).read_text(encoding='utf-8')
    except (OSError, DataCatalogError):
        return ''
    match = re.search(r'最近一次 DATA 审查：([^（\n]*)', text)
    return match.group(1).strip() if match else ''


def catalog_rows(catalog_path=None) -> dict:
    catalog = read_data_catalog(catalog_path)
    rows = []
    for entry in catalog['entries']:
        end, kind = coverage_end(entry['coverage_usage'])
        rows.append({
            'dataset_id': entry['dataset_id'], 'delivery': entry['delivery'], 'status': entry['status'],
            'content': _plain(entry['content']), 'address': _plain(entry['address']),
            'format': _plain(entry['format_granularity']), 'coverage': _plain(entry['coverage_usage']),
            'code_use': _plain(entry['code_use']), 'end': end, 'end_kind': kind,
        })
    return {'rows': rows, 'counts': catalog['counts'], 'review': review_line(catalog_path)}


def filter_rows(rows, *, status='ALL', delivery='ALL', text=''):
    text = (text or '').strip().lower()
    result = []
    for row in rows:
        if status != 'ALL' and row['status'] != status:
            continue
        if delivery != 'ALL' and row['delivery'] != delivery:
            continue
        if text and not any(text in str(row[k]).lower() for k in ('dataset_id', 'content', 'coverage', 'code_use')):
            continue
        result.append(row)
    order = {'READY': 0, 'REVIEW_REQUIRED': 1, 'NOT_READY': 2, 'DEPRECATED': 3}
    return sorted(result, key=lambda r: (order.get(r['status'], 9), r['delivery'] != 'FILE', r['dataset_id']))


def end_text(row) -> str:
    if not row['end']:
        return '—'
    return {'until': f"至 {row['end']}", 'observed': f"{row['end']} 观察", 'since': f"{row['end']} 起"}[row['end_kind']]


def service_status(catalog_path=None) -> dict:
    """READY / REVIEW_REQUIRED / ... / NOT_LISTED for each DATA service the page can use."""
    result = {}
    for dataset_id in SERVICES:
        try:
            result[dataset_id] = get_data_catalog_entry(catalog_path, dataset_id=dataset_id)['status']
        except DataCatalogError:
            result[dataset_id] = 'NOT_LISTED'
    return result


__all__ = ['STATUS_NAMES', 'DELIVERY_NAMES', 'SERVICES', 'SERVICE_PURPOSE', 'coverage_end', 'review_line', 'catalog_rows',
           'filter_rows', 'end_text', 'service_status']
