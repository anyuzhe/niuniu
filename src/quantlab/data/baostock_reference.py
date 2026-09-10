"""Archive dated Baostock reference responses without inventing PIT timestamps."""
from datetime import date,datetime,timezone
from pathlib import Path
import re
import socket
from quantlab.storage.codec import encode,digest


def fetch_reference(symbols,start,end,output,industry_dates=()):
    import baostock as bs
    from importlib.metadata import version
    symbols=list(symbols);industry_dates=sorted(set(industry_dates or (start,end)))
    if not symbols or len(set(symbols))!=len(symbols) or any(not re.fullmatch(r'(sh|sz)\.\d{6}',s) for s in symbols):raise ValueError('Require unique sh./sz. symbols')
    if start>end or any(not start<=d<=end for d in industry_dates):raise ValueError('Invalid reference date range')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    manifest={'provider':'baostock','sdk_version':version('baostock'),'start':start,'end':end,'symbols':symbols,'industry_dates':industry_dates,
        'status':'running','files':[],'strict_pit_ready':False,'price_bounds_available':False,
        'scope':'Industry covers queried dates only. Quarterly shares are reported-period snapshots, not exact daily capitalization. updateDate/pubDate have no intraday publication or revision history. ST/tradestatus are retrospective daily observations; official daily price bounds are absent.'}
    old=socket.getdefaulttimeout();socket.setdefaulttimeout(15);logged=False
    def save(kind,symbol,params,query):
        result=query();rows=[]
        if result.error_code!='0':raise ValueError(kind+': '+result.error_msg)
        while result.next():
            if result.error_code!='0':raise ValueError(kind+': '+result.error_msg)
            rows.append(dict(zip(result.fields,result.get_row_data())))
        if result.error_code!='0':raise ValueError(kind+': '+result.error_msg)
        if any(r.get('code')!=symbol for r in rows):raise ValueError('Provider returned wrong symbol')
        observed=datetime.now(timezone.utc)
        record={'kind':kind,'symbol':symbol,'request':params,'fetched_at':observed,'historical_available_at':None,'fields':result.fields,'rows':rows}
        name=f'{len(manifest["files"]):05d}-{symbol}-{kind}.json';(output/name).write_text(encode(record))
        manifest['files'].append({'path':name,'rows':len(rows),'sha256':digest(record),'status':'received' if rows else 'no_data'})
        (output/'manifest.json').write_text(encode(manifest))
    try:
        response=bs.login()
        if response.error_code!='0':raise ValueError('Baostock login: '+response.error_msg)
        logged=True
        for symbol in symbols:
            save('basic',symbol,{},lambda:bs.query_stock_basic(symbol))
            for day in industry_dates:
                save('industry',symbol,{'date':day},lambda:bs.query_stock_industry(symbol,date=day.isoformat()))
            for year in range(start.year,end.year+1):
                for quarter,month in enumerate((3,6,9,12),1):
                    # Include the previous reported quarter when the range begins mid-year.
                    if date(year,month,1)>end:continue
                    save('quarterly_shares',symbol,{'year':year,'quarter':quarter},lambda:bs.query_profit_data(symbol,year=year,quarter=quarter))
            fields='date,code,close,preclose,volume,turn,tradestatus,isST'
            save('daily_status',symbol,{'fields':fields,'start':start,'end':end,'adjustflag':'3'},lambda:bs.query_history_k_data_plus(symbol,fields,start_date=start.isoformat(),end_date=end.isoformat(),frequency='d',adjustflag='3'))
        manifest['status']='completed'
    except Exception as error:
        manifest.update(status='failed',error=str(error));raise
    finally:
        (output/'manifest.json').write_text(encode(manifest))
        try:
            if logged:bs.logout()
        finally:socket.setdefaulttimeout(old)
    return manifest
