"""Optional public-provider historical status collection; no PIT timestamp invention."""
from datetime import datetime,timezone
from pathlib import Path
import socket,re
from quantlab.storage.codec import encode,digest


def fetch_status(symbols,start,end,output):
    import baostock as bs
    from importlib.metadata import version
    if any(not re.fullmatch(r'(sh|sz)\.\d{6}',s) for s in symbols):raise ValueError('Baostock status expects sh./sz. symbols')
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    manifest={'provider':'baostock','version':version('baostock'),'fields':'date,code,preclose,tradestatus,isST',
        'start':start,'end':end,'symbols':symbols,'files':[],'status':'running',
        'limitations':'Retrospective daily status, not a history of first publication times. No official price bounds. Do not assign past available_at from session date.'}
    old=socket.getdefaulttimeout();socket.setdefaulttimeout(15);logged_in=False
    try:
        login=bs.login()
        if login.error_code!='0':raise ValueError('Baostock login: '+login.error_msg)
        logged_in=True
        for symbol in symbols:
            query=bs.query_history_k_data_plus(symbol,manifest['fields'],start_date=start.isoformat(),end_date=end.isoformat(),frequency='d',adjustflag='3')
            if query.error_code!='0':raise ValueError('Baostock query: '+query.error_msg)
            rows=[]
            while query.next():
                if query.error_code!='0':raise ValueError('Baostock page: '+query.error_msg)
                rows.append(dict(zip(query.fields,query.get_row_data())))
            if not rows:raise ValueError('No historical status rows: '+symbol)
            if any(r['code']!=symbol or r['isST'] not in ('0','1') or r['tradestatus'] not in ('0','1') for r in rows):raise ValueError('Invalid provider status rows')
            record={'symbol':symbol,'fetched_at':datetime.now(timezone.utc),'historical_available_at':None,'rows':rows}
            path=output/(symbol+'.json');path.write_text(encode(record))
            manifest['files'].append({'path':str(path.resolve()),'rows':len(rows),'sha256':digest(record)})
        manifest['status']='completed'
    except Exception as error:
        manifest.update(status='failed',error=str(error));raise
    finally:
        (output/'manifest.json').write_text(encode(manifest))
        try:
            if logged_in:bs.logout()
        finally:socket.setdefaulttimeout(old)
    return manifest
