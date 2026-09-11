"""At-most-once desktop dispatch receipts, independent of research authorization."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import json
import sqlite3
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.storage.codec import digest, encode


def notice_events(output):
    listing = ControlStore(output).list(); events = []; errors = list(listing['errors'])
    for state in listing['controls']:
        try:
            UUID(state['grant_id']); UUID(state['watch_id'])
            for key, notice in state['notices'].items():
                if notice.get('unread') is not True: continue
                stamp = datetime.fromisoformat(notice['last_notified'])
                if stamp.tzinfo is None: raise ValueError('Notice timestamp has no timezone')
                identity = {'watch_id':state['watch_id'], 'grant_id':state['grant_id'],
                    'notice_key':key, 'last_notified':stamp.astimezone(timezone.utc).isoformat()}
                events.append({**identity, 'event_id':digest(identity), 'kind':str(notice['kind'])[:100]})
        except (KeyError, TypeError, ValueError) as error:
            errors.append({'watch_id':state.get('watch_id'), 'error':type(error).__name__})
    events.sort(key=lambda event:(event['last_notified'],event['event_id']), reverse=True)
    return {'events':events, 'errors':errors}

class DeliveryStore:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.directory = self.output/'_notification_delivery'
        self.path = self.directory/'receipts.sqlite3'
        if not self.output.is_dir(): raise ValueError('Notification workspace is missing')
    @contextmanager
    def connection(self, write=False):
        paths = [self.directory, self.path, *[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if any(path.is_symlink() for path in paths): raise ValueError('Notification store symlink')
        if write: self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():
            yield None; return
        db = sqlite3.connect(self.path.as_uri()+('?mode=rwc' if write else '?mode=ro'),
            uri=True, timeout=1, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
            yield db
            if write: db.commit()
        except BaseException:
            if write: db.rollback()
            raise
        finally: db.close()

    def reserve(self, events, *, limit=20, now=None):
        if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('Invalid notification limit')
        if not events: return []
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None: raise ValueError('Notification clock requires timezone')
        reserved = []; stamp = now.astimezone(timezone.utc).isoformat()
        with self.connection(write=True) as db:
            count = db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]
            for event in events:
                identity = {k:event[k] for k in ('watch_id','grant_id','notice_key','last_notified')}
                if event['event_id'] != digest(identity): raise ValueError('Invalid notification identity')
                if datetime.fromisoformat(event['last_notified']) > now: continue
                existing = db.execute('SELECT 1 FROM deliveries WHERE id=?',(event['event_id'],)).fetchone()
                if existing: continue
                if count >= 10000: raise ValueError('通知记录达到10000条上限；应用内提醒不受影响')
                db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?)',
                    (event['event_id'],encode(event),'reserved',stamp,stamp))
                reserved.append(event); count += 1
                if len(reserved) >= limit: break
        return reserved
    def finish(self, events, state):
        if state not in ('handed_to_qt','dispatch_failed','suppressed'):
            raise ValueError('Invalid dispatch result; visibility cannot be certified')
        stamp = datetime.now(timezone.utc).isoformat()
        if not events: return
        with self.connection(write=True) as db:
            for event in events:
                db.execute('UPDATE deliveries SET state=?,updated_at=? WHERE id=? AND state=?',
                    (state,stamp,event['event_id'],'reserved'))
    def history(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 200: raise ValueError('Invalid history limit')
        with self.connection() as db:
            if db is None: return {'total':0,'deliveries':[],'display_confirmed':False}
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='deliveries'").fetchone():
                return {'total':0,'deliveries':[],'display_confirmed':False}
            total = db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]
            rows = db.execute('SELECT * FROM deliveries ORDER BY created_at DESC,id DESC LIMIT ?', (limit,)).fetchall()
            return {'total':total, 'deliveries':[{**dict(row),'payload':json.loads(row['payload'])} for row in rows],
                'display_confirmed':False, 'policy':'Reserved before dispatch; unresolved reservations are not automatically retried. In-app notices remain authoritative.'}


def notification_text(events):
    names = {'snapshot_updated':'跟踪已更新', 'historical_input_revision':'历史输入修订',
        'insufficient_mature_dates':'成熟样本不足', 'missing_or_ineligible':'缺数或资格提醒',
        'reauthorization_required':'需要重新授权', 'failed':'研究失败',
        'cancelled':'任务取消', 'interrupted':'任务中断', 'blocked':'跟踪受阻', 'lost_job':'任务记录缺失',
        'data_series_updated':'数据通道已更新','data_update_failed':'数据下载失败','data_revision_review':'数据修订待确认'}
    counts = {}
    for event in events:
        name = names.get(event['kind'],'其他跟踪提醒'); counts[name] = counts.get(name,0)+1
    body = '；'.join(name+' '+str(count)+'条' for name,count in counts.items())
    return '牛牛研究提醒', body+'。请打开应用内提醒核对。'
