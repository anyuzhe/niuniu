"""Native control of the existing durable completed-bar paper feed."""
import json
import re
from pathlib import Path
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QFileDialog, QPushButton
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.paper import PaperAccount, advance_from_files
from .widgets import button, label, row, raw


class PaperToolsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window=window;self.busy=False;self.setWindowTitle('模拟账户 · 行情交付与恢复');self.resize(900,700)
        box=QVBoxLayout(self);form=QFormLayout();box.addLayout(form)
        self.account=QLineEdit('paper-account');form.addRow('账户名（保存于当前实验目录 / paper）',self.account)
        self.paths={}
        for key,title in [('bars','不复权行情 Parquet'),('targets','已可用目标权重 Parquet'),('rules','逐时点交易规则 JSON'),('config','成交配置 JSON（新账户可留空）')]:
            field=QLineEdit();field.setAccessibleName(title);self.paths[key]=field
            def choose(checked=False, field=field):
                path,_=QFileDialog.getOpenFileName(self,'选择输入文件',str(window.output),'数据文件 (*.json *.parquet)')
                if path:field.setText(path)
            form.addRow(title,row(field,button('选择',choose)))
        self.backend=QComboBox();self.backend.addItems(['open','vnpy_rules']);form.addRow('成交后端',self.backend)
        self.status=label('交付外部更新的完整快照；重复交付幂等。恢复账户沿用其冻结配置。','muted',True);box.addWidget(self.status)
        self.step_button=button('交付一次',self.step,True);self.follow_button=button('持续交付（每 5 秒）',self.follow);self.stop_button=button('停止持续交付',self.stop)
        box.addWidget(row(self.step_button,self.follow_button,self.stop_button,button('读取账户',self.read),button('独立账务核对',self.reconcile)))
        self.output=raw({});box.addWidget(self.output,1)
        box.addWidget(label('输入必须是已完成行情和已可用目标。迟到、修订或未来输入会拒绝；遇错停止持续交付。此处没有券商连接。','note',True))
        self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.step)
        for control in self.findChildren(QPushButton):control.setAutoDefault(False)

    def account_path(self):
        name=self.account.text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name):raise ValueError('账户名限英文、数字、下划线或短横线，1–80 字符')
        path=self.window.output/'paper'/(name+'.json')
        if path.is_symlink() or path.parent.is_symlink():raise ValueError('账户路径不能是符号链接')
        return path

    def perform(self, work):
        if self.busy:return
        self.busy=True;self.status.setText('正在处理…');self.step_button.setEnabled(False)
        def done(result,error):
            self.busy=False;self.step_button.setEnabled(True)
            if error:self.stop();self.status.setText(error)
            else:self.status.setText('持续交付中' if self.timer.isActive() else '完成')
            self.output.setPlainText(error or json.dumps(result,ensure_ascii=False,indent=2,default=str))
        self.window.async_call(work,done,guarded=False)

    def step(self):
        if self.busy:return
        try:
            account=self.account_path();paths={k:v.text().strip() for k,v in self.paths.items()};backend=self.backend.currentText()
            if any(not Path(paths[k]).is_file() for k in ('bars','targets','rules')):raise ValueError('请选择行情、目标权重和交易规则文件')
            def work():
                previous=PaperAccount(account).read() if account.exists() else None
                cfg=ExecutionConfig(**json.loads(Path(paths['config']).read_text())) if paths['config'] else ExecutionConfig(**previous['identity']['config']) if previous else ExecutionConfig()
                return advance_from_files(account,paths['bars'],paths['targets'],paths['rules'],cfg,backend)
            self.perform(work)
        except (ValueError,OSError) as error:self.stop();self.status.setText(str(error))

    def follow(self):
        self.timer.start();self.step()

    def stop(self):
        self.timer.stop();self.status.setText('已停止后续交付；正在处理的一次交付会完成并落盘。' if self.busy else '持续交付已停止')

    def read(self):
        try:
            path=self.account_path()
            self.perform(lambda:{k:v for k,v in PaperAccount(path).read().items() if k in ('revision','watermark','summary','identity','limitations')})
        except (ValueError,OSError) as error:self.status.setText(str(error))

    def reconcile(self):
        from quantlab.execution.reconcile import reconcile_account
        try:
            path=self.account_path();self.perform(lambda:reconcile_account(path))
        except (ValueError,OSError) as error:self.status.setText(str(error))

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
