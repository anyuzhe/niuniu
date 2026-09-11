"""Streaming integrity of local research DAGs, independent of display caches."""
from pathlib import Path
from uuid import UUID
import hashlib
import os
import stat
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record_fields
from quantlab.progress import checkpoint

VERSION = 'sha256-research-tree-v1'
DERIVED = {'summary.json','detail.json','identity.json','reproduction.json'}
FIELDS = {'run_id','experiment_id','manifest','status','children','periods','folds','evaluations'}


def file_hash(path):
    if path.is_symlink(): raise ValueError('Evidence file cannot be a symlink')
    if not stat.S_ISREG(path.lstat().st_mode): raise ValueError('Evidence must be a regular file')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode): raise ValueError('Evidence must be a regular file')
        sha = hashlib.sha256()
        while chunk := stream.read(1024*1024):
            checkpoint(); sha.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    if any(getattr(before,k)!=getattr(after,k) for k in fields) or path.is_symlink():
        raise ValueError('Evidence changed while hashing')
    return {'bytes':before.st_size,'sha256':sha.hexdigest()}

def references(record):
    found = []
    def visit(value, depth=0):
        if depth>64: raise ValueError('Archive lineage nesting exceeds limit')
        for key in ('children','periods','folds','evaluations'):
            children = value.get(key,[])
            if not isinstance(children,list): raise ValueError('Invalid archive lineage list')
            for item in children:
                if not isinstance(item,dict): raise ValueError('Invalid archive child')
                if 'run_id' in item and item['run_id'] not in found: found.append(item['run_id'])
                visit(item,depth+1)
    visit(record)
    return found


def snapshot_tree(output, run_id):
    root = Path(output).resolve(); runs = {}; active = set(); file_count = 0
    def visit(identifier):
        nonlocal file_count
        if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:
            raise ValueError('Invalid evidence run UUID')
        if identifier in active: raise ValueError('Cyclic archive lineage')
        if identifier in runs: return
        if len(runs)+len(active)>=4096: raise ValueError('Archive graph exceeds limit')
        folder = root/identifier
        if folder.is_symlink() or not folder.is_dir(): raise ValueError('Missing local evidence archive')
        path = folder/'experiment.json'; before = file_hash(path)
        record = load_record_fields(path,FIELDS)
        if record['run_id']!=identifier or record['experiment_id']!=digest(record['manifest']):
            raise ValueError('Archive identity mismatch')
        files = {}; pending = [folder]
        while pending:
            directory = pending.pop()
            if len(directory.relative_to(folder).parts)>32: raise ValueError('Evidence nesting too deep')
            for item in sorted(directory.iterdir()):
                mode = item.lstat().st_mode
                if stat.S_ISLNK(mode): raise ValueError('Symlink in evidence archive')
                if stat.S_ISDIR(mode): pending.append(item)
                elif stat.S_ISREG(mode):
                    name = item.relative_to(folder).as_posix()
                    if name in DERIVED: continue
                    file_count += 1
                    if file_count>100000: raise ValueError('Evidence file count exceeds limit')
                    files[name] = file_hash(item)
                else: raise ValueError('Special file in evidence archive')
        if files.get('experiment.json')!=before: raise ValueError('Archive changed while reading')
        active.add(identifier); children = references(record)
        for child in children: visit(child)
        active.remove(identifier)
        runs[identifier] = {'experiment_id':record['experiment_id'],'children':children,'files':files}
    visit(run_id)
    return {'version':VERSION,'root_run_id':run_id,'runs':runs,'excluded_derived_files':sorted(DERIVED)}


def verify_tree(output, expected):
    if not isinstance(expected,dict) or expected.get('version')!=VERSION:
        raise ValueError('Missing versioned full-tree receipt; recreate the research package')
    if snapshot_tree(output,expected['root_run_id'])!=expected:
        raise ValueError('Research evidence tree changed: record, descendant or data bytes differ')
