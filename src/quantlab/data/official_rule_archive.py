"""Archive official exchange rule documents and bind them to an explicit MarketRules snapshot."""
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
import hashlib,json,os
from quantlab.execution.rules import MarketRules
from quantlab.storage.codec import encode
from quantlab.data.qualification import _official_source,_official_rule_receipt

MAX_BYTES=8_000_000


def archive_official_rules(data_root,rules_records,urls,*,opener=urlopen):
    root=Path(data_root).resolve();rules=MarketRules(rules_records);urls=list(dict.fromkeys(urls))
    sources={r['source'] for r in rules.records}
    if not sources or any(not _official_source(url) for url in sources|set(urls)):
        raise ValueError('官方规则归档只接受上交所/深交所/北交所HTTPS地址')
    if not sources<=set(urls):raise ValueError('每个MarketRules.source都必须包含在下载URL中')
    directory=root/'research/official_rules';directory.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for url in urls:
        response=opener(Request(url,headers={'User-Agent':'NiuniuResearch/1.0'}),timeout=15)
        final=response.geturl()
        if not _official_source(final):raise ValueError('官方规则下载发生非交易所域名跳转')
        payload=response.read(MAX_BYTES+1)
        if not payload or len(payload)>MAX_BYTES:raise ValueError('官方规则原文为空或超过8MB')
        sha=hashlib.sha256(payload).hexdigest();relative=Path('research/official_rules')/(sha+'.bin');target=root/relative
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('规则归档哈希冲突')
        if not target.exists():target.write_bytes(payload)
        evidence.append({'url':url,'path':relative.as_posix(),'sha256':sha,'fetched_at':datetime.now(timezone.utc).isoformat()})
    receipt={'format':'official-market-rules-v1','rules_snapshot':rules.snapshot_id,'sources':evidence}
    target=root/'research/official_market_rules.json';temporary=target.with_suffix('.tmp')
    if target.exists():
        current=json.loads(target.read_text())
        same=lambda rows:{(r['url'],r['path'],r['sha256']) for r in rows}
        if current.get('format')=='official-market-rules-v1' and current.get('rules_snapshot')==rules.snapshot_id and same(current.get('sources',[]))==same(evidence):
            verified=_official_rule_receipt(root,rules.snapshot_id)
            if not verified['verified']:raise ValueError('既有官方规则回执校验失败：'+verified['reason'])
            return {'path':str(target),'rules_snapshot':rules.snapshot_id,'sources':len(evidence),'created':False}
        raise ValueError('已有不同的官方规则回执；请使用新的数据工作空间或人工归档旧回执')
    temporary.write_text(encode(receipt));os.replace(temporary,target)
    verified=_official_rule_receipt(root,rules.snapshot_id)
    if not verified['verified']:raise ValueError('官方规则回执写入后自校验失败：'+verified['reason'])
    return {'path':str(target),'rules_snapshot':rules.snapshot_id,'sources':len(evidence),'created':True,
        'scope':'Archived exchange documents and rule snapshot identity; does not infer missing per-session bounds.'}
