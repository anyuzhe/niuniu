"""Readable inference and market-state tables from saved results."""
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QTabWidget
from .widgets import label,table

METRICS={'daily_mean_ic':'日均 IC','daily_mean_rank_ic':'日均 Rank IC','daily_mean_forward_return':'日均未来收益'}
STATES={'Bull':'上涨','Bear':'下跌','Neutral':'中性','Trend':'趋势','Range':'震荡','Transition':'过渡','Low':'低','Medium':'中','High':'高','Expansion':'扩张','Contraction':'收缩','Balanced':'均衡'}

def research_statistics(record):
    tabs=QTabWidget();intervals=[];states=[]
    def visit(node,path='当前实验'):
        if not isinstance(node,dict):return
        for horizon,metrics in (node.get('metrics') or {}).items():
            for name,value in (metrics.get('bootstrap') or {}).items():
                intervals.append([path,horizon,METRICS.get(name,name),value.get('estimate'),value.get('ci_low'),value.get('ci_high'),value.get('confidence'),value.get('valid_days'),value.get('reason') or ('已计算' if value.get('status')=='computed' else value.get('status'))])
        summary=node.get('regime_summary') or {}
        for state in summary.get('state_counts',[]):states.append([path,*[STATES.get(state.get('regime_'+k),state.get('regime_'+k,'未知')) for k in ('direction','structure','volatility','liquidity','breadth')],state.get('len')])
        for key in ('periods','folds','children','evaluations'):
            children=node.get(key,[])
            for i,child in (children.items() if isinstance(children,dict) else enumerate(children)):
                if isinstance(child,dict):visit(child,path+' / '+str(child.get('name',child.get('phase',i))))
    visit(record)
    def page(title,headers,rows,note):
        w=QWidget();box=QVBoxLayout(w);box.addWidget(label(note,'note',True));box.addWidget(table(headers,rows),1);tabs.addTab(w,title)
    if intervals:page('置信区间',['阶段','持有期','指标','估计值','区间下限','区间上限','置信水平','有效日期数','状态'],intervals,'日期块重采样区间；样本不足会明确标为不可计算。')
    inference=record.get('inference') or {}
    if inference:
        rows=[[t.get('path'),t.get('horizon'),METRICS.get(t.get('metric'),t.get('metric')),t.get('estimate'),t.get('p_value'),t.get('p_holm'),'通过' if t.get('reject_holm') is True else '未通过' if t.get('reject_holm') is False else '不可计算',t.get('reason') or t.get('status')] for t in inference.get('tests',[])]
        page('多重检验',['阶段','持有期','指标','估计值','原始 p 值','Holm p 值','显著性','状态'],rows,f"计划 {inference.get('planned_tests',0)} 项，可计算 {inference.get('available_tests',0)} 项。Holm 仅覆盖本研究登记范围；未通过不等于证明无效或等效。")
    if states:page('市场状态分布',['阶段','方向','结构','波动','流动性','广度','股票×K线样本数'],states,'以下为归档中的状态组合计数；不是独立交易次数。')
    if not tabs.count():page('统计结果',['项目','状态'],[['附加统计','本实验未保存置信区间、多重检验或市场状态统计']],'可在新建研究的设置中启用对应统计。')
    return tabs
