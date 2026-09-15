"""Archive official exchange rule documents and bind them to explicit MarketRules records."""
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
import hashlib,json,os

from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode
from quantlab.data.qualification import _official_source,_official_rule_receipt

MAX_BYTES=8_000_000
FORMAT='official-market-rules-v2'


def _aware(value,name):
    try:stamp=datetime.fromisoformat(value) if isinstance(value,str) else value
    except ValueError:raise ValueError(name+' 需要带时区 ISO 时间') from None
    if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise ValueError(name+' 需要带时区 ISO 时间')
    return stamp


def archive_official_rules(data_root,rules_records,urls,publication_times=None,*,
        confirm_publication_time=False,opener=urlopen,now_fn=None):
    root=Path(data_root).resolve();rules=MarketRules(rules_records);urls=list(dict.fromkeys(urls))
    sources={r['source'] for r in rules.records}
    if not sources or any(not _official_source(url) for url in sources|set(urls)):
        raise ValueError('官方规则归档只接受上交所/深交所/北交所HTTPS地址')
    if not sources<=set(urls):raise ValueError('每个MarketRules.source都必须包含在下载URL中')
    if confirm_publication_time is not True:raise ValueError('必须由宿主显式确认每份规则原文的publication time')
    if not isinstance(publication_times,dict) or set(publication_times)!=set(urls):
        raise ValueError('每个URL必须且只能提供一个published_at')
    now_fn=now_fn or (lambda:datetime.now(timezone.utc));publications={}
    for url,value in publication_times.items():
        stamp=_aware(value,'published_at')
        if stamp>_aware(now_fn(),'归档时钟'):raise ValueError('published_at不能晚于当前归档时间')
        publications[url]=stamp
    for record in rules.records:
        if publications[record['source']]>record['available_at']:
            raise ValueError('MarketRules.available_at不能早于来源published_at')
    research=root/'research';receipt_dir=research/'official_market_rules';document_dir=research/'official_rules'
    if receipt_dir.is_symlink() or document_dir.is_symlink():raise ValueError('官方规则归档目录不能是符号链接')
    receipt_dir.mkdir(parents=True,exist_ok=True);document_dir.mkdir(parents=True,exist_ok=True)
    target=receipt_dir/(rules.snapshot_id+'.json')
    if target.exists():
        verified=_official_rule_receipt(root,rules.snapshot_id)
        if not verified['verified']:raise ValueError('既有官方规则回执校验失败：'+verified['reason'])
        current=json.loads(target.read_text());actual={item['url']:item['published_at'] for item in current['sources']}
        expected={url:stamp.isoformat() for url,stamp in publications.items()}
        if actual!=expected:raise ValueError('同一规则快照已有不同来源或publication time回执')
        return {'path':str(target),'rules_snapshot':rules.snapshot_id,'rules':len(rules.records),
            'sources':len(current['sources']),'created':False,'publication_time_confirmed':True}
    evidence=[]
    for url in urls:
        response=opener(Request(url,headers={'User-Agent':'NiuniuResearch/1.0'}),timeout=15)
        final=response.geturl()
        if not _official_source(final):raise ValueError('官方规则下载发生非交易所域名跳转')
        payload=response.read(MAX_BYTES+1)
        if not payload or len(payload)>MAX_BYTES:raise ValueError('官方规则原文为空或超过8MB')
        sha=hashlib.sha256(payload).hexdigest();relative=Path('research/official_rules')/(sha+'.bin');document=root/relative
        if document.exists() and hashlib.sha256(document.read_bytes()).hexdigest()!=sha:raise ValueError('规则归档哈希冲突')
        if not document.exists():
            temporary=document.with_suffix('.tmp');temporary.write_bytes(payload);os.replace(temporary,document)
        fetched=_aware(now_fn(),'归档时钟')
        if publications[url]>fetched:raise ValueError('published_at不能晚于fetched_at')
        evidence.append({'url':url,'path':relative.as_posix(),'sha256':sha,'fetched_at':fetched.isoformat(),
            'published_at':publications[url].isoformat(),'publication_time_confirmed':True})
    receipt={'format':FORMAT,'rules_snapshot':rules.snapshot_id,'rules':rules.records,'sources':evidence}
    temporary=target.with_suffix('.tmp');temporary.write_text(encode(receipt));os.replace(temporary,target)
    verified=_official_rule_receipt(root,rules.snapshot_id)
    if not verified['verified']:raise ValueError('官方规则回执写入后自校验失败：'+verified['reason'])
    return {'path':str(target),'rules_snapshot':rules.snapshot_id,'rules':len(rules.records),
        'sources':len(evidence),'created':True,'publication_time_confirmed':True,
        'scope':'Publication-time receipt + archived exchange bytes + exact supplied records; semantic mapping and fees remain host-reviewed.'}


__all__=['FORMAT','archive_official_rules']
