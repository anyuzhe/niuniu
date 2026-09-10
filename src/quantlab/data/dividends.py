"""Normalize available MQC cash-dividend records without inventing PIT availability."""
from datetime import datetime,timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import re
import polars as pl
from quantlab.execution.corporate_actions import CashDividends
from quantlab.storage.codec import digest


def import_cash_dividends(root,symbols,tax_rate,observed_at=None,include_stock=False):
    observed_at=observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:raise ValueError('Observation time requires timezone')
    records=[];unresolved=[];sources=[];tz=ZoneInfo('Asia/Shanghai')
    at=lambda value,hour,minute=0:datetime.fromisoformat(value).replace(hour=hour,minute=minute,tzinfo=tz)
    for symbol in symbols:
        if not re.fullmatch(r'(sh|sz|bj)\.\d{6}',symbol):raise ValueError('Invalid symbol')
        path=Path(root)/'lake/bronze/provider=baostock/corporate_actions_dividend'/(symbol.replace('.','_')+'.parquet')
        if not path.exists():
            unresolved.append({'symbol':symbol,'reason':'missing_source_file'});continue
        before=path.stat();data=pl.read_parquet(path);file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        if (before.st_size,before.st_mtime_ns)!=(path.stat().st_size,path.stat().st_mtime_ns):raise ValueError('Dividend source changed during read')
        sources.append({'path':str(path),'sha256':file_hash,'rows':data.height})
        for row in data.to_dicts():
            try:
                if row['code']!=symbol:raise ValueError('Source symbol mismatch')
                stock_parts=[Decimal(str(row.get(k) or 0)) for k in ('dividStocksPs','dividReserveToStockPs')]
                if any(not v.is_finite() or v<0 for v in stock_parts):raise ValueError('Invalid stock distribution components')
                stock_ratio=float(sum(stock_parts))
                if stock_ratio and not include_stock:
                    raise ValueError('Stock distributions require share-accounting support')
                fetched=datetime.fromisoformat(row['fetch_ts'])
                if fetched.tzinfo is None:fetched=fetched.replace(tzinfo=tz)
                record={'action_id':digest({'symbol':symbol,'record_date':row['dividRegistDate'],'ex_date':row['dividOperateDate']}),
                    'symbol':symbol,'record_at':at(row['dividRegistDate'],15),'ex_at':at(row['dividOperateDate'],9,30),
                    'pay_at':at(row['dividPayDate'],15),'available_at':max(observed_at,fetched),
                    'cash_per_share':float(row['dividCashPsBeforeTax']),'tax_rate':tax_rate,
                    'source':str(path)+'#sha256='+file_hash+'; date-only payment modeled at 15:00; fixed configured tax'}
                if stock_ratio:
                    record.update(stock_per_share=stock_ratio,list_at=at(row['dividStockMarketDate'],9,30),fractional_policy='reject')
                    record['source']+='; source stock-listing date modeled tradable at 09:30; fractional entitlement rejected'
                CashDividends([record]);records.append(record)
            except (ValueError,KeyError,TypeError,InvalidOperation) as error:
                unresolved.append({'symbol':symbol,'source_record':row,'reason':str(error)})
    CashDividends(records)
    return {'corporate_actions':records,'sources':sources,'unresolved':unresolved,'observed_at':observed_at,
        'strict_pit_ready':False,'includes_stock_distributions':include_stock,'scope':'Retrospective accounting only. Actual import availability is retained. Announcement dates do not certify historical delivery. Missing/unsupported records are unresolved, not zero entitlements. Listing-open timing is an explicit date-only model.'}
