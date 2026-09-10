"""Native company-action configuration and complete paginated ledger."""
import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QTabWidget,QPlainTextEdit,QWidget,QHeaderView,QDoubleSpinBox,QComboBox
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode
from .widgets import label,button,row,table,raw
from .action_editor import RecordsEditor,SCHEMAS


def configure_actions(parent):
    account_mode=parent.price_mode.currentData()=='account'
    dialog=QDialog(parent);dialog.setWindowTitle('公司行动与费用配置' if account_mode else '历史费用规则');dialog.resize(1000,760)
    layout=QVBoxLayout(dialog)
    layout.addWidget(label('按证券及公告配置事件；记录时间须含时区，来源与可用时间须明确。系统不会自动把当前规则回填到历史。' if account_mode else '研究回测直接使用所选复权价格，不重复处理公司行动。此处可配置有明确生效日期的历史交易费用；常规手续费与滑点保留在实验扩展配置中。','note',True))
    tabs=QTabWidget();layout.addWidget(tabs,1);editors={}
    try:
        original=json.loads(parent.advanced.toPlainText())
        if not isinstance(original,dict):raise ValueError('扩展配置必须为对象')
        execution=original.get('execution',{})
        if not isinstance(execution,dict):raise ValueError('execution 必须为对象')
        execution={**execution,'price_mode':parent.price_mode.currentData()}
    except (ValueError,TypeError) as error:parent.status.setText(str(error));return
    for key,title in [('corporate_actions','现金分红／送转及持有期税'),('stock_splits','拆并股及待上市权益'),('rights_issues','配股认购／配售／退款'),('rights_trading','可转让配股权'),('market_rules','历史交易费用与规则')]:
        if execution['price_mode']=='research' and key!='market_rules':continue
        page=QWidget();box=QVBoxLayout(page)
        box.addWidget(label('通过新增、编辑和删除维护记录；可选安排展开后填写。导入的其他实验配置保持不变。','muted',True))
        symbols=parent.symbols.text().replace(',',' ').replace('，',' ').split()
        editor=RecordsEditor(SCHEMAS[key],original.get(key,[]) if key=='market_rules' else execution.get(key,[]) or [],title,page,symbols[0] if symbols else '',parent.start.date())
        editor.setAccessibleName(title+'配置');box.addWidget(editor,1);editors[key]=editor;tabs.addTab(page,title)
    status=label('修改后先校验；取消不会改变原实验。','muted',True);layout.addWidget(status)
    mode=QComboBox();mode.addItem('严格历史可用时间','strict');mode.addItem('回顾性资料（不能证明当时可知）','retrospective');mode.setCurrentIndex(mode.findData(execution.get('corporate_action_mode','strict')))
    tax_rate=QDoubleSpinBox();tax_rate.setRange(0.,1.);tax_rate.setDecimals(4);tax_rate.setSingleStep(.01);tax_rate.setAccessibleName('导入分红固定税率')
    from .business_view import BusinessDetails
    import_report=BusinessDetails({});import_report.setAccessibleName('公司行动导入检查')
    if execution['price_mode']=='account':tabs.addTab(import_report,'导入来源／未解析记录')
    def import_history():
        from quantlab.data.dividends import import_cash_dividends
        import re
        symbols=[v for v in re.split(r'[\s,，]+',parent.symbols.text().strip()) if v]
        if not symbols:status.setText('先在实验表单填写证券代码。');return
        import_button.setEnabled(False);status.setText('正在只读导入分红和送转资料…')
        rate=tax_rate.value()
        def done(value,error):
            import_button.setEnabled(True)
            if not dialog.isVisible():return
            if error:status.setText(error);return
            import_report.setPlainText(encode(value))
            try:
                current=json.loads(editors['corporate_actions'].toPlainText())
                if not isinstance(current,list):raise ValueError('现金／送转页必须为数组')
                known={r['action_id'] for r in current};added=[r for r in value['corporate_actions'] if r['action_id'] not in known]
                editors['corporate_actions'].setPlainText(encode(current+added));mode.setCurrentIndex(mode.findData('retrospective'))
                status.setText(f"新增 {len(added)} 条，未解析 {len(value['unresolved'])} 条。已切换回顾性口径；固定税率 {rate:.2%} 为本次指定假设，请审核来源页。")
            except (ValueError,KeyError,TypeError) as exc:status.setText(str(exc))
        parent.window.async_call(lambda:import_cash_dividends(parent.window.data_root,symbols,rate,include_stock=True),done,guarded=False)
    import_button=button('导入本地分红／送转（回顾性）',import_history);import_button.setEnabled(bool(parent.window.data_root))
    if execution['price_mode']=='account':layout.addWidget(row(label('事件时间口径'),mode,label('导入固定税率'),tax_rate,import_button))
    def collect():
        updated={**original};config={**execution}
        for key,editor in editors.items():
            value=json.loads(editor.toPlainText())
            if not isinstance(value,list):raise ValueError(key+' 必须为数组')
            if key=='market_rules':
                if value:MarketRules(value);updated[key]=value
                else:updated.pop(key,None)
            else:config[key]=value or None
        config['corporate_action_mode']=mode.currentData();validated=ExecutionConfig(**config)
        validated.validate_price_inputs(MarketRules(updated['market_rules']) if updated.get('market_rules') else None);updated['execution']=config
        return updated
    def validate():
        try:collect();status.setText('配置校验通过；未执行回测。');return True
        except (ValueError,TypeError,KeyError) as error:status.setText('配置未通过：'+str(error));return False
    def apply():
        if validate():parent.advanced.setPlainText(encode(collect()));dialog.accept()
    layout.addWidget(row(button('校验公司行动与费用' if account_mode else '校验费用规则',validate),button('应用到本次实验',apply,True),button('取消',dialog.reject)))
    try:dialog.exec()
    finally:parent.raise_();parent.activateWindow()


def action_ledger(execution,preview=False,load_full=None):
    page=QWidget();layout=QVBoxLayout(page)
    notice=label('金额单位：元；股份单位：股。应收尚未到账，应付税款尚未扣收。选择流水查看完整数量、时点与来源。','note',True);layout.addWidget(notice)
    status=label('','muted',True);layout.addWidget(status)
    from .business_view import BusinessDetails
    holder={'events':[],'offset':0,'table':None};details=BusinessDetails({});details.setAccessibleName('公司行动明细')
    controls=row();layout.addWidget(controls)
    grid=QWidget();grid_layout=QVBoxLayout(grid);grid_layout.setContentsMargins(0,0,0,0);layout.addWidget(grid,3);layout.addWidget(details,2)
    names={'dividend_accrual':'分红应收确认','dividend_payment':'分红到账','stock_accrual':'送转待上市','stock_listing':'送转上市','fractional_accrual':'零碎股应收确认','fractional_payment':'零碎股款到账',
        'stock_split':'拆并股结算','split_cash_payment':'并股折现款到账','rights_subscription':'配股认购','rights_ex':'配股除权待上市','rights_listing':'配股上市','rights_cancellation':'配股取消／回收','rights_refund':'配股退款／补偿',
        'rights_allocation':'配股配售结果','rights_allocation_refund':'未配售款退款','tradable_rights_delivery':'配股权交付','tradable_rights_exercise':'配股权行权','tradable_rights_listing':'行权股份上市','tradable_rights_expiry':'配股权到期失效',
        'dividend_tax_assessment':'持有期税确认','dividend_tax_payment':'持有期税扣收'}
    def render():
        events=holder['events'];offset=holder['offset'];selected=events[offset:offset+100];rows=[]
        separate={e['action_id'] for e in events if e['kind']=='fractional_accrual'}
        for e in selected:
            kind=e['kind'];fee=e.get('fee',0.)
            if kind=='dividend_accrual':fee+=e.get('tax',0.)
            if kind in ('stock_split','fractional_accrual') or (kind=='dividend_accrual' and e['action_id'] not in separate):fee+=e.get('fractional_fee',0.)+e.get('fractional_tax',0.)
            if kind in ('rights_cancellation','rights_allocation'):fee-=e.get('fee_refund',0.)
            if kind=='dividend_tax_assessment':fee+=e.get('tax',0.)
            instrument=e.get('rights_symbol') if e.get('rights_position_delta',0) else e.get('symbol')
            rows.append([str(e.get('at',''))[:19].replace('T',' '),names.get(kind,kind),instrument,e.get('position_delta',0),e.get('pending_share_delta',0),e.get('rights_position_delta',0),
                f"{e.get('cash_delta',0.):+,.2f}",f"{e.get('receivable_delta',0.)+e.get('prepaid_delta',0.):+,.2f}",f"{e.get('payable_delta',0.):+,.2f}",f"{fee:+,.2f}"])
        old=holder['table']
        if old:grid_layout.removeWidget(old);old.deleteLater()
        view=table(['时间','事件','证券','持仓变动','待上市变动','权利变动','现金变动','应收变动','应付税变动','税费／返还'],rows);view.setAccessibleName('公司行动账本')
        view.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        view.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        for i,e in enumerate(selected):
            view.item(i,0).setToolTip(str(e.get('at','')))
            for j in range(3,10):view.item(i,j).setTextAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        view.itemSelectionChanged.connect(lambda:details.setPlainText(encode(selected[view.currentRow()])) if view.currentRow()>=0 else None)
        holder['table']=view;grid_layout.addWidget(view)
        # Populate details without emitting selection accessibility events while
        # this table is still inside a hidden tab on macOS.
        if selected:details.setPlainText(encode(selected[0]))
        else:details.setPlainText('没有公司行动事件。')
        previous.setEnabled(offset>0);following.setEnabled(offset+100<len(events))
        status.setText(('摘要预览；载入完整账本后可查看全部事件。 ' if holder.get('preview') else '完整账本。 ')+f"{offset+1 if events else 0}–{min(offset+100,len(events))} / {len(events)}")
    def move(delta):holder['offset']=max(0,holder['offset']+delta);render()
    previous=button('上一页',lambda:move(-100));following=button('下一页',lambda:move(100));controls.layout().addWidget(previous);controls.layout().addWidget(following)
    def populate(value,is_preview=False):
        events=[]
        for priority,key in enumerate(('split_ledger','corporate_action_ledger','rights_ledger','rights_trading_ledger','dividend_tax_ledger')):
            events.extend((entry,priority,i) for i,entry in enumerate(value.get(key,[])))
        events.sort(key=lambda v:(str(v[0].get('at','')),v[1],v[2]));holder.update(events=[e for e,_,_ in events],offset=0,preview=is_preview);render()
    if preview and load_full:
        def load():
            full.setEnabled(False);status.setText('正在读取完整账本…')
            def done(value,error):
                full.setEnabled(True)
                if error:status.setText('读取失败：'+error);return
                populate(value);full.hide()
            load_full(done)
        full=button('载入完整公司行动账本',load);controls.layout().addWidget(full)
    controls.layout().addStretch();populate(execution,preview)
    return page
