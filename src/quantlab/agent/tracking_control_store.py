"""Durable host authorizations and an in-app inbox, separate from model tools."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
import fcntl
from quantlab.experiments.campaign_state import read_checked, write_checked


def identifier(value):
    if not isinstance(value,str) or str(UUID(value))!=value:
        raise ValueError('Invalid tracking control UUID')
    return value


class ControlStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.root=self.output/'_tracking_control'
        if not self.output.is_dir():raise ValueError('Missing tracking workspace')
    def folder(self,watch_id):
        path=self.root/identifier(watch_id)
        if self.root.is_symlink() or path.is_symlink():raise ValueError('Control path symlink')
        return path
    def get(self,watch_id):
        path=self.folder(watch_id)/'state.json'
        if path.is_symlink():raise ValueError('Control record symlink')
        if not path.exists():return None
        if path.stat().st_size>2_000_000:raise ValueError('Oversized control record')
        state=read_checked(path)
        if state.get('watch_id')!=watch_id:raise ValueError('Control identity mismatch')
        return state
    @contextmanager
    def locked(self,watch_id):
        folder=self.folder(watch_id);folder.mkdir(parents=True,exist_ok=True)
        lock=folder/'control.lock'
        if lock.is_symlink():raise ValueError('Control lock symlink')
        with lock.open('a+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield folder
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    def save(self,state):
        write_checked(self.folder(state['watch_id'])/'state.json',state)
    def list(self):
        if self.root.is_symlink():raise ValueError('Control root symlink')
        values=[];errors=[]
        if self.root.exists():
            for folder in sorted(self.root.iterdir()):
                try:
                    value=self.get(folder.name)
                    if value is not None:values.append(value)
                except (OSError,ValueError,KeyError,TypeError) as error:
                    errors.append({'entry':folder.name,'error':str(error)[:200]})
        return {'controls':values,'errors':errors}
    def revoke(self,watch_id):
        with self.locked(watch_id):
            state=self.get(watch_id)
            if state is None:raise ValueError('No tracking authorization')
            state['enabled']=False;state['status']='revoked';self.save(state)
    def acknowledge(self,watch_id):
        with self.locked(watch_id):
            state=self.get(watch_id)
            if state is None:raise ValueError('No tracking authorization')
            for notice in state['notices'].values():notice['unread']=False
            self.save(state)


def notify(state,key,kind,detail,stamp):
    """Deduplicate by condition; reminders at most once per six hours."""
    notices=state['notices'];old=notices.get(key);text=stamp.isoformat()
    if old is None:
        if len(notices)>=128:
            oldest=min(notices,key=lambda k:notices[k]['last_seen'])
            del notices[oldest]
        notices[key]={'kind':kind,'detail':detail,'first_seen':text,'last_seen':text,
            'last_notified':text,'occurrences':1,'unread':True}
    else:
        old.update(detail=detail,last_seen=text,occurrences=old['occurrences']+1)
        if stamp-datetime.fromisoformat(old['last_notified'])>=timedelta(hours=6):
            old.update(unread=True,last_notified=text)


def control_summary(state):
    if state is None:return {'enabled':False,'status':'not_authorized','network_download':False}
    grant=state['grant']
    return {'watch_id':state['watch_id'],'grant_id':state['grant_id'],
        'enabled':state['enabled'],'status':state['status'],'last_check':state['last_check'],
        'next_check':state['next_check'],'expires_at':grant['expires_at'],
        'end_cap':grant['end'],'max_jobs':grant['max_jobs'],'reserved_jobs':len(state['cycles']),
        'interval_minutes':grant['interval_minutes'],'authorization_source':state['authorization_source'],
        'target_session':state.get('target_session'),'delivery_audit':state.get('delivery_audit'),
        'auto_download':grant.get('auto_download',{'enabled':False}),
        'accepted_publication_id':state.get('accepted_publication_id'),
        'last_data_update':state.get('last_data_update'),'data_update_count':len(state.get('data_updates',[])),
        'cycles':[{k:v for k,v in c.items() if k not in ('spec','guard')} for c in state['cycles']],
        'notices':list(state['notices'].values()),'desktop_open_required':True,
        'last_reconciliation':state.get('last_reconciliation'),
        'network_download':False,'model_can_authorize':False}
