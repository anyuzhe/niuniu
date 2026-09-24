"""数据中心 sections over DATA's services: update status, preview / trial query, update and seal jobs.

All data, plans, runs and logs come from quantlab.data.data_services (DATA-owned). This
module only lays them out, and never runs a job without showing DATA's plan first.
"""
from datetime import datetime

from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLineEdit, QPlainTextEdit, QSpinBox,
                             QTableWidgetItem, QWidget)

from .widgets import Card, button, kpis, label, row, table

HEALTH = {'ok': '正常', 'lagging': '落后', 'error': '异常', 'unknown': '未知'}
HEALTH_COLORS = {'ok': QColor('#22d787'), 'lagging': QColor('#f6b72f'), 'error': QColor('#f35f62'),
                 'unknown': QColor('#8fa4b7')}
VERIFY = {'ok': '核对无误', 'mismatch': '有改动或缺失', 'never': '未核对'}
ACTION = {'fetch': '采集', 'skip_existing': '已有，跳过', 'seal': '封存', 'verify': '核对', 'start': '启动', 'stop': '停止'}
RUN_STATE = {'queued': '排队中', 'running': '运行中', 'succeeded': '完成', 'failed': '失败', 'cancelled': '已取消',
             'interrupted': '中断'}
TRIGGER = {'user': '手动', 'autostart': '打开牛牛时自动启动'}
LIVE = ('queued', 'running')


def _alive(widget):
    return widget is not None and not sip.isdeleted(widget)


def service(window, name):
    """One instance per window and data root (the preview service keeps DATA's rate limiter)."""
    cache = window.__dict__.setdefault('_data_services', {})
    key = (name, str(window.data_root))
    if key not in cache:
        from quantlab.data import data_services
        cache[key] = getattr(data_services, name)(window.data_root)
    return cache[key]


def call(window, work, done, status):
    """Run DATA calls off the UI thread; their errors stay in this section, not the window status bar."""
    def guarded():
        try:
            return {'value': work()}
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    def finished(result, error):
        if not _alive(status):
            return
        failure = error or (result or {}).get('error')
        if failure:
            status.setText(failure.split(': ', 1)[-1][:300])
            return
        done(result['value'])

    window.async_call(guarded, finished)


def _time(value):
    if not value:
        return '—'
    try:
        return datetime.fromisoformat(value).strftime('%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(value)[:16]


def _fill(grid, rows, colors=None):
    grid.setRowCount(len(rows))
    for i, values in enumerate(rows):
        for j, value in enumerate(values):
            item = QTableWidgetItem('—' if value is None else str(value))
            item.setToolTip(item.text())
            if colors and colors[i][1] is not None and colors[i][0] == j:
                item.setForeground(colors[i][1])
            grid.setItem(i, j, item)


# ------------------------------------------------------------------ A. update status

def status_section(window, box):
    status = label('正在读取更新状态…', 'muted', True)
    only_problems = QCheckBox('只看落后、异常和未知')
    box.addWidget(row(status, only_problems, button('刷新', lambda: load())))
    summary = QWidget()
    box.addWidget(summary)
    datasets = Card('各数据集')
    grid = table(['数据', '最新日期', '最近更新', '行数', '文件数', '状态', '说明', '已封存到'], [])
    grid.setMinimumHeight(460)
    datasets.add(grid)
    box.addWidget(datasets)
    seals = Card('最近的封存')
    seal_grid = table(['日期', '版本', '封存时间', '文件', '行数', '待封存', '核对', '问题'], [])
    seals.add(seal_grid)
    seals.add(label('封存后这一天的按日期数据只读不写；“核对”按封存清单重算校验码。日K、5 分钟、日状态、前复权按证券逐日追加，不在封存范围。',
                    'muted', True))
    box.addWidget(seals)
    state = {'value': None}

    def show():
        value = state['value']
        if value is None or not _alive(grid):
            return
        rows = [r for r in value['datasets']
                if not only_problems.isChecked() or r['health'] in ('lagging', 'error', 'unknown')]
        counts = {k: sum(r['health'] == k for r in value['datasets']) for k in HEALTH}
        status.setText(f"数据侧状态 {_time(value['as_of'])} · 状态索引 {_time(value.get('status_index_built_at'))} 生成"
                       + (f" · 交易日历到 {value['calendar_through']}" if value.get('calendar_through') else ''))
        old = summary.layout()
        if old is None:
            from PyQt6.QtWidgets import QVBoxLayout
            layout = QVBoxLayout(summary)
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        summary.layout().addWidget(kpis([(HEALTH[k], str(counts[k]), '') for k in HEALTH]))

        def note(r):
            parts = [r.get('health_reason') or '']
            if r.get('last_record_at'):
                parts.append(f"今天记录 {r.get('records_today', 0)} 次，失败 {r.get('failures_today', 0)} 次，"
                             f"最近 {_time(r['last_record_at'])}")
            return '；'.join(p for p in parts if p) or '—'

        _fill(grid, [[r['dataset_id'], r['latest_date'], _time(r['last_success_at']),
                      f"{r['rows']:,}" if r.get('rows') is not None else None,
                      f"{r['files']:,}" if r.get('files') is not None else None,
                      HEALTH.get(r['health'], r['health']), note(r), r.get('sealed_through')] for r in rows],
              [(5, HEALTH_COLORS.get(r['health'])) for r in rows])
        _fill(seal_grid, [[s['date'], s.get('revision'), _time(s.get('sealed_at')), s.get('files'),
                           f"{s['rows']:,}" if s.get('rows') is not None else None,
                           '、'.join(s.get('pending') or []) or '—', VERIFY.get(s['verify_status'], s['verify_status']),
                           s.get('problems')] for s in value.get('seals', [])],
              [(6, QColor('#f35f62') if s['verify_status'] == 'mismatch' else None) for s in value.get('seals', [])])

    def got(value):
        state['value'] = value
        show()

    def load():
        status.setText('正在读取更新状态…')
        call(window, lambda: service(window, 'DataStatusService').list_status(), got, status)

    only_problems.toggled.connect(lambda _: show())
    load()
    return state


# ------------------------------------------------------------------ B. preview / trial query

def preview_section(window, box, rows):
    """rows: catalog rows (for the dataset list)."""
    files = [r['dataset_id'] for r in rows if r['status'] == 'READY' and r['delivery'] == 'FILE']
    apis = [r['dataset_id'] for r in rows if r['status'] == 'READY' and r['delivery'] == 'API']
    chooser = QComboBox()
    chooser.setAccessibleName('选择数据')
    for dataset_id in files:
        chooser.addItem(f'文件 · {dataset_id}', ('file', dataset_id))
    for dataset_id in apis:
        chooser.addItem(f'接口 · {dataset_id}', ('api', dataset_id))
    status = label('选一项数据。文件数据看前几行；查询接口按参数试查一次（会真实联网，一次一查）。', 'muted', True)
    form_holder = QWidget()
    form = QFormLayout(form_holder)
    run_button = button('预览', lambda: go(), True)
    box.addWidget(row(chooser, run_button))
    box.addWidget(form_holder)
    box.addWidget(status)
    result = Card('结果')
    grid = table([], [])
    grid.setMinimumHeight(360)
    result.add(grid)
    box.addWidget(result)
    state = {'inputs': {}, 'kind': None, 'dataset': None}

    def clear_form():
        while form.rowCount():
            form.removeRow(0)
        state['inputs'] = {}

    def add_input(name, spec):
        if spec.get('enum'):
            widget = QComboBox()
            if not spec.get('required'):
                widget.addItem('（不填）', None)
            for value in spec['enum']:
                widget.addItem(str(value), value)
        else:
            widget = QLineEdit()
            example = spec.get('example')
            hint = spec.get('description') or ''
            widget.setPlaceholderText(' · '.join(str(p) for p in (hint, f'例：{example}' if example else '') if p))
        widget.setAccessibleName(name)
        form.addRow(f"{name}{'（必填）' if spec.get('required') else ''}", widget)
        state['inputs'][name] = (widget, spec)

    def choose(_=None):
        kind, dataset_id = chooser.currentData() or (None, None)
        state.update(kind=kind, dataset=dataset_id)
        clear_form()
        grid.setRowCount(0)
        grid.setColumnCount(0)
        if kind == 'file':
            run_button.setText('预览')
            add_input('code', {'description': '证券代码（可不填）', 'example': '600519'})
            add_input('date', {'description': '日期（可不填，默认最新）', 'example': '2026-09-24'})
            limit = QSpinBox()
            limit.setRange(1, 200)
            limit.setValue(20)
            limit.setAccessibleName('行数')
            form.addRow('行数', limit)
            state['inputs']['limit'] = (limit, {'type': 'integer'})
            status.setText('文件数据：按证券存放的默认看 sh.600000 最近几行，按日期存放的默认看最新一天。')
        elif kind == 'api':
            run_button.setText('试查')
            status.setText('正在读取参数说明…')

            def got(schema):
                if state['dataset'] != dataset_id or not _alive(status):
                    return
                for spec in schema['params']:
                    add_input(spec['name'], spec)
                status.setText(f"来源：{schema.get('source') or '—'} · {schema.get('rate_limit') or ''}")

            call(window, lambda: service(window, 'DataPreviewService').query_schema(dataset_id), got, status)

    def values():
        params = {}
        for name, (widget, spec) in state['inputs'].items():
            if isinstance(widget, QSpinBox):
                params[name] = widget.value()
            elif isinstance(widget, QComboBox):
                if widget.currentData() is not None:
                    params[name] = widget.currentData()
            elif widget.text().strip():
                params[name] = widget.text().strip()
        return params

    def show(value):
        columns = [c['name'] for c in value.get('columns', [])]
        grid.setColumnCount(len(columns))
        grid.setHorizontalHeaderLabels(columns)
        for j, c in enumerate(value.get('columns', [])):
            header = grid.horizontalHeaderItem(j)
            if header is not None and c.get('description'):
                header.setToolTip(f"{c.get('type', '')} · {c['description']}")
        _fill(grid, [[r.get(c) for c in columns] for r in value.get('rows', [])])
        parts = [f"{len(value.get('rows', []))} 行"]
        if value.get('total_rows') is not None:
            parts.append(f"共 {value['total_rows']:,} 行" + ('，只显示前面一部分' if value.get('truncated') else ''))
        if value.get('source_files'):
            parts.append('文件：' + '、'.join(value['source_files'][:3]))
        if value.get('source'):
            parts.append('来源：' + value['source'])
        if value.get('as_of'):
            parts.append('数据时间 ' + _time(value['as_of']))
        if value.get('note'):
            parts.append(value['note'])
        if value.get('warnings'):
            parts.append('提示：' + '；'.join(str(w) for w in value['warnings'] if w))
        status.setText(' · '.join(parts))

    def go():
        kind, dataset_id = state['kind'], state['dataset']
        if not dataset_id:
            return
        params = values()
        status.setText('正在读取…' if kind == 'file' else '正在查询（会联网）…')
        preview = service(window, 'DataPreviewService')
        if kind == 'file':
            limit = params.pop('limit', 20)
            work = lambda: preview.preview(dataset_id, limit=limit, filters=params or None)
        else:
            work = lambda: preview.query(dataset_id, params)
        call(window, work, show, status)

    chooser.currentIndexChanged.connect(choose)
    choose()
    return state


# ------------------------------------------------------------------ C. update and seal jobs

def jobs_section(window, box):
    jobs = service(window, 'DataUpdateJobs')
    status = label('正在读取任务…', 'muted', True)
    chooser = QComboBox()
    chooser.setAccessibleName('任务')
    description = label('', 'muted', True)
    form_holder = QWidget()
    form = QFormLayout(form_holder)
    plan_button = button('生成计划', lambda: make_plan(), True)
    box.addWidget(row(chooser, plan_button))
    box.addWidget(description)
    box.addWidget(form_holder)
    box.addWidget(status)
    plan_card = Card('计划（确认后才执行）')
    plan_text = label('选择任务、填好参数后点“生成计划”。生成计划不会写任何数据。', 'muted', True)
    plan_grid = table(['步骤', '动作', '数据', '日期', '覆盖已有', '说明'], [])
    run_button = button('确认执行', lambda: confirm(), True)
    run_button.setEnabled(False)
    plan_card.add(plan_text)
    plan_card.add(plan_grid)
    plan_card.add(run_button)
    box.addWidget(plan_card)
    runs_card = Card('运行记录（单击看进度和日志）')
    runs_grid = table(['开始', '任务', '触发', '状态', '进度', '当前步骤', '结束'], [])
    runs_grid.setMinimumHeight(240)
    run_detail = label('', 'muted', True)
    log_view = QPlainTextEdit()
    log_view.setReadOnly(True)
    log_view.setMaximumHeight(220)
    log_view.setAccessibleName('运行日志')
    cancel_button = button('取消这次运行', lambda: cancel())
    cancel_button.setEnabled(False)
    runs_card.add(runs_grid)
    runs_card.add(run_detail)
    runs_card.add(log_view)
    runs_card.add(cancel_button)
    box.addWidget(runs_card)
    box.addWidget(label('任务由数据侧在后台独立进程里执行，关掉牛牛也不会中断；运行记录保存在数据盘上。'
                        '盘中记录器在交易日打开牛牛时会自动启动（你授权的唯一例外），其他任务都要先看计划、确认后才执行。',
                        'muted', True))
    state = {'jobs': [], 'inputs': {}, 'plan': None, 'runs': [], 'selected': None, 'log_offset': 0}
    job_names = {}

    def clear_form():
        while form.rowCount():
            form.removeRow(0)
        state['inputs'] = {}

    def choose(_=None):
        clear_form()
        state['plan'] = None
        run_button.setEnabled(False)
        _fill(plan_grid, [])
        plan_text.setText('选择任务、填好参数后点“生成计划”。生成计划不会写任何数据。')
        job = chooser.currentData()
        if not job:
            return
        facts = [f"预计约 {max(1, round(job['estimated_seconds'] / 60))} 分钟"]
        if job.get('uses_network'):
            facts.append('会联网')
        if job.get('needs_data_disk'):
            facts.append('需要连着数据盘')
        description.setText(job['description'] + '（' + '，'.join(facts) + '）')
        for spec in job['params']:
            widget = QLineEdit()
            default = spec.get('default')
            widget.setPlaceholderText(' · '.join(p for p in (spec.get('description') or '',
                                                                 f'默认 {default}' if default else '',
                                                                 'YYYY-MM-DD' if spec['type'] == 'date' else '') if p))
            widget.setAccessibleName(spec['name'])
            form.addRow(f"{spec.get('description') or spec['name']}{'（必填）' if spec.get('required') else ''}", widget)
            state['inputs'][spec['name']] = widget

    def got_jobs(value):
        state['jobs'] = value['jobs']
        chooser.blockSignals(True)
        for job in value['jobs']:
            chooser.addItem(job['name'], job)
            job_names[job['job_id']] = job['name']
        chooser.blockSignals(False)
        status.setText('')
        choose()
        load_runs()

    def show_plan(plan):
        state['plan'] = plan
        _fill(plan_grid, [[s['name'], ACTION.get(s['action'], s['action']),
                           '、'.join(s.get('datasets') or []) or '—', '、'.join(s.get('dates') or []) or '—',
                           '是' if s.get('overwrites') else '否', s.get('note')] for s in plan['steps']])
        lines = [f"预计约 {max(1, round((plan.get('estimated_seconds') or 0) / 60))} 分钟 · "
                 f"计划 {_time(plan.get('expires_at'))} 前有效"]
        lines += ['提示：' + w for w in plan.get('warnings') or []]
        if plan.get('blocked_reason'):
            lines.append('不能执行：' + plan['blocked_reason'])
        plan_text.setText('\n'.join(lines))
        plan_text.setObjectName('note' if plan.get('blocked_reason') else 'muted')
        run_button.setEnabled(not plan.get('blocked_reason') and bool(plan['steps']))
        status.setText('')

    def make_plan():
        job = chooser.currentData()
        if not job:
            return
        params = {name: widget.text().strip() for name, widget in state['inputs'].items() if widget.text().strip()}
        run_button.setEnabled(False)
        status.setText('正在生成计划…')
        call(window, lambda: jobs.plan(job['job_id'], params), show_plan, status)

    def confirm():
        plan = state['plan']
        if not plan or plan.get('blocked_reason'):
            return
        run_button.setEnabled(False)
        status.setText('正在启动…')

        def started(value):
            state['plan'] = None
            state['selected'] = value['run_id']
            state['log_offset'] = 0
            log_view.clear()
            status.setText(f"已在后台启动（{value['run_id']}）。")
            load_runs()

        call(window, lambda: jobs.run(plan['plan_id']), started, status)

    def show_runs(value):
        state['runs'] = value['runs']
        runs = value['runs']
        _fill(runs_grid, [[_time(r.get('started_at') or r.get('created_at')), job_names.get(r['job_id'], r['job_id']),
                           TRIGGER.get(r.get('trigger'), r.get('trigger')), RUN_STATE.get(r['state'], r['state']),
                           f"{(r.get('progress') or 0) * 100:.0f}%", r.get('step'), _time(r.get('finished_at'))]
                          for r in runs],
              [(3, QColor('#f35f62') if r['state'] in ('failed', 'interrupted') else
                QColor('#22d787') if r['state'] == 'succeeded' else None) for r in runs])
        if state['selected']:
            show_selected()

    def load_runs():
        call(window, lambda: jobs.list_runs(20), show_runs, status)

    def show_selected():
        run = next((r for r in state['runs'] if r['run_id'] == state['selected']), None)
        if run is None:
            return
        result = run.get('result') or {}
        parts = [f"{job_names.get(run['job_id'], run['job_id'])} · {RUN_STATE.get(run['state'], run['state'])}"]
        if run.get('params'):
            parts.append('参数：' + '，'.join(f'{k}={v}' for k, v in run['params'].items()))
        for d in result.get('datasets') or []:
            parts.append(f"{d['dataset_id']}：到 {d.get('through') or '—'}，写入 {d.get('rows_written') or 0} 行"
                         + (f"，失败 {len(d['failures'])} 项" if d.get('failures') else ''))
        if result.get('seal'):
            parts.append(f"已封存 {result['seal'].get('date')}（{result['seal'].get('manifest')}）")
        if run.get('error'):
            parts.append('错误：' + run['error'])
        run_detail.setText('\n'.join(parts))
        cancel_button.setEnabled(run['state'] in LIVE)
        run_id = run['run_id']

        def got_log(value):
            if state['selected'] != run_id or not _alive(log_view):
                return
            if value['lines']:
                log_view.appendPlainText('\n'.join(value['lines']))
            state['log_offset'] = value['next_offset']

        call(window, lambda: jobs.log(run_id, state['log_offset']), got_log, status)

    def select(r, _c=None):
        if not 0 <= r < len(state['runs']):
            return
        state['selected'] = state['runs'][r]['run_id']
        state['log_offset'] = 0
        log_view.clear()
        show_selected()

    def cancel():
        run_id = state['selected']
        if not run_id:
            return
        cancel_button.setEnabled(False)
        status.setText('正在取消…')
        call(window, lambda: jobs.cancel(run_id), lambda _: (status.setText('已取消。'), load_runs()), status)

    def tick():
        if not _alive(runs_grid):
            return
        if any(r['state'] in LIVE for r in state['runs']):
            load_runs()

    chooser.currentIndexChanged.connect(choose)
    runs_grid.cellClicked.connect(select)
    timer = QTimer(runs_grid)  # dies with the page
    timer.timeout.connect(tick)
    timer.start(3000)
    call(window, jobs.list_jobs, got_jobs, status)
    return state


__all__ = ['status_section', 'preview_section', 'jobs_section', 'service', 'HEALTH', 'RUN_STATE', 'ACTION']
