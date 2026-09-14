"""Read-only Agent Scorecard UI; no ranking, auto-weighting or task execution."""
from PyQt6.QtWidgets import QDialog,QTabWidget,QVBoxLayout,QWidget

from quantlab.agent.scorecard import AgentScorecardService
from .business_view import BusinessDetails
from .widgets import button,label,row,table

ROLE_LABELS={'chief_researcher':'Chief Researcher','market_scanner':'Market Scanner',
    'skeptic':'Skeptic / Risk','quant_researcher':'Quant Researcher','developer':'Developer'}
TASK_LABELS={'decision':'Decision','peer_review_independent':'Peer Review · 独立',
    'peer_review_synthesis':'Peer Review · Chief 综合'}


def _pct(metric):
    value=(metric or {}).get('value') if isinstance(metric,dict) else None
    return '—' if value is None else f'{value:.1%}'


class AgentScorecardDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.service=AgentScorecardService(window.output);self.value=None
        self.setWindowTitle('Agent Scorecard · 按任务类型');self.resize(1260,820)
        box=QVBoxLayout(self)
        box.addWidget(label('只读运行纪律与证据覆盖；无模型总分、无自动调权、无多数票奖励。样本不足保持 UNKNOWN。','note',True))
        box.addWidget(row(button('刷新',self.reload,True),button('关闭',self.close)))
        self.tabs=QTabWidget();box.addWidget(self.tabs,1);self.reload()

    def detail(self,value,title):
        dialog=QDialog(self);dialog.setWindowTitle(title);dialog.resize(900,700)
        layout=QVBoxLayout(dialog);layout.addWidget(BusinessDetails(value),1);layout.addWidget(button('关闭',dialog.close))
        self.window.show_dialog(dialog)

    def reload(self):
        self.value=self.service.build();self.tabs.clear();self.render_agents();self.render_system()

    def render_agents(self):
        page=QWidget();layout=QVBoxLayout(page);rows=self.value['rows']
        data=[]
        for value in rows:
            m=value['metrics'];task=value['task_type']
            if task=='decision':a=_pct(m['on_time_rate']);b=_pct(m['evidence_link_rate']);c=_pct(m['follow_up_rate'])
            elif task=='peer_review_independent':a=_pct(m['completion_rate']);b=_pct(m['explicit_evidence_rate']);c=_pct(m['tool_use_rate'])
            else:a=_pct(m['synthesis_completion_rate']);b=_pct(m['explicit_evidence_rate']);c=_pct(m['reviewer_input_completion_rate'])
            data.append([ROLE_LABELS.get(value['role_id'],value['role_id']),TASK_LABELS.get(task,task),value['samples'],
                value['sample_status'],a,b,c,','.join(value.get('observed_models') or []) or '—'])
        layout.addWidget(label('Decision 的“证据”表示可追溯链接，不表示证据内容自动判真；Peer Review 也不把共识当正确。','muted',True))
        layout.addWidget(table(['Role','任务类型','样本','样本状态','及时/完成','证据覆盖','跟踪/输入','观测模型'],data,
            lambda i:self.detail(rows[i],'Scorecard · '+rows[i]['role_id']+' / '+rows[i]['task_type'])),1)
        self.tabs.addTab(page,'Agent / Task Type')

    def render_system(self):
        page=QWidget();layout=QVBoxLayout(page);playbook=self.value['system_baselines']['playbook_prediction'];paper=self.value['system_baselines']['paper_lifecycle']
        m=playbook['metrics'];rows=[['Playbook Prediction',playbook['samples'],_pct(m['full_candidate_set_rate']),_pct(m['strict_pit_rate']),
            m['labeled_predictions'],_pct(m['exact_match_rate']),_pct(m['micro_precision']),_pct(m['micro_recall'])]]
        layout.addWidget(label('System baseline 不是 Agent 分数；Selection 匹配也不是 Alpha/盈利认证。','note',True))
        layout.addWidget(table(['系统任务','样本','FULL','STRICT_PIT','有标签','Exact','Precision','Recall'],rows),0)
        layout.addWidget(BusinessDetails({'paper_lifecycle':paper,'policy':self.value['policy'],'meta':self.value['meta']}),1)
        self.tabs.addTab(page,'System Baselines')


__all__=['AgentScorecardDialog']
