"""Host authority for DevTask lifecycle, worktree isolation and human merge."""
from __future__ import annotations

from pathlib import Path

from quantlab.storage.codec import digest

from .contracts import paths_overlap,uuid_text
from .store import DevTaskError,DevTaskStore
from .workspace import GitWorkspace,WorkspaceError


class DevStudioError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _translate(exc):
    if isinstance(exc,(DevTaskError,WorkspaceError)):return DevStudioError(exc.code,str(exc))
    return exc


class DevStudioService:
    def __init__(self,output,repo_root,now_fn=None):
        self.output=Path(output).resolve();self.store=DevTaskStore(self.output,now_fn=now_fn)
        try:self.workspace=GitWorkspace(repo_root)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def create_task(self,spec):
        try:
            self.workspace.ensure_clean();branch=self.workspace.current_branch();base=self.workspace.head()
            # Store creates the UUID, so reserve a temporary UUID then persist with same path via low-level state creation.
            from uuid import uuid4
            task_id=str(uuid4());worktree=self.workspace.create_worktree(task_id,base)
            # DevTaskStore.create owns UUID generation. Create then rename worktree if IDs differ would be wasteful,
            # therefore use a private-compatible state initialization here with the reserved id.
            from .contracts import normalize_task_spec
            from .store import FORMAT,_now
            normalized=normalize_task_spec(spec);at=_now(self.store.now_fn)
            state={'format':FORMAT,'task_id':task_id,'spec':normalized,'repo_root':str(self.workspace.repo),
                'base_branch':branch,'base_sha':base,'worktree_path':str(worktree),'state':'DRAFT',
                'created_at':at,'updated_at':at,'subtasks':[],'test_runs':[],'main_acceptance':None,'merge':None,'events':[]}
            with self.store.locked(task_id):
                self.store._event(state,'CREATED','DevTask created at frozen base SHA; no model execution yet.',at);self.store._save(state)
            return state
        except (WorkspaceError,DevTaskError,ValueError) as exc:
            # Best effort cleanup only when worktree was allocated but state failed.
            if 'worktree' in locals():
                try:self.workspace.remove_worktree(worktree,force=True)
                except Exception:pass
            code=getattr(exc,'code','INVALID_ARGUMENT');raise DevStudioError(code,str(exc)) from None

    def get(self,task_id):
        try:return self.store.get(task_id)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def list(self,limit=200):return self.store.list(limit)

    def add_subtask(self,task_id,spec):
        try:return self.store.add_subtask(task_id,spec)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def start_subtask(self,task_id,subtask_id):
        try:sub=self.store.start_subtask(task_id,subtask_id)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None
        if sub['spec']['role']=='REVIEWER':
            fingerprint=self.workspace_fingerprint(task_id)
            try:self.store.set_subtask_runtime_evidence(task_id,subtask_id,'review_workspace_fingerprint',fingerprint)
            except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None
            sub=self.get(task_id);sub=next(s for s in sub['subtasks'] if s['subtask_id']==subtask_id)
        return sub

    def finish_subtask(self,task_id,subtask_id,result):
        try:return self.store.finish_subtask(task_id,subtask_id,result)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def reopen_subtask(self,task_id,subtask_id,instruction=''):
        try:return self.store.reopen_subtask(task_id,subtask_id,instruction)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    @staticmethod
    def _subtask(state,subtask_id):
        sub=next((s for s in state['subtasks'] if s['subtask_id']==subtask_id),None)
        if sub is None:raise DevStudioError('NOT_FOUND','subtask not found')
        return sub

    def workspace_fingerprint(self,task_id):
        state=self.get(task_id)
        try:value=self.workspace.diff(state['worktree_path'])
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None
        return digest({'patch':value['patch'],'untracked':value['untracked'],'changed_files':value['changed_files']})

    def read_file(self,task_id,subtask_id,path):
        state=self.get(task_id);self._subtask(state,uuid_text(subtask_id,'subtask_id'))
        try:return self.workspace.read_file(state['worktree_path'],path)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def search(self,task_id,subtask_id,query,paths=None):
        state=self.get(task_id);self._subtask(state,uuid_text(subtask_id,'subtask_id'))
        try:return self.workspace.search(state['worktree_path'],query,paths)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def write_file(self,task_id,subtask_id,path,text,expected_sha256=None):
        state=self.get(task_id);sub=self._subtask(state,uuid_text(subtask_id,'subtask_id'))
        if sub['status']!='RUNNING' or sub['spec']['role']!='IMPLEMENTER':
            raise DevStudioError('WRITE_FORBIDDEN','only a running IMPLEMENTER may write')
        normalized=path.replace('\\','/').strip('/')
        if not any(normalized==lease or normalized.startswith(lease+'/') for lease in sub['spec']['lease_paths']):
            raise DevStudioError('LEASE_VIOLATION','path is outside Implementer lease')
        try:return self.workspace.write_file(state['worktree_path'],normalized,text,expected_sha256)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def run_test(self,task_id,subtask_id,argv,timeout=300):
        state=self.get(task_id);sub=self._subtask(state,uuid_text(subtask_id,'subtask_id'))
        if sub['status']!='RUNNING' or sub['spec']['role']!='TESTER':raise DevStudioError('TEST_FORBIDDEN','only running TESTER may run tests')
        if argv not in state['spec']['test_commands']:
            raise DevStudioError('TEST_NOT_FROZEN','Tester may run only DevTask test_commands frozen at task creation')
        try:evidence=self.workspace.run_test(state['worktree_path'],argv,timeout)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None
        evidence={**evidence,'workspace_fingerprint':self.workspace_fingerprint(task_id)}
        try:self.store.record_test(task_id,evidence)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None
        return evidence

    def diff(self,task_id,subtask_id=None):
        state=self.get(task_id)
        if subtask_id:self._subtask(state,uuid_text(subtask_id,'subtask_id'))
        try:return self.workspace.diff(state['worktree_path'])
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def audit_changes(self,task_id):
        state=self.get(task_id)
        try:changed=self.workspace.changed_files(state['worktree_path'])
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None
        allowed=state['spec']['allowed_paths']
        implementer_leases=[p for s in state['subtasks'] if s['spec']['role']=='IMPLEMENTER' for p in s['spec']['lease_paths']]
        outside_allowed=[];outside_leases=[]
        for path in changed:
            if allowed and not any(path==scope or path.startswith(scope+'/') for scope in allowed):outside_allowed.append(path)
            if not any(path==lease or path.startswith(lease+'/') for lease in implementer_leases):outside_leases.append(path)
        return {'changed_files':changed,'allowed_paths':allowed,'implementer_leases':implementer_leases,
            'outside_allowed_paths':outside_allowed,'outside_implementer_leases':outside_leases,
            'ok':not outside_allowed and not outside_leases}

    def accept(self,task_id,verdict,summary,evidence=None):
        if str(verdict).upper()=='ACCEPT':
            audit=self.audit_changes(task_id)
            if not audit['ok']:raise DevStudioError('FINAL_DIFF_SCOPE','final diff contains files outside frozen path authority')
            state=self.get(task_id);fingerprint=self.workspace_fingerprint(task_id)
            reviewers=[s for s in state['subtasks'] if s['spec']['role']=='REVIEWER' and s['status']=='DONE' and (s.get('result') or {}).get('verdict')=='PASS']
            if not any(s.get('review_workspace_fingerprint')==fingerprint for s in reviewers):
                raise DevStudioError('STALE_REVIEW','Reviewer PASS does not cover the current final worktree diff')
            for command in state['spec']['test_commands']:
                if not any(r.get('argv')==command and r.get('passed') and r.get('workspace_fingerprint')==fingerprint for r in state['test_runs']):
                    raise DevStudioError('STALE_TESTS','frozen tests do not cover the current final worktree diff')
            evidence=[*(evidence or []),{'change_audit':audit,'workspace_fingerprint':fingerprint}]
        try:return self.store.set_main_acceptance(task_id,verdict,summary,evidence)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def human_merge(self,task_id,message,confirmed=False):
        state=self.get(task_id)
        if state['state']!='READY_FOR_HUMAN':raise DevStudioError('TASK_STATE','DevTask is not ready for human merge')
        audit=self.audit_changes(task_id)
        if not audit['ok']:raise DevStudioError('FINAL_DIFF_SCOPE','final diff failed path authority audit')
        try:merged=self.workspace.human_merge(state['worktree_path'],state['base_sha'],state['base_branch'],
            state['spec']['allowed_paths'],message,confirmed=confirmed)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None
        try:return self.store.mark_merged(task_id,merged)
        except DevTaskError as exc:raise DevStudioError(exc.code,str(exc)) from None

    def cleanup(self,task_id,force=False):
        state=self.get(task_id)
        if state['state']!='MERGED' and not force:raise DevStudioError('TASK_STATE','only merged DevTask may be cleaned without force')
        try:self.workspace.remove_worktree(state['worktree_path'],force=force)
        except WorkspaceError as exc:raise DevStudioError(exc.code,str(exc)) from None
        return {'task_id':task_id,'worktree_removed':True}


__all__=['DevStudioError','DevStudioService']
