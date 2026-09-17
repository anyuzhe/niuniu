"""P07 raw arithmetic diagnostic on original daily amounts, never a QM50 backtest."""
from datetime import date,timedelta
from pathlib import Path
import io
import re
from collections import Counter
import polars as pl
from quantlab.agent.local_data_tools import LocalMarketDataTools,MAX_TOTAL_BYTES
from quantlab.agent.research_specs import regular_bytes,sha
from quantlab.trading.qm50_contract import previous_relative_amount

MAINBOARD=re.compile(r'(sh\.(600|601|603|605)\d{3}|sz\.(000|001|002|003)\d{3})')

def diagnose(data_root,symbols_text,start_text,end_text):
    start,end=date.fromisoformat(start_text),date.fromisoformat(end_text)
    symbols=symbols_text.replace(',',' ').split()
    if not 1<=len(symbols)<=10 or len(set(symbols))!=len(symbols) or any(not MAINBOARD.fullmatch(s) for s in symbols):
        raise ValueError('P07诊断只接受1–10个不同沪深主板代码；代码前缀不认证当日风险状态')
    if not start<=end or (end-start).days>370:raise ValueError('P07诊断日期最多371天')
    local=LocalMarketDataTools(data_root);directory=local._directory('1d','raw')
    calendar_path=local._safe(local.root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet')
    calendar_bytes=regular_bytes(calendar_path,32*1024*1024)
    calendar=pl.read_parquet(io.BytesIO(calendar_bytes))
    if not {'calendar_date','is_trading_day'}<=set(calendar.columns):raise ValueError('交易日历字段缺失')
    dated=calendar.with_columns(pl.col('calendar_date').str.to_date().alias('day')).sort('day')
    if dated['day'].n_unique()!=dated.height or dated['day'].null_count():raise ValueError('交易日历日期重复或缺失')
    if any(v not in ('0','1') for v in dated['is_trading_day']):raise ValueError('交易日历状态未知')
    if dated['day'].min()>start or dated['day'].max()<end:raise ValueError('交易日历不覆盖诊断区间，不推测未来交易日')
    days=dated.filter(pl.col('is_trading_day')=='1')['day'].to_list()
    requested=[d for d in days if start<=d<=end]
    if not requested:raise ValueError('区间没有已知交易日')
    positions={d:i for i,d in enumerate(days)}
    records=[];sources=[];budget=[MAX_TOTAL_BYTES]
    for symbol in symbols:
        path=directory/(symbol.replace('.','_')+'.parquet')
        frame,source=local._read(path,budget)
        if not {'volume','amount','fetch_ts'}<=set(frame.columns):raise ValueError('原始成交量/成交额/抓取记录缺失，不推算')
        if frame['date'].null_count() or frame['date'].n_unique()!=frame.height or set(frame['code'].to_list())!={symbol}:
            raise ValueError('证券身份或日线日期不一致')
        rows={r['date']:r for r in frame.to_dicts()};sources.append({'symbol':symbol,**source})
        for day in requested:
            index=positions[day];past=days[max(0,index-21):index]
            values=[rows.get(d) for d in past]
            row={'symbol':symbol,'decision_date':day.isoformat(),'factor_id':'P07','previous_date':past[-1].isoformat() if past else None,
                'window_start':past[0].isoformat() if len(past)==21 else None,'window_end':past[-2].isoformat() if len(past)==21 else None,
                'raw_formula_value':None,'score':None,'historical_decision_value':None,'asof_qualified':False,
                'scope':'RETROSPECTIVE_RAW_FIELD_DIAGNOSTIC_NOT_CANDIDATE_BACKTEST'}
            if len(past)!=21:calc={'value':None,'status':'INSUFFICIENT_HISTORY'}
            elif any(v is None or v.get('volume') is None or v['volume']<=0 for v in values):
                calc={'value':None,'status':'MISSING_SOURCE'}
            else:calc=previous_relative_amount(values[-1]['amount'],[v['amount'] for v in values[:-1]])
            row.update(raw_formula_value=calc['value'],calculation_status=calc['status'],strict_status='MISSING_SOURCE',
                strict_reason='历史available_at及合格昨日涨停候选全集未认证；原始计算不能用于Q或交易')
            records.append(row)
        if sha(path.read_bytes())!=source['sha256']:raise ValueError('诊断期间源文件变化')
    if sha(calendar_path.read_bytes())!=sha(calendar_bytes):raise ValueError('诊断期间日历变化')
    table=pl.DataFrame(records)
    return table,{'factor_id':'P07','field':'prev_relative_amount','symbols':symbols,'start':start_text,'end':end_text,
        'rows':len(records),'calculation_counts':dict(Counter(r['calculation_status'] for r in records)),
        'strict_status':'MISSING_SOURCE','score_generated':False,'core_Q_generated':False,'trades_generated':False,
        'source_files':sources,'calendar_sha256':sha(calendar_bytes),'source_bytes_unchanged':True,
        'formula':'amount[D-1] / median(amount of the 20 valid trading days strictly BEFORE D-1)',
        'examples':records[:2]+records[-2:],
        'limitations':['只在21个连续已知交易日均有实际正成交量、正成交额时输出原始比值；缺失/零成交不跳过、不填零。',
            '无完整历史可用时点/证券状态/候选池，不是完整P07严格回测或整个QM50模型结果。',
            '没有计算未来收益、IC、排名、Q、组合或成交。']}
