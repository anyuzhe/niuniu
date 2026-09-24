"""Low-cost A-share live quotes from Tencent/Eastmoney/Sina with fail-closed consensus.

These are public webpage quote interfaces, not official exchange feeds. The adapter
never upgrades them to Strict PIT and does not promise SLA or long-term endpoint stability.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from itertools import combinations
from statistics import median
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
import hashlib,json,re,time

from quantlab.storage.codec import digest
from .decision import SYMBOL

TZ=ZoneInfo('Asia/Shanghai')
PROVIDER_ID='public-web-consensus-v1'
SOURCE_ORDER=('tencent','eastmoney','sina')
MAX_SYMBOLS=200
HTTP_TIMEOUT=5
MAX_BODY=2_000_000
ALLOWED_HOSTS={'qt.gtimg.cn','hq.sinajs.cn','push2.eastmoney.com'}

def _symbols(values):
    if not isinstance(values,list) or not values or len(values)>MAX_SYMBOLS:return _bad('symbols须为1–200只证券')
    result=[]
    for value in values:
        if not isinstance(value,str) or not SYMBOL.fullmatch(value.lower()):return _bad('symbol须为sh/sz/bj.XXXXXX')
        value=value.lower()
        if value not in result:result.append(value)
    return result


def _bad(message):raise ValueError(message)
def _positive(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if value>0 else None

def _nonnegative(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if value>=0 else None

def _iso_local(value,fmt):
    try:return datetime.strptime(value,fmt).replace(tzinfo=TZ).isoformat()
    except (TypeError,ValueError):return None

def _http(url,encoding='utf-8',headers=None):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS:raise ValueError('public quote host is not allowlisted')
    req=Request(url,headers={'User-Agent':'Mozilla/5.0',**(headers or {})})
    with urlopen(req,timeout=HTTP_TIMEOUT) as response:
        final=urlparse(response.geturl())
        if final.scheme!='https' or final.hostname not in ALLOWED_HOSTS:raise ValueError('public quote redirect left allowlist')
        body=response.read(MAX_BODY+1)
    if len(body)>MAX_BODY:raise ValueError('public quote response exceeds 2MB')
    return body.decode(encoding,'replace'),hashlib.sha256(body).hexdigest()

def _parse_tencent(text,response_hash):
    rows={}
    for code,body in re.findall(r'v_([a-z]{2}\d{6})="([^"]*)";',text):
        fields=body.split('~')
        if len(fields)<38:continue
        symbol=code[:2]+'.'+code[2:];trade=fields[35].split('/') if len(fields)>35 else []
        volume=_nonnegative(trade[1]) if len(trade)>1 else _nonnegative(fields[6])
        amount=_nonnegative(trade[2]) if len(trade)>2 else None
        rows[symbol]={'source':'tencent','symbol':symbol,'name':fields[1],
            'last':_positive(fields[3]),'previous_close':_positive(fields[4]),'open':_positive(fields[5]),
            'high':_positive(fields[33]),'low':_positive(fields[34]),
            'volume':volume*100 if volume is not None else None,'amount':amount,
            'bid1':_positive(fields[9]),'ask1':_positive(fields[19]),
            'as_of':_iso_local(fields[30],'%Y%m%d%H%M%S'),'response_hash':response_hash}
    return rows


def _parse_sina(text,response_hash):
    rows={}
    for code,body in re.findall(r'var hq_str_([a-z]{2}\d{6})="([^"]*)";',text):
        fields=body.split(',')
        if len(fields)<32:continue
        symbol=code[:2]+'.'+code[2:]
        stamp=_iso_local(fields[30]+' '+fields[31],'%Y-%m-%d %H:%M:%S')
        rows[symbol]={'source':'sina','symbol':symbol,'name':fields[0],
            'open':_positive(fields[1]),'previous_close':_positive(fields[2]),'last':_positive(fields[3]),
            'high':_positive(fields[4]),'low':_positive(fields[5]),'bid1':_positive(fields[6]),'ask1':_positive(fields[7]),
            'volume':_nonnegative(fields[8]),'amount':_nonnegative(fields[9]),'as_of':stamp,'response_hash':response_hash}
    return rows

def _parse_eastmoney(text,response_hash):
    """Batch ``ulist.np`` response (``fltt=2``: decimal prices; f5 in lots, f6 in yuan)."""
    try:rows=(json.loads(text).get('data') or {}).get('diff') or []
    except (ValueError,TypeError,AttributeError):return {}
    if isinstance(rows,dict):rows=list(rows.values())
    result={}
    for data in rows:
        if not isinstance(data,dict):continue
        code=str(data.get('f12') or '')
        if not re.fullmatch(r'\d{6}',code):continue
        prefix='sh' if str(data.get('f13'))=='1' else ('bj' if code.startswith(('920','4','8')) else 'sz')
        symbol=prefix+'.'+code
        stamp=None
        try:stamp=datetime.fromtimestamp(int(data['f124']),timezone.utc).astimezone(TZ).isoformat()
        except (KeyError,TypeError,ValueError,OSError):pass
        volume=_nonnegative(data.get('f5'))
        result[symbol]={'source':'eastmoney','symbol':symbol,'name':str(data.get('f14') or ''),
            'last':_positive(data.get('f2')),'high':_positive(data.get('f15')),'low':_positive(data.get('f16')),
            'open':_positive(data.get('f17')),'previous_close':_positive(data.get('f18')),
            'bid1':_positive(data.get('f31')),'ask1':_positive(data.get('f32')),
            'volume':volume*100 if volume is not None else None,'amount':_nonnegative(data.get('f6')),
            'as_of':stamp,'response_hash':response_hash}
    return result


def _market_id(symbol):return '1' if symbol.startswith('sh.') else '0'
def _wire(symbol):return symbol.replace('.','')

def _tencent(symbols,http_get):
    codes=','.join(_wire(s) for s in symbols)
    text,h=http_get('https://qt.gtimg.cn/q='+quote(codes,safe=','),'gb18030',{})
    rows=_parse_tencent(text,h);return rows,{'endpoint':'qt.gtimg.cn','hash':h,'responses':len(rows)}


def _sina(symbols,http_get):
    codes=','.join(_wire(s) for s in symbols);headers={'Referer':'https://finance.sina.com.cn/'}
    text,h=http_get('https://hq.sinajs.cn/list='+quote(codes,safe=','),'gb18030',headers)
    rows=_parse_sina(text,h);return rows,{'endpoint':'hq.sinajs.cn','hash':h,'responses':len(rows)}


EM_BATCH=100
EM_MIN_INTERVAL=1.5  # Eastmoney drops connections from an IP that requests faster than this
EM_FIELDS='f12,f13,f14,f2,f5,f6,f15,f16,f17,f18,f31,f32,f124'

def _eastmoney(symbols,http_get):
    """One batch request per 100 symbols (serial), instead of one request per symbol."""
    rows={};hashes=[];errors={}
    headers={'Referer':'https://quote.eastmoney.com/'}
    for index in range(0,len(symbols),EM_BATCH):
        chunk=symbols[index:index+EM_BATCH]
        secids=','.join(_market_id(s)+'.'+s.split('.')[1] for s in chunk)
        url='https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids='+secids+'&fields='+EM_FIELDS
        for attempt in range(2):
            try:
                text,h=http_get(url,'utf-8',headers);hashes.append(h)
                parsed=_parse_eastmoney(text,h)
                rows.update({s:parsed[s] for s in chunk if s in parsed})
                for s in chunk:errors.pop(s,None)
                break
            except Exception as error:
                for s in chunk:errors[s]=type(error).__name__
                if attempt==0:time.sleep(EM_MIN_INTERVAL)
        if index+EM_BATCH<len(symbols):time.sleep(EM_MIN_INTERVAL)
    evidence={'endpoint':'push2.eastmoney.com','hash':digest(hashes),'responses':len(rows),'errors':errors}
    return rows,evidence


def _price_tolerance(value):return max(.011,min(.03,abs(value)*.0002))
def _pair_agrees(a,b,key):
    x=a.get(key);y=b.get(key)
    if x is None or y is None:return False
    center=(x+y)/2
    return abs(x-y)<=_price_tolerance(center)


def _candidate_subsets(quotes):
    ordered=[quotes[name] for name in SOURCE_ORDER if name in quotes]
    for size in range(len(ordered),1,-1):
        for subset in combinations(ordered,size):yield subset


def _choose_subset(quotes,required):
    for subset in _candidate_subsets(quotes):
        if all(all(_pair_agrees(a,b,key) for a,b in combinations(subset,2)) for key in required):
            return list(subset)
    return []

def _first(subset,key):
    for source in SOURCE_ORDER:
        row=next((r for r in subset if r['source']==source),None)
        if row and row.get(key) is not None:return row[key]
    return None


def _execution_profile(subset,prices):
    bid=sum(1 for row in subset if row.get('bid1') and row.get('bid1')>0)
    ask=sum(1 for row in subset if row.get('ask1') and row.get('ask1')>0)
    one_price=max(prices)-min(prices)<1e-9 if prices else True
    if bid>=2 and ask>=2 and not one_price:return 'STANDARD_ACCESS'
    if prices and (one_price or bid==0 or ask==0):return 'QUEUE_DEPENDENT'
    return 'UNKNOWN'


def _consensus_item(symbol,source_rows,frame):
    quotes={source:rows[symbol] for source,rows in source_rows.items() if symbol in rows}
    required=['previous_close','last'] if frame=='AUCTION' else ['previous_close','open','high','low','last']
    subset=_choose_subset(quotes,required)
    if not subset:
        idle=[row for row in quotes.values() if row.get('volume')==0 and row.get('open') is None]
        if len(idle)>=2:
            return None,None,{'symbol':symbol,'reason':'no_trade_today','tradable':False,
                'previous_close':_first(idle,'previous_close'),'sources':sorted(r['source'] for r in idle),
                'note':'至少两源显示当日零成交且无开盘价（停牌或未成交），不输出行情价格'}
        return None,None,{'symbol':symbol,'reason':'fewer_than_two_agreeing_sources','sources':sorted(quotes)}
    values={key:_first(subset,key) for key in required}
    current_keys=('last',) if frame=='AUCTION' else ('open','high','low','last')
    prices=[values[key] for key in current_keys if values.get(key) is not None]
    as_of=[datetime.fromisoformat(row['as_of']) for row in subset if row.get('as_of')]
    if len(as_of)<2:return None,None,{'symbol':symbol,'reason':'source_time_missing','sources':[r['source'] for r in subset]}
    volume_values=[row['volume'] for row in subset if row.get('volume') is not None]
    amount_values=[row['amount'] for row in subset if row.get('amount') is not None]
    item={'symbol':symbol,'name':str(_first(subset,'name') or ''),'previous_close':values['previous_close'],
        'tradable':bool(values['last'] and values['last']>0),'execution_profile':_execution_profile(subset,prices),
        'metrics':{'agreement_sources':[r['source'] for r in subset],
            'source_times':{r['source']:r.get('as_of') for r in subset},
            'source_last':{r['source']:r.get('last') for r in subset},
            'bid1':_first(subset,'bid1'),'ask1':_first(subset,'ask1')}}
    if frame=='AUCTION':item['auction_price']=values['last']
    else:item.update(open=values['open'],high=values['high'],low=values['low'],last=values['last'],
        volume=float(median(volume_values)) if volume_values else None,amount=float(median(amount_values)) if amount_values else None)
    return item,min(as_of).astimezone(TZ).isoformat(),None


class PublicWebConsensusProvider:
    def __init__(self,http_get=None,now_fn=None):
        self.http_get=http_get or _http
        self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
    def capabilities(self):
        return {'format':'niuniu-market-snapshot-provider-v1','provider_id':PROVIDER_ID,
            'provider':'Tencent + Eastmoney + Sina consensus','implemented':True,'live_channel':True,'network':True,
            'frames':['AUCTION','R1','R2','R3'],'full_snapshot':True,'source_hash_required':True,
            'credentials_required':False,'automatic_capture':True,'strict_pit_source_verified':False,
            'source_roles':{'tencent':'primary','eastmoney':'secondary','sina':'fallback_validation'},
            'scope':'Public webpage quotes for research/self-use; no exchange-feed SLA or Strict PIT certification.'}
    def capture(self,trading_day,frame,symbols):
        if frame not in ('AUCTION','R1','R2','R3'):raise ValueError('live provider frame无效')
        symbols=_symbols(symbols);source_rows={};source_evidence={};source_errors={}
        now=self.now_fn()
        if not isinstance(now,datetime) or now.tzinfo is None:raise ValueError('provider now_fn必须返回带时区datetime')
        now=now.astimezone(TZ)
        for name,loader in (('tencent',_tencent),('eastmoney',_eastmoney),('sina',_sina)):
            try:
                rows,evidence=loader(symbols,self.http_get);clean={};rejected={}
                for symbol,row in rows.items():
                    try:stamp=datetime.fromisoformat(row['as_of']).astimezone(TZ)
                    except (TypeError,ValueError,KeyError):rejected[symbol]='timestamp_missing';continue
                    if stamp.date().isoformat()!=trading_day:rejected[symbol]='wrong_trading_day';continue
                    if stamp>now+timedelta(seconds=30):rejected[symbol]='future_timestamp';continue
                    clean[symbol]=row
                evidence={**evidence,'accepted':len(clean),'rejected_timestamps':rejected};source_rows[name]=clean;source_evidence[name]=evidence
            except Exception as error:source_errors[name]=type(error).__name__+': '+str(error)[:160]
        instruments=[];times=[];issues=[]
        for symbol in symbols:
            item,stamp,issue=_consensus_item(symbol,source_rows,frame)
            if item is None:issues.append(issue);continue
            instruments.append(item);times.append(datetime.fromisoformat(stamp))
        if not instruments:raise ValueError('三源未形成任何两源一致的实时证券快照')
        as_of=min(times).astimezone(TZ).isoformat();complete=len(instruments)==len(symbols)
        evidence={'sources':source_evidence,'errors':source_errors,'symbols':symbols,
            'issues':issues,'agreement_policy':'at least 2 sources; price tolerance=max(0.011,min(0.03,2bp*price))'}
        return {'trading_day':trading_day,'frame':frame,'as_of':as_of,'provider':PROVIDER_ID,
            'provider_ref':'tencent:qt.gtimg.cn | eastmoney:push2.eastmoney.com | sina:hq.sinajs.cn',
            'source_hash':digest(evidence),'completeness':'FULL' if complete else 'PARTIAL',
            'strict_pit_source_verified':False,'instruments':instruments,
            'market_metrics':{'requested_symbols':len(symbols),'consensus_symbols':len(instruments),
                'source_counts':{name:len(rows) for name,rows in source_rows.items()},'source_errors':source_errors,
                'source_health':{name:{'response_hash':evidence.get('hash'),'responses':evidence.get('responses',len(source_rows.get(name,{}))),
                    'accepted':evidence.get('accepted',len(source_rows.get(name,{}))),'errors':evidence.get('errors',{}),
                    'rejected_timestamps':evidence.get('rejected_timestamps',{})} for name,evidence in source_evidence.items()},
                'consensus_issues':issues},
            'notes':'腾讯主源、东方财富第二主源、新浪备用校验；公开网页行情仅作为实时研究证据，不认证Strict PIT。'}


__all__=['PROVIDER_ID','PublicWebConsensusProvider','_parse_tencent','_parse_sina','_parse_eastmoney']
