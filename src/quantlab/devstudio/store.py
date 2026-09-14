"""Checksummed durable DevTask state with dynamic subtasks and path leases."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID,uuid4
import fcntl
import time

from quantlab.experiments.campaign_state import read_checked,write_checked
from .contracts import normalize_task_spec,normalize_subtask_spec,normalize_result,paths_overlap,uuid_text

FORMAT='niuniu-devtask-v1'
TERMINAL=('MERGED','CANCELLED')


class DevTaskError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _now(now_fn):
    value=now_fn()
    if not isinstance(value,datetime) or value.tzinfo is None:raise DevTaskError('INVALID_CLOCK','DevTask clock must be timezone-aware')
    return value.astimezone(timezone.utc).isoformat()


class DevTaskStore:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise DevTaskError('INVALID_WORKSPACE','workspace does not exist')
        self.root=self.output/'_devstudio'/'tasks'

    def _folder(self,task_id):return self.root/uuid_text(task_id,'task_id')
    def _path(self,task_id):return self._folder(task_id)/'state.json'

    @contextmanager
    def locked(self,task_id):
        task_id=uuid_text(task_id,'task_id');folder=self._folder(task_id)
        if self.root.is_symlink() or folder.is_symlink():raise DevTaskError('INVALID_WORKSPACE','DevTask path cannot be symlink')
        folder.mkdir(parents=True,exist_ok=True);lock=folder/'task.lock'
        if lock.is_symlink():raise DevTaskError('INVALID_WORKSPACE','DevTask lock cannot be symlink')
        with lock.open('a+b') as stream:
            deadline=time.monotonic()+5.0
            while True:
                try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise DevTaskError('BUSY','DevTask state lock timed out') from None
                    time.sleep(.02)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def _read(self,task_id):
        path=self._path(task_id)
        if not path.exists():raise DevTaskError('NOT_FOUND','DevTask not found')
        try:value=read_checked(path)
        except (OSError,ValueError) as exc:raise DevTaskError('CORRUPT_STATE',str(exc)) from None
        if value.get('format')!=FORMAT or value.get('task_id')!=task_id:raise DevTaskError('CORRUPT_STATE','DevTask identity mismatch')
        return value

    def _save(self,state):
        if len(str(state))>8_000_000:raise DevTaskError('STATE_BUDGET','DevTask state too large')
        write_checked(self._path(state['task_id']),state)

    @staticmethod
    def _event(state,kind,detail,at):
        state['updated_at']=at;state.setdefault('events',[]).append({'at':at,'kind':kind,'detail':str(detail)[:1000]})
        if len(state['events'])>1000:state['events']=state['events'][-1000:]

    def create(self,spec,repo_root,base_branch,base_sha,worktree_path):
        try:spec=normalize_task_spec(spec)
        except ValueError as exc:raise DevTaskError('INVALID_ARGUMENT',str(exc)) from None
        task_id=str(uuid4());at=_now(self.now_fn)
        state={'format':FORMAT,'task_id':task_id,'spec':spec,'repo_root':str(Path(repo_root).resolve()),
            'base_branch':base_branch,'base_sha':base_sha,'worktree_path':str(Path(worktree_path).resolve()),
            'state':'DRAFT','created_at':at,'updated_at':at,'subtasks':[],'test_runs':[],
            'main_acceptance':None,'merge':None,'events':[]}
        with self.locked(task_id):
            self._event(state,'CREATED','DevTask created at frozen base SHA; no model execution yet.',at);self._save(state)
        return state

    def get(self,task_id):
        task_id=uuid_text(task_id,'task_id')
        with self.locked(task_id):return self._read(task_id)

    def list(self,limit=200):
        if type(limit) is not int or not 1<=limit<=2000:raise DevTaskError('INVALID_ARGUMENT','limit out of range')
        if not self.root.exists():return []
        rows=[]
        for folder in sorted((p for p in self.root.iterdir() if p.is_dir()),reverse=True):
            try:rows.append(self._read(folder.name))
            except (DevTaskError,ValueError):continue
            if len(rows)>=limit:break
        return rows

    def add_subtask(self,task_id,spec):
        task_id=uuid_text(task_id,'task_id')
        try:spec=normalize_subtask_spec(spec)
        except ValueError as exc:raise DevTaskError('INVALID_ARGUMENT',str(exc)) from None
        with self.locked(task_id):
            state=self._read(task_id)
            if state['state'] in TERMINAL or state['state']=='READY_FOR_HUMAN':raise DevTaskError('TASK_FROZEN','cannot add subtask in current state')
            if len(state['subtasks'])>=50:raise DevTaskError('SUBTASK_BUDGET','DevTask subtask budget exceeded')
            if spec['role']=='REVIEWER' and any(s['spec']['role']=='REVIEWER' and s['status']!='CANCELLED' for s in state['subtasks']):
                raise DevTaskError('REVIEWER_EXISTS','DevTask permits one independent Reviewer; reopen it instead of creating another')
            known={s['subtask_id'] for s in state['subtasks']}
            if any(dep not in known for dep in spec['depends_on']):raise DevTaskError('INVALID_DEPENDENCY','depends_on references unknown subtask')
            if spec['role']=='REVIEWER':
                prerequisites=[s['subtask_id'] for s in state['subtasks'] if s['spec']['role'] in ('IMPLEMENTER','TESTER')]
                spec['depends_on']=list(dict.fromkeys([*spec['depends_on'],*prerequisites]))
            allowed=state['spec']['allowed_paths']
            if spec['lease_paths'] and allowed:
                for lease in spec['lease_paths']:
                    if not any(lease==scope or lease.startswith(scope+'/') for scope in allowed):
                        raise DevTaskError('PATH_SCOPE_VIOLATION','lease path is outside DevTask allowed_paths')
            for lease in spec['lease_paths']:
                for other in state['subtasks']:
                    for owned in other['spec'].get('lease_paths',[]):
                        if paths_overlap(lease,owned):raise DevTaskError('LEASE_CONFLICT',f'write lease conflicts with {other["subtask_id"]}')
            sub={'subtask_id':str(uuid4()),'spec':spec,'status':'PENDING','created_at':_now(self.now_fn),
                'started_at':None,'finished_at':None,'result':None,'attempts':0}
            if spec['role'] in ('IMPLEMENTER','TESTER'):
                for reviewer in state['subtasks']:
                    if reviewer['spec']['role']=='REVIEWER' and reviewer['status']=='PENDING' and sub['subtask_id'] not in reviewer['spec']['depends_on']:
                        reviewer['spec']['depends_on'].append(sub['subtask_id'])
            state['subtasks'].append(sub);state['state']='PLANNED'
            self._event(state,'SUBTASK_ADDED',sub['subtask_id']+' '+spec['role']+' '+spec['title'],_now(self.now_fn));self._save(state);return sub

    def start_subtask(self,task_id,subtask_id):
        task_id=uuid_text(task_id,'task_id');subtask_id=uuid_text(subtask_id,'subtask_id')
        with self.locked(task_id):
            state=self._read(task_id);sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
            if sub is None:raise DevTaskError('NOT_FOUND','subtask not found')
            if sub['status']=='RUNNING':return sub
            if sub['status']!='PENDING':raise DevTaskError('SUBTASK_STATE','subtask cannot start')
            by_id={s['subtask_id']:s for s in state['subtasks']}
            if any(by_id[d]['status']!='DONE' for d in sub['spec']['depends_on']):raise DevTaskError('DEPENDENCY_BLOCKED','dependencies are not done')
            running=sum(s['status']=='RUNNING' for s in state['subtasks'])
            if running>=state['spec']['max_parallel_subagents']:raise DevTaskError('PARALLEL_BUDGET','max parallel subagents reached')
            at=_now(self.now_fn);sub.update(status='RUNNING',started_at=at,attempts=sub['attempts']+1);state['state']='RUNNING'
            self._event(state,'SUBTASK_STARTED',subtask_id,at);self._save(state);return sub

    def set_subtask_runtime_evidence(self,task_id,subtask_id,key,value):
        task_id=uuid_text(task_id,'task_id');subtask_id=uuid_text(subtask_id,'subtask_id')
        if key not in ('review_workspace_fingerprint','runtime_model','runtime_provider','runtime_effort','requested_effort'):
            raise DevTaskError('INVALID_ARGUMENT','unsupported runtime evidence key')
        with self.locked(task_id):
            state=self._read(task_id);sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
            if sub is None:raise DevTaskError('NOT_FOUND','subtask not found')
            if key in ('runtime_model','runtime_provider'):
                if sub['status'] not in ('RUNNING','DONE'):raise DevTaskError('SUBTASK_STATE','runtime identity may be recorded only for running/done subtask')
            elif sub['status']!='RUNNING':raise DevTaskError('SUBTASK_STATE','subtask is not running')
            sub[key]=value;self._save(state);return value

    def finish_subtask(self,task_id,subtask_id,result):
        task_id=uuid_text(task_id,'task_id');subtask_id=uuid_text(subtask_id,'subtask_id')
        try:result=normalize_result(result)
        except ValueError as exc:raise DevTaskError('INVALID_ARGUMENT',str(exc)) from None
        with self.locked(task_id):
            state=self._read(task_id);sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
            if sub is None:raise DevTaskError('NOT_FOUND','subtask not found')
            if sub['status']=='DONE':return sub
            if sub['status']!='RUNNING':raise DevTaskError('SUBTASK_STATE','subtask is not running')
            leases=sub['spec']['lease_paths']
            if sub['spec']['role']!='IMPLEMENTER' and result['changed_files']:
                raise DevTaskError('WRITE_FORBIDDEN','read-only subtask reported changed files')
            for changed in result['changed_files']:
                if not any(changed==lease or changed.startswith(lease+'/') for lease in leases):
                    raise DevTaskError('LEASE_VIOLATION','subtask changed file outside its path lease')
            at=_now(self.now_fn);sub.update(status='DONE',finished_at=at,result=result)
            if all(s['status'] in ('DONE','CANCELLED') for s in state['subtasks']):state['state']='REVIEW'
            self._event(state,'SUBTASK_FINISHED',subtask_id+' '+result['verdict'],at);self._save(state);return sub

    def reopen_subtask(self,task_id,subtask_id,instruction=''):
        task_id=uuid_text(task_id,'task_id');subtask_id=uuid_text(subtask_id,'subtask_id')
        with self.locked(task_id):
            state=self._read(task_id);sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
            if sub is None:raise DevTaskError('NOT_FOUND','subtask not found')
            if sub['status'] not in ('DONE','BLOCKED'):raise DevTaskError('SUBTASK_STATE','only DONE/BLOCKED subtask may be reopened')
            if instruction:
                if not isinstance(instruction,str) or len(instruction)>12000:raise DevTaskError('INVALID_ARGUMENT','instruction is invalid')
                sub['spec']['instruction']=instruction.strip()
            at=_now(self.now_fn);sub.update(status='PENDING',started_at=None,finished_at=None,result=None)
            state['state']='PLANNED';state['main_acceptance']=None
            self._event(state,'SUBTASK_REOPENED',subtask_id,at);self._save(state);return sub

    def block_subtask(self,task_id,subtask_id,reason):
        task_id=uuid_text(task_id,'task_id');subtask_id=uuid_text(subtask_id,'subtask_id')
        with self.locked(task_id):
            state=self._read(task_id);sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
            if sub is None:raise DevTaskError('NOT_FOUND','subtask not found')
            if sub['status'] not in ('PENDING','RUNNING'):raise DevTaskError('SUBTASK_STATE','subtask cannot be blocked')
            at=_now(self.now_fn);sub.update(status='BLOCKED',finished_at=at,result={'summary':str(reason)[:1000],'changed_files':[],
                'tests':[],'evidence':[],'verdict':'FAIL','stop_reason':str(reason)[:1000]});state['state']='BLOCKED'
            self._event(state,'SUBTASK_BLOCKED',subtask_id+' '+str(reason)[:500],at);self._save(state);return sub

    def record_test(self,task_id,evidence):
        task_id=uuid_text(task_id,'task_id')
        if not isinstance(evidence,dict) or 'argv' not in evidence or 'passed' not in evidence:raise DevTaskError('INVALID_ARGUMENT','test evidence invalid')
        with self.locked(task_id):
            state=self._read(task_id);item={**evidence,'recorded_at':_now(self.now_fn)};state['test_runs'].append(item)
            if len(state['test_runs'])>200:state['test_runs']=state['test_runs'][-200:]
            self._event(state,'TEST_RECORDED',('PASS ' if evidence['passed'] else 'FAIL ')+str(evidence['argv']),item['recorded_at']);self._save(state);return item

    def set_main_acceptance(self,task_id,verdict,summary,evidence=None):
        task_id=uuid_text(task_id,'task_id');verdict=str(verdict).upper()
        if verdict not in ('ACCEPT','REPLAN','BLOCK'):raise DevTaskError('INVALID_ARGUMENT','invalid main verdict')
        with self.locked(task_id):
            state=self._read(task_id)
            running=[s for s in state['subtasks'] if s['status']=='RUNNING']
            if running:raise DevTaskError('SUBTASKS_RUNNING','cannot accept while subtasks are running')
            reviewers=[s for s in state['subtasks'] if s['spec']['role']=='REVIEWER' and s['status']=='DONE']
            reviewer_pass=any((s.get('result') or {}).get('verdict')=='PASS' for s in reviewers)
            required=state['spec']['test_commands']
            test_pass=True
            for command in required:
                if not any(run.get('argv')==command and run.get('passed') for run in state['test_runs']):test_pass=False
            if verdict=='ACCEPT':
                if any(s['status'] not in ('DONE','CANCELLED') for s in state['subtasks']):raise DevTaskError('SUBTASKS_INCOMPLETE','all subtasks must finish')
                if not reviewer_pass:raise DevTaskError('REVIEW_REQUIRED','independent Reviewer PASS is required')
                if not test_pass:raise DevTaskError('TESTS_REQUIRED','all frozen test commands must pass')
            at=_now(self.now_fn);state['main_acceptance']={'verdict':verdict,'summary':str(summary)[:8000],
                'evidence':evidence or [],'at':at,'reviewer_pass':reviewer_pass,'tests_pass':test_pass}
            state['state']='READY_FOR_HUMAN' if verdict=='ACCEPT' else ('PLANNED' if verdict=='REPLAN' else 'BLOCKED')
            self._event(state,'MAIN_'+verdict,str(summary)[:500],at);self._save(state);return state

    def mark_merged(self,task_id,merge):
        task_id=uuid_text(task_id,'task_id')
        with self.locked(task_id):
            state=self._read(task_id)
            if state['state']!='READY_FOR_HUMAN':raise DevTaskError('TASK_STATE','task is not ready for human merge')
            at=_now(self.now_fn);state['merge']={**merge,'at':at};state['state']='MERGED';self._event(state,'HUMAN_MERGED',merge.get('commit',''),at);self._save(state);return state


__all__=['FORMAT','TERMINAL','DevTaskError','DevTaskStore']
