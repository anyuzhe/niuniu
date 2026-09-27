"""Editable model connection panel; only non-secret settings are persisted."""
from dataclasses import asdict
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget,QFormLayout,QLineEdit,QComboBox,QSpinBox,QCheckBox
from quantlab.agent.model_config import ModelConfig


class ModelSettings(QWidget):
    changed=pyqtSignal()
    def __init__(self,config,parent=None):
        super().__init__(parent);self.original=config;form=QFormLayout(self)
        self.provider=QComboBox()
        for text,key in [('Codex CLI · 现有 ChatGPT 登录','codex_cli'),
            ('Responses API','responses'),('兼容 Chat Completions API','chat_completions'),
            ('Pi SDK · 现有本机模型配置','pi_sdk')]:self.provider.addItem(text,key)
        self.provider.setCurrentIndex(self.provider.findData(config.provider));form.addRow('模型接入方式',self.provider)
        self.model=QComboBox();self.model.setEditable(True);self.model.setEditText(config.model)
        form.addRow('模型 ID（Pi：provider/model；CLI 可留空）',self.model)
        self.effort=QComboBox()
        for value in ('','none','minimal','low','medium','high','xhigh'):self.effort.addItem(value or '服务默认',value)
        self.effort.setCurrentIndex(self.effort.findData(config.effort));form.addRow('推理强度',self.effort)
        self.codex=QLineEdit(config.codex_path);self.pi=QLineEdit(config.pi_path);self.url=QLineEdit(config.base_url)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('仅在当前窗口内存保存；留空读取下面环境变量')
        self.key_env=QLineEdit(config.api_key_env)
        for title,c in [('Codex 可执行路径（留空自动寻找）',self.codex),
            ('Pi 可执行路径（留空自动寻找）',self.pi),('API Base URL',self.url),
            ('API Key（不落盘）',self.key),('密钥环境变量',self.key_env)]:form.addRow(title,c)
        self.timeout=QSpinBox();self.timeout.setRange(10,600);self.timeout.setValue(config.timeout_seconds)
        self.calls=QSpinBox();self.calls.setRange(1,24);self.calls.setValue(config.max_tool_calls)
        self.rounds=QSpinBox();self.rounds.setRange(1,16);self.rounds.setValue(config.max_rounds)
        self.tokens=QSpinBox();self.tokens.setRange(128,16384);self.tokens.setValue(config.max_output_tokens)
        self.context=QSpinBox();self.context.setRange(2000,200000);self.context.setValue(config.max_context_chars)
        for title,c in [('模型总时限（秒）',self.timeout),('每轮最多工具调用',self.calls),
            ('API 最多往返轮数',self.rounds),('API 输出 token 上限／CLI 文本预算基数',self.tokens),
            ('上下文字符预算',self.context)]:form.addRow(title,c)
        self.compat=QCheckBox('仅本进程兼容旧 agents 字段，不改全局配置');self.compat.setChecked(config.legacy_agent_compat)
        form.addRow(self.compat)
        self.allow=QCheckBox('允许把本轮对话和研究摘要发送给上述服务（Codex CLI 也会联网）')
        form.addRow(self.allow)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        for c in (self.url,self.codex,self.pi):c.textChanged.connect(lambda:self.allow.setChecked(False))
        self.fields={'model':self.model,'effort':self.effort,'codex_path':self.codex,'pi_path':self.pi,'base_url':self.url,'api_key_env':self.key_env}
        for control in (self.model,self.effort):
            (control.editTextChanged if control.isEditable() else control.currentIndexChanged).connect(lambda *_:self._modified())
        for control in (self.url,self.codex,self.pi,self.key_env):control.textChanged.connect(lambda *_:self._modified())
        for control in (self.timeout,self.calls,self.rounds,self.tokens,self.context):control.valueChanged.connect(lambda *_:self._modified())
        self.compat.toggled.connect(lambda *_:self._modified())
        self._provider_changed()
    def _modified(self):
        self.allow.setChecked(False);self.changed.emit()
    def _provider_changed(self):
        provider=self.provider.currentData();cli=provider=='codex_cli';pi=provider=='pi_sdk'
        self.codex.setEnabled(cli);self.pi.setEnabled(pi);self.compat.setEnabled(cli)
        for c in (self.url,self.key,self.key_env):c.setEnabled(not (cli or pi))
        if cli or pi:self.key.clear()
        self.model.lineEdit().setPlaceholderText('填写现有 Pi 配置中的 provider/model' if pi else '填写实际模型 ID；Codex CLI 可留空')
        self.pi.setToolTip('使用已经安装并授权的 Pi；推理发送到其配置的上游服务，不是自动安装或新增授权。')
        self._modified()
    def collect(self):
        return ModelConfig(**{**asdict(self.original),'provider':self.provider.currentData(),
            'model':self.model.currentText().strip(),'effort':self.effort.currentData(),
            'codex_path':self.codex.text().strip(),'pi_path':self.pi.text().strip(),'base_url':self.url.text().strip(),
            'api_key_env':self.key_env.text().strip(),'timeout_seconds':self.timeout.value(),
            'max_tool_calls':self.calls.value(),'max_rounds':self.rounds.value(),
            'max_output_tokens':self.tokens.value(),'max_context_chars':self.context.value(),
            'legacy_agent_compat':self.compat.isChecked()})

    def apply_models(self,info):
        current=self.model.currentText();self.model.clear();self.model.addItem('')
        for item in info.get('models',[]):
            value=item if isinstance(item,str) else item.get('model') or item.get('id')
            if value:self.model.addItem(value)
        self.model.setEditText(current)
