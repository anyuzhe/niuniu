"""Explicit, bounded public-data requests; no implicit latest-date substitution."""
from datetime import date
import re

DAILY_FIELDS = 'date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST'
DATASETS = {
    'daily_raw':'不复权日线、估值、换手及ST/停牌状态',
    'daily_qfq':'前复权日线（供应商当前复权版本）',
    'calendar':'完整日期区间的交易日历',
    'basic':'证券基本资料', 'industry':'指定日期的行业响应',
    'securities':'指定日期全市场证券列表',
    'index_members':'指定日期上证50、沪深300、中证500成分',
    'financials':'明确季度的六类财务报告',
    'adjustments':'所选证券的复权因子事件',
    'daily_market':'指定日期全A股不复权日线（0.9.3）',
    'daily_etf':'指定日期全ETF不复权日线（0.9.3）',
    'daily_adjustments':'指定日期全市场复权因子事件（0.9.3）',
}
REPORTS = ('profit','operation','growth','balance','cash_flow','dupont')
LIMITATIONS = [
    '历史响应在本次抓取时观察到，不认证首次发布时间或完整修订历史。',
    '行业/成分只覆盖明确查询日期；updateDate不是已验证的生效或首次公布时刻。',
    '季报股本不能替代每日股本；此接口集合不提供可靠每日总市值或官方涨跌停价。',
    '日频估值来自供应商历史口径；次日使用只是保守研究约定，不是严格PIT认证。',
    '每日全市场接口包含其实际返回证券，不能凭接口名称认定历史全市场无遗漏。',
]


def import_plan(spec):
    required = {'symbols','start','end','datasets','snapshot_dates','quarters'}
    if not isinstance(spec,dict) or set(spec)!=required:
        raise ValueError('导入配置字段必须为 '+', '.join(sorted(required)))
    symbols=spec['symbols'];datasets=spec['datasets'];dates=spec['snapshot_dates'];quarters=spec['quarters']
    if not isinstance(symbols,list) or not 1<=len(symbols)<=100 or len(set(symbols))!=len(symbols):
        raise ValueError('导入须指定1–100个不同证券代码')
    if any(not isinstance(s,str) or not re.fullmatch(r'(sh|sz)\.\d{6}',s) for s in symbols):
        raise ValueError('Baostock本批仅支持明确的sh./sz.证券代码')
    start=date.fromisoformat(spec['start']);end=date.fromisoformat(spec['end'])
    if not 1<=(end-start).days+1<=4000:raise ValueError('日期范围须为1–4000自然日')
    if not isinstance(datasets,list) or not datasets or len(set(datasets))!=len(datasets) or set(datasets)-set(DATASETS):
        raise ValueError('未知或重复的数据类别')
    if 'daily_qfq' in datasets and 'daily_raw' not in datasets:
        raise ValueError('前复权导入需要同时选择原始日线，以保留估值及状态原值')
    if not isinstance(dates,list) or len(dates)>16 or len(set(dates))!=len(dates):
        raise ValueError('最多16个不同快照查询日')
    if any(not start<=date.fromisoformat(d)<=end for d in dates):raise ValueError('快照查询日超出范围')
    if set(datasets)&{'industry','securities','index_members','daily_market','daily_etf','daily_adjustments'} and not dates:
        raise ValueError('所选类别需要明确快照查询日，不能默认为最新')
    if not isinstance(quarters,list) or len(quarters)>24 or len(set(quarters))!=len(quarters):
        raise ValueError('最多24个不同财务季度')
    for q in quarters:
        if not isinstance(q,str) or not re.fullmatch(r'20\d{2}Q[1-4]',q) or int(q[:4])<2007 or int(q[:4])>end.year:
            raise ValueError('季度使用2007年起的YYYYQ1格式，不能晚于截止年份')
    if 'financials' in datasets and not quarters:raise ValueError('财务导入必须明确报告季度')
    plan={**spec,'symbols':sorted(symbols),'datasets':sorted(datasets),'snapshot_dates':sorted(dates),'quarters':sorted(quarters)}
    calls=query_plan(plan)
    if len(calls)>400:raise ValueError('本批超过400项查询，请缩小股票、季度或日期范围')
    return plan,calls


def query_plan(plan):
    calls=[];selected=set(plan['datasets']);period={'start_date':plan['start'],'end_date':plan['end']}
    def add(kind,method,params,symbol=None):
        calls.append({'kind':kind,'method':method,'params':params,'symbol':symbol})
    if 'calendar' in selected:add('calendar','query_trade_dates',period)
    for symbol in plan['symbols']:
        for kind,flag in (('daily_raw','3'),('daily_qfq','2')):
            if kind in selected:add(kind,'query_history_k_data_plus',
                {'code':symbol,'fields':DAILY_FIELDS,**period,'frequency':'d','adjustflag':flag},symbol)
        if 'basic' in selected:add('basic','query_stock_basic',{'code':symbol},symbol)
        if 'adjustments' in selected:add('adjustments','query_adjust_factor',{'code':symbol,**period},symbol)
        if 'financials' in selected:
            for q in plan['quarters']:
                for report in REPORTS:add(report,'query_'+report+'_data',
                    {'code':symbol,'year':int(q[:4]),'quarter':int(q[-1])},symbol)
    for day in plan['snapshot_dates']:
        if 'industry' in selected:
            for symbol in plan['symbols']:add('industry','query_stock_industry',{'code':symbol,'date':day},symbol)
        if 'securities' in selected:add('securities','query_all_stock',{'day':day})
        if 'index_members' in selected:
            for index in ('sz50','hs300','zz500'):add(index,'query_'+index+'_stocks',{'date':day})
        for kind,method in (('daily_market','query_daily_history_k_AStock'),
                ('daily_etf','query_daily_history_k_ETF'),('daily_adjustments','query_daily_adjust_factor')):
            if kind in selected:add(kind,method,{'date':day})
    return calls
