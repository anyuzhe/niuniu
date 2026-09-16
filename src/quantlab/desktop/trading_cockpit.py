"""Default Trading Desk cockpit over read-only durable business evidence."""
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDateEdit,QGridLayout,QHBoxLayout,QSizePolicy,QTabWidget,QTableWidget,QVBoxLayout,QWidget

from quantlab.trading.cockpit import TradingCockpitService
from .widgets import Card,button,label,row,table


def fact_text(record):
    facts=record.get('facts') or {}
    parts=[]
    labels={'limit_up_count':'涨停','limit_down_count':'跌停','twenty_cm_limit_up_count':'20cm','breadth_up':'上涨','breadth_down':'下跌','amount_billion':'额(亿)','leader_symbol':'龙头','leader_return':'龙头涨跌'}
    for key in ('limit_up_count','limit_down_count','twenty_cm_limit_up_count','breadth_up','breadth_down','amount_billion','leader_symbol','leader_return'):
        if key in facts:parts.append(labels[key]+'='+str(facts[key]))
    return '；'.join(parts) if parts else '未提供正式市场事实'


class TradingCockpitWidget(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.service=TradingCockpitService(window.output,window.data_root);self.request=0;self.value=None
        self.box=QVBoxLayout(self);self.day=QDateEdit();self.day.setCalendarPopup(True);self.day.setDate(QDate.currentDate())
        self.status=label('正在读取 Trading Cockpit…','muted',True)
        self.box.addWidget(row(label('业务日期'),self.day,button('刷新',self.reload,True),button('＋ Decision',window.new_decision),button('AI 助手',window.research_chat),button('Research Agenda',window.research_agenda)))
        self.box.addWidget(self.status)
        self.body=QVBoxLayout();self.box.addLayout(self.body);self.day.dateChanged.connect(lambda:self.reload(explicit=True));self.reload(explicit=False)

    def clear(self):
        while self.body.count():
            item=self.body.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()

    def reload(self,*args,explicit=True):
        self.request+=1;request=self.request
        day=self.day.date().toString('yyyy-MM-dd') if explicit else ''
        self.status.setText('正在聚合已保存证据…')
        def done(value,error):
            if request!=self.request:return
            if error:self.status.setText('读取失败：'+error);return
            self.value=value
            if not explicit:
                self.day.blockSignals(True);self.day.setDate(QDate.fromString(value['trading_day'],'yyyy-MM-dd'));self.day.blockSignals(False)
            self.render(value)
        self.window.async_call(lambda:self.service.build(day),done)

    def render(self,value):
        selected=self.tabs.currentIndex() if hasattr(self,'tabs') else 0
        self.clear();counts=value['state_counts'];watch=value['watches'];agenda=value['agenda'];lifecycle=value.get('paper_lifecycle') or {}
        self.status.setText(f"{value['trading_day']} · {value['day_source']} · 最近已保存Frame {value['latest_saved_frame'] or '无'}")
        stats=[
            ('候选',len(value['candidates']),'DISCOVERED / WATCH / READY'),
            ('计划 / 持有',len(value['plans']),'Strategy Intent，不等于成交'),
            ('主线快照',len(value['themes']),f"有正式facts {value['theme_fact_snapshots']}"),
            ('行情快照',len(value.get('market_snapshots',[])),'MarketSnapshot，不自动联网刷新'),
            ('Agenda',agenda.get('total',0),'确定性待办，不自动执行'),
            ('Watch',len(watch['rows']),f"不可读 {watch['unreadable']}"),
            ('Paper计划',len(value.get('paper_plans',[])),f"已执行 {value.get('paper_plan_executed',0)}"),
            ('长期Paper',lifecycle.get('dynamic_account_count',0),f"复盘 {lifecycle.get('paper_reviews',0)} / 再平衡 {lifecycle.get('paper_rebalances',0)}"),
            ('风险项',len(value['risks']),'Decision + Theme 已保存风险'),
        ]
        summary=QWidget();grid=QGridLayout(summary);grid.setContentsMargins(0,0,0,0);grid.setSpacing(8)
        for i,(title,total,caption) in enumerate(stats):
            card=Card();card.body.setContentsMargins(12,6,12,6);card.body.setSpacing(2)
            heading=row(label(title,'muted'),label(total,'gold'));heading.layout().setStretch(0,1)
            card.add(heading);card.add(label(caption,'muted',True));grid.addWidget(card,i//3,i%3)
        for column in range(3):grid.setColumnStretch(column,1)
        self.body.addWidget(summary)
        self.tabs=QTabWidget();self.body.addWidget(self.tabs,1)
        theme=Card('主线 / 市场事实')
        theme_rows=[[r['theme'],r['machine_state'],r['ai_state'],fact_text(r),r.get('facts_source','') or '—',r.get('risk_review','')[:70]] for r in value['themes']]
        theme.add(label(value['market_facts_policy'],'note',True));theme.add(table(['主题','Machine','AI','正式 facts','来源','Risk Review'],theme_rows),1)

        snapshots=Card('MarketSnapshot / 实时证据')
        latest=value.get('latest_market_snapshots') or {}
        snapshot_rows=[]
        for frame in ('PREP','AUCTION','R1','R2','R3'):
            r=latest.get(frame)
            if r:snapshot_rows.append([frame,r['as_of'],r['provider'],r['completeness'],r['capture_status'],
                '是' if r.get('strict_pit_eligible') else '否',len(r.get('instruments') or [])])
        snapshots.add(label('这里只展示已冻结快照；打开首页不会联网刷新行情。','note',True))
        snapshots.add(table(['Frame','as_of','Provider','完整性','捕获状态','Strict PIT候选','证券数'],snapshot_rows),1)
        self.add_section('市场事实',theme,snapshots)

        candidates=Card('候选股票')
        crows=[[d['symbol'],d['action'],d.get('theme',''),d['trading_day'],d['frame'],d.get('ai_thesis','')[:80]] for d in value['candidates']]
        candidates.add(table(['证券','状态','主题','业务日','Frame','当前判断'],crows,lambda i:self.window.open_stock_dossier(value['candidates'][i]['symbol'])),1)
        plans=Card('当前计划 / 持有意图')
        prows=[[d['symbol'],d['action'],d['trading_day'],d['frame'],d.get('transition_reason','')[:60],d.get('exit_condition','')[:60]] for d in value['plans']]
        plans.add(table(['证券','状态','业务日','Frame','转移理由','退出条件'],prows,lambda i:self.window.open_stock_dossier(value['plans'][i]['symbol'])),1)
        self.add_section('候选与计划',candidates,plans)

        paper=Card('PaperPlan / 模拟执行')
        paper_rows=[]
        for p in value.get('paper_plans',[])[:50]:
            spec=p.get('spec') or {};execution=p.get('execution') or {}
            paper_rows.append([p.get('status',''),spec.get('account_name',''),','.join(spec.get('universe_symbols') or []),
                spec.get('selection_frame',''),execution.get('account_revision','—'),len(execution.get('new_fills') or [])])
        paper.add(label('这里只展示已保存 PaperPlan/模拟成交回执；Cockpit 不会自动创建计划或执行账户。','note',True))
        paper.add(table(['状态','账户','Universe','Selection Frame','账户Revision','本次成交'],paper_rows),1)

        life=Card('长期 Paper / 生命周期统计')
        life.add(label('预测、Intent、模拟成交、复盘和账户收益分开计数；这里只读，不自动执行。','note',True))
        life_rows=[
            ['SYSTEM_PREDICTION',lifecycle.get('system_predictions',0),f"NO_TRADE={lifecycle.get('no_trade_predictions',0)}"],
            ['Paper执行',lifecycle.get('paper_executions',0),f"有成交={lifecycle.get('paper_executions_with_fill',0)} / 无成交={lifecycle.get('paper_executions_no_fill',0)}"],
            ['复盘',lifecycle.get('paper_reviews',0),str(lifecycle.get('paper_reviews_by_frame',{}))],
            ['再平衡',lifecycle.get('paper_rebalances',0),str(lifecycle.get('paper_rebalance_status',{}))],
            ['拒单',sum((lifecycle.get('paper_rejection_reasons') or {}).values()),str(lifecycle.get('paper_rejection_reasons',{}))],
        ]
        life.add(table(['层','数量','说明'],life_rows),1);self.add_section('模拟执行',paper,life)

        ai=Card('AI 结论 / 风险')
        ai_rows=[[d['symbol'],d['action'],d.get('theme',''),d.get('ai_thesis','')[:95],'/'.join(d.get('risk_flags') or []),d.get('invalidation','')[:70]] for d in value['ai_conclusions']]
        ai.add(label('这里只展示已保存 Decision 的 AI Thesis；打开首页不会重新调用模型。','note',True));ai.add(table(['证券','状态','主题','AI Thesis','Risk Flags','失效条件'],ai_rows),1)
        risk=Card('风险复核')
        risk_rows=[]
        for r in value['risks']:
            if r['kind']=='decision':risk_rows.append(['股票',r['symbol'],r['action'],'；'.join(r.get('risk_flags') or []) or r.get('invalidation') or r.get('exit_condition')])
            else:risk_rows.append(['主线',r['theme'],'—',r.get('risk_review','')])
        risk.add(table(['类型','对象','状态','风险'],risk_rows),1)
        self.add_section('AI 与风险',ai,risk)

        agenda_card=Card('Research Agenda')
        agenda_rows=[[a['priority'],a['kind'],a['title'],a['reason'][:85],a['action'][:85]] for a in agenda.get('items',[])]
        agenda_card.add(table(['优先级','类型','待办','原因','建议动作'],agenda_rows),1)
        if agenda.get('error'):agenda_card.add(label('Agenda 读取未完成：'+agenda['error'],'note',True))
        watch_card=Card('Watch / 跟踪')
        watch_rows=[[w['name'],w['factor_id'],'启用' if w['active'] else '暂停',w['snapshots'],w['alert_count'],w['updated_at'].replace('T',' ')[:19]] for w in watch['rows']]
        watch_card.add(table(['名称','因子','状态','快照','提醒','更新'],watch_rows,lambda i:self.window.factor_watches(watch['rows'][i]['watch_id'])),1)
        self.add_section('研究与跟踪',agenda_card,watch_card)
        self.tabs.setCurrentIndex(selected)

    def add_section(self,title,*cards):
        page=QWidget();box=QHBoxLayout(page);box.setContentsMargins(8,8,8,8);box.setSpacing(8)
        for card in cards:
            card.body.setContentsMargins(12,8,12,8);card.body.setSpacing(6)
            for view in card.findChildren(QTableWidget):
                view.setMinimumHeight(140)
                view.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
                view.horizontalHeader().setMinimumSectionSize(45)
                for column in range(view.columnCount()):
                    item=view.horizontalHeaderItem(column);item.setToolTip(item.text())
            box.addWidget(card,1)
        self.tabs.addTab(page,title)
