"""Top-level A-share trading-desk pages; the research lab remains intact underneath."""
from collections import Counter, defaultdict

from quantlab.trading.decision_store import DecisionStore
from .widgets import Card, button, kpis, label, row, table


def _store(window):
    return DecisionStore(window.output)


def _decisions(window, history=False, limit=200):
    return _store(window).list(include_superseded=history,limit=limit)['records']


def today_page(window):
    box=window.page('今日交易','A 股个人交易研究驾驶舱 · 市场事实、主线、股票状态、AI结论、风险、Agenda 与 Watch。')
    from .trading_cockpit import TradingCockpitWidget
    box.addWidget(TradingCockpitWidget(window),1)


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
    box=window.page('持仓计划','Strategy Intent 状态机 · 动作变化由新 Decision 驱动，与 Paper/真实成交严格分开。')
    from quantlab.trading.strategy_intent import allowed_next
    latest=_store(window).latest_by_symbol()
    box.addWidget(label('这里展示 Strategy Intent，不代表真实账户持仓；只有模拟/券商成交回执才能改变 Paper/未来 Real Position。','note',True))
    rows=[]
    for d in latest:
        rows.append([d['symbol'],d['trading_day'],d['frame'],d['action'],' / '.join(allowed_next(d['action'])),d.get('intent_transition_kind','legacy'),d.get('transition_reason','')[:70],d.get('hold_reason','')[:60],d.get('exit_condition','')[:60]])
    box.addWidget(table(['证券','交易日','Frame','当前状态','允许下一动作','转移类型','转移理由','持有依据','退出条件'],rows),1)


def review_page(window):
    box=window.page('复盘中心','Decision Ledger · 原判、修订、后续结果分开保留，不用后来行情覆盖当时判断。')
    records=_decisions(window,history=True)
    rows=[[d.get('submitted_local',d['submitted_at']).replace('T',' ')[:19],d['trading_day'],d['symbol'],d['frame'],d['action'],d.get('submission_status','legacy'),d.get('revision_of')[:8] if d.get('revision_of') else '—',d.get('outcome','')[:70]] for d in records]
    def compare():
        from .decision_frames import FrameComparisonDialog
        window.show_dialog(FrameComparisonDialog(window))
    def policy():
        from .decision_frames import FramePolicyDialog
        window.show_dialog(FramePolicyDialog(window))
    box.addWidget(row(button('＋ 新增 Decision',window.new_decision,True),button('跨轮对比',compare),button('Frame Policy',policy),label('迟交/补录会保留状态；旧记录显示 legacy。','muted')))
    box.addWidget(table(['实际提交时间','交易日','证券','Frame','动作','提交状态','修订自','Outcome'],rows,lambda i:window.open_decision(records[i]) if records else None),1)


def ai_team_page(window):
    box=window.page('AI 团队','Role 与模型分离 · Chief 默认单独完成，需要时再启动有限同行复核。')
    from .ai_team import AITeamWidget
    box.addWidget(AITeamWidget(window),1)

def research_lab_page(window):
    box=window.page('研究实验室','保留原牛牛全部研究能力；外部经验先进入只读Research Skill，再经宿主复核进入Trading Knowledge。')
    box.addWidget(row(button('Research Skill Library',window.research_skill_library,True),
        button('交易知识 / Playbook Lab',window.playbook_lab),
        label('Research Skill只读证据 → 人工StrategySource → Playbook；不自动写库、选股或交易。','note',True)))
    entries=[
        ('研究总览',0),('数据中心',1),('因子库',2),('市场状态',3),('结构与事件',4),('序列构建器',5),
        ('理论实验室',6),('实验中心',7),('组合与模型',8),('策略回测',9),('结果对比',10),('研究设置',11),
    ]
    grid=Card('原研究模块')
    for title,index in entries:
        grid.add(button(title,lambda checked=False,i=index:window.navigate(i),index in (0,7)))
    box.addWidget(grid,1)


def dev_studio_page(window):
    box=window.page('开发工作台','P10 Dev Studio · DevTask → Main Agent → Dynamic Subagents → Reviewer → Human Merge Gate。')
    from .dev_studio import DevStudioWidget
    box.addWidget(DevStudioWidget(window),1)


def system_center_page(window):
    box=window.page('系统中心','P11 System Health · 服务、任务、数据、PIT、Paper、Dev 和日志统一只读健康证据；在线状态不等于研究正确。')
    from .system_health import SystemHealthWidget
    box.addWidget(SystemHealthWidget(window),1)
