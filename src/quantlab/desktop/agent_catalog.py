"""Native inspection of the same read-only research API offered to agents."""
import json
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QSpinBox, QListWidget, QListWidgetItem
from quantlab.agent.catalog import ReadOnlyResearchAPI
from .widgets import label, button, row
from .business_view import BusinessDetails


class AgentCatalogDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.api = ReadOnlyResearchAPI(window.output)
        self.setWindowTitle('AI 研究接口 · 查询与助手入口'); self.resize(1000, 780)
        box = QVBoxLayout(self)
        box.addWidget(label('供人和智能体共用的研究查询入口。下方可打开聊天助手；本查询面板仍只读。', 'note', True))
        box.addWidget(button('打开内置研究助手',lambda:self.window.research_chat(),True))
        proposal_button=button('研究提案与人工批准',self.open_proposals)
        proposal_button.setEnabled(bool(getattr(window,'data_root',None)));box.addWidget(proposal_button)
        self.tools = QComboBox(); box.addWidget(self.tools)
        self.definitions = self.api.schemas()
        for item in self.definitions: self.tools.addItem(item['name']+' · '+item['description'], item['name'])
        self.form = QFormLayout(); box.addLayout(self.form); self.controls = {}; self.labels = {}
        names = {'query':'检索关键词','offset':'起始位置','limit':'每页数量','factor_id':'因子编号',
                 'version':'版本','status':'状态过滤（留空全部）','kind':'实验类型（留空全部）','run_id':'实验 UUID','job_id':'任务 UUID'}
        for key in names:
            control = QSpinBox() if key in ('offset','limit') else QLineEdit()
            if key == 'offset': control.setRange(0, 100000)
            if key == 'limit': control.setRange(1, 20); control.setValue(10)
            if key == 'version': control.setText('1.0.0')
            title = label(names[key]); self.form.addRow(title, control)
            self.controls[key] = control; self.labels[key] = title
        self.run_button = button('执行只读查询', self.query, True)
        box.addWidget(row(self.run_button, button('查看工具合同', self.show_schemas)))
        self.status = label('尚未查询。', 'muted', True); box.addWidget(self.status)
        self.details = BusinessDetails({}); box.addWidget(self.details, 1)
        self.evidence = QListWidget(); self.evidence.setMaximumHeight(110)
        self.evidence.setAccessibleName('实际实验引用'); box.addWidget(self.evidence)
        box.addWidget(button('在原工作台打开选中实验', self.open_evidence))
        self.evidence.itemDoubleClicked.connect(lambda _: self.open_evidence())
        self.tools.currentIndexChanged.connect(self.select_tool); self.select_tool()

    def open_proposals(self):
        from .agent_proposals import ProposalDialog
        self.window.show_dialog(ProposalDialog(self.window))

    def select_tool(self):
        fields = self.definitions[self.tools.currentIndex()]['parameters']['properties']
        for key, control in self.controls.items():
            control.setVisible(key in fields); self.labels[key].setVisible(key in fields)

    def show_schemas(self):
        self.details.setPlainText(json.dumps({'tools':self.api.schemas()}, ensure_ascii=False, indent=2))
        self.evidence.clear(); self.status.setText('工具合同；没有运行研究。')

    def query(self):
        if not self.run_button.isEnabled(): return
        fields = self.definitions[self.tools.currentIndex()]['parameters']['properties']
        arguments = {key: c.value() if isinstance(c, QSpinBox) else c.text().strip()
                     for key, c in self.controls.items() if key in fields}
        name = self.tools.currentData(); self.run_button.setEnabled(False)
        self.status.setText('正在读取当前工作空间…')
        def done(result, error):
            if sip.isdeleted(self): return
            self.run_button.setEnabled(True); self.evidence.clear()
            if error: self.status.setText('读取失败：'+error); return
            self.details.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.status.setText('只读查询完成；未修改研究数据。' if result['ok'] else result['error']['message'])
            for item in result['evidence']:
                if item['kind'] != 'experiment': continue
                row_item = QListWidgetItem(item['run_id']); row_item.setData(Qt.ItemDataRole.UserRole, item['run_id'])
                self.evidence.addItem(row_item)
        self.window.async_call(lambda: self.api.call(name, arguments), done, guarded=False)

    def open_evidence(self):
        item = self.evidence.currentItem()
        if item is None: self.status.setText('请选择一个实际实验引用。'); return
        self.hide(); self.window.open_run(item.data(Qt.ItemDataRole.UserRole))
