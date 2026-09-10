"""Inspect and freeze an assessment of the proposed sample, never label gaps ready."""
from pathlib import Path
from datetime import date,datetime,timezone
import json
import polars as pl
from quantlab.data.base import DataRequest
from quantlab.data.audit import audit_market
from quantlab.data.query import query_bars
from quantlab.domain import Timeframe
from quantlab.execution.rules import MarketRules
from quantlab.execution.rules_audit import audit_market_rules
from quantlab.storage.codec import encode,digest

if __name__=='__main__':
    out=Path('artifacts/stock-acceptance');root=Path('/Volumes/Lexar/MQC-DATA')
    request=DataRequest(('sh.600519','sz.000001','sz.000858','sh.601318','sz.300750'),Timeframe.DAILY,date(2025,1,1),date(2026,9,4))
    audit=audit_market(root,request)
    (out/'proposed-sample-data-audit.json').write_text(encode(audit))
    calendar=pl.read_parquet(root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet')
    dates=calendar.filter(pl.col('is_trading_day')=='1')['calendar_date'].str.to_date().to_list()
    # No official rule file has been supplied. An empty set explicitly models missing input.
    rules=audit_market_rules(MarketRules([]),request.symbols,[d for d in dates if request.start<=d<=request.end])
    (out/'proposed-sample-rule-audit.json').write_text(encode(rules))
    industry=pl.read_parquet(root/'lake/bronze/provider=baostock/industry/industry.parquet')
    latest,_=query_bars(root,DataRequest(request.symbols,Timeframe.MIN5,date(2026,9,1),datetime.now().date()))
    blockers=['No official historical rule input supplied','Historical industry availability/market-cap series not supplied',
        'Corporate-action files missing for part of the proposed universe','Continuous fresh producer not verified']
    assessment={'assessed_at':datetime.now(timezone.utc),'request':request,'data_files':audit['files'],
        'data_audit_hash':digest(audit),'data_quality_checked':all(r['status']=='checked' for r in audit['results']),
        'official_rules_input':None,'official_rules_covered':rules['covered_symbol_sessions'],'official_rules_expected':rules['expected_symbol_sessions'],
        'industry_update_dates':industry['updateDate'].unique().sort().to_list(),'latest_source_5m':latest.group_by('code').agg(pl.col('time').max()).to_dicts(),
        'status':'blocked','ready_for_real_rule_research':False,'unmet_requirements':blockers,
        'research_schedule':{'train_end':'2025-08-31','valid_end':'2025-12-31','test_end':'2026-09-04'},
        'scope':'Frozen assessment of a proposed sample, not an accepted data set. No new OOS/ablation/return significance claim before required inputs are available.'}
    with (out/'research-sample-assessment.json').open('x') as handle:handle.write(encode(assessment))
    print(encode({k:assessment[k] for k in ('status','data_quality_checked','official_rules_covered','official_rules_expected','latest_source_5m')}))
