"""Native as-of candle replay over immutable archived bars."""
import polars as pl
from bisect import bisect_left, bisect_right
from datetime import datetime
from PyQt6 import sip
from PyQt6.QtCore import QTimer,QDateTime,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QSpinBox,QDateTimeEdit,QTabWidget,QCheckBox
from quantlab.sequence.replay import replay_page
from .widgets import label,button,row,Chart,raw


class ReplayWidget(QWidget):
    def __init__(self,window,run_id,record):
        super().__init__(window);self.window=window;self.record=record;self.bars=None;self.busy=False;self.epoch=0
        box=QVBoxLayout(self);self.symbol=QComboBox();self.cursor=QSpinBox(self);self.cursor.setMinimum(0);self.cursor.hide()
        self.times=[];self.points={'signal':[],'fill':[]};self.source_bars=None;self.period_request=0
        self.date=QDateTimeEdit();self.date.setCalendarPopup(True);self.date.setKeyboardTracking(False)
        self.date.setAccessibleName('回放日期');self.date.setEnabled(False)
        self.symbol.setEditable(True);self.symbol.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.symbol.lineEdit().setAccessibleName('回放证券代码')
        self.symbol.lineEdit().setPlaceholderText('输入归档中的证券代码')
        self.play=button('播放',self.toggle);self.play.setEnabled(False)
        box.addWidget(row(label('证券'),self.symbol,label('回放日期'),self.date,self.play))
        self.period=None
        config=record.get('manifest',{}).get('config',{})
        if config.get('factor_id','').startswith('CHAN.CLASSIC_MULTISCALE_'):
            params=record.get('manifest',{}).get('parameters',config.get('parameters',{}))
            self.period=QComboBox();self.period.setAccessibleName('缠论层级回放周期');self.period.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            periods=[config['data']['timeframe'],params.get('middle_timeframe','15m'),params.get('higher_timeframe','60m')]
            for period in dict.fromkeys(periods):self.period.addItem('日线' if period=='1d' else period[:-1]+' 分钟',period)
            self.period.setEnabled(False);self.period.currentIndexChanged.connect(self.change_period)
            box.addWidget(row(label('缠论层级回放周期'),self.period))
        self.navigation={}
        for kind,title in [('bar','交易日'),('signal','信号 / 事件'),('fill','成交')]:
            for direction,prefix in [(-1,'上一个'),(1,'下一个')]:
                self.navigation[kind,direction]=button(prefix+title,lambda k=kind,d=direction:self.jump(k,d))
                self.navigation[kind,direction].setEnabled(False)
        box.addWidget(row(*self.navigation.values()))
        self.status=label('正在读取归档 K 线…','muted',True);box.addWidget(self.status);self.chart=Chart();box.addWidget(self.chart,1)
        overlays=QCheckBox('显示已知结构 / 事件 / 活跃区域（紫点 / 金线 / 蓝框）');overlays.setChecked(True)
        overlays.toggled.connect(lambda checked:(setattr(self.chart,'show_overlays',checked),self.chart.update()));box.addWidget(overlays)
        from .replay_details import ReplayDetails
        names={v['definition']['factor_id']:v['definition']['name_cn'] for v in getattr(window,'factors',[])}
        self.details=ReplayDetails(names);self.evidence=QTabWidget();self.objects=raw({});self.fills=raw([])
        self.evidence.addTab(self.details,'已知结构、事件与成交明细');self.evidence.addTab(self.objects,'高级：原始结构记录');self.evidence.addTab(self.fills,'高级：原始成交记录')
        for i in (1,2):self.evidence.setTabVisible(i,False)
        advanced=QCheckBox('显示高级原始记录');advanced.toggled.connect(lambda show:[self.evidence.setTabVisible(i,show) for i in (1,2)])
        box.addWidget(advanced);box.addWidget(self.evidence,1)
        self.timer=QTimer(self);self.timer.setInterval(600);self.timer.timeout.connect(self.advance)
        self.symbol.currentTextChanged.connect(self.reset);self.cursor.valueChanged.connect(self.refresh)
        self.date.dateTimeChanged.connect(self.seek_date)
        def done(bars,error):
            if sip.isdeleted(self):return
            if error:self.status.setText(error);return
            self.source_bars=self.bars=bars;self.symbol.addItems(sorted(bars['symbol'].unique().to_list()));self.play.setEnabled(True)
            if self.period is not None:self.period.setEnabled(True)
        # Adjusted structures must be drawn over the same archived signal prices.
        replay_run_id=run_id
        if record.get('manifest',{}).get('signal_data_snapshot',{}).get('adjustment','raw')!='raw':
            replay_run_id=record['children'][0]['run_id']
        window.async_call(lambda:pl.read_parquet(window.catalog.file(replay_run_id,'bars.parquet')),done,False)

    def change_period(self):
        if self.source_bars is None:return
        from quantlab.multitimeframe.resample import resample_bars
        period=self.period.currentData();self.period_request+=1;request=self.period_request
        cutoff=self.times[self.cursor.value()] if self.times else None
        self.timer.stop();self.play.setText('播放');self.play.setEnabled(False);self.epoch+=1
        self.status.setText('正在从归档低周期 K 线聚合完整层级…')
        def done(bars,error):
            if sip.isdeleted(self) or request!=self.period_request:return
            if error:self.status.setText(error);return
            self.bars=bars;self.reset()
            if cutoff and self.times:self.cursor.setValue(max(0,bisect_right(self.times,cutoff)-1))
        self.window.async_call(lambda:resample_bars(self.source_bars,period,require_all=False),done,False)

    def reset(self):
        if self.bars is None:return
        frame=self.bars.filter(pl.col('symbol')==self.symbol.currentText()).sort('datetime')
        self.times=frame['available_at'].to_list();count=len(self.times)
        self.date.setEnabled(bool(count))
        for control in self.navigation.values():control.setEnabled(False)
        if not count:
            self.epoch+=1;self.busy=False;self.timer.stop();self.play.setText('播放');self.play.setEnabled(False)
            self.chart.candles=[];self.chart.overlays={};self.chart.update()
            self.objects.setPlainText('{}');self.fills.setPlainText('[]')
            self.details.set_data({})
            self.status.setText('请输入归档中完整的证券代码。');return
        self.play.setEnabled(True)
        self.daily=len({t.date() for t in self.times})==count
        self.date.blockSignals(True)
        self.date.setDisplayFormat('yyyy-MM-dd' if self.daily else 'yyyy-MM-dd HH:mm')
        self.date.setDateTimeRange(QDateTime(self.times[0]),QDateTime(self.times[-1]))
        self.date.blockSignals(False)
        self.date.setToolTip('非交易日期定位到此前最近交易日；只显示截至所选日期的已知信息。')
        for direction,prefix in [(-1,'上一个'),(1,'下一个')]:
            self.navigation['bar',direction].setText(prefix+('交易日' if self.daily else '时点'))
        events=list(self.record.get('replay',{}).get('events',[]))
        for sequence in self.record.get('sequence_audit',{}).get('sequences',[]):events.extend(sequence.get('events',[]))
        for kind,items,key in [('signal',events,'available_at'),('fill',self.record.get('fills',[]),'filled_at')]:
            self.points[kind]=sorted({i for v in items if v['symbol']==self.symbol.currentText()
                if 0<=(i:=bisect_left(self.times,datetime.fromisoformat(v[key])))<count})
        self.cursor.blockSignals(True);self.cursor.setMaximum(max(0,count-1));self.cursor.setValue(0);self.cursor.blockSignals(False);self.refresh()

    def seek_date(self,value):
        if not self.times:return
        requested=value.toPyDateTime().replace(tzinfo=self.times[0].tzinfo)
        if self.daily:requested=requested.replace(hour=23,minute=59,second=59)
        at=max(0,bisect_right(self.times,requested)-1)
        self.timer.stop();self.play.setText('播放')
        self.cursor.setValue(at);self.sync_navigation()

    def jump(self,kind,direction):
        self.timer.stop();self.play.setText('播放')
        at=self.cursor.value()
        candidates=range(len(self.times)) if kind=='bar' else self.points[kind]
        index=bisect_right(candidates,at) if direction>0 else bisect_left(candidates,at)-1
        if 0<=index<len(candidates):self.cursor.setValue(candidates[index])

    def sync_navigation(self):
        if not self.times:return
        at=self.cursor.value();self.date.blockSignals(True)
        self.date.setDateTime(QDateTime(self.times[at]));self.date.blockSignals(False)
        for (kind,direction),control in self.navigation.items():
            points=range(len(self.times)) if kind=='bar' else self.points[kind]
            control.setEnabled(bool(points) and (points[-1]>at if direction>0 else points[0]<at))

    def refresh(self):
        if self.bars is None or not self.times:return
        self.sync_navigation()
        self.epoch+=1;epoch=self.epoch;symbol=self.symbol.currentText();cursor=self.cursor.value();bars=self.bars;self.busy=True
        def done(data,error):
            if sip.isdeleted(self):return
            if epoch!=self.epoch:return
            self.busy=False
            if error:self.timer.stop();self.play.setText('播放');self.status.setText(error);return
            self.chart.candles=data['bars'];self.chart.overlays={k:data[k] for k in ('structures','events','zones','zone_states')};self.chart.update();self.status.setText(f"{data['symbol']} · {data['at']+1}/{data['total_bars']} · 已知信息截至 {data['as_of']} · {self.record.get('manifest',{}).get('signal_data_snapshot',self.record.get('manifest',{}).get('data_snapshot',{})).get('adjustment','未知口径')} · 回测价格 {self.record.get('manifest',{}).get('data_snapshot',{}).get('adjustment','未知')} · 仅诊断叠加")
            from quantlab.storage.codec import encode
            import json
            self.objects.setPlainText(json.dumps(json.loads(encode({k:data[k] for k in ('structures','events','zones','zone_states','overlay_rules')})),ensure_ascii=False,indent=2))
            self.fills.setPlainText(json.dumps(json.loads(encode(data['fills'])),ensure_ascii=False,indent=2))
            self.details.set_data(data)
        self.window.async_call(lambda:replay_page(bars,self.record,symbol,cursor,100),done,False)

    def toggle(self):
        if self.timer.isActive():self.timer.stop();self.play.setText('播放')
        else:self.timer.start();self.play.setText('暂停')

    def advance(self):
        if not self.isVisible():self.timer.stop();self.play.setText('播放');return
        if self.busy:return
        if self.cursor.value()>=self.cursor.maximum():self.timer.stop();self.play.setText('播放');return
        self.cursor.setValue(self.cursor.value()+1)

    def hideEvent(self,event):
        self.timer.stop();self.play.setText('播放');super().hideEvent(event)
