"""Verified large-file compaction for stopped TDX personal-research lakes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path,PurePosixPath
import hashlib
import json
import shutil

import duckdb

from quantlab.agent.tdx_collection_cli import writer_lease
from quantlab.data.tdx_lake import FAMILIES, PAGE_FILES, TdxLake, digest, now, safe, write_json
from quantlab.data.tdx_sharding import read_role


def _manifest_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _install_archive_rows(lake: TdxLake, pages: list[dict]) -> None:
    with lake.archive_db() as con:
        con.execute('BEGIN IMMEDIATE')
        for page in pages:
            raw = page['raw_bytes'];parquet = page['parquet_bytes'];manifest_bytes = page['manifest_bytes']
            manifest = page['manifest']
            values = (page['source_id'], page['family'], raw, parquet, manifest_bytes,
                      manifest['raw_sha256'], manifest['parquet_sha256'], _manifest_sha(manifest_bytes),
                      manifest['rows'], now())
            old = con.execute('SELECT raw_sha256,parquet_sha256,manifest_sha256,rows FROM page_archive WHERE source_id=?',
                              (page['source_id'],)).fetchone()
            if old:
                if tuple(old) != values[5:9]:
                    raise ValueError('Archived TDX page conflicts with verified live bytes: '+page['source_id'])
            else:
                con.execute('INSERT INTO page_archive VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        con.commit()
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def _materialize_query_rows(lake: TdxLake, pages: list[dict]) -> None:
    by_family: dict[str, list[dict]] = {}
    for page in pages:
        by_family.setdefault(page['family'], []).append(page)
    with duckdb.connect(str(lake.catalog)) as con:
        for family, family_pages in by_family.items():
            table = 'tdx_'+family+'_compacted'
            identifiers = [page['source_id'] for page in family_pages]
            paths = [str(page['source'].folder/'data.parquet') for page in family_pages]
            marks = ','.join('?' for _ in identifiers)
            con.execute('BEGIN TRANSACTION')
            con.execute('DELETE FROM '+table+' WHERE source_id IN ('+marks+')', identifiers)
            con.execute('COMMIT')
            con.execute('BEGIN TRANSACTION')
            con.execute('INSERT INTO '+table+' SELECT * FROM read_parquet(?,union_by_name=true,hive_partitioning=false)', [paths])
            con.execute('COMMIT')
            actual = dict(con.execute('SELECT source_id,count(*) FROM '+table+' WHERE source_id IN ('+marks+') GROUP BY source_id', identifiers).fetchall())
            expected = {page['source_id']: page['manifest']['rows'] for page in family_pages}
            if any(actual.get(source_id, 0) != rows for source_id, rows in expected.items()):
                raise ValueError('Compacted TDX query rows differ from verified page row counts')


def _verify_archive_rows(lake: TdxLake, pages: list[dict]) -> None:
    with lake.archive_db(readonly=True) as con:
        for page in pages:
            row=con.execute('SELECT raw_bytes,parquet_bytes,manifest_bytes FROM page_archive WHERE source_id=? AND family=?',
                            (page['source_id'],page['family'])).fetchone()
            if row is None:raise ValueError('TDX archived page disappeared during verification')
            raw,parquet,manifest_bytes=map(bytes,row)
            manifest=json.loads(manifest_bytes);core={key:value for key,value in manifest.items() if key!='checksum'}
            if core!=page['manifest'] or hashlib.sha256(raw).hexdigest()!=core['raw_sha256'] or hashlib.sha256(parquet).hexdigest()!=core['parquet_sha256'] or hashlib.sha256(manifest_bytes).hexdigest()!=page['manifest_sha256']:
                raise ValueError('TDX archive verification differs from live page: '+page['source_id'])


def _load_live_page(lake: TdxLake, record: dict) -> dict | None:
    source=lake.page_source(record['family'],record['source_id'],record['chunk'])
    if source.folder is None:
        relative=PurePosixPath(record['chunk'].replace('\\','/'))
        folder=safe(lake.root,lake.root.joinpath(*relative.parts))
        return {**record,'residual_folder':folder,'archived_source':source} if folder.is_dir() else None
    raw=source.read_bytes('response.json.gz');parquet=source.read_bytes('data.parquet');manifest_bytes=source.read_bytes('manifest.json')
    manifest=json.loads(manifest_bytes);core={key:value for key,value in manifest.items() if key!='checksum'}
    from quantlab.data.tdx_lake import digest
    if digest(core)!=manifest.get('checksum') or core.get('source_id')!=record['source_id'] or core.get('family')!=record['family']:
        raise ValueError('Page manifest changed')
    if hashlib.sha256(raw).hexdigest()!=core['raw_sha256']:raise ValueError('Page bytes changed: response.json.gz')
    if hashlib.sha256(parquet).hexdigest()!=core['parquet_sha256']:raise ValueError('Page bytes changed: data.parquet')
    return {**record,'source':source,'manifest':core,'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),
            'raw_bytes':raw,'parquet_bytes':parquet,'manifest_bytes':manifest_bytes}


def _cleanup_archived_residual(lake: TdxLake, item: dict) -> None:
    manifest=item['archived_source'].verify()
    with duckdb.connect(str(lake.catalog),read_only=True) as con:
        rows=con.execute('SELECT count(*) FROM tdx_'+item['family']+'_compacted WHERE source_id=?',[item['source_id']]).fetchone()[0]
    if rows!=manifest['rows']:
        raise ValueError('Interrupted TDX compaction lacks materialized query rows: '+item['source_id'])
    folder=safe(lake.root,item['residual_folder'])
    names={path.name for path in folder.iterdir()}
    if not names.issubset(PAGE_FILES):
        raise ValueError('Unexpected file in interrupted TDX page: '+str(folder))
    for filename in names:
        path=safe(lake.root,folder/filename)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['archived_source'].sha256(filename):
            raise ValueError('Interrupted TDX page differs from archive: '+str(path))
    _delete_exact_page_folder(folder)


def _delete_exact_page_folder(folder) -> None:
    names={path.name for path in folder.iterdir()}
    if not names.issubset(PAGE_FILES):raise ValueError('Unexpected file in verified TDX page directory')
    for filename in PAGE_FILES:
        (folder/filename).unlink(missing_ok=True)
    folder.rmdir()


def compact_storage(lake: TdxLake, *, families=FAMILIES, batch_pages=1000, max_pages=None) -> dict:
    """Archive exact page bytes, materialize query rows, then remove small-file copies."""
    families = tuple(families)
    if not families or any(family not in FAMILIES for family in families):
        raise ValueError('Invalid TDX compaction family')
    if type(batch_pages) is not int or not 1 <= batch_pages <= 5000:
        raise ValueError('TDX compaction batch_pages outside supported bounds')
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise ValueError('TDX compaction max_pages outside supported bounds')
    if not (lake.base/'STOP').exists():
        raise ValueError('TDX STOP is required before storage compaction')
    lake.initialize_archive()
    lake.initialize_compacted_catalog(create_views=False)
    with lake.archive_db(readonly=True) as con:
        archived_source_ids={row[0] for row in con.execute('SELECT source_id FROM page_archive')}
    archive_pages_before=len(archived_source_ids)
    started_free = shutil.disk_usage(lake.root).free
    compacted = rows = logical_bytes = 0
    by_family = {family: 0 for family in families}
    with writer_lease(lake):
        with lake.db(readonly=True) as con:
            marks = ','.join('?' for _ in families)
            records = [dict(row) for row in con.execute(
                'SELECT rowid,source_id,family,chunk FROM publications WHERE family IN ('+marks+') ORDER BY rowid', families)]
        cursor=0
        while max_pages is None or compacted < max_pages:
            remaining = batch_pages if max_pages is None else min(batch_pages, max_pages-compacted)
            pages=[]
            while cursor<len(records) and len(pages)<remaining:
                batch=[]
                while cursor<len(records) and len(batch)<remaining-len(pages):
                    record=records[cursor];cursor+=1
                    if record['source_id'] in archived_source_ids:
                        relative=PurePosixPath(record['chunk'].replace('\\','/'))
                        if not safe(lake.root,lake.root.joinpath(*relative.parts)).is_dir():continue
                    batch.append(record)
                if not batch:continue
                with ThreadPoolExecutor(max_workers=min(16,len(batch))) as pool:
                    loaded=[page for page in pool.map(lambda record:_load_live_page(lake,record),batch) if page is not None]
                for item in loaded:
                    if 'residual_folder' in item:_cleanup_archived_residual(lake,item)
                    else:pages.append(item)
            if not pages:
                break
            _install_archive_rows(lake, pages)
            archived_source_ids.update(page['source_id'] for page in pages)
            _materialize_query_rows(lake, pages)
            _verify_archive_rows(lake, pages)
            for page in pages:
                logical_bytes += sum(len(page[key]) for key in ('raw_bytes','parquet_bytes','manifest_bytes'))
                rows += page['manifest']['rows'];by_family[page['family']] += 1
            with ThreadPoolExecutor(max_workers=min(16,len(pages))) as pool:
                list(pool.map(lambda page:_delete_exact_page_folder(page['source'].folder),pages))
            compacted += len(pages)
            with lake.archive_db(readonly=True) as con:archive_pages_total=con.execute('SELECT count(*) FROM page_archive').fetchone()[0]
            write_json(lake.base/'storage-compaction.json', {
                'format': 'tdx-large-file-storage-v1', 'state': 'RUNNING', 'compacted_pages': compacted,
                'compacted_pages_this_run':compacted,'archive_pages_before':archive_pages_before,
                'archive_pages_total':archive_pages_total,
                'rows': rows, 'logical_source_bytes': logical_bytes, 'families': by_family,
                'observed_at': now(), 'history_complete': False})
    lake.initialize_compacted_catalog(create_views=True)
    with lake.archive_db(readonly=True) as con:archive_pages_total=con.execute('SELECT count(*) FROM page_archive').fetchone()[0]
    result = {'format': 'tdx-large-file-storage-v1', 'state': 'COMPLETE', 'compacted_pages': compacted,
              'compacted_pages_this_run':compacted,'archive_pages_before':archive_pages_before,
              'archive_pages_total':archive_pages_total,
              'rows': rows, 'logical_source_bytes': logical_bytes, 'families': by_family,
              'free_bytes_before': started_free, 'free_bytes_after': shutil.disk_usage(lake.root).free,
              'observed_at': now(), 'history_complete': False}
    write_json(lake.base/'storage-compaction.json', result)
    return result


def synchronize_export_history(worker: TdxLake, coordinator: TdxLake) -> dict:
    """Restore missing acknowledged sequence rows from the canonical import ledger."""
    if not (worker.base/'STOP').exists() or not (coordinator.base/'STOP').exists():
        raise ValueError('Worker and coordinator STOP are required before sequence synchronization')
    worker_role=read_role(worker);coordinator_role=read_role(coordinator)
    if not worker_role or worker_role.get('role')!='worker' or not coordinator_role or coordinator_role.get('role')!='coordinator':
        raise ValueError('Worker/coordinator roles required')
    assignment=worker_role['assignment']
    registered={item['assignment_id'] for item in coordinator_role['cluster']['assignments']}
    if assignment['assignment_id'] not in registered or assignment['cluster_id']!=coordinator_role['cluster']['cluster_id']:
        raise ValueError('Worker is not registered with this coordinator')
    with coordinator.db(readonly=True) as con:
        exists=con.execute("SELECT 1 FROM sqlite_master WHERE name='distributed_imports'").fetchone()
        imports=[dict(row) for row in con.execute('SELECT * FROM distributed_imports WHERE assignment_id=? ORDER BY sequence_no',(assignment['assignment_id'],))] if exists else []
    if imports and [row['sequence_no'] for row in imports] != list(range(1,imports[-1]['sequence_no']+1)):
        raise ValueError('Canonical import history is not contiguous')
    installed=0
    with writer_lease(worker):
        with worker.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS distributed_result_bundles(bundle_id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,acked INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,sequence_no INTEGER NOT NULL UNIQUE)')
            for row in imports:
                old=con.execute('SELECT bundle_id,sha256,acked FROM distributed_result_bundles WHERE sequence_no=?',(row['sequence_no'],)).fetchone()
                if old:
                    if old['bundle_id']!=row['bundle_id'] or old['sha256']!=row['sha256'] or not old['acked']:
                        raise ValueError('Worker export sequence conflicts with canonical import ledger')
                    continue
                con.execute('INSERT INTO distributed_result_bundles VALUES (?,?,?,?,?,?,?)',
                            (row['bundle_id'],'',row['sha256'],0,1,row['imported_at'],row['sequence_no']))
                installed+=1
            con.commit()
    return {'assignment_id':assignment['assignment_id'],'canonical_sequences':len(imports),
            'installed_sequences':installed,'next_sequence':(imports[-1]['sequence_no']+1 if imports else 1),
            'history_complete':False}


def merge_local_workers(coordinator: TdxLake, workers: tuple[TdxLake, ...], *, batch_pages=1000) -> dict:
    """Drain stopped local workers through the normal bundle/MERGED receipt path."""
    if type(batch_pages) is not int or not 1<=batch_pages<=5000:
        raise ValueError('Local merge batch_pages outside supported bounds')
    if not (coordinator.base/'STOP').exists() or any(not (worker.base/'STOP').exists() for worker in workers):
        raise ValueError('Coordinator and every worker must be stopped before local merge')
    from quantlab.agent.tdx_distributed import export_results,import_results
    from quantlab.agent.tdx_worker_service import acknowledge,deliver_pending
    summaries=[]
    for worker in workers:
        sequence=synchronize_export_history(worker,coordinator)
        delivered=deliver_pending(worker,canonical_root=coordinator.root)
        bundles=pages=imported=duplicates=0
        while True:
            with worker.db(readonly=True) as con:
                has_exports=con.execute("SELECT 1 FROM sqlite_master WHERE name='distributed_exports'").fetchone()
                if has_exports:
                    remaining=con.execute("""SELECT count(*) FROM publications p JOIN jobs j ON j.chunk=p.chunk
                      LEFT JOIN distributed_exports x ON x.source_id=p.source_id
                      WHERE j.state IN ('SAVED','EMPTY') AND x.source_id IS NULL""").fetchone()[0]
                else:
                    remaining=con.execute("""SELECT count(*) FROM publications p JOIN jobs j ON j.chunk=p.chunk
                      WHERE j.state IN ('SAVED','EMPTY')""").fetchone()[0]
            if not remaining:break
            receipt=export_results(worker,worker.base/'_outbox',max_pages=min(batch_pages,remaining),max_bytes=512*1024**2)
            if not receipt['exported_pages']:raise ValueError('Local merge export made no progress')
            ack=import_results(coordinator,Path(receipt['path']),receipt['sha256'])
            acknowledge(worker,receipt,ack)
            bundles+=1;pages+=receipt['exported_pages'];imported+=ack['imported_pages'];duplicates+=ack['duplicate_pages']
        role=read_role(worker)
        summaries.append({'machine_name':role['assignment']['machine_name'],'assignment_id':role['assignment']['assignment_id'],
                          'restored_sequences':sequence['installed_sequences'],'delivered_pending_bundles':delivered,
                          'new_bundles':bundles,'exported_pages':pages,'imported_pages':imported,'duplicate_pages':duplicates})
    return {'workers':summaries,'state':'MERGED','history_complete':False,'observed_at':now()}


def _retirement_path(worker: TdxLake, chunk: str, family: str, source_id: str, *, checkpoint=False) -> Path:
    relative=PurePosixPath(chunk.replace('\\','/'))
    base=worker.base.relative_to(worker.root).parts
    allowed=(base+('_checkpoints',family,source_id),) if checkpoint else (
        base+(family,'pages',source_id),base+('_empty_pages',family,source_id),
        base+('_stored',family,source_id))
    if relative.parts not in allowed:
        raise ValueError('Worker page path is outside its expected family/source directory: '+chunk)
    return worker.root.joinpath(*relative.parts)


def _retirement_files(worker: TdxLake, expected: dict[Path, str], archived: dict) -> list[Path]:
    """Preflight every deletion target; an orphan or extra file keeps all worker bytes."""
    targets=[]
    roots=[(worker.base/family/'pages',False) for family in FAMILIES]
    roots.extend((worker.base/name,True) for name in ('_empty_pages','_stored','_checkpoints'))
    for root,nested in roots:
        root=safe(worker.root,root)
        if not root.exists():continue
        if root.is_symlink() or not root.is_dir():raise ValueError('Unsafe worker page root: '+str(root))
        parents=list(root.iterdir()) if nested else [root]
        for parent in parents:
            if parent.is_symlink() or not parent.is_dir() or (nested and parent.name not in FAMILIES):
                raise ValueError('Unexpected worker page directory: '+str(parent))
            for folder in parent.iterdir():
                if folder.is_symlink() or not folder.is_dir() or folder not in expected:
                    raise ValueError('Unrecorded worker page; refusing retirement: '+str(folder))
                source_id=folder.name;family=expected[folder]
                names={path.name for path in folder.iterdir()}
                if not names.issubset(PAGE_FILES):
                    raise ValueError('Unexpected file in worker page: '+str(folder))
                hashes=archived[source_id][2:]
                for filename,checksum in zip(PAGE_FILES,hashes):
                    path=folder/filename
                    if path.exists():
                        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
                            raise ValueError('Worker page differs from canonical archive: '+str(path))
                targets.append(folder)
    return targets


def retire_local_worker_pages(coordinator: TdxLake, workers: tuple[TdxLake, ...], *, dry_run=False) -> dict:
    """Remove only exact, stopped worker copies after full canonical and filesystem preflight."""
    if not (coordinator.base/'STOP').exists() or any(not (worker.base/'STOP').exists() for worker in workers):
        raise ValueError('Coordinator and every worker must be stopped before retirement')
    roots=(coordinator,)+workers
    if len({lake.root for lake in roots})!=len(roots):raise ValueError('Duplicate retirement root')
    with ExitStack() as leases:
        for lake in sorted(roots,key=lambda item:str(item.root)):
            leases.enter_context(writer_lease(lake))
        role=read_role(coordinator)
        if not role or role.get('role')!='coordinator':raise ValueError('Canonical coordinator role required')
        cluster=role['cluster'];registered={item['assignment_id'] for item in cluster['assignments']}
        with coordinator.db(readonly=True) as con:
            canonical={row['source_id']:(row['family'],row['rows']) for row in con.execute('SELECT source_id,family,rows FROM publications')}
            imports={row['bundle_id']:(row['sha256'],row['assignment_id'],row['sequence_no'])
                     for row in con.execute('SELECT bundle_id,sha256,assignment_id,sequence_no FROM distributed_imports')}
        with coordinator.archive_db(readonly=True) as con:
            archived={row['source_id']:(row['family'],row['rows'],row['raw_sha256'],row['parquet_sha256'],row['manifest_sha256'])
                      for row in con.execute('SELECT source_id,family,rows,raw_sha256,parquet_sha256,manifest_sha256 FROM page_archive')}
        prepared=[]
        for worker in workers:
            identity=read_role(worker)
            if not identity or identity.get('role')!='worker':raise ValueError('Registered worker role required')
            identity=identity['assignment']
            if identity['cluster_id']!=cluster['cluster_id'] or identity['assignment_id'] not in registered:
                raise ValueError('Worker assignment is not registered with canonical coordinator')
            with worker.db(readonly=True) as con:
                tables={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                publications=[dict(row) for row in con.execute('SELECT source_id,family,rows,chunk FROM publications ORDER BY source_id')]
                exports=dict(con.execute('SELECT source_id,bundle_id FROM distributed_exports'))
                bundles={row['bundle_id']:dict(row) for row in con.execute('SELECT bundle_id,sha256,sequence_no,acked FROM distributed_result_bundles')}
                jobs=[dict(row) for row in con.execute('SELECT job_id,family,state,rows,chunk FROM jobs WHERE chunk IS NOT NULL')]
                witnesses=dict(con.execute('SELECT job_id,source_id FROM checkpoint_witnesses')) if 'checkpoint_witnesses' in tables else {}
            source_ids={row['source_id'] for row in publications}
            if source_ids!=set(exports) or any(not row['acked'] for row in bundles.values()):
                raise ValueError('Worker still has unacknowledged or unexported publications')
            for source_id,bundle_id in exports.items():
                bundle=bundles.get(bundle_id)
                if not bundle or imports.get(bundle_id)!=(bundle['sha256'],identity['assignment_id'],bundle['sequence_no']):
                    raise ValueError('Worker export lacks matching canonical MERGED receipt: '+source_id)
            expected={};publication_chunks={}
            for row in publications:
                source_id=row['source_id'];family=row['family'];count=row['rows']
                if canonical.get(source_id)!=(family,count) or archived.get(source_id,())[:2]!=(family,count):
                    raise ValueError('Canonical archive does not cover worker publication: '+source_id)
                path=_retirement_path(worker,row['chunk'],family,source_id)
                expected[path]=family;publication_chunks[row['chunk']]=(family,count)
            checkpoint_ids=[]
            for job in jobs:
                family=job['family'];state=job['state'];chunk=job['chunk']
                if state in ('SAVED','EMPTY'):
                    if publication_chunks.get(chunk)!=(family,job['rows']):
                        raise ValueError('Worker job/publication chunk mismatch: '+chunk)
                elif state=='CHECKPOINT':
                    source_id=PurePosixPath(chunk.replace('\\','/')).name
                    if archived.get(source_id,())[:2]!=(family,job['rows']):
                        raise ValueError('Canonical archive does not cover worker checkpoint: '+source_id)
                    if chunk.startswith('_checkpoint_witnesses/'):
                        if witnesses.get(job['job_id'])!=source_id:
                            raise ValueError('Worker checkpoint witness is missing or mismatched: '+source_id)
                    else:
                        path=_retirement_path(worker,chunk,family,source_id,checkpoint=True)
                        expected[path]=family
                    checkpoint_ids.append(source_id)
                else:
                    raise ValueError('Unpublished worker job retains unique page bytes: '+chunk)
            targets=_retirement_files(worker,expected,archived)
            core={'format':'tdx-local-worker-retirement-v1','cluster_id':identity['cluster_id'],
                  'assignment_id':identity['assignment_id'],'machine_name':identity['machine_name'],
                  'canonical_root':str(coordinator.root),'publication_count':len(publications),
                  'publication_digest':digest(sorted(source_ids)),'checkpoint_count':len(checkpoint_ids),
                  'checkpoint_digest':digest(sorted(checkpoint_ids)),'history_complete':False}
            prepared.append((worker,core,targets))
        if dry_run:
            return {'state':'VERIFIED_READY','workers':[{'machine_name':core['machine_name'],
                    'publications':core['publication_count'],'checkpoints':core['checkpoint_count'],
                    'physical_page_directories':len(targets)} for _,core,targets in prepared],
                    'canonical_archive_pages':len(archived),'observed_at':now(),'history_complete':False}
        summaries=[]
        for worker,core,targets in prepared:
            marker=worker.base/'retired-to-canonical.json'
            write_json(marker,{**core,'state':'VERIFIED_READY','observed_at':now()})
            for folder in targets:_delete_exact_page_folder(folder)
            write_json(marker,{**core,'state':'RETIRED','observed_at':now()})
            summaries.append({'machine_name':core['machine_name'],'publications':core['publication_count'],
                              'checkpoints':core['checkpoint_count'],'publication_digest':core['publication_digest']})
        return {'state':'RETIRED','workers':summaries,'canonical_archive_pages':len(archived),
                'observed_at':now(),'history_complete':False}
