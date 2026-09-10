"""Business forms for the existing corporate-action and reference contracts."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import math
import re
from uuid import uuid4
from PyQt6.QtCore import QDate, QDateTime, QTime, Qt
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QFormLayout,QScrollArea,QGroupBox,
    QLineEdit,QComboBox,QCheckBox,QDateTimeEdit,QDateEdit,QDialogButtonBox,QTableWidgetItem)
from .widgets import label,button,row,table


def field(title,kind='text',default='',optional=False,**extra):
    return dict(title=title,kind=kind,default=default,optional=optional,**extra)


def at(title,optional=False):return field(title+'（北京时间）','time',optional=optional)
def number(title,default=0.,optional=False):return field(title,'number',default,optional)
def integer(title,default=0,optional=False):return field(title,'integer',default,optional)
def group(title,schema,optional=True):return field(title,'group',{},optional,schema=schema)
def records(title,schema,optional=False):return field(title,'records',[],optional,schema=schema)
FRACTION=field('零碎股份处理','choice','reject',choices=[('拒绝含零碎股份的分配','reject'),('向下取整（按明确规则处理余数）','floor')])
INSUFFICIENT=field('资金不足处理','choice','error',choices=[('报错并停止','error'),('跳过本次认购','skip')])
SOURCE=field('资料来源／公告依据')
IDENTITY={'action_id':field('事件编号（可自行命名）'),'symbol':field('证券代码'),'source':SOURCE}
FRACTIONAL={'price':number('每股折现金额（元）'),'tax_rate':number('折现税率（比例）'),'fee':number('折现手续费（元）'),'pay_at':at('折现款支付时间',True)}
BANDS={'months':field('持有不足月数（不设上限表示最后一档）','nullable_integer',None),'rate':number('该档税率（比例）')}
LOTS={'acquired_at':field('买入日期','date'),'quantity':integer('对应股份数量（股）')}
HOLDING={'basis_per_share':number('每股计税基数（元）'),'available_at':at('税制资料可用时间'),'source':SOURCE,'bands':records('持有期税率档位',BANDS),'lots':records('明确持仓批次',LOTS,True)}
ALLOCATION={'shares':integer('最终配售股数'),'at':at('配售生效时间'),'available_at':at('配售资料可用时间'),'refund_at':at('未配售款退款时间'),'fee_refund':number('退回手续费（元）'),'source':SOURCE}
RECOVERY={'shares':integer('回收股份数量'),'missing_share_price':number('不足回收股份每股补偿（元）'),'source':SOURCE}
CANCEL={'cancel_at':at('取消生效时间'),'refund_at':at('退款时间'),'available_at':at('取消资料可用时间'),'fee_refund':number('退回手续费（元）'),'source':SOURCE,'recovery':group('上市后回收安排',RECOVERY)}
EXERCISE={'at':at('行权时间'),'listing_at':at('行权股份上市时间'),'available_at':at('行权资料可用时间'),'rights_quantity':integer('行权权利份数'),'shares_per_right':integer('每份权利取得股数',1),'subscription_price':number('每股认购价格（元）'),'fee':number('行权手续费（元）'),'insufficient_assets':field('权利或资金不足处理','choice','error',choices=INSUFFICIENT['choices']),'source':SOURCE}
SCHEMAS={
 'corporate_actions':{**IDENTITY,'record_at':at('股权登记时间'),'ex_at':at('除权除息时间'),'pay_at':at('分红支付时间'),'available_at':at('公告可用时间'),'cash_per_share':number('每股现金分红（元）'),'tax_rate':number('固定税率（比例）'),
    '_stock':field('同时送股／转增','flat_group',{},True,schema={'stock_per_share':number('每股送转股数'),'list_at':at('送转股份上市时间'),'fractional_policy':FRACTION}),
    'entitlement_quantity':integer('明确登记股份数量（股）',optional=True),'entitled_pending_actions':field('参与本次权益的待上市事件编号（空格分隔）','strings',[],True),
    'fractional_settlement':group('零碎股折现安排',FRACTIONAL),'holding_tax':group('按持有期递延计税（固定税率需为零）',HOLDING)},
 'stock_splits':{**IDENTITY,'effective_at':at('拆并股生效时间'),'available_at':at('公告可用时间'),'numerator':integer('转换后股数（比例分子）',2),'denominator':integer('转换前股数（比例分母）',1),'fractional_policy':FRACTION,
    'fractional_settlement':group('零碎股折现安排',FRACTIONAL),'convert_entitlements':field('同时转换的待上市事件编号（空格分隔）','strings',[],True),
    'entitlement_allocations':field('待上市权益明确分配','mapping',{},True,schema={'reference':field('关联事件编号'),'shares':integer('分配完整股数'),'cash':number('折现金额（元）'),'principal_reduction':number('减少认购本金（元）')})},
 'rights_issues':{**IDENTITY,'record_at':at('股权登记时间'),'subscribe_at':at('认购缴款时间'),'ex_at':at('除权时间'),'list_at':at('配股上市时间'),'available_at':at('公告可用时间'),'numerator':integer('可配股数（比例分子）',1),'denominator':integer('原持股数（比例分母）',10),'subscription_price':number('每股认购价格（元）'),'subscription_shares':integer('本次主动认购股数'),'insufficient_cash':INSUFFICIENT,'fractional_policy':FRACTION,
    'subscription_fee':number('认购手续费（元）',optional=True),'entitlement_quantity':integer('明确登记股份数量（股）',optional=True),'allow_oversubscription':field('允许超额认购','bool',False,True),'allocation':group('最终配售与退款',ALLOCATION),'cancellation':group('取消认购与退款',CANCEL)},
 'rights_trading':{**IDENTITY,'rights_symbol':field('配股权独立证券代码'),'record_at':at('股权登记时间'),'deliver_at':at('配股权交付时间'),'expires_at':at('配股权失效时间'),'available_at':at('公告可用时间'),'numerator':integer('取得权利份数（比例分子）',1),'denominator':integer('原持股数（比例分母）',10),'fractional_policy':FRACTION,'entitlement_quantity':integer('明确登记股份数量（股）',optional=True),'exercise':group('主动行权安排',EXERCISE)},
 'market_rules':{'symbol':field('证券代码'),'effective_at':at('规则生效时间'),'available_at':at('规则可用时间'),'expires_at':at('规则到期时间'),'suspended':field('全天停牌','bool',False),'st':field('ST 股票','bool',False),'limit_up':field('涨停价格（不设限时留空）','nullable_number',None),'limit_down':field('跌停价格（不设限时留空）','nullable_number',None),
    'commission_bps':number('佣金（万分之一）'),'minimum_commission':number('最低佣金（元）'),'sell_tax_bps':number('卖出税费（万分之一）'),'transfer_bps':number('过户费（万分之一）'),'source':SOURCE},
 'industry_events':{'symbol':field('证券代码'),'sector':field('行业名称'),'effective_at':at('行业归属生效时间'),'available_at':at('行业资料可用时间'),'source':SOURCE},
 'size_events':{'symbol':field('证券代码'),'market_cap':number('每日真实市值（统一金额单位）'),'effective_at':at('市值生效时间'),'available_at':at('市值资料可用时间'),'expires_at':at('市值到期时间'),'source':SOURCE},
}


class RecordFields(QWidget):
    def __init__(self,schema,value,parent=None,symbol='',date=None):
        super().__init__(parent);self.schema=schema;self.original=deepcopy(value);self.getters={};self.controls={};self.optional={}
        form=QFormLayout(self);self.date=date or QDate.currentDate();self.symbol=symbol
        for key,s in schema.items():
            title=s['title'];kind=s['kind'];default=s['default']
            if key=='action_id':default='event_'+uuid4().hex[:8]
            if key=='symbol':default=symbol
            value={k:deepcopy(self.original[k]) for k in s['schema'] if k in self.original} if kind=='flat_group' else self.original.get(key,default)
            present=any(k in self.original for k in s.get('schema',{})) if kind=='flat_group' else key in self.original
            if kind in ('group','flat_group'):
                control=RecordFields(s['schema'],value,self,symbol,self.date);getter=control.collect
            elif kind in ('records','mapping'):
                rows=[{'reference':k,**v} for k,v in value.items()] if kind=='mapping' else value
                control=RecordsEditor(s['schema'],rows,title,self,symbol,self.date)
                def get_rows(c=control,mapping=kind=='mapping'):
                    values=c.values()
                    if not mapping:return values
                    result={}
                    for entry in values:
                        ref=entry.pop('reference')
                        if not ref or ref in result:raise ValueError('关联事件编号不能为空或重复')
                        result[ref]=entry
                    return result
                getter=get_rows
            elif kind=='bool':
                control=QCheckBox(title);control.setChecked(value);getter=control.isChecked
            elif kind=='choice':
                control=QComboBox()
                for name,code in s['choices']:control.addItem(name,code)
                index=control.findData(value)
                if index<0:control.addItem('导入的未识别选项：'+str(value),value);index=control.count()-1
                control.setCurrentIndex(index);getter=control.currentData
            elif kind in ('time','date'):
                if kind=='time':
                    control=QDateTimeEdit();control.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
                    parsed=datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))) if value else datetime.combine(self.date.toPyDate(),datetime.min.time()).replace(hour=15)
                    control.setDateTime(QDateTime(QDate(parsed.year,parsed.month,parsed.day),QTime(parsed.hour,parsed.minute,parsed.second)))
                    getter=lambda c=control:c.dateTime().toString('yyyy-MM-ddTHH:mm:ss')+'+08:00'
                else:
                    control=QDateEdit(QDate.fromString(value,'yyyy-MM-dd') if value else self.date);control.setDisplayFormat('yyyy-MM-dd');getter=lambda c=control:c.date().toString('yyyy-MM-dd')
                control.setCalendarPopup(True)
            else:
                text=' '.join(value) if kind=='strings' else '' if value is None else str(value)
                control=QLineEdit(text)
                def read(c=control,k=kind,t=title):
                    text=c.text().strip()
                    if k.startswith('nullable_') and not text:return None
                    if k in ('number','nullable_number'):
                        try:v=float(text)
                        except ValueError:raise ValueError(t+'请填写数字')
                        if not math.isfinite(v):raise ValueError(t+'必须为有限数值')
                        return v
                    if k in ('integer','nullable_integer'):
                        try:return int(text)
                        except ValueError:raise ValueError(t+'请填写整数')
                    if k=='strings':return [v for v in re.split(r'[\s,，]+',text) if v]
                    if not text:raise ValueError(t+'不能为空')
                    return text
                getter=read
            control.setAccessibleName(title);self.controls[key]=control
            # Keep untouched imported precision and timestamp offsets intact.
            if present and kind not in ('group','flat_group','records','mapping'):
                original=deepcopy(self.original[key])
                marker=(control.text() if isinstance(control,QLineEdit) else getter())
                def preserve(c=control,g=getter,v=original,m=marker):
                    displayed=c.text() if isinstance(c,QLineEdit) else g()
                    return deepcopy(v) if displayed==m else g()
                getter=preserve
            self.getters[key]=getter
            if s['optional']:
                box=QGroupBox(title);box.setCheckable(True);box.setChecked(present);layout=QVBoxLayout(box);layout.addWidget(control);control.setVisible(present);box.toggled.connect(control.setVisible);self.optional[key]=box;form.addRow(box)
            else:form.addRow(title if kind!='bool' else '',control)
        for c in self.findChildren(QComboBox):c.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def collect(self):
        result=deepcopy(self.original)
        for key,s in self.schema.items():
            active=key not in self.optional or self.optional[key].isChecked()
            if s['kind']=='flat_group':
                for child in s['schema']:result.pop(child,None)
                if active:result.update(self.getters[key]())
            elif active:result[key]=self.getters[key]()
            else:result.pop(key,None)
        return result


class RecordDialog(QDialog):
    def __init__(self,parent,schema,value,title,symbol='',date=None):
        super().__init__(parent);self.setWindowTitle(title);self.resize(840,740);self.result_value=None
        box=QVBoxLayout(self);box.addWidget(label('按业务字段填写；所有时间为北京时间。比例 0.05 表示 5%。资料来源须真实，未提供的可选安排不作推断。','note',True))
        self.fields=RecordFields(schema,value,self,symbol,date);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.fields);box.addWidget(scroll,1)
        self.status=label('保存后请在外层校验整组记录的时间与关联关系。','muted',True);box.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);controls.accepted.connect(self.finish);controls.rejected.connect(self.reject);box.addWidget(controls)
    def finish(self):
        try:self.result_value=self.fields.collect()
        except (ValueError,TypeError) as error:self.status.setText(str(error));return
        self.accept()


class RecordsEditor(QWidget):
    def __init__(self,schema,values,title,parent=None,symbol='',date=None):
        super().__init__(parent);self.schema=schema;self.title=title;self.symbol=symbol;self.date=date;self._values=deepcopy(values)
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);self.view=table([],[]);self.view.setAccessibleName(title+'记录');box.addWidget(self.view,1)
        box.addWidget(row(button('新增'+title,lambda:self.edit(False)),button('编辑所选记录',lambda:self.edit(True)),button('删除所选记录',self.remove)))
        self.view.cellDoubleClicked.connect(lambda *_:self.edit(True));self.refresh()
    def values(self):return deepcopy(self._values)
    def toPlainText(self):return json.dumps(self._values,ensure_ascii=False)
    def setPlainText(self,text):
        value=json.loads(text)
        if not isinstance(value,list) or any(not isinstance(r,dict) for r in value):raise ValueError(self.title+'必须为记录列表')
        self._values=value;self.refresh()
    def refresh(self):
        keys=[k for k,s in self.schema.items() if s['kind'] not in ('group','flat_group','records','mapping','strings')][:6]
        self.view.setColumnCount(len(keys));self.view.setHorizontalHeaderLabels([self.schema[k]['title'] for k in keys]);self.view.setRowCount(len(self._values))
        for i,entry in enumerate(self._values):
            for j,key in enumerate(keys):
                value=entry.get(key);text='未设置' if value is None else '是' if value is True else '否' if value is False else str(value)
                if value and self.schema[key]['kind']=='time':
                    text=datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                item=QTableWidgetItem(text);item.setToolTip(str(value) if value is not None else '未设置');self.view.setItem(i,j,item)
    def edit(self,existing):
        index=self.view.currentRow()
        if existing and index<0:return
        value=self._values[index] if existing else {}
        dialog=RecordDialog(self,self.schema,value,('编辑' if existing else '新增')+self.title,self.symbol,self.date)
        if dialog.exec():
            if existing:self._values[index]=dialog.result_value
            else:self._values.append(dialog.result_value)
            self.refresh();self.view.selectRow(index if existing else len(self._values)-1)
    def remove(self):
        index=self.view.currentRow()
        if index>=0:self._values.pop(index);self.refresh()


class RecordsDialog(QDialog):
    def __init__(self,parent,key,values,title,validator):
        super().__init__(parent);self.setWindowTitle(title);self.resize(1000,740);self.result_value=None;self.validator=validator
        box=QVBoxLayout(self);box.addWidget(label('维护明确的历史资料；不把当前行业或季度股本自动当作历史已知的每日资料。','note',True))
        self.editor=RecordsEditor(SCHEMAS[key],values or [],title,self);box.addWidget(self.editor,1)
        box.addWidget(button('导入已有资料文件',self.import_records));self.status=label('保存时检查时间、来源和记录格式。','muted',True);box.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);controls.accepted.connect(self.finish);controls.rejected.connect(self.reject);box.addWidget(controls)
    def import_records(self):
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path
        from quantlab.storage.codec import encode
        path,_=QFileDialog.getOpenFileName(self,'选择已有历史资料','','资料文件 (*.json *.parquet)')
        if not path:return
        try:
            if path.endswith('.parquet'):
                import polars as pl
                values=json.loads(encode(pl.read_parquet(path).to_dicts()))
            else:values=json.loads(Path(path).read_text())
            self.validator(values);self.editor.setPlainText(json.dumps(values,ensure_ascii=False));self.status.setText(f'已导入 {len(values)} 条；尚未应用。')
        except (ValueError,TypeError,KeyError,OSError) as error:self.status.setText('资料未通过：'+str(error))
    def finish(self):
        try:self.result_value=self.editor.values();self.validator(self.result_value)
        except (ValueError,TypeError,KeyError) as error:self.status.setText('资料未通过：'+str(error));return
        self.accept()
