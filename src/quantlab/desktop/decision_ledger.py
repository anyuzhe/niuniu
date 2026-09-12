"""Manual host UI for append-only trading decisions."""
from uuid import uuid4

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QComboBox,QDateEdit,QDialog,QFormLayout,QLineEdit,QPlainTextEdit,QVBoxLayout

from quantlab.trading.decision import ACTIONS, FRAMES
from quantlab.trading.decision_store import DecisionError, DecisionStore
from quantlab.trading.strategy_intent import StrategyIntentService
from .widgets import button,label,row

FRAME_LABELS = {
    'PREP':'盘前计划','AUCTION':'竞价确认','R1':'早盘 R1','R2':'中段 R2','R3':'收盘 R3',
    'D1':'次日 D1','D2':'第二日 D2','D3_PLUS':'D3+ 持续跟踪',
}
ACTION_LABELS = {
    'DISCOVERED':'发现','WATCH':'观察','READY':'准备','PLAN_OPEN':'计划开仓','OPEN':'开仓意图',
    'ADD':'加仓意图','HOLD':'持有','REDUCE':'减仓意图','EXIT':'退出意图',
    'INVALIDATED':'计划失效','REJECTED':'放弃','EXPIRED':'过期',
}


class DecisionEditor(QDialog):
    def __init__(self, window, source=None):
        super().__init__(window); self.window=window; self.store=DecisionStore(window.output); self.intent=StrategyIntentService(window.output)
        self.source=source or {}; self.saved=None
        self.setWindowTitle('新增 Decision' if not source else '修订 Decision')
        self.resize(720,760); outer=QVBoxLayout(self); form=QFormLayout(); outer.addLayout(form)
        self.symbol=QLineEdit(self.source.get('symbol','')); form.addRow('证券代码',self.symbol)
        self.day=QDateEdit(); self.day.setCalendarPopup(True); self.day.setDate(QDate.fromString(self.source.get('trading_day',''),'yyyy-MM-dd') if source else QDate.currentDate()); form.addRow('交易日',self.day)
        self.frame=QComboBox(); [self.frame.addItem(FRAME_LABELS[v],v) for v in FRAMES]; form.addRow('Decision Frame',self.frame)
        self.action=QComboBox(); [self.action.addItem(ACTION_LABELS[v],v) for v in ACTIONS]; form.addRow('策略动作',self.action)
        self.transition_reason=QLineEdit(self.source.get('transition_reason',''));self.transition_reason.setPlaceholderText('动作变化的原因；留空时可复用判断/机器状态');form.addRow('状态转移理由',self.transition_reason)
        self.theme=QLineEdit(self.source.get('theme','')); form.addRow('主线 / 主题',self.theme)
        self.theme_role=QLineEdit(self.source.get('theme_role','')); form.addRow('主题角色',self.theme_role)
        self.ai_thesis=QPlainTextEdit(self.source.get('ai_thesis','')); self.ai_thesis.setMaximumHeight(100); form.addRow('判断 / 依据',self.ai_thesis)
        self.buy_zone=QLineEdit(self.source.get('buy_zone','')); form.addRow('买入区间',self.buy_zone)
        self.confirm_trigger=QLineEdit(self.source.get('confirm_trigger','')); form.addRow('确认触发',self.confirm_trigger)
        self.invalidation=QLineEdit(self.source.get('invalidation','')); form.addRow('失效条件',self.invalidation)
        self.hold_reason=QLineEdit(self.source.get('hold_reason','')); form.addRow('持有理由',self.hold_reason)
        self.add_condition=QLineEdit(self.source.get('add_condition','')); form.addRow('加仓条件',self.add_condition)
        self.reduce_condition=QLineEdit(self.source.get('reduce_condition','')); form.addRow('减仓条件',self.reduce_condition)
        self.exit_condition=QLineEdit(self.source.get('exit_condition','')); form.addRow('退出条件',self.exit_condition)
        self.reference=QLineEdit(self.source.get('reference_decision_id') or ''); self.reference.setPlaceholderText('D1/D2/D3+ 必填：更早的同一证券 Decision UUID'); form.addRow('关联原始 Decision',row(self.reference,button('最近原判',self.fill_reference)))
        self.effective_at=QLineEdit(self.source.get('effective_at') or ''); self.effective_at.setPlaceholderText('可选，例如 2026-09-11T10:25:00+08:00'); form.addRow('信息实际可用时点',self.effective_at)
        self.status=label('Decision 保存后不可修改；submitted_at 由宿主写入。迟交/补录会自动标记，不能伪装成原时点提交。','note',True); outer.addWidget(self.status)
        outer.addWidget(row(button('保存 Decision',self.save,True),button('取消',self.reject)))
        if source:
            self.frame.setCurrentIndex(max(0,self.frame.findData(source['frame'])))
            self.action.setCurrentIndex(max(0,self.action.findData(source['action'])))
            self.symbol.setReadOnly(True); self.day.setEnabled(False); self.frame.setEnabled(False)

    def fill_reference(self):
        symbol=self.symbol.text().strip().lower();day=self.day.date().toString('yyyy-MM-dd')
        records=self.store.list(symbol=symbol,include_superseded=False,limit=200)['records'] if symbol else []
        source=next((d for d in records if d['trading_day']<day and d['frame'] in ('PREP','AUCTION','R1','R2','R3')),None)
        if source:
            self.reference.setText(source['decision_id'])
            self.action.setCurrentIndex(max(0,self.action.findData(source['action'])))
            for control,key in ((self.buy_zone,'buy_zone'),(self.confirm_trigger,'confirm_trigger'),(self.invalidation,'invalidation'),(self.hold_reason,'hold_reason'),(self.add_condition,'add_condition'),(self.reduce_condition,'reduce_condition'),(self.exit_condition,'exit_condition')):
                if not control.text().strip() and source.get(key):control.setText(source[key])
            self.status.setText('已选择最近的更早原判并继承当前策略动作/计划字段：'+source['trading_day']+' '+source['frame'])
        else:self.status.setText('没有找到同一证券、更早交易日的原始 Decision。')

    def payload(self):
        return {
            'symbol':self.symbol.text().strip(),'trading_day':self.day.date().toString('yyyy-MM-dd'),
            'frame':self.frame.currentData(),'action':self.action.currentData(),'role_id':'human',
            'transition_reason':self.transition_reason.text().strip(),
            'theme':self.theme.text().strip(),'theme_role':self.theme_role.text().strip(),
            'ai_thesis':self.ai_thesis.toPlainText().strip(),'buy_zone':self.buy_zone.text().strip(),
            'confirm_trigger':self.confirm_trigger.text().strip(),'invalidation':self.invalidation.text().strip(),
            'hold_reason':self.hold_reason.text().strip(),'add_condition':self.add_condition.text().strip(),
            'reduce_condition':self.reduce_condition.text().strip(),'exit_condition':self.exit_condition.text().strip(),
            'revision_of':self.source.get('decision_id') if self.source else None,
            'reference_decision_id':self.reference.text().strip() or None,
            'effective_at':self.effective_at.text().strip() or None,
            'source':'desktop_manual',
        }

    def save(self):
        try:
            self.saved=self.intent.transition(str(uuid4()),self.payload())
        except DecisionError as exc:
            self.status.setText(f'{exc.code}: {exc}'); return
        self.accept()
