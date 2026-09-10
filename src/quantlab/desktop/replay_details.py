"""Paged business evidence for exactly the replay cursor's known information."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QTableWidgetItem
from .widgets import table,label,button,row,fmt


class ReplayDetails(QWidget):
    def __init__(self,names=None):
        super().__init__();self.names=names or {};self.items=[];self.page=0
        box=QVBoxLayout(self);self.table=table(['类型','可用 / 成交时间','名称','方向','价格 / 区间','说明'],[]);box.addWidget(self.table,1)
        self.previous=button('上一页',lambda:self.move(-1));self.next=button('下一页',lambda:self.move(1));self.status=label()
        box.addWidget(row(self.previous,self.status,self.next));self.render()

    def set_data(self,data):
        names={'pivot_high':'顶分型','pivot_low':'底分型','bi_up':'向上笔','bi_down':'向下笔','segment_up':'向上线段','segment_down':'向下线段',
            'center':'中枢','higher_center':'递归中枢','chan_multiscale_segment':'实际周期已确认线段'}
        states={'added':'新出现','revised':'结构修订','removed':'结构移除','nested':'嵌套已连接','unlinked':'嵌套失效',
            'active':'有效','completed':'完成','invalidated':'失效','expired':'到期','timeout':'超时','created':'形成','touched':'触及','filled':'已回补'}
        items=[]
        for key,title in [('structures','结构'),('events','事件'),('zones','区域'),('fills','成交')]:
            for item in data.get(key,[]):
                meta=item.get('metadata',{});kind=item.get('kind','');name=self.names.get(item.get('factor_id'),names.get(kind,kind or ('价格区域' if key=='zones' else item.get('symbol','事件'))))
                if kind=='chan_multiscale_segment':name=item.get('timeframe','')+' · '+name
                low=item.get('lower',item.get('lower_price',meta.get('lower')));high=item.get('upper',item.get('upper_price',meta.get('upper')))
                price=f'{fmt(low)} – {fmt(high)}' if low is not None and high is not None else fmt(item.get('price',meta.get('price')))
                stamp=item.get('filled_at',item.get('available_at',''));direction={'buy':'买入','sell':'卖出',1:'向上',-1:'向下',0:'—'}.get(item.get('side',item.get('direction',0)),'—')
                note=states.get(meta.get('status'),meta.get('status',''))
                if key=='fills':note=f"{item.get('quantity',0)} 股 · 佣金 {fmt(item.get('commission'))}"
                if kind=='chan_multiscale_segment':note=str(item.get('start_at',''))+' 至 '+str(item.get('end_at',''))
                items.append([title,str(stamp),name,direction,price,note])
        self.items=sorted(items,key=lambda r:r[1],reverse=True);self.page=0;self.render()

    def move(self,delta):self.page+=delta;self.render()

    def render(self):
        pages=max(1,(len(self.items)+99)//100);self.page=max(0,min(self.page,pages-1));items=self.items[self.page*100:(self.page+1)*100]
        self.table.setRowCount(len(items))
        for i,values in enumerate(items):
            for j,value in enumerate(values):
                text=str(value);cell=QTableWidgetItem(text.replace('T',' ')[:19] if j==1 else text);cell.setToolTip(text);self.table.setItem(i,j,cell)
        self.previous.setEnabled(self.page>0);self.next.setEnabled(self.page+1<pages)
        self.status.setText(f'截至回放时刻已知 {len(self.items)} 条 · 第 {self.page+1} / {pages} 页')
