"""Decision Frame policy and cross-round review UI."""
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDateEdit,QDialog,QFormLayout,QLineEdit,QVBoxLayout

from quantlab.trading.decision_frames import compare_intraday
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.frame_policy import FramePolicyStore
from .widgets import button,label,row,table


class FrameComparisonDialog(QDialog):
    def __init__(self,window,symbol='',trading_day=''):
        super().__init__(window);self.window=window;self.store=DecisionStore(window.output)
        self.setWindowTitle('Decision 跨轮对比');self.resize(1100,720)
        box=QVBoxLayout(self);self.symbol=QLineEdit(symbol);self.symbol.setPlaceholderText('sh.600000')
        self.day=QDateEdit();self.day.setCalendarPopup(True);self.day.setDate(QDate.fromString(trading_day,'yyyy-MM-dd') if trading_day else QDate.currentDate())
        box.addWidget(row(self.symbol,self.day,button('刷新',self.reload,True)))
        self.notice=label('缺失 Frame 保持 missing；不会拿后续判断回填旧轮次。','note',True);box.addWidget(self.notice)
        self.holder=QVBoxLayout();box.addLayout(self.holder);self.reload()

    def reload(self):
        while self.holder.count():
            item=self.holder.takeAt(0)
            if item.widget():item.widget().deleteLater()
        symbol=self.symbol.text().strip().lower();day=self.day.date().toString('yyyy-MM-dd')
        try:report=compare_intraday(self.store,symbol,day)
        except Exception as exc:self.notice.setText(str(exc));return
        rows=[]
        for item in report['rows']:
            d=item['decision'] or {}
            action_change=(item['changes'].get('action') or {})
            rows.append([item['frame'],item['status'],d.get('action','—'),d.get('theme','—'),d.get('submission_status','legacy'),
                '是' if action_change.get('changed') else '否',d.get('ai_thesis','')[:90]])
        self.holder.addWidget(table(['Frame','状态','动作','主题','提交状态','动作变化','当时判断'],rows),1)
        self.notice.setText(report['policy'])


class FramePolicyDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.store=FramePolicyStore(window.output);self.policy=self.store.load()
        self.setWindowTitle('Decision Frame Policy');self.resize(640,520)
        outer=QVBoxLayout(self);form=QFormLayout();outer.addLayout(form)
        self.version=QLineEdit(self.policy['version']);form.addRow('Policy version',self.version)
        self.timezone=QLineEdit(self.policy['timezone']);form.addRow('Timezone',self.timezone)
        self.controls={}
        for frame in ('PREP','AUCTION','R1','R2','R3'):
            spec=self.policy['windows'][frame];start=QLineEdit(spec['start']);end=QLineEdit(spec['end'])
            self.controls[frame]=(start,end);form.addRow(frame+' 开始 / 结束',row(start,end))
        outer.addWidget(label('这是牛牛自己的研究/决策 Frame，不是交易所官方规则。修改时间窗口时必须同时更换 policy version。','note',True))
        self.status=label('','muted',True);outer.addWidget(self.status)
        outer.addWidget(row(button('保存 Policy',self.save,True),button('取消',self.reject)))

    def save(self):
        policy={'version':self.version.text().strip(),'timezone':self.timezone.text().strip(),'windows':{k:(dict(v) if v else None) for k,v in self.policy['windows'].items()}}
        for frame,(start,end) in self.controls.items():
            policy['windows'][frame]['start']=start.text().strip();policy['windows'][frame]['end']=end.text().strip()
        try:self.store.save(policy)
        except Exception as exc:self.status.setText(str(exc));return
        self.accept()
