"""Readable, paginated archived fills and rejection reasons."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QTabWidget,QLineEdit,QTableWidgetItem,QHeaderView
from .widgets import label,button,row,table,fmt

REASONS={'missing_market_rule':'缺少当时可用的交易规则','suspended':'停牌','st_buy_blocked':'禁止买入 ST',
    'session_price_limit':'触及当日涨跌停价','configured_price_limit':'触及配置涨跌幅',
    'lagged_volume_capacity':'超过滞后成交量容量','unknown_industry':'缺少当时行业资料',
    'pending_stock_or_t_plus_one':'股份待到账或 T+1 限制','actual_position_or_exposure_cap':'实际单股仓位或总敞口受限',
    'cash_lot_or_actual_risk':'资金、整手或实际风控受限','actual_sector_cap':'实际行业仓位受限',
    'cash_for_sell_fees':'卖出费用资金不足','rights_outside_trading_lifetime':'配股权不在交易有效期'}


class TradeLedger(QWidget):
    PAGE_SIZE=200

    def __init__(self,record,loader):
        super().__init__();self.record=record;self.loader=loader;self.page=0
        self.complete=not bool(record.get('_display_summary'));self.filtered=[]
        box=QVBoxLayout(self)
        self.status=label('','muted',True);box.addWidget(self.status)
        self.load_button=button('载入全部成交与拒单',self.load);box.addWidget(self.load_button)
        self.symbol=QLineEdit();self.symbol.setPlaceholderText('筛选证券代码，如 sz.002099');self.symbol.setAccessibleName('成交证券筛选')
        box.addWidget(self.symbol)
        self.tabs=QTabWidget();box.addWidget(self.tabs,1)
        self.fills=table(['成交时间','证券','方向','股数','价格','佣金','卖出税费','过户费','滑点成本'],[])
        self.rejections=table(['时间','证券','方向','申请股数','成交股数','未完全成交原因'],[])
        for title,control in [('成交账本',self.fills),('拒单与部分成交',self.rejections)]:
            control.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            control.horizontalHeader().setStretchLastSection(True)
            control.setColumnWidth(0,200);control.setColumnWidth(1,105);self.tabs.addTab(control,title)
        self.previous=button('上一页',lambda:self.turn(-1));self.next=button('下一页',lambda:self.turn(1));self.page_label=label()
        box.addWidget(row(self.previous,self.page_label,self.next))
        self.symbol.textChanged.connect(self.reset);self.tabs.currentChanged.connect(self.reset);self.render()

    def load(self):
        self.load_button.setEnabled(False);self.status.setText('正在读取完整账本…')
        def done(value,error):
            self.load_button.setEnabled(True)
            if error:self.status.setText('读取失败：'+str(error));return
            self.record={**self.record,**value};self.complete=True;self.reset()
        self.loader(done)

    def reset(self,*args):self.page=0;self.render()
    def turn(self,step):self.page+=step;self.render()

    def render(self):
        key='fills' if self.tabs.currentIndex()==0 else 'rejections';control=self.fills if key=='fills' else self.rejections
        query=self.symbol.text().strip().lower();self.filtered=[r for r in self.record.get(key,[]) if query in r.get('symbol','').lower()]
        pages=max(1,(len(self.filtered)+self.PAGE_SIZE-1)//self.PAGE_SIZE);self.page=max(0,min(self.page,pages-1))
        records=self.filtered[self.page*self.PAGE_SIZE:(self.page+1)*self.PAGE_SIZE];control.setRowCount(len(records))
        fields=('filled_at','symbol','side','quantity','price','commission','tax','transfer_fee','slippage_cost') if key=='fills' else ('at','symbol','side','requested','filled','reason')
        for i,record in enumerate(records):
            for j,field in enumerate(fields):
                value=record.get(field);original=str(value) if value is not None else '—'
                if field=='side':value={'buy':'买入','sell':'卖出'}.get(value,value)
                elif field=='reason':value=REASONS.get(value,value)
                elif field in ('at','filled_at') and value:value=str(value).replace('T',' ')
                elif isinstance(value,float):value=f'{value:,.6f}' if field=='price' else f'{value:,.2f}'
                cell=QTableWidgetItem(fmt(value));cell.setToolTip(original);control.setItem(i,j,cell)
        self.previous.setEnabled(self.page>0);self.next.setEnabled(self.page+1<pages)
        self.page_label.setText(f'第 {self.page+1} / {pages} 页 · 当前筛选 {len(self.filtered)} 条')
        self.load_button.setVisible(not self.complete)
        counts=self.record.get('_display_summary',{}).get('counts',{})
        nf=len(self.record.get('fills',[])) if self.complete else counts.get('/fills',len(self.record.get('fills',[])))
        nr=len(self.record.get('rejections',[])) if self.complete else counts.get('/rejections',len(self.record.get('rejections',[])))
        self.status.setText(f'归档成交 {nf} 笔，拒单或部分成交 {nr} 次。'+('全部记录已载入，按页浏览。' if self.complete else '当前仅为预览；载入全部后可筛选完整账本。'))
