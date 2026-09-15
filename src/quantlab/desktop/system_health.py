"""Read-only P11 System Health page."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout

from quantlab.agent.system_health import SystemHealthService
from .widgets import Card,button,kpis,label,row,table


ORDER=('workspace','artifact_growth','jobs','tracking_daemon','mcp','notifications','market_data_series','daily_market','market_snapshots','daily_orchestrator','pit_playbook','paper_lifecycle','broker_shadow','dev_studio','logs')
LABELS={'workspace':'工作空间','artifact_growth':'产物增长','jobs':'研究任务','tracking_daemon':'Tracking Daemon','mcp':'MCP',
    'notifications':'Notifications','market_data_series':'Market Data / Series','daily_market':'DailyMarket',
    'market_snapshots':'MarketSnapshot','daily_orchestrator':'Daily Orchestrator','pit_playbook':'PIT / Playbook',
    'paper_lifecycle':'Paper Lifecycle','broker_shadow':'Broker Shadow','dev_studio':'Dev Studio','logs':'后台日志'}


class SystemHealthWidget(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.request=0;self.value=None
        self.box=QVBoxLayout(self);self.status=label('正在读取 System Health…','muted',True)
        self.box.addWidget(row(button('刷新健康状态',self.reload,True),button('数据中心',lambda:window.navigate(1)),
            button('运行任务',window.show_jobs),button('研究设置',lambda:window.navigate(11)),self.status))
        self.body=QVBoxLayout();self.box.addLayout(self.body);self.reload()

    def clear(self):
        while self.body.count():
            item=self.body.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()

    def reload(self,*_):
        self.request+=1;request=self.request;self.status.setText('正在只读聚合 receipts / locks / metadata…')
        def done(value,error):
            if request!=self.request:return
            if error:self.status.setText('读取失败：'+error);return
            self.value=value;self.render(value)
        self.window.async_call(lambda:SystemHealthService(self.window.output,self.window.data_root).build(),done,guarded=False)

    def render(self,value):
        self.clear();summary=value['summary'];self.status.setText('检查时间 '+value['checked_at'].replace('T',' ')[:19])
        self.body.addWidget(kpis([
            ('Runtime',summary['runtime_status'],'服务/任务/Dev/log'),
            ('Research Readiness',summary['research_readiness_status'],'数据/PIT/Orchestrator/Paper'),
            ('Blockers',summary['blocker_count'],'需要明确处理'),
            ('Warnings',summary['warning_count'],'需要关注，不等于系统错误'),
        ]))
        card=Card('组件健康证据')
        rows=[]
        for name in ORDER:
            item=value['components'][name]
            rows.append([LABELS[name],item['status'],item['summary'],', '.join(item['blockers']) or '—',', '.join(item['warnings']) or '—'])
        card.add(table(['组件','状态','摘要','Blocker','Warning'],rows),1);self.body.addWidget(card)
        notes=Card('解释边界')
        notes.add(label(value['interpretation'],'note',True))
        notes.add(label('System Health 不会自动重启服务、重跑任务、下载数据、接受修订、修改 PIT 资格、merge/push 或执行交易。','note',True))
        self.body.addWidget(notes)
