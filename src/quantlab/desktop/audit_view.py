"""Readable summaries and paged transitions from archived sequence audit only."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QComboBox
from .widgets import label,table,raw,row,button


class AuditView(QWidget):
    def __init__(self,audit):
        super().__init__();box=QVBoxLayout(self)
        sequences=audit.get('sequences',[])
        if not sequences:
            box.addWidget(label('本实验没有序列审计记录。新建实验时可勾选“保存序列审计”。','muted',True));return
        scope=audit.get('scope','—')
        if scope=='loaded_history_before_universe_regime_context_filters':scope='已加载历史，股票池／市场状态／上下文筛选之前'
        box.addWidget(label(f"审计截止：{audit.get('as_of','—')}\n范围：{scope}\n计数为状态记录数；入选完成数以归档筛选结果为准，不等于成交笔数。",'muted',True))
        self.selector=QComboBox()
        for sequence in sequences:
            factor=sequence.get('factor',{})
            self.selector.addItem(f"{sequence.get('alias','—')} · {factor.get('name_cn',factor.get('factor_id','—'))}")
        box.addWidget(self.selector)
        self.summary=QVBoxLayout();box.addLayout(self.summary)
        self.position=0;self.transitions=[];self.page_size=100
        self.previous=button('上一页',lambda:self.move(-1));self.next=button('下一页',lambda:self.move(1));self.page_label=label('','muted')
        box.addWidget(row(self.previous,self.page_label,self.next))
        self.records=QVBoxLayout();box.addLayout(self.records,1)
        box.addWidget(label('单击状态记录查看事件 ID 与可用时间；完整事件内容保留在“完整记录”。','muted',True))
        self.detail=raw({});self.detail.setMaximumHeight(150);box.addWidget(self.detail)
        def select():
            sequence=sequences[self.selector.currentIndex()];counts=sequence.get('status_record_counts',{})
            while self.summary.count():self.summary.takeAt(0).widget().deleteLater()
            counts_table=table(['激活记录','完成记录','失效记录','超时记录','期末待完成','入选完成','事件记录'],[[
                *[counts.get(k,0) for k in ('active','completed','invalidated','timeout')],
                sequence.get('pending_at_end',0),sequence.get('selected_completions',0),len(sequence.get('events',[]))]])
            counts_table.setMinimumHeight(85);counts_table.setMaximumHeight(100);self.summary.addWidget(counts_table)
            self.is_nesting=factor_is_nesting=sequence.get('factor',{}).get('factor_id','').startswith('CHAN.CLASSIC_MULTISCALE_')
            self.transitions=sequence.get('events',[]) if factor_is_nesting else sequence.get('transitions',[])
            self.position=0;self.render()
        self.selector.currentIndexChanged.connect(select);select()

    def move(self,direction):
        self.position=max(0,min(max(0,(len(self.transitions)-1)//self.page_size),self.position+direction));self.render()

    def render(self):
        while self.records.count():self.records.takeAt(0).widget().deleteLater()
        start=self.position*self.page_size;items=self.transitions[start:start+self.page_size];total=len(self.transitions)
        self.page_label.setText(f'{start+1 if items else 0}–{start+len(items)} / {total}')
        self.previous.setEnabled(start>0);self.next.setEnabled(start+len(items)<total)
        names={'active':'激活','completed':'完成','invalidated':'失效','timeout':'超时'}
        if self.is_nesting:
            self.current_table=table(['证券','嵌套状态','当前可用时间','由高到低的周期'],[[
                item.get('symbol'),'已连接' if item.get('metadata',{}).get('status')=='nested' else '连接失效',item.get('available_at'),
                ' → '.join(reversed(item.get('metadata',{}).get('levels',[])))] for item in items])
        else:self.current_table=table(['证券','状态','发生时间','可用时间','入选完成'],[[
            item.get('symbol'),names.get(item.get('status'),item.get('status')),item.get('occurred_at'),item.get('available_at'),
            '—' if item.get('completion_selected') is None else ('是' if item['completion_selected'] else '否')] for item in items])
        self.records.addWidget(self.current_table)
        def show(index,*_):
            if not 0<=index<len(items):return
            if self.is_nesting:
                metadata=items[index].get('metadata',{});parts=metadata.get('segments',[])
                lines=['最高周期最新已确认线段 → 时间范围完全包含的下级线段。']
                for n,segment in enumerate(parts,1):
                    period={'1d':'日线','60m':'60 分钟','30m':'30 分钟','15m':'15 分钟','5m':'5 分钟','1m':'1 分钟'}.get(segment['timeframe'],segment['timeframe'])
                    lines.append(f"第 {n} 层 · {period} · {'向上' if segment['direction']==1 else '向下'}\n范围：{segment['start_at']} 至 {segment['end_at']}\n结构在 {segment['available_at']} 可用")
                if not parts:lines.append('原有嵌套不再成立；没有用未来结构补回历史连接。')
                self.detail.setPlainText('\n\n'.join(lines));return
            import json
            from quantlab.storage.codec import encode
            self.detail.setPlainText(json.dumps(json.loads(encode(items[index])),ensure_ascii=False,indent=2))
        self.current_table.currentCellChanged.connect(show)
        self.detail.setPlainText('单击状态记录查看详情。' if items else '该分量没有序列状态记录；事件数量见上方汇总。')
