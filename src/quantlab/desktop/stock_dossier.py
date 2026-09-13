"""Native read-only Stock Dossier over immutable Decision/research/watch evidence."""
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog,QTabWidget,QVBoxLayout,QWidget

from quantlab.trading.stock_dossier import StockDossier
from .business_view import BusinessDetails
from .widgets import label,table,kpis


class StockDossierDialog(QDialog):
    def __init__(self, window, symbol):
        super().__init__(window);self.window=window;self.symbol=symbol;self.value=None
        self.setWindowTitle(symbol+' · 股票研究档案');self.resize(1220,820)
        self.box=QVBoxLayout(self)
        self.notice=label('正在聚合已有 Decision、实验、Watch 与 Playbook 证据；不会启动新研究。','note',True)
        self.box.addWidget(self.notice)
        self.tabs=QTabWidget();self.box.addWidget(self.tabs,1)
        self.window.async_call(lambda:StockDossier(window.output).get(symbol),self.loaded,guarded=False)

    def page(self):
        page=QWidget();layout=QVBoxLayout(page);return page,layout

    def loaded(self, value, error):
        if sip.isdeleted(self):return
        if error:self.notice.setText('股票档案读取失败：'+error);return
        self.value=value;self.notice.setText(value['policy']);self.tabs.clear()
        self.render_overview();self.render_decisions();self.render_experiments();self.render_watches();self.render_playbooks()
    def render_overview(self):
        value=self.value;current=value['current_decision'];page,layout=self.page()
        counts=value['counts'];layout.addWidget(kpis([
            ('当前 Decision',counts['decision_current'],'未被 revision 替代'),
            ('历史 Decision',counts['decision_history'],'包含旧版本'),
            ('相关实验',counts['experiments'],'已保存归档'),
            ('相关 Watch',counts['watches'],'人工跟踪池'),
            ('Playbook 命中',counts['playbooks'],'候选/选择历史'),
        ]))
        layout.addWidget(label('主题：'+(' / '.join(value['themes']) if value['themes'] else '尚无 Decision 主题标签'),'muted',True))
        details=BusinessDetails(current or {'status':'尚无当前 Decision'});layout.addWidget(details,1)
        if current:
            layout.addWidget(label('当前策略动作是 Strategy Intent；不等于真实成交或真实账户持仓。','note',True))
        self.tabs.addTab(page,'当前概览')

    def render_decisions(self):
        rows=self.value['decision_history'];page,layout=self.page()
        control=table(['交易日','Frame','动作','主题','实际提交时间','提交状态','判断'],[[d['trading_day'],d['frame'],d['action'],d.get('theme',''),d.get('submitted_local',d['submitted_at']).replace('T',' ')[:19],d.get('submission_status','legacy'),d.get('ai_thesis','')[:100]] for d in rows],lambda i:self.window.open_decision(rows[i]))
        layout.addWidget(label('原判和 revision 同时保留；后来的判断不会覆盖当时记录。','note',True));layout.addWidget(control,1)
        self.tabs.addTab(page,'Decision 时间线')

    def render_experiments(self):
        rows=self.value['experiments'];page,layout=self.page()
        control=table(['研究问题','因子','类型','周期','范围','状态'],[[r['question'],r['factor_id'],r['kind'],r['timeframe'],f"{r['start']} → {r['end']}",r['status']] for r in rows],lambda i:self.window.open_run(rows[i]['run_id']))
        layout.addWidget(label('这里只列入证券列表中明确包含该股票的已保存实验，不按文字相似度猜关联。','note',True));layout.addWidget(control,1)
        self.tabs.addTab(page,'研究证据')

    def render_watches(self):
        rows=self.value['watches'];page,layout=self.page()
        control=table(['跟踪名称','因子','状态','快照数','最近变化','最近更新'],[[r['name'],r['factor_id'],'启用' if r['active'] else '暂停',r['snapshots'],r.get('latest_change') or '—',r['updated_at'].replace('T',' ')[:19]] for r in rows],lambda i:self.window.factor_watches(rows[i]['watch_id']))
        layout.addWidget(label(f"相关 Watch {len(rows)} 个；无法读取 {self.value['unreadable_watches']} 项。打开档案不会刷新跟踪。",'note',True));layout.addWidget(control,1)
        self.tabs.addTab(page,'Watch / 跟踪')
    def render_playbooks(self):
        rows=self.value['playbooks'];page,layout=self.page()
        control=table(['玩法','版本','交易日','Frame','候选完整性','PIT','被选角色','未选角色'],[[
            r['playbook_name'],r['version'],r['trading_day'],r['frame'],r['completeness'],r['pit_status'],
            ' / '.join(r['selected_by']) or '—',' / '.join(r['unselected_by']) or '—'] for r in rows])
        layout.addWidget(label('这里只显示冻结 CandidateSet 中真实出现过该股票的记录；被选/未选都保留，不能只看赢家。','note',True))
        layout.addWidget(control,1);self.tabs.addTab(page,'Playbook / 10选2')
