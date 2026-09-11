"""Host-managed watch definitions and immutable monitoring snapshots."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import fcntl
from quantlab.experiments.campaign_state import read_checked, write_checked


def now(): return datetime.now(timezone.utc).isoformat()


class WatchStore:
    def __init__(self, output):
        self.output = Path(output).resolve(); self.root = self.output/'_tracking'
        if not self.output.is_dir(): raise ValueError('Watch workspace does not exist')
    def folder(self, watch_id):
        if not isinstance(watch_id, str) or str(UUID(watch_id)) != watch_id:
            raise ValueError('Invalid watch UUID')
        path = self.root/watch_id
        if self.root.is_symlink() or path.is_symlink(): raise ValueError('Watch directory symlink')
        return path
    @contextmanager
    def locked(self, watch_id):
        folder = self.folder(watch_id); folder.mkdir(parents=True, exist_ok=True)
        lock = folder/'watch.lock'
        if lock.is_symlink(): raise ValueError('Watch lock symlink')
        with lock.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try: yield folder
            finally: fcntl.flock(stream, fcntl.LOCK_UN)
    def read(self, watch_id):
        folder = self.folder(watch_id)
        for name in ('definition.json','state.json'):
            p = folder/name
            if p.is_symlink() or p.stat().st_size > 2_000_000:
                raise ValueError('Invalid watch record')
        definition = read_checked(folder/'definition.json')
        state = read_checked(folder/'state.json')
        if definition.get('watch_id') != watch_id or state.get('watch_id') != watch_id:
            raise ValueError('Watch identity mismatch')
        return definition, state
    def snapshot(self, watch_id, key):
        if not isinstance(key,str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid snapshot key')
        folder = self.folder(watch_id)/'snapshots'; path = folder/(key+'.json')
        if folder.is_symlink() or path.is_symlink() or path.stat().st_size > 2_000_000:
            raise ValueError('Invalid monitoring snapshot')
        value = read_checked(path)
        if value.get('snapshot_id') != key or value.get('watch_id') != watch_id:
            raise ValueError('Snapshot identity mismatch')
        return value
    def initialize(self, watch_id, definition):
        with self.locked(watch_id) as folder:
            target = folder/'definition.json'
            if target.exists():
                old = read_checked(target)
                if {k:v for k,v in old.items() if k != 'created_at'} != definition:
                    raise ValueError('Same watch ID cannot refer to a different definition')
            else: write_checked(target, {**definition,'created_at':now()})
            state = folder/'state.json'
            if not state.exists():
                write_checked(state, {'watch_id':watch_id,'active':True,
                    'history':[],'refresh_requests':[],'updated_at':now()})
    def publish(self, watch_id, value, expected_latest):
        with self.locked(watch_id) as folder:
            _, state = self.read(watch_id)
            if not state['active']: raise ValueError('Watch is paused')
            key = value['snapshot_id']; history = state['history']
            if key in history: return self.snapshot(watch_id,key), False
            if (history[-1] if history else None) != expected_latest:
                raise ValueError('Watch advanced during calculation; refresh its state and retry')
            if len(history) >= 5000: raise ValueError('Snapshot history budget reached')
            directory = folder/'snapshots'
            if directory.is_symlink(): raise ValueError('Snapshot directory symlink')
            directory.mkdir(exist_ok=True); target = directory/(key+'.json')
            if target.exists():
                saved = self.snapshot(watch_id,key)
                if saved['previous_snapshot_id'] != expected_latest:
                    raise ValueError('Orphan snapshot belongs to a different revision chain')
                value = saved
            else: write_checked(target, value)
            state['history'].append(key); state['updated_at'] = now()
            write_checked(folder/'state.json', state)
            return value, True
    def add_request(self, watch_id, request):
        with self.locked(watch_id) as folder:
            _, state = self.read(watch_id)
            if not state['active']: raise ValueError('Watch is paused')
            old = next((r for r in state['refresh_requests'] if r['proposal_id']==request['proposal_id']),None)
            if old is not None:
                if old != request: raise ValueError('Refresh request conflict')
                return
            if len(state['refresh_requests']) >= 500: raise ValueError('Refresh request history budget reached')
            state['refresh_requests'].append(request); state['updated_at'] = now()
            write_checked(folder/'state.json',state)
    def set_active(self, watch_id, active):
        if type(active) is not bool: raise ValueError('Active must be boolean')
        with self.locked(watch_id) as folder:
            _, state = self.read(watch_id)
            state.update(active=active,updated_at=now()); write_checked(folder/'state.json',state)
    def list(self):
        if self.root.is_symlink(): raise ValueError('Watch root symlink')
        if not self.root.exists(): return {'watches':[],'unreadable':0}
        rows = []; skipped = 0
        for folder in self.root.iterdir():
            if not folder.is_dir() and not folder.is_symlink(): continue
            try:
                definition, state = self.read(folder.name)
                rows.append({'watch_id':folder.name,'name':definition['name'],
                    'factor_id':definition['rule']['config']['factor_id'],
                    'base_run_id':definition['base_run_id'],'active':state['active'],
                    'snapshots':len(state['history']),'updated_at':state['updated_at']})
            except (OSError,ValueError,KeyError,TypeError): skipped += 1
        return {'watches':sorted(rows,key=lambda r:r['updated_at'],reverse=True),
                'unreadable':skipped}
