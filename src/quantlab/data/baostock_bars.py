"""Bounded existing-SDK historical bar fetch, explicitly not a live feed."""
from datetime import datetime,time,timezone
from zoneinfo import ZoneInfo
import math
import socket
import re
import polars as pl
from quantlab.data.validation import validate_bars
from quantlab.storage.codec import digest


def fetch_raw_bars(symbols,timeframe,start,end):
    import baostock as bs
    from importlib.metadata import version
    if timeframe not in ('1d','5m') or start>end:raise ValueError('Invalid bar request')
    if not symbols or len(set(symbols))!=len(symbols) or any(not re.fullmatch(r'(sh|sz)\.\d{6}',s) for s in symbols):raise ValueError('Baostock expects unique sh./sz. stock symbols')
    fields='date,'+('time,' if timeframe=='5m' else '')+'code,open,high,low,close,volume,amount,adjustflag'
    old=socket.getdefaulttimeout();socket.setdefaulttimeout(15);logged_in=False;rows=[];counts={}
    try:
        response=bs.login()
        if response.error_code!='0':raise ValueError('Baostock login failed: '+response.error_msg)
        logged_in=True
        for symbol in symbols:
            query=bs.query_history_k_data_plus(symbol,fields,start_date=start.isoformat(),end_date=end.isoformat(),frequency='d' if timeframe=='1d' else '5',adjustflag='3')
            count=0
            while query.error_code=='0' and query.next():
                raw=dict(zip(query.fields,query.get_row_data()));count+=1
                if raw['code']!=symbol or raw['adjustflag']!='3':raise ValueError('Unexpected symbol/adjustment from provider')
                day=datetime.fromisoformat(raw['date']).date()
                if not start<=day<=end:raise ValueError('Provider returned rows outside requested range')
                dt=datetime.combine(day,time(15),ZoneInfo('Asia/Shanghai')) if timeframe=='1d' else datetime.strptime(raw['time'],'%Y%m%d%H%M%S%f').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
                if dt.date()!=day:raise ValueError('Provider date/time mismatch')
                if timeframe=='5m' and (dt.second or dt.microsecond or dt.hour*60+dt.minute not in set(range(575,691,5))|set(range(785,901,5))):raise ValueError('Unexpected 5m trading slot')
                rows.append({'symbol':symbol,'exchange':symbol[:2],'datetime':dt,'available_at':dt,'timeframe':timeframe,
                    **{c:float(raw[c]) for c in ('open','high','low','close','volume')},'turnover':float(raw['amount']),'adj_factor':1.})
            if query.error_code!='0':raise ValueError('Incomplete Baostock fetch: '+query.error_msg)
            counts[symbol]=count
    finally:
        try:
            if logged_in:bs.logout()
        finally:socket.setdefaulttimeout(old)
    observed=datetime.now(timezone.utc)
    source={'provider':'baostock','sdk_version':version('baostock'),'adjustment':'raw','observed_at':observed,
        'request':{'symbols':symbols,'timeframe':timeframe,'start':start,'end':end},'rows_by_symbol':counts,
        'scope':'Historical bars fetched now. Nominal close availability is not a first-publication timestamp. Not a live feed or PIT certification.'}
    frame=None
    if rows:
        frame=pl.DataFrame(rows).with_columns(pl.col('datetime','available_at').dt.convert_time_zone('Asia/Shanghai')).sort('symbol','datetime')
        validate_bars(frame)
        if frame['available_at'].max()>observed:raise ValueError('Provider returned uncompleted future bars')
        source['normalized_hash']=digest(frame.write_json())
    return frame,source
