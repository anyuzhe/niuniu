"""Small coordinator-verified pagination witnesses for remote bootstrap only.

Original raw/Parquet pages stay in canonical storage. Workers receive the exact
previous request, hashes, row count and normalized row digest, all pinned by the
operator's transfer SHA. These are NOT source publications or queryable data.
Incoming results still pass the independent canonical original-page verifier.
"""
from __future__ import annotations
import gzip,hashlib,json,shutil,tarfile
from pathlib import Path
from uuid import uuid4
from quantlab.data.tdx_lake import TdxLake,digest,encode,rows_for,now,write_json,safe,is_redirect
from quantlab.data.tdx_sharding import sealed,checked,read_role,ROLE_FILE,validate_assignment,validate_worker_queue
from quantlab.agent.tdx_distributed import file_sha,validate_plan,validate_job,require_disk,_insert_job
from quantlab.agent.tdx_collection_cli import validate_scheduler_policy

FORMAT='tdx-checkpoint-witness-bootstrap-v1'
PREFIX='_checkpoint_witnesses/'
MAX_JSON=64*1024**2

def row_digest(rows):
    return digest([{k:v for k,v in row.items() if k not in ('index','absolute_index')} for row in rows])

def verify_witness(w,job,descriptor,assignment):
    checked(w)
    if w.get('format')!='tdx-pagination-witness-v1' or w.get('assignment_id')!=assignment['assignment_id']:
        raise ValueError('Checkpoint witness identity mismatch')
    if w.get('job_id')!=job['job_id'] or w.get('rows')!=job['rows'] or not w['rows']:
        raise ValueError('Checkpoint witness cursor/row count mismatch')
    for k in ('source_id','raw_sha256','parquet_sha256','manifest_sha256'):
        if w.get(k)!=descriptor.get(k):raise ValueError('Checkpoint witness source hash mismatch')
    for k in ('plan_id','family','symbol','day','offset'):
        if w.get(k)!=job[k]:raise ValueError('Checkpoint witness request mismatch')
    import re
    if not re.fullmatch('[a-f0-9]{64}',w.get('row_digest','')) or w.get('qualification')!='checkpoint_only_not_published':
        raise ValueError('Invalid checkpoint witness qualification/digest')
    return w

def build_witness_bootstrap(full_receipt,output):
    source=Path(full_receipt['path'])
    if source.stat().st_size!=full_receipt['bytes'] or file_sha(source)!=full_receipt['sha256']:raise ValueError('Original bootstrap SHA/size mismatch')
    witnesses=[]
    with tarfile.open(source,'r:') as arc:
        rawbody=arc.extractfile('bundle.json').read(MAX_JSON+1)
        if len(rawbody)>MAX_JSON:raise ValueError('Oversized original bootstrap metadata')
        body=json.loads(rawbody);checked(body,'bundle_id')
        if body['bundle_id']!=full_receipt['bundle_id'] or body.get('format')!='tdx-worker-bootstrap-v1':raise ValueError('Original bootstrap identity mismatch')
        if any(j['chunk'] for j in body['frontier_jobs']):raise ValueError('Saved frontier bytes require the original full bootstrap')
        descriptors={p['job_id']:p for p in body['pages']}
        if set(descriptors)!={j['job_id'] for j in body['checkpoint_jobs']}:
            raise ValueError('Witness mode requires checkpoint-only source pages')
        for i,job in enumerate(body['checkpoint_jobs']):
            item=descriptors[job['job_id']];prefix='pages/'+item['source_id']+'/'
            raw=arc.extractfile(prefix+'response.json.gz').read();pq=arc.extractfile(prefix+'data.parquet').read();mb=arc.extractfile(prefix+'manifest.json').read()
            for data,key in ((raw,'raw_sha256'),(pq,'parquet_sha256'),(mb,'manifest_sha256')):
                if hashlib.sha256(data).hexdigest()!=item[key]:raise ValueError('Original checkpoint bytes changed')
            manifest=json.loads(mb);checked(manifest)
            with gzip.GzipFile(fileobj=__import__('io').BytesIO(raw)) as stream:payload=stream.read(MAX_JSON+1)
            if len(payload)>MAX_JSON:raise ValueError('Oversized original response')
            value=json.loads(payload);request=value['request'];rows=rows_for(job['family'],value['result'])
            if request['job_id']!=job['job_id'] or len(rows)!=job['rows'] or not rows:
                raise ValueError('Original checkpoint request/row count mismatch')
            if digest({'job':job['job_id'],'body':value['result']})!=item['source_id']:raise ValueError('Original source_id mismatch')
            w=sealed({'format':'tdx-pagination-witness-v1','assignment_id':body['assignment']['assignment_id'],
                **{k:job[k] for k in ('job_id','plan_id','family','symbol','day','offset','rows')},
                **{k:item[k] for k in ('source_id','raw_sha256','parquet_sha256','manifest_sha256')},
                'row_digest':row_digest(rows),'qualification':'checkpoint_only_not_published'})
            verify_witness(w,job,item,body['assignment']);witnesses.append(w)
            if i and i%1000==0:print(encode({'phase':'verified_checkpoint_witnesses','count':i,'machine':body['assignment']['machine_name']}),flush=True)
    content=sealed({'format':FORMAT,'source_bundle_id':body['bundle_id'],'source_sha256':full_receipt['sha256'],
        'source_bytes':full_receipt['bytes'],'source_body':body,'witnesses':witnesses,'created_at':now(),'history_complete':False})
    encoded=encode(content).encode()
    if len(encoded)>MAX_JSON:raise ValueError('Witness bootstrap metadata exceeds budget')
    compressed=gzip.compress(encoded,compresslevel=6,mtime=0);sid=hashlib.sha256(compressed).hexdigest()
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);require_disk(output,len(compressed))
    target=output/(sid+'.tar')
    if target.exists():
        if file_sha(target)!=sid:raise ValueError('Transport identity conflict')
    else:
        with target.open('xb') as f:f.write(compressed)
    receipt={'bundle_id':sid,'sha256':sid,'bytes':len(compressed),'path':str(target),'format':FORMAT,
        'source_bundle_id':body['bundle_id'],'source_sha256':full_receipt['sha256'],'source_bytes':full_receipt['bytes'],
        'machine_name':body['assignment']['machine_name'],'shard_id':body['assignment']['shard_id'],
        'checkpoint_witnesses':len(witnesses),'created_at':now()}
    write_json(output/(sid+'.receipt.json'),sealed(receipt));return receipt

def install_witness_bootstrap(destination,path,expected_sha,expected_source_sha):
    path=Path(path);destination=Path(destination).absolute()
    if is_redirect(path) or is_redirect(destination) or file_sha(path)!=expected_sha:raise ValueError('Witness transport path/SHA invalid')
    with gzip.open(path,'rb') as f:raw=f.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:raise ValueError('Oversized witness archive')
    value=json.loads(raw);checked(value)
    if value.get('format')!=FORMAT or value.get('source_sha256')!=expected_source_sha or value.get('history_complete') is not False:
        raise ValueError('Witness source bootstrap binding mismatch')
    body=value['source_body'];checked(body,'bundle_id')
    if body['bundle_id']!=value['source_bundle_id'] or body.get('format')!='tdx-worker-bootstrap-v1':raise ValueError('Witness original metadata mismatch')
    plan=body['plan'];pid=body['plan_id'];policy=body['policy'];validate_plan(plan,pid);validate_scheduler_policy(policy,pid)
    assignment=validate_assignment(body['assignment'],plan,pid,policy['policy_id'])
    if destination.exists() and any(destination.iterdir()):
        role=read_role(TdxLake(destination))
        if role and role.get('role')=='worker' and role.get('bootstrap_id')==expected_sha and role.get('bootstrap_sha256')==expected_sha:
            return {'already_installed':True,'shard_id':assignment['shard_id'],'data_root':str(destination)}
        raise ValueError('Nonempty worker root cannot be overwritten')
    frontier=[validate_job(j,assignment,plan) for j in body['frontier_jobs']]
    prior=[validate_job(j,assignment,plan) for j in body['checkpoint_jobs']]
    ids=[j['job_id'] for j in frontier+prior]
    if len(ids)!=len(set(ids)) or any(j['chunk'] for j in frontier):raise ValueError('Unsupported saved frontier/duplicate jobs')
    descriptors={p['job_id']:p for p in body['pages']};witnesses={w['job_id']:w for w in value['witnesses']}
    if len(witnesses)!=len(value['witnesses']) or set(witnesses)!=set(descriptors) or set(witnesses)!={j['job_id'] for j in prior}:
        raise ValueError('Witness inventory mismatch')
    endings=set()
    for job in prior:
        verify_witness(witnesses[job['job_id']],job,descriptors[job['job_id']],assignment)
        endings.add((job['family'],job['symbol'],job['day'],job['offset']+job['rows']))
    for job in frontier:
        if job['offset'] and (job['family'].startswith('bars_') or job['family']=='trades') and (job['family'],job['symbol'],job['day'],job['offset']) not in endings:
            raise ValueError('Missing exact checkpoint witness for frontier')
    destination.parent.mkdir(parents=True,exist_ok=True);require_disk(destination.parent,len(raw)*3)
    stage=destination.parent/('.'+destination.name+'.witness-'+str(uuid4()));stage.mkdir()
    try:
        lake=TdxLake(stage,create=True);assert lake.add_plan(plan)==pid
        with lake.db() as c:
            c.execute('CREATE TABLE checkpoint_witnesses(job_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,body TEXT NOT NULL)')
            for job in prior:
                w=witnesses[job['job_id']]
                c.execute('INSERT INTO checkpoint_witnesses VALUES (?,?,?)',(job['job_id'],w['source_id'],encode(w)))
                _insert_job(c,{**job,'state':'CHECKPOINT','chunk':PREFIX+w['source_id']})
            for job in frontier:_insert_job(c,job)
            c.commit()
        write_json(lake.base/'active-plan.json',{'plan_id':pid,'created_at':now()});write_json(lake.base/'scheduler-policy.json',policy)
        write_json(lake.base/ROLE_FILE,sealed({'role':'worker','assignment':assignment,'bootstrap_id':expected_sha,'bootstrap_sha256':expected_sha,
            'source_bootstrap_id':value['source_bundle_id'],'source_bootstrap_sha256':expected_source_sha,
            'checkpoint_mode':'verified_digest_witness_v1','witness_checksums':{k:w['checksum'] for k,w in witnesses.items()},
            'baseline_queue_counts':body['baseline_queue_counts'],'created_at':now()}))
        (lake.base/'STOP').write_text('BOOTSTRAP_AWAITING_BOUNDED_ACCEPTANCE',encoding='utf-8');validate_worker_queue(lake,assignment)
        if destination.exists():destination.rmdir()
        stage.rename(destination);TdxLake(destination,create=True)
        return {'already_installed':False,'data_root':str(destination),'shard_id':assignment['shard_id'],'symbols':assignment['symbol_count'],
            'frontier_jobs':len(frontier),'checkpoint_witnesses':len(prior),'stop_requested':True,'history_complete':False}
    finally:
        if stage.exists():shutil.rmtree(stage)

def previous_witness_digest(lake,previous):
    role=read_role(lake)
    if not role or role.get('role')!='worker' or role.get('checkpoint_mode')!='verified_digest_witness_v1' or previous['state']!='CHECKPOINT':
        raise ValueError('MISSING_CHECKPOINT: invalid witness role/state')
    with lake.db(readonly=True) as c:row=c.execute('SELECT body FROM checkpoint_witnesses WHERE job_id=?',(previous['job_id'],)).fetchone()
    if row is None:raise ValueError('MISSING_CHECKPOINT: witness missing')
    w=json.loads(row[0]);checked(w)
    if role['witness_checksums'].get(previous['job_id'])!=w['checksum'] or previous['chunk']!=PREFIX+w['source_id']:
        raise ValueError('MISSING_CHECKPOINT: witness checksum changed')
    verify_witness(w,previous,w,role['assignment'])
    return w['row_digest']

def transport_variant(exchange,bid,canonical_bootstraps):
    exchange=Path(exchange).resolve();directory=exchange/'bootstrap-variants';meta=safe(exchange,directory/(bid+'.receipt.json'))
    if not meta.is_file():return None
    if meta.stat().st_size>10000:raise ValueError('Oversized transport receipt')
    value=json.loads(meta.read_text(encoding='utf-8'));checked(value);source=canonical_bootstraps.get(value.get('source_bundle_id'))
    if not source or value.get('format')!=FORMAT or value.get('source_sha256')!=source['sha256'] or value.get('source_bytes')!=source['bytes']:
        raise ValueError('Unregistered bootstrap variant')
    if value.get('bundle_id')!=bid or value.get('sha256')!=bid or not 0<value.get('bytes',0)<=MAX_JSON:raise ValueError('Invalid variant identity/size')
    path=safe(exchange,directory/(bid+'.tar'))
    if Path(value['path'])!=path:raise ValueError('Invalid transport variant path')
    return value
