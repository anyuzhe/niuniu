"""Six-role development settings and request -> reviewed plan -> isolated task UI."""
from __future__ import annotations

from dataclasses import asdict
from threading import Event

from PyQt6 import sip
from PyQt6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPlainTextEdit,
                             QComboBox, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from quantlab.agent.model_config import ModelConfig
from quantlab.devstudio.planning import DevRequestPlanner
from quantlab.devstudio.team import (DOMAINS, LABELS, BRIEFS, load_team_models,
                                    save_team_models)
from .widgets import button, label, row


def plan_summary(plan):
    spec = plan['spec']
    team = spec['team']
    lines = [spec['title'], '基线：' + plan['base_sha'], '需求：' + spec['request'], '', '验收标准：']
    lines += ['  ' + c for c in spec['acceptance_criteria']]
    lines += ['', '精确文件与负责人：']
    lines += [f'  {domain} · {path}' for path, domain in team['path_owners'].items()]
    lines += ['', '冻结测试（逐模块隔离执行）：']
    lines += ['  ' + ' '.join(cmd) for cmd in spec['test_commands']]
    lines += ['', '六角色模型（本任务冻结，修改设置不影响此计划）：']
    for domain in DOMAINS:
        cfg = team['models'][domain]
        lines.append(f"  {domain} {LABELS[domain]}：{cfg['provider']} / {cfg['model'] or 'CLI 默认模型'} / {cfg['effort'] or '服务默认强度'}")
    lines += ['', f"并行写入者最多 {team['max_writers']} 个；本次最多 {team['max_cycles']} 个协作轮次；每个子任务最多三次执行。",
              '接口合同与依赖：', spec['notes'] or '无补充']
    if plan['sensitive_paths']:
        lines += ['', '需要重点审阅的敏感文件：', *['  ' + p for p in plan['sensitive_paths']]]
    lines += ['', *plan['warnings'], '计划有效至：' + plan['expires_at']]
    return '\n'.join(lines)


class DevTeamModelsDialog(QDialog):
    def __init__(self, window, output):
        super().__init__(window)
        self.output = output
        self.values = load_team_models(output)
        self.fields = {}
        self.setWindowTitle('开发团队 · 六角色模型配置')
        self.resize(820, 760)
        box = QVBoxLayout(self)
        box.addWidget(label('角色可以使用同一个模型，也可以分别选择模型/协议。这里只保存配置，不连接模型；API 密钥只填写环境变量名，不填写密钥。已有任务保持其冻结配置。', 'note', True))
        tabs = self.tabs = QTabWidget()
        box.addWidget(tabs, 1)
        for domain in DOMAINS:
            page = QWidget()
            form = QFormLayout(page)
            form.addRow(label(BRIEFS[domain], 'muted', True))
            cfg = self.values[domain]
            fields = {}
            for key, title, options in (
                ('provider', '协议', ('codex_cli', 'responses', 'chat_completions', 'pi_sdk')),
                ('effort', '推理强度', ('', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh')),
            ):
                widget = QComboBox()
                widget.addItems(options)
                widget.setCurrentText(cfg[key])
                widget.setAccessibleName(domain + '.' + key)
                fields[key] = widget
                form.addRow(title, widget)
            for key, title in (('model', '模型 ID（CLI 可留空）'), ('base_url', 'API 地址'),
                               ('api_key_env', '密钥环境变量名'), ('codex_path', 'Codex 可执行文件（可留空）'),
                               ('pi_path', 'Pi 可执行文件（留空自动发现）')):
                widget = QLineEdit(cfg[key])
                if key == 'model':
                    widget.setPlaceholderText('Pi: openai-codex/gpt-6-luna；API: 自定义模型 ID')
                widget.setAccessibleName(domain + '.' + key)
                fields[key] = widget
                form.addRow(title, widget)
            for key, title, low, high in (
                ('timeout_seconds', '单次模型超时（秒）', 10, 600),
                ('max_tool_calls', '单次工具调用上限', 1, 24),
                ('max_rounds', '单次模型往返上限', 1, 16),
                ('max_output_tokens', '单次输出 Token 上限', 128, 16384),
                ('max_context_chars', '上下文字符预算', 2000, 200000),
            ):
                widget = QSpinBox()
                widget.setRange(low, high)
                widget.setValue(cfg[key])
                widget.setAccessibleName(domain + '.' + key)
                fields[key] = widget
                form.addRow(title, widget)
            self.fields[domain] = fields
            tabs.addTab(page, domain + ' · ' + LABELS[domain])
        self.status = label('', 'muted', True)
        box.addWidget(self.status)
        box.addWidget(label('Pi 使用本机已安装 SDK 和登录，仅开放牛牛角色工具，不加载 Pi 插件或内置 shell。模型 ID 可自定义为 provider/model。', 'muted', True))
        box.addWidget(row(button('复制当前配置到全部角色', self.copy_to_all), button('保存角色配置', self.save, True), button('取消', self.reject)))

    def copy_to_all(self):
        domain = DOMAINS[self.tabs.currentIndex()]
        try:
            cfg = dict(self.values[domain])
            for key, widget in self.fields[domain].items():
                cfg[key] = (widget.currentText() if isinstance(widget, QComboBox) else
                            widget.value() if isinstance(widget, QSpinBox) else widget.text().strip())
            cfg = asdict(ModelConfig(**cfg))
        except (ValueError, TypeError) as exc:
            self.status.setText('配置未复制：' + str(exc))
            return
        for target, fields in self.fields.items():
            self.values[target] = dict(cfg)
            for key, widget in fields.items():
                if isinstance(widget, QComboBox): widget.setCurrentText(cfg[key])
                elif isinstance(widget, QSpinBox): widget.setValue(cfg[key])
                else: widget.setText(cfg[key])
        self.status.setText('已填入全部六角色；点击保存后生效，旧任务不受影响。')

    def payload(self):
        values = {}
        for domain, fields in self.fields.items():
            cfg = dict(self.values[domain])
            for key, widget in fields.items():
                cfg[key] = (widget.currentText() if isinstance(widget, QComboBox) else
                            widget.value() if isinstance(widget, QSpinBox) else widget.text().strip())
            values[domain] = asdict(ModelConfig(**cfg))
        return values

    def save(self):
        try:
            save_team_models(self.output, self.payload())
        except Exception as exc:
            self.status.setText('配置未保存：' + str(exc))
            return
        self.accept()


class DevRequestDialog(QDialog):
    """No task or worktree exists until the user confirms the exact generated plan."""
    def __init__(self, window, service):
        super().__init__(window)
        self.window = window
        self.service = service
        self.plan = None
        self.created = None
        self.start_requested = False
        self.busy = False
        self.stop = Event()
        self.destroyed.connect(lambda _=None, stop=self.stop: stop.set())
        self.setWindowTitle('提出开发需求 · 六角色协作')
        self.resize(1000, 800)
        box = QVBoxLayout(self)
        box.addWidget(label('描述你希望牛牛增加或修改的功能。总控先只读分析代码并生成文件分工、接口和测试计划；确认后在隔离工作区按角色开发。完成后仍由你确认合并。', 'note', True))
        self.request = QPlainTextEdit()
        self.request.setAccessibleName('开发需求')
        self.request.setPlaceholderText('例如：数据中心增加失败原因筛选，并让 AI 助手能读取同样的状态；不要改变 DATA 数据来源或发布状态。')
        self.request.setMaximumHeight(160)
        box.addWidget(self.request)
        self.plan_button = button('生成计划（调用总控模型）', self.generate, True)
        self.settings_button = button('六角色模型设置', self.settings)
        box.addWidget(row(self.plan_button, self.settings_button, button('请求停止', self.stop_work)))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName('开发计划预览')
        box.addWidget(self.preview, 1)
        self.status = label('生成计划会把需求及必要代码发送到所选模型；不会运行测试、采集数据或改代码。', 'muted', True)
        box.addWidget(self.status)
        self.confirm_button = button('确认计划并开始开发', self.confirm, True)
        self.confirm_button.setEnabled(False)
        box.addWidget(row(self.confirm_button, button('关闭', self.reject)))
        self.request.textChanged.connect(self.invalidate)

    def set_busy(self, busy):
        self.busy = busy
        self.request.setEnabled(not busy)
        self.plan_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.confirm_button.setEnabled(not busy and self.plan is not None)

    def invalidate(self):
        self.plan = None
        self.confirm_button.setEnabled(False)
        self.preview.clear()

    def settings(self):
        if self.busy:
            return
        try:
            dialog = DevTeamModelsDialog(self.window, self.service.output)
        except Exception as exc:
            self.status.setText('无法读取角色配置：' + str(exc))
            return
        dialog.accepted.connect(self.invalidate)
        self.window.show_dialog(dialog)

    def generate(self):
        request = self.request.toPlainText().strip()
        if not request or self.busy:
            self.status.setText('请先填写开发需求。')
            return
        self.invalidate()
        self.stop.clear()
        self.set_busy(True)
        self.status.setText('总控正在只读分析需求与代码；尚未创建开发任务。')
        def done(value, error):
            if sip.isdeleted(self):
                return
            self.set_busy(False)
            if error or self.stop.is_set():
                self.status.setText(error or '规划已停止，没有开始开发。')
                return
            self.plan = value
            self.preview.setPlainText(plan_summary(value))
            self.confirm_button.setEnabled(True)
            self.status.setText('请审阅文件归属、接口、测试和六角色模型；确认后才开始隔离开发。')
        self.window.async_call(lambda: DevRequestPlanner(self.service).plan(request, allow_send=True, stop=self.stop), done, False)

    def confirm(self):
        if self.busy or self.plan is None:
            return
        if self.plan['spec']['request'] != self.request.toPlainText().strip():
            self.invalidate()
            self.status.setText('需求已变化，请重新生成计划。')
            return
        plan = self.plan
        self.stop.clear()
        self.set_busy(True)
        self.status.setText('正在核对计划版本并创建隔离任务…')
        def done(value, error):
            if sip.isdeleted(self):
                return
            self.set_busy(False)
            if error:
                self.status.setText(error)
                self.invalidate()
                return
            self.created = value
            self.start_requested = not self.stop.is_set()
            self.accept()
        self.window.async_call(lambda: self.service.create_from_plan(plan, confirmed=True), done, False)

    def stop_work(self):
        self.stop.set()
        if self.busy:
            self.status.setText('停止请求已发出；当前调用退出后不再继续，不会自动合并。')

    def reject(self):
        if self.busy:
            self.stop_work()
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.stop_work()
            event.ignore()
        else:
            event.accept()


__all__ = ['DevTeamModelsDialog', 'DevRequestDialog', 'plan_summary']
