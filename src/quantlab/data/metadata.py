from datetime import datetime,time,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import polars as pl
from quantlab.storage.codec import digest


def import_metadata(root,symbols,observed_at=None):
    observed_at=observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:raise ValueError('Observation time requires timezone')
    base=Path(root)/'lake/bronze/provider=baostock';industry=pl.read_parquet(base/'industry/industry.parquet')
    records=[];actions=[];sources=[]
    for row in industry.filter(pl.col('code').is_in(symbols)).to_dicts():
        effective=datetime.fromisoformat(row['updateDate']).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        records.append({'symbol':row['code'],'sector':row['industry'],'effective_at':effective,
            'available_at':max(effective,observed_at),'source':'MQC industry snapshot; first observed by this import at '+observed_at.isoformat()})
    sources.append({'kind':'industry','hash':digest(industry.write_json())})
    for symbol in symbols:
        path=base/'corporate_actions_dividend'/(symbol.replace('.','_')+'.parquet')
        if not path.exists():continue
        f=pl.read_parquet(path);sources.append({'kind':'corporate_actions','symbol':symbol,'hash':digest(f.write_json())})
        for row in f.to_dicts():
            fetched=datetime.fromisoformat(row['fetch_ts']).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            actions.append({'symbol':symbol,'available_at':max(observed_at,fetched),'source_record':row,
                'applied_to_execution':False,'reason':'Source dates and entitlements retained; settlement and tax treatment not inferred'})
    return {'observed_at':observed_at,'industry_events':records,'corporate_action_records':actions,'sources':sources,
        'missing':['historical ST','historical suspension','official session price bounds','historical industry availability'],
        'limitations':'Import availability is observation time, not backdated announcement availability. Corporate actions are retained for audit only and are not applied to accounts.'}
