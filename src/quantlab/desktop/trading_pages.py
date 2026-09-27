"""Top-level A-share trading-desk pages; the research lab remains intact underneath."""
from collections import Counter, defaultdict

from quantlab.trading.decision_store import DecisionStore
from .widgets import Card, button, kpis, label, row, table


def _store(window):
    return DecisionStore(window.output)


def _decisions(window, history=False, limit=200):
    return _store(window).list(include_superseded=history,limit=limit)['records']


def today_page(window):
    box=window.page('交易台','A 股个人交易研究驾驶舱 · 市场事实、主线、股票状态、AI结论、风险、Agenda 与 Watch。')
    from .trading_cockpit import TradingCockpitWidget
    box.addWidget(TradingCockpitWidget(window),1)


def theme_page(window):
    box=window.page('主题矩阵','A 股主题 × 明确日期 × Decision Frame · Market Facts / Machine Rule / AI / Risk 分层。')
    from .theme_matrix import ThemeMatrixWidget
    box.addWidget(ThemeMatrixWidget(window),1)


def stock_page(window):
    box=window.page('股票决策档案','Stock Dossier 入口 · 先按证券聚合 Decision；P3 再接实验、Watch 与完整股票档案。')
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
    box=window.page('决策复盘','Decision Ledger · 原判、修订、后续结果分开保留，不用后来行情覆盖当时判断。')
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
    box=window.page('研究实验室','研究总览 / 因子候选 / 实验对比 / Alpha Factory / Watch 统一入口；legacy导航和Baostock菜单仍保留。')
    page_epoch=window.epoch
    def open_method(name, missing):
        def _open():
            if window.closing or window.epoch!=page_epoch:return
            method=getattr(window,name,None)
            if callable(method):
                try:method()
                except Exception as exc:window.status.setText(missing+'：'+str(exc))
            else:
                window.status.setText(missing+'：当前窗口未加载数据工作台扩展，请从Baostock/数据版入口打开。')
        return _open
    def open_legacy(index):
        return lambda checked=False,i=index: None if (window.closing or window.epoch!=page_epoch) else window.navigate(i)
    def open_factor_evidence():
        if window.closing or window.epoch!=page_epoch:return
        from .factor_evidence import FactorEvidenceDialog
        window.show_dialog(FactorEvidenceDialog(window))
    box.addWidget(row(button('Research Skill Library',window.research_skill_library,True),
        button('交易知识 / Playbook Lab',window.playbook_lab),
        label('Research Skill只读证据 → 人工StrategySource → Playbook；不自动写库、选股或交易。','note',True)))
    overview=Card('研究总览 / 待办')
    overview.add(label('从已有ResearchAgendaService读取待办；只展示/打开人工入口，不替模型批准研究。','muted',True))
    agenda_status=label('正在读取有界待办摘要…','muted',True);overview.add(agenda_status)
    overview.add(row(button('研究议程',window.research_agenda,True),button('AI 研究助手',window.research_chat),
                     button('研究记忆',window.research_memory)))
    box.addWidget(overview)
    agenda_output,agenda_data_root=window.output,window.data_root
    def agenda_done(value,error):
        from PyQt6 import sip
        if window.closing or window.epoch!=page_epoch or sip.isdeleted(agenda_status):return
        if window.output!=agenda_output or window.data_root!=agenda_data_root:return
        if error:
            agenda_status.setText('研究总览不可读：'+error);return
        kinds=Counter(item.get('kind','unknown') for item in value.get('items',[]))
        anomalies=[k for k in kinds if 'error' in k or 'integrity' in k or 'failed' in k or 'unreadable' in k]
        agenda_status.setText('待办 '+str(value.get('total',0))+' 项；前50项类型：'+', '.join(f'{k}×{v}' for k,v in kinds.most_common(8))+
            ('；本页含异常/失败/不可读：'+', '.join(anomalies) if anomalies else '；本次返回的摘要中未出现异常项，不代表全库健康认证。'))
    window.async_call(lambda:__import__('quantlab.agent.research_agenda',fromlist=['ResearchAgendaService']).ResearchAgendaService(agenda_output,agenda_data_root).build(50),agenda_done,guarded=False)
    factors=Card('因子与候选')
    factors.add(label('因子定义、DSL候选、候选只读对照分开；名称相同不等于同一规则。','muted',True))
    factors.add(row(button('因子库',open_legacy(2),True),button('因子证据发现（只读）',open_factor_evidence),
                    button('受限DSL候选注册',open_method('open_dsl_candidates','DSL候选不可用')),
                    button('候选因子对照（只读）',open_method('open_candidate_review','候选对照不可用')),
                    button('候选增量证据包',open_method('open_incremental_evidence','增量证据不可用'))))
    box.addWidget(factors)
    experiments=Card('实验与对比')
    experiments.add(label('实验中心、回测和结果对比继续复用原内核；不创建第二权威库。','muted',True))
    experiments.add(row(button('新建实验',window.new_experiment,True),button('实验中心',open_legacy(7)),
                        button('策略回测',open_legacy(9)),button('结果对比',open_legacy(10)),
                        button('归档日线研究输入',open_method('open_archived_daily_dataset','归档输入不可用'))))
    box.addWidget(experiments)
    factory=Card('Alpha Factory')
    factory.add(label('Factory必须人工核对后提交；同步结果和进入观察池仍是显式人工动作。','muted',True))
    factory.add(row(button('安全 Alpha Factory',open_method('open_alpha_factory','Alpha Factory不可用'),True),
                    button('研究议程里的Factory待办',window.research_agenda)))
    box.addWidget(factory)
    watch=Card('观察池 / Watch')
    watch.add(label('Watch序贯监测只发出复核信号，不自动停用因子、换参数或交易。','muted',True))
    watch.add(row(button('观察池 / Watch',window.factor_watches,True),
                  button('跟踪基准换版',open_method('open_watch_rebase','Watch换版不可用')),
                  button('日历驱动到期检查',open_method('open_readiness','到期检查不可用')),
                  button('受控自动跟踪',open_method('open_tracking_control','跟踪控制不可用'))))
    box.addWidget(watch)
    entries=[('研究总览',0),('数据中心',1),('因子库',2),('市场状态',3),('结构与事件',4),('序列构建器',5),
        ('理论实验室',6),('实验中心',7),('组合与模型',8),('策略回测',9),('结果对比',10),('研究设置',11)]
    grid=Card('Legacy 研究模块（兼容入口，不隐藏功能）')
    for title,index in entries:
        grid.add(button(title,open_legacy(index),index in (0,7)))
    box.addWidget(grid,1)


def dev_studio_page(window):
    box=window.page('开发工作台','P10 Dev Studio · DevTask → Main Agent → Dynamic Subagents → Reviewer → Human Merge Gate。')
    from .dev_studio import DevStudioWidget
    box.addWidget(DevStudioWidget(window),1)


def system_center_page(window):
    box=window.page('系统中心','P11 System Health · 服务、任务、数据、PIT、Paper、Dev 和日志统一只读健康证据；在线状态不等于研究正确。')
    from .system_health import SystemHealthWidget
    box.addWidget(SystemHealthWidget(window),1)
