"""Native widgets matching the supplied Niuniu desktop design."""
import json
import math
from pathlib import Path
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QPainterPath
from PyQt6.QtWidgets import (QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QPlainTextEdit,
    QWidget, QSizePolicy)
from quantlab.storage.codec import encode

ASSETS = Path(__file__).parent / 'assets'
STYLE = '''
QWidget { background: #071019; color: #edf4fb; font-family: "PingFang SC"; font-size: 13px; }
QFrame#sidebar { background:#08151e; border-right:1px solid #23384a; }
QFrame#topbar { background:#09151e; border-bottom:1px solid #23384a; }
QFrame#card { background:#0d1a25; border:1px solid #23384a; border-radius:8px; }
QFrame#card QLabel,QFrame#card QWidget#transparent { background:transparent; }
QLabel { background:transparent; border:0; }
QLabel#heroTitle { font-size:28px; font-weight:700; font-family:"Kaiti SC"; }
QLabel#brand { font-size:29px; font-weight:700; font-family:"Kaiti SC"; }
QLabel#muted { color:#8fa4b7; font-size:12px; }
QLabel#gold { color:#f6b72f; }
QLabel#stat { font-size:29px; font-weight:700; }
QLabel#panelTitle { font-size:16px; font-weight:600; }
QLabel#note { color:#d8b978; background:#191f22; border-left:3px solid #f6b72f; padding:10px; }
QPushButton { background:#10212e; border:1px solid #294355; border-radius:6px; padding:8px 13px; min-height:20px; }
QPushButton:hover { background:#192b35; border-color:#aa8129; }
QPushButton:focus,QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QTableWidget:focus { border:1px solid #f6b72f; }
QPushButton:disabled { color:#607382; background:#0a1720; }
QPushButton#primary { color:#1f1b10; background:#f6b72f; border-color:#f6b72f; font-weight:600; }
QPushButton#nav { text-align:left; background:transparent; border:1px solid transparent; padding:12px 18px; font-size:16px; font-family:"Kaiti SC"; color:#adc1d1; }
QPushButton#nav:checked { color:#ffcc55; background:#29291f; border:1px solid #574923; border-left:4px solid #f6b72f; font-weight:700; }
QPushButton#nav:hover { background:#14242f; }
QPushButton#link { background:transparent; border:0; color:#8fa4b7; padding:0; }
QLineEdit,QComboBox,QDateEdit,QDateTimeEdit,QSpinBox,QDoubleSpinBox { background:#0b1a26; border:1px solid #294355; border-radius:5px; padding:8px; min-height:20px; selection-background-color:#846523; }
QComboBox QAbstractItemView { background:#10212e; selection-background-color:#3c3521; color:#edf4fb; }
QPlainTextEdit,QTextBrowser { background:#0a1721; border:1px solid #23384a; border-radius:6px; padding:10px; selection-background-color:#725924; }
QTableWidget { background:#0c1a24; alternate-background-color:#0e1e2b; border:0; gridline-color:#203343; selection-background-color:#34321f; selection-color:#ffda80; }
QTableWidget::item { padding:7px; border-bottom:1px solid #1e3342; }
QHeaderView::section { background:#0d1b27; color:#8fa4b7; padding:10px 8px; border:0; border-bottom:1px solid #23384a; font-size:12px; }
QTableCornerButton::section { background:#0d1b27; border:0; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#08151e; width:8px; margin:0; }
QScrollBar::handle:vertical { background:#29404e; min-height:25px; border-radius:4px; }
QScrollBar:horizontal { background:#08151e; height:8px; }
QScrollBar::handle:horizontal { background:#29404e; min-width:25px; }
QScrollBar::add-line,QScrollBar::sub-line { width:0; height:0; }
QTabWidget::pane { border:1px solid #23384a; background:#0d1a25; }
QTabBar::tab { background:#10212e; padding:10px 16px; color:#9eb2c2; }
QTabBar::tab:selected { color:#f6b72f; border-bottom:2px solid #f6b72f; }
QSplitter::handle { background:#152a38; }
QCheckBox { spacing:8px; background:transparent; }
QToolTip { color:#edf4fb; background:#152a38; border:1px solid #486077; }
'''


def label(text='', name='', wrap=False):
    w = QLabel(str(text)); w.setObjectName(name); w.setWordWrap(wrap)
    w.setTextFormat(Qt.TextFormat.PlainText)
    return w


def button(text, callback, primary=False):
    w = QPushButton(text)
    # Editing a field must not invoke the first unrelated action on Return.
    # Explicit dialog acceptance remains owned by its QDialogButtonBox.
    w.setAutoDefault(False)
    if primary: w.setObjectName('primary')
    w.clicked.connect(lambda checked=False: callback())
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    return w


def row(*widgets, spacing=12):
    w = QWidget(); w.setObjectName('transparent'); box = QHBoxLayout(w)
    box.setContentsMargins(0,0,0,0); box.setSpacing(spacing)
    for item in widgets: box.addWidget(item)
    return w


class Card(QFrame):
    def __init__(self, title='', action=None):
        super().__init__(); self.setObjectName('card')
        self.body = QVBoxLayout(self); self.body.setContentsMargins(16,14,16,16); self.body.setSpacing(12)
        if title:
            heading = row(label(title,'panelTitle'))
            heading.layout().setStretch(0,1)
            if action:
                more=button('›',action);more.setObjectName('link');more.setFixedWidth(24)
                more.setAccessibleName('打开'+title);heading.layout().addWidget(more)
            self.body.addWidget(heading)
    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch); return widget


def hero(title, subtitle):
    w = QWidget(); w.setObjectName('transparent'); box = QHBoxLayout(w); box.setContentsMargins(0,0,0,0)
    text = QWidget(); text.setObjectName('transparent'); v = QVBoxLayout(text); v.setContentsMargins(0,0,0,0)
    v.addWidget(label(title,'heroTitle')); v.addWidget(label(subtitle,'muted',True))
    box.addWidget(text,1)
    motto = label('先研究，再策略\n先因子，再模型','gold'); box.addWidget(motto)
    art = label(); art.setPixmap(QPixmap(str(ASSETS/'niuniu_mascot.png')).scaled(125,92,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    box.addWidget(art); w.setMinimumHeight(90)
    return w


def kpis(items):
    cards=[]
    for i,(title,value,caption) in enumerate(items):
        c=Card(); c.setMinimumHeight(108)
        icon=label(['▥','≡','↗','⌘','⇢','◎'][i%6],'gold'); icon.setFixedWidth(38)
        icon.setStyleSheet('font-size:26px; color:'+['#f6b72f','#9c78ff','#22d787','#4e96ff'][i%4]+';')
        info=QWidget(); info.setObjectName('transparent'); v=QVBoxLayout(info); v.setContentsMargins(0,0,0,0);v.setSpacing(3)
        v.addWidget(label(title,'muted')); v.addWidget(label(value,'stat'));v.addWidget(label(caption,'muted',True)); c.add(row(icon,info));cards.append(c)
    return row(*cards)


def fmt(value):
    if value is None: return '—'
    if isinstance(value,bool):return '是' if value else '否'
    if isinstance(value,float): return f'{value:.6g}' if math.isfinite(value) else '—'
    if isinstance(value,(dict,list,tuple)): return encode(value)
    return {'completed':'已完成','failed':'失败','running':'运行中','queued':'排队中'}.get(str(value),str(value))


def table(headers, rows, activate=None):
    w=QTableWidget(len(rows),len(headers));w.setHorizontalHeaderLabels(headers)
    w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.setShowGrid(False);w.verticalHeader().hide();w.verticalHeader().setDefaultSectionSize(39)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    w.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
    w.horizontalHeader().setMinimumSectionSize(70)
    for i,values in enumerate(rows):
        for j,value in enumerate(values):
            item=QTableWidgetItem(fmt(value));item.setToolTip(fmt(value));w.setItem(i,j,item)
            if value in ('completed','已完成'):item.setForeground(QColor('#22d787'))
            elif value in ('failed','失败'):item.setForeground(QColor('#f35f62'))
    if activate:w.cellDoubleClicked.connect(lambda r,c:activate(r))
    w.setMinimumHeight(170)
    return w


def raw(value):
    w=QPlainTextEdit(); w.setReadOnly(True)
    w.setPlainText(json.dumps(json.loads(encode(value)),ensure_ascii=False,indent=2)); return w


def execution_table(execution):
    fields={
        'initial_cash':('初始资金（元）',',.2f'),
        'final_equity':('期末权益（元）',',.2f'),
        'net_return':('净收益率','.4%'),
        'max_drawdown':('最大回撤','.4%'),
        'sharpe':('Sharpe（日收益，252 日年化）','.4f'),
        'annualized_volatility':('年化波动率','.4%'),
        'annualized_return':('年化收益率','.4%'),
        'fills':('成交笔数',None),
        'rejections':('拒单次数',None),
        'commission':('佣金（元）',',.2f'),
        'sell_tax':('卖出税费（元）',',.2f'),
        'slippage_cost':('滑点成本（元）',',.2f'),
        'transfer_fee':('过户费（元）',',.2f'),
        'split_receivable':('待到账拆并股折现（元）',',.2f'),
        'dividend_tax_payable':('待扣持有期税（元）',',.2f'),
        'dividend_tax':('已确认持有期税（元）',',.2f'),
        'dividend_receivable':('应收分红及零碎股折现（元）',',.2f'),
        'subscription_receivable':('认购预付款及待退款（元）',',.2f'),
        'dividend_cash':('分红及零碎股累计到账（元）',',.2f'),
        'unprocessed_target_snapshots':('未处理目标快照数',None),
    }
    keys=[k for k in dict.fromkeys([*fields,*execution]) if k in execution and not isinstance(execution[k],(list,dict))]
    rows=[]
    for key in keys:
        name,pattern=fields.get(key,(key,None));value=execution[key]
        shown=format(value,pattern) if pattern and isinstance(value,(int,float)) and math.isfinite(value) else fmt(value)
        rows.append([name,shown])
    result=table(['指标','归档值（格式化）'],rows)
    for index,key in enumerate(keys):
        result.item(index,1).setToolTip(f'{key} = {execution[key]}')
    return result


class Flow(QWidget):
    def __init__(self,nodes):
        super().__init__();self.nodes=nodes;self.setMinimumHeight(185);self.setMinimumWidth(450)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap=25; count=max(1,len(self.nodes)); width=(self.width()-gap*(count-1)-8)/count
        for i,(title,sub) in enumerate(self.nodes):
            x=4+i*(width+gap); rect=QRectF(x,14,width,min(self.height()-28,180))
            p.setPen(QColor('#7b6227' if i>=count-2 else '#294355'));p.setBrush(QColor('#10222e'));p.drawRoundedRect(rect,7,7)
            p.setPen(QColor('#edf4fb'));font=p.font();font.setPixelSize(12);font.setBold(True);p.setFont(font)
            p.drawText(rect.adjusted(9,12,-8,-30),Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap,title)
            p.setPen(QColor('#8fa4b7'));font.setPixelSize(11);font.setBold(False);p.setFont(font)
            p.drawText(rect.adjusted(9,65,-8,-10),Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap,sub)
            if i<count-1:
                p.setPen(QPen(QColor('#f6b72f'),1.5));y=rect.center().y();end=x+width+gap-5
                p.drawLine(QPointF(x+width+4,y),QPointF(end,y));p.drawLine(QPointF(end-5,y-4),QPointF(end,y));p.drawLine(QPointF(end-5,y+4),QPointF(end,y))


class Chart(QWidget):
    """Painter-based chart; accepts archived values only, never generated prices."""
    def __init__(self, values=None, candles=None):
        super().__init__();self.values=values or [];self.candles=candles or [];self.overlays={};self.show_overlays=True;self.setMinimumHeight(240)
    @staticmethod
    def axis(source):
        lo,hi=min(source),max(source)
        if lo==hi:
            padding=max(abs(hi)*.01,.5);lo-=padding;hi+=padding
        step=(hi-lo)/4
        decimals=max(2,1-math.floor(math.log10(step)))
        labels=[f'{hi-step*i:,.{decimals}f}' for i in range(5)]
        return lo,hi,labels

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#0b1a24'))
        source=[v for b in self.candles for v in (b['high'],b['low'])] if self.candles else self.values
        if not source:
            p.setPen(QColor('#8fa4b7'));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'选择已保存实验，显示真实归档数据');return
        lo,hi,ticks=self.axis(source);span=hi-lo
        label_width=max(p.fontMetrics().horizontalAdvance(tick) for tick in ticks)+12
        rect=QRectF(14,20,max(1,self.width()-label_width-28),self.height()-55)
        y=lambda value:rect.bottom()-(value-lo)/span*rect.height()
        for i in range(5):
            line=rect.top()+rect.height()*i/4;p.setPen(QColor('#203343'));p.drawLine(QPointF(rect.left(),line),QPointF(rect.right(),line))
            p.setPen(QColor('#8fa4b7'));p.drawText(QRectF(rect.right()+7,line-10,label_width,20),Qt.AlignmentFlag.AlignLeft,ticks[i])
        if self.candles:
            step=rect.width()/len(self.candles)
            for i,b in enumerate(self.candles):
                x=rect.left()+(i+.5)*step;color=QColor('#f35f62' if b['close']>=b['open'] else '#22d787');p.setPen(color);p.setBrush(color)
                p.drawLine(QPointF(x,y(b['high'])),QPointF(x,y(b['low'])))
                p.drawRect(QRectF(x-step*.3,min(y(b['open']),y(b['close'])),max(1,step*.6),max(1,abs(y(b['open'])-y(b['close'])))))
            if self.show_overlays:
                from datetime import datetime
                def clock(value):return datetime.fromisoformat(value) if isinstance(value,str) else value
                times=[clock(b['available_at']) for b in self.candles]
                def position(value):
                    at=clock(value)
                    return next((rect.left()+(i+.5)*step for i,t in enumerate(times) if t>=at),None)
                p.save();p.setClipRect(rect)
                for zone in self.overlays.get('zones',[]):
                    state=self.overlays.get('zone_states',{}).get(zone['zone_id'],{})
                    if state.get('status','active')!='active':continue
                    x=position(zone['available_at'])
                    right=rect.right()
                    if 'start_visible_index' in zone:
                        x=rect.left()+(zone['start_visible_index']+.5)*step
                        right=rect.left()+(zone['end_visible_index']+.5)*step
                    if x is None:continue
                    p.setPen(QPen(QColor('#4e96ff'),1));p.setBrush(QColor(78,150,255,35))
                    p.drawRect(QRectF(x,y(zone['upper_price']),right-x,y(zone['lower_price'])-y(zone['upper_price'])))
                for structure in self.overlays.get('structures',[]):
                    if 'start_visible_index' in structure:
                        upward=structure.get('direction')==1
                        start_price=structure['lower'] if upward else structure['upper']
                        end_price=structure['upper'] if upward else structure['lower']
                        p.setPen(QPen(QColor('#9c78ff' if structure['kind'].startswith('bi_') else '#f6b72f'),1.5))
                        p.drawLine(QPointF(rect.left()+(structure['start_visible_index']+.5)*step,y(start_price)),
                            QPointF(rect.left()+(structure['end_visible_index']+.5)*step,y(end_price)))
                    if structure.get('price') is None or clock(structure['occurred_at'])<times[0]:continue
                    x=position(structure['occurred_at'])
                    if x is not None:
                        p.setPen(QColor('#9c78ff'));p.setBrush(QColor('#9c78ff'));p.drawEllipse(QPointF(x,y(structure['price'])),4,4)
                for event in self.overlays.get('events',[]):
                    if clock(event['available_at'])<times[0]:continue
                    x=position(event['available_at'])
                    if x is not None:
                        index=min(len(self.candles)-1,int((x-rect.left())/step))
                        p.setPen(QPen(QColor('#f6b72f'),2));p.drawLine(QPointF(x,y(self.candles[index]['high'])-10),QPointF(x,y(self.candles[index]['high'])-3))
                p.restore()
        else:
            path=QPainterPath()
            for i,value in enumerate(self.values):
                point=QPointF(rect.left()+i*rect.width()/max(1,len(self.values)-1),y(value))
                path.moveTo(point) if i==0 else path.lineTo(point)
            p.setPen(QPen(QColor('#f6b72f'),2));p.drawPath(path)
        caption=getattr(self,'caption',None) or ('归档顺序  →    '+('K 线（红涨绿跌）' if self.candles else '净值 · 原始口径'))
        p.setPen(QColor('#8fa4b7'));p.drawText(QRectF(14,self.height()-25,self.width()-30,22),caption)
