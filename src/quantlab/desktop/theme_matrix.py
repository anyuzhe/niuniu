"""Host-managed A-share Theme Matrix; missing evidence remains UNKNOWN."""
from datetime import datetime
from uuid import uuid4

from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import QComboBox,QDateEdit,QDialog,QFormLayout,QLineEdit,QPlainTextEdit,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget

from quantlab.trading.decision import FRAMES
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.theme_state import THEME_STATES
from quantlab.trading.theme_store import ThemeError,ThemeStore
from .business_view import BusinessDetails
from .widgets import button,label,row

STATE_LABELS={'UNKNOWN':'未知','PREHEAT':'预热','START':'启动','MAIN_RISE':'主升','DIVERGENCE':'分歧','REPAIR':'修复','ACCELERATION':'加速','OVERHEAT':'过热','DECLINE':'退潮'}
FRAME_LABELS={'PREP':'盘前','AUCTION':'竞价','R1':'R1','R2':'R2','R3':'R3','D1':'D1','D2':'D2','D3_PLUS':'D3+'}
FACT_INPUTS=(('constituents','成分数',int),('active_constituents','活跃成分数',int),('limit_up_count','涨停数',int),('limit_down_count','跌停数',int),('twenty_cm_limit_up_count','20cm涨停数',int),('breadth_up','上涨宽度',int),('breadth_down','下跌宽度',int),('amount_billion','成交额（亿元）',float),('leader_symbol','龙头证券',str),('leader_return','龙头涨跌幅',float))


def parse_ids(text):
    return [v for v in text.replace(',',' ').split() if v]


class ThemeSnapshotEditor(QDialog):
    def __init__(self,window,source=None):
        super().__init__(window);self.window=window;self.source=source or {};self.store=ThemeStore(window.output);self.saved=None
        self.setWindowTitle('新增 Theme Snapshot' if not source else '修订 Theme Snapshot');self.resize(760,860)
        outer=QVBoxLayout(self);form=QFormLayout();outer.addLayout(form)
        self.theme=QLineEdit(self.source.get('theme',''));form.addRow('主题 / 主线',self.theme)
        self.day=QDateEdit();self.day.setCalendarPopup(True);self.day.setDate(QDate.fromString(self.source.get('trading_day',''),'yyyy-MM-dd') if source else QDate.currentDate());form.addRow('交易日',self.day)
        self.frame=QComboBox();[self.frame.addItem(FRAME_LABELS[v],v) for v in FRAMES];form.addRow('Decision Frame',self.frame)
        self.machine=QComboBox();[self.machine.addItem(STATE_LABELS[v],v) for v in THEME_STATES];form.addRow('Machine Rule 状态',self.machine)
        self.ai=QComboBox();[self.ai.addItem(STATE_LABELS[v],v) for v in THEME_STATES];form.addRow('AI 判断状态',self.ai)
        self.machine_rule=QLineEdit(self.source.get('machine_rule',''));form.addRow('规则说明',self.machine_rule)
        self.rule_version=QLineEdit(self.source.get('machine_rule_version',''));form.addRow('规则版本',self.rule_version)
        self.fact_controls={}
        for key,title,_ in FACT_INPUTS:
            control=QLineEdit(str(self.source.get('facts',{}).get(key,'')));self.fact_controls[key]=control;form.addRow(title,control)
        self.fact_source=QLineEdit(self.source.get('facts_source',''));form.addRow('事实来源',self.fact_source)
        self.fact_as_of=QLineEdit(self.source.get('facts_as_of') or '');self.fact_as_of.setPlaceholderText('例如 2026-09-11T14:50:00+08:00');form.addRow('事实时点',self.fact_as_of)
        self.evidence=QLineEdit(' '.join(self.source.get('quant_evidence_ids',[])));form.addRow('量化实验 UUID',self.evidence)
        self.ai_thesis=QPlainTextEdit(self.source.get('ai_thesis',''));self.ai_thesis.setMaximumHeight(90);form.addRow('AI Thesis',self.ai_thesis)
        self.risk=QPlainTextEdit(self.source.get('risk_review',''));self.risk.setMaximumHeight(90);form.addRow('Risk Review',self.risk)
        self.status=label('未提供市场事实时保持 UNKNOWN；不会用 AI 文本补造事实。','note',True);outer.addWidget(self.status)
        outer.addWidget(row(button('保存 Theme Snapshot',self.save,True),button('取消',self.reject)))
        if source:
            self.theme.setReadOnly(True);self.day.setEnabled(False);self.frame.setEnabled(False)
            self.frame.setCurrentIndex(max(0,self.frame.findData(source['frame'])));self.machine.setCurrentIndex(max(0,self.machine.findData(source['machine_state'])));self.ai.setCurrentIndex(max(0,self.ai.findData(source['ai_state'])))

    def facts(self):
        result={}
        for key,_,kind in FACT_INPUTS:
            text=self.fact_controls[key].text().strip()
            if not text:continue
            result[key]=text if kind is str else kind(text)
        return result

    def payload(self):
        theme=self.theme.text().strip();day=self.day.date().toString('yyyy-MM-dd');frame=self.frame.currentData()
        decisions=DecisionStore(self.window.output).list(trading_day=day,frame=frame,include_superseded=False,limit=200)['records']
        decision_ids=[d['decision_id'] for d in decisions if d.get('theme')==theme]
        return {'theme':theme,'trading_day':day,'frame':frame,'machine_state':self.machine.currentData(),'ai_state':self.ai.currentData(),
            'facts':self.facts(),'facts_source':self.fact_source.text().strip(),'facts_as_of':self.fact_as_of.text().strip() or None,
            'machine_rule':self.machine_rule.text().strip(),'machine_rule_version':self.rule_version.text().strip(),
            'quant_evidence_ids':parse_ids(self.evidence.text()),'decision_ids':decision_ids,
            'ai_thesis':self.ai_thesis.toPlainText().strip(),'risk_review':self.risk.toPlainText().strip(),
            'revision_of':self.source.get('snapshot_id') if self.source else None,'source':'desktop_host'}

    def save(self):
        try:self.saved=self.store.create(str(uuid4()),self.payload())
        except (ThemeError,ValueError) as exc:self.status.setText(str(exc));return
        self.accept()


class ThemeMatrixWidget(QWidget):
    MAX_COLUMNS=24
    def __init__(self,window):
        super().__init__();self.window=window;self.store=ThemeStore(window.output);self.records={}
        box=QVBoxLayout(self);self.notice=label('Theme Matrix 只显示正式 Theme Snapshot；Decision 主题标签只扩展坐标轴，不推导状态。','note',True);box.addWidget(self.notice)
        box.addWidget(row(button('＋ 新增 Theme Snapshot',self.create,True),button('刷新矩阵',self.reload)))
        self.table=QTableWidget();self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems);box.addWidget(self.table,1)
        self.table.cellDoubleClicked.connect(self.open_cell);self.reload()

    def create(self):
        dialog=ThemeSnapshotEditor(self.window);dialog.accepted.connect(self.reload);self.window.show_dialog(dialog)

    def reload(self):
        matrix=self.store.matrix();decisions=DecisionStore(self.window.output).list(include_superseded=False,limit=200)['records']
        themes=set(matrix['themes']);axes=set(matrix['columns'])
        for item in decisions:
            if item.get('theme'):
                themes.add(item['theme']);axes.add((item['trading_day'],item['frame']))
        columns=sorted(axes)[-self.MAX_COLUMNS:];themes=sorted(themes)
        self.table.clear();self.table.setRowCount(len(themes));self.table.setColumnCount(1+len(columns));self.table.setHorizontalHeaderLabels(['主题',*[f'{d}\n{FRAME_LABELS.get(f,f)}' for d,f in columns]])
        self.records={}
        for i,theme in enumerate(themes):
            self.table.setItem(i,0,QTableWidgetItem(theme))
            for j,(day,frame) in enumerate(columns,1):
                record=matrix['lookup'].get((theme,day,frame));self.records[i,j]=record
                if record:
                    facts=len(record.get('facts',{}));text=STATE_LABELS[record['machine_state']]+'\nAI:'+STATE_LABELS[record['ai_state']]+(f'\n事实{facts}' if facts else '')
                else:text='未知\nAI:未知'
                item=QTableWidgetItem(text);item.setTextAlignment(Qt.AlignmentFlag.AlignCenter);self.table.setItem(i,j,item)
        self.notice.setText(matrix['policy']+f' 当前 {len(themes)} 个主题，{len(columns)} 个明确日期/Frame 列。')
        self.table.resizeColumnsToContents();self.table.resizeRowsToContents()

    def open_cell(self,row,column):
        if column==0:return
        record=self.records.get((row,column))
        if record is None:self.notice.setText('该主题/日期/Frame 没有正式 Theme Snapshot，因此保持 UNKNOWN。');return
        full=self.store.get(record['snapshot_id']);dialog=QDialog(self.window);dialog.setWindowTitle(full['theme']+' · '+full['trading_day']+' · '+full['frame']);dialog.resize(900,760)
        layout=QVBoxLayout(dialog);layout.addWidget(BusinessDetails(full),1)
        evidence=row_widget=QWidget();ev=QVBoxLayout(evidence);ev.setContentsMargins(0,0,0,0)
        for run_id in full.get('quant_evidence_ids',[]):ev.addWidget(button('打开量化实验 '+run_id[:8],lambda checked=False,r=run_id:self.window.open_run(r)))
        decisions=DecisionStore(self.window.output)
        for decision_id in full.get('decision_ids',[]):
            try:d=decisions.get(decision_id)
            except Exception:continue
            ev.addWidget(button('打开 Decision '+decision_id[:8],lambda checked=False,x=d:self.window.open_decision(x)))
        layout.addWidget(evidence)
        if not full.get('superseded_by'):layout.addWidget(button('基于此快照新建修订',lambda:(dialog.close(),self.revise(full)),True))
        self.window.show_dialog(dialog)

    def revise(self,record):
        dialog=ThemeSnapshotEditor(self.window,record);dialog.accepted.connect(self.reload);self.window.show_dialog(dialog)
