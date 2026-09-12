"""Top-level A-share trading-desk pages; the research lab remains intact underneath."""
from collections import Counter, defaultdict

from quantlab.trading.decision_store import DecisionStore
from .widgets import Card, button, kpis, label, row, table


def _store(window):
    return DecisionStore(window.output)


def _decisions(window, history=False, limit=200):
    return _store(window).list(include_superseded=history,limit=limit)['records']


def today_page(window):
    box=window.page('今日交易','A 股个人交易研究驾驶舱 · 市场事实、计划、AI 判断与研究证据分层呈现。')
    decisions=_decisions(window); latest=_store(window).latest_by_symbol()
    actions=Counter(item['action'] for item in latest)
    box.addWidget(kpis([
        ('股票档案',len(latest),'已有 Decision 的证券'),('本日 Decision',sum(d['trading_day']==window.as_of_day() for d in decisions),'当前自然日；不推断交易日'),
        ('观察 / 准备',actions['WATCH']+actions['READY'],'当前最新状态'),('计划开仓',actions['PLAN_OPEN'],'策略意图，不等于成交'),
        ('持有意图',actions['OPEN']+actions['ADD']+actions['HOLD'],'不等于真实账户'),('风险退出',actions['REDUCE']+actions['EXIT']+actions['INVALIDATED'],'需要理由或失效条件'),
    ]))
    left=Card('今日待处理')
    left.add(label('Trading Desk 第一阶段先接 Decision Ledger；主线实时数据、R1/R2/R3 自动生成将在后续阶段接入。','note',True))
    left.add(row(button('＋ 新增 Decision',window.new_decision,True),button('查看复盘账本',lambda:window.navigate_root(4))))
    right=Card('最近 Decision')
    rows=[[d['trading_day'],d['symbol'],d['frame'],d['action'],d.get('theme',''),d.get('ai_thesis','')[:60]] for d in decisions[:12]]
    right.add(table(['交易日','证券','Frame','动作','主线','判断'],rows),1)
    panels=row(left,right);panels.layout().setStretch(0,1);panels.layout().setStretch(1,2);box.addWidget(panels,1)


def theme_page(window):
    box=window.page('主线市场','A 股主题 × 明确日期 × Decision Frame · Market Facts / Machine Rule / AI / Risk 分层。')
    from .theme_matrix import ThemeMatrixWidget
    box.addWidget(ThemeMatrixWidget(window),1)


def stock_page(window):
    box=window.page('股票中心','Stock Dossier 入口 · 先按证券聚合 Decision；P3 再接实验、Watch 与完整股票档案。')
    latest=_store(window).latest_by_symbol()
    rows=[[d['symbol'],d.get('theme',''),d.get('theme_role',''),d['trading_day'],d['frame'],d['action'],d.get('ai_thesis','')[:80]] for d in latest]
    card=Card('股票档案');box.addWidget(row(button('＋ 新增 Decision',window.new_decision,True),label('双击证券可查看 Decision 时间线。','muted')))
    card.add(table(['证券','主题','角色','最近交易日','Frame','状态','最近判断'],rows,lambda i:window.open_stock_dossier(latest[i]['symbol']) if latest else None),1);box.addWidget(card,1)


def position_page(window):
    box=window.page('持仓计划','策略意图中心 · 计划/开/加/持/减/退，与 Paper/真实成交严格分开。')
    active={'PLAN_OPEN','OPEN','ADD','HOLD','REDUCE','EXIT'};latest=[d for d in _store(window).latest_by_symbol() if d['action'] in active]
    box.addWidget(label('这里展示 Strategy Intent，不代表真实账户持仓；只有成交回执才能改变 Paper/未来 Real Position。','note',True))
    box.addWidget(table(['证券','交易日','Frame','动作','买入区间','确认触发','持有理由','退出条件'],[[d['symbol'],d['trading_day'],d['frame'],d['action'],d.get('buy_zone',''),d.get('confirm_trigger',''),d.get('hold_reason',''),d.get('exit_condition','')] for d in latest]),1)


def review_page(window):
    box=window.page('复盘中心','Decision Ledger · 原判、修订、后续结果分开保留，不用后来行情覆盖当时判断。')
    records=_decisions(window,history=True)
    rows=[[d['submitted_at'].replace('T',' ')[:19],d['trading_day'],d['symbol'],d['frame'],d['action'],d.get('revision_of')[:8] if d.get('revision_of') else '—',d.get('outcome','')[:70]] for d in records]
    box.addWidget(row(button('＋ 新增 Decision',window.new_decision,True),label('历史 revision 默认全部显示；当前版本由 revision 链判定。','muted')))
    box.addWidget(table(['提交时间','交易日','证券','Frame','动作','修订自','Outcome'],rows,lambda i:window.open_decision(records[i]) if records else None),1)


def ai_team_page(window):
    box=window.page('AI 团队','Role 与模型分离 · 日常单助理负责，需要时再按需复核。')
    roles=[
        ('Chief Researcher','主对话、综合证据、生成提案；不能自行批准研究。'),
        ('Market Scanner','后续负责覆盖检查，重点防漏股票、漏主题、漏数据。'),
        ('Skeptic / Risk Reviewer','后续按需挑战结论、PIT 和执行风险。'),
        ('Quant Researcher','复用现有 Research Lab / Factory / Watch / PIT。'),
        ('Developer','后续仅在 Dev Studio 隔离 worktree 中修改代码。'),
    ]
    box.addWidget(table(['Role','当前职责'],roles))
    box.addWidget(row(button('打开 AI 研究助手',window.research_chat,True),button('研究议程',window.research_agenda),button('研究记忆',window.research_memory),button('AI 工具接口',window.agent_catalog)))
    box.addWidget(label('P8 才启用正式 Peer Review 任务链；当前不会伪装成已经有多 Agent 自动会议。','note',True))


def research_lab_page(window):
    box=window.page('研究实验室','保留原牛牛全部研究能力；Trading Desk 只是新的业务入口，不削弱实验内核。')
    entries=[
        ('研究总览',0),('数据中心',1),('因子库',2),('市场状态',3),('结构与事件',4),('序列构建器',5),
        ('理论实验室',6),('实验中心',7),('组合与模型',8),('策略回测',9),('结果对比',10),('研究设置',11),
    ]
    grid=Card('原研究模块')
    for title,index in entries:
        grid.add(button(title,lambda checked=False,i=index:window.navigate(i),index in (0,7)))
    box.addWidget(grid,1)


def system_center_page(window):
    box=window.page('系统中心','数据、PIT、任务、服务和工作空间集中入口；在线状态不等于研究正确。')
    box.addWidget(kpis([
        ('研究产物',str(window.output.name),'当前 workspace'),('行情目录','已配置' if window.data_root else '未配置','研究执行输入'),
        ('Decision Ledger',_store(window).list(limit=1)['total'],'append-only'),('研究任务','查看','JobQueue / archived jobs'),
    ]))
    box.addWidget(row(button('数据中心',lambda:window.navigate(1),True),button('运行任务',window.show_jobs),button('研究设置',lambda:window.navigate(11))))
    box.addWidget(label('P11 再把 MCP、tracking daemon、数据更新、日志和心跳统一成 System Health；本阶段先统一入口。','note',True))
