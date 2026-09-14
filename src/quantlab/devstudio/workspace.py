"""Isolated git worktree and path-scoped file/test primitives for Dev Studio."""
from __future__ import annotations

from pathlib import Path
from subprocess import run,PIPE,TimeoutExpired
from tempfile import NamedTemporaryFile
import hashlib
import os

from .contracts import repo_path


class WorkspaceError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _sha(data):return hashlib.sha256(data).hexdigest()


class GitWorkspace:
    def __init__(self,repo_root):
        self.repo=Path(repo_root).expanduser().resolve()
        if not self.repo.is_dir() or self.repo.is_symlink():raise WorkspaceError('INVALID_REPO','repository path is invalid')
        try:root=self.git('rev-parse','--show-toplevel').strip()
        except WorkspaceError:raise
        if Path(root).resolve()!=self.repo:raise WorkspaceError('INVALID_REPO','repo_root must be git top-level')

    def git(self,*args,cwd=None,input_bytes=None,timeout=60,check=True):
        try:result=run(['git','-C',str(cwd or self.repo),*args],input=input_bytes,stdout=PIPE,stderr=PIPE,timeout=timeout)
        except (OSError,TimeoutExpired) as exc:raise WorkspaceError('GIT_FAILED',str(exc)) from None
        if check and result.returncode:
            raise WorkspaceError('GIT_FAILED',result.stderr.decode('utf-8','replace')[:1000])
        return result.stdout.decode('utf-8','replace')

    def current_branch(self):
        branch=self.git('symbolic-ref','--quiet','--short','HEAD',check=False).strip()
        if not branch:raise WorkspaceError('DETACHED_MAIN','main workspace cannot be detached')
        return branch

    def head(self,cwd=None):return self.git('rev-parse','HEAD',cwd=cwd).strip()

    def clean(self,cwd=None):return not bool(self.git('status','--porcelain=v1','--untracked-files=all',cwd=cwd).strip())

    def ensure_clean(self):
        if not self.clean():raise WorkspaceError('DIRTY_MAIN','repository must be clean before creating or merging DevTask')

    def default_worktree_path(self,task_id):
        root=self.repo.parent/'.niuniu-dev-worktrees'/self.repo.name
        if root.is_symlink():raise WorkspaceError('INVALID_WORKTREE_ROOT','worktree root cannot be symlink')
        return root/task_id

    def create_worktree(self,task_id,base_sha):
        target=self.default_worktree_path(task_id)
        if target.exists():raise WorkspaceError('WORKTREE_EXISTS','DevTask worktree already exists')
        target.parent.mkdir(parents=True,exist_ok=True)
        self.git('worktree','add','--detach',str(target),base_sha,timeout=120)
        if self.head(target)!=base_sha:
            raise WorkspaceError('WORKTREE_BASE_MISMATCH','worktree did not open at frozen base SHA')
        return target.resolve()

    def remove_worktree(self,path,force=False):
        target=Path(path).resolve()
        expected=(self.repo.parent/'.niuniu-dev-worktrees'/self.repo.name).resolve()
        if os.path.commonpath([str(target),str(expected)])!=str(expected):raise WorkspaceError('INVALID_WORKTREE','refusing to remove foreign path')
        if target.exists():self.git('worktree','remove',*(['--force'] if force else []),str(target),timeout=120)
        self.git('worktree','prune')

    @staticmethod
    def _within(root,path):
        return os.path.commonpath([str(root),str(path)])==str(root)

    def safe_path(self,worktree,relative,*,create_parent=False):
        root=Path(worktree).resolve();rel=repo_path(relative);raw=root/rel
        current=root
        for part in Path(rel).parts[:-1]:
            current=current/part
            if current.exists() and current.is_symlink():raise WorkspaceError('SYMLINK_PATH','Dev Studio path cannot traverse symlink')
        if raw.exists() and raw.is_symlink():raise WorkspaceError('SYMLINK_PATH','Dev Studio target cannot be symlink')
        resolved=raw.resolve(strict=False)
        if not self._within(root,resolved):raise WorkspaceError('PATH_ESCAPE','path escapes worktree')
        if create_parent:
            parent=raw.parent;parent.mkdir(parents=True,exist_ok=True)
            if parent.is_symlink() or not self._within(root,parent.resolve()):raise WorkspaceError('PATH_ESCAPE','parent escapes worktree')
        return raw

    def list_files(self,worktree,limit=5000):
        if type(limit) is not int or not 1<=limit<=10000:raise WorkspaceError('INVALID_ARGUMENT','limit out of range')
        output=self.git('ls-files','-co','--exclude-standard','-z',cwd=worktree)
        rows=[]
        for value in output.split('\0'):
            if not value:continue
            try:value=repo_path(value)
            except ValueError:continue
            if value not in rows:rows.append(value)
            if len(rows)>=limit:break
        return rows

    def read_file(self,worktree,relative,max_bytes=200000):
        path=self.safe_path(worktree,relative)
        if not path.is_file():raise WorkspaceError('NOT_FOUND','file not found')
        data=path.read_bytes()
        if len(data)>max_bytes:raise WorkspaceError('FILE_TOO_LARGE','file exceeds read budget')
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:raise WorkspaceError('BINARY_FILE','binary file is not readable by Dev Studio text tool') from None
        return {'path':repo_path(relative),'sha256':_sha(data),'text':text,'bytes':len(data)}

    def write_file(self,worktree,relative,text,expected_sha256=None,max_bytes=500000):
        if not isinstance(text,str):raise WorkspaceError('INVALID_ARGUMENT','text must be string')
        data=text.encode('utf-8')
        if len(data)>max_bytes:raise WorkspaceError('FILE_TOO_LARGE','write exceeds budget')
        path=self.safe_path(worktree,relative,create_parent=True)
        before=path.read_bytes() if path.exists() else None;mode=(path.stat().st_mode & 0o777) if path.exists() else 0o644
        if expected_sha256 is not None and expected_sha256!=(_sha(before) if before is not None else None):
            raise WorkspaceError('STALE_WRITE','file changed since read')
        with NamedTemporaryFile('wb',delete=False,dir=path.parent,prefix='.niuniu-dev-',suffix='.tmp') as stream:
            temporary=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,mode)
        try:temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
        return {'path':repo_path(relative),'before_sha256':_sha(before) if before is not None else None,
            'after_sha256':_sha(data),'bytes':len(data)}

    def search(self,worktree,query,paths=None,max_results=100,max_bytes_per_file=500000):
        if not isinstance(query,str) or not query or len(query)>500:raise WorkspaceError('INVALID_ARGUMENT','query is invalid')
        selected=paths or self.list_files(worktree)
        results=[]
        for relative in selected:
            try:item=self.read_file(worktree,relative,max_bytes_per_file)
            except WorkspaceError:continue
            for number,line in enumerate(item['text'].splitlines(),1):
                if query.casefold() in line.casefold():
                    results.append({'path':item['path'],'line':number,'text':line[:1000]})
                    if len(results)>=max_results:return results
        return results

    def changed_files(self,worktree):
        # NUL-delimited porcelain keeps Unicode and spaces exact; include both sides of rename/copy.
        status=self.git('status','--porcelain=v1','-z','--untracked-files=all',cwd=worktree)
        tokens=status.split('\0');rows=[];index=0
        while index<len(tokens):
            token=tokens[index];index+=1
            if not token or len(token)<4:continue
            code=token[:2];values=[token[3:]]
            if ('R' in code or 'C' in code) and index<len(tokens) and tokens[index]:
                values.append(tokens[index]);index+=1
            for value in values:
                try:value=repo_path(value)
                except ValueError:continue
                if value not in rows:rows.append(value)
        return rows

    def diff(self,worktree,max_bytes=2_000_000):
        tracked=self.git('diff','--binary','HEAD',cwd=worktree).encode()
        # Untracked text is summarized separately to avoid shelling out to no-index repeatedly.
        untracked=[]
        tracked_names={value for value in self.git('ls-files','-z',cwd=worktree).split('\0') if value}
        for rel in self.list_files(worktree):
            if rel not in tracked_names:
                path=self.safe_path(worktree,rel)
                data=path.read_bytes()
                untracked.append({'path':rel,'sha256':_sha(data),'bytes':len(data)})
        if len(tracked)>max_bytes:raise WorkspaceError('DIFF_TOO_LARGE','tracked diff exceeds budget')
        return {'patch':tracked.decode('utf-8','replace'),'untracked':untracked,'changed_files':self.changed_files(worktree)}

    def run_test(self,worktree,argv,timeout=300):
        if not isinstance(argv,list) or not argv:raise WorkspaceError('INVALID_TEST','test argv is required')
        # No shell. Only repository Python test runners are allowed.
        allowed=False
        if len(argv)>=3 and argv[0] in ('python','python3') and argv[1]=='-m' and argv[2] in ('unittest','pytest','compileall'):
            allowed=True
        if not allowed:raise WorkspaceError('TEST_NOT_ALLOWED','only python -m unittest/pytest/compileall is allowed')
        python=self.repo/'.venv/bin/python'
        if not python.is_file():raise WorkspaceError('PYTHON_NOT_FOUND','repository .venv/bin/python is required')
        command=[str(python),*argv[1:]]
        before=self.git('diff','--binary','HEAD',cwd=worktree)
        try:result=run(command,cwd=worktree,stdout=PIPE,stderr=PIPE,timeout=timeout,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        except TimeoutExpired:raise WorkspaceError('TEST_TIMEOUT','test command timed out') from None
        after=self.git('diff','--binary','HEAD',cwd=worktree)
        if before!=after:raise WorkspaceError('TEST_SIDE_EFFECT','test command changed tracked working-tree content')
        stdout=result.stdout.decode('utf-8','replace');stderr=result.stderr.decode('utf-8','replace')
        return {'argv':argv,'returncode':result.returncode,'stdout_tail':stdout[-12000:],'stderr_tail':stderr[-12000:],
            'passed':result.returncode==0}

    def prepare_patch(self,worktree,allowed_paths):
        # Host-only staging inside isolated worktree so untracked files enter the patch.
        self.git('add','-A',cwd=worktree)
        raw_names=self.git('diff','--cached','--name-only','-z','HEAD',cwd=worktree)
        from .contracts import paths_overlap
        names=[repo_path(name) for name in raw_names.split('\0') if name]
        if allowed_paths and any(not any(paths_overlap(name,allowed) and (name==allowed or name.startswith(allowed+'/') or allowed.startswith(name+'/')) for allowed in allowed_paths) for name in names):
            raise WorkspaceError('PATH_SCOPE_VIOLATION','final diff contains files outside DevTask allowed_paths')
        patch=self.git('diff','--cached','--binary','HEAD',cwd=worktree).encode('utf-8')
        if len(patch)>8_000_000:raise WorkspaceError('DIFF_TOO_LARGE','merge patch exceeds 8MB')
        return names,patch

    def human_merge(self,worktree,base_sha,base_branch,allowed_paths,message,confirmed=False):
        if confirmed is not True:raise WorkspaceError('CONFIRMATION_REQUIRED','human merge requires explicit confirmation')
        self.ensure_clean()
        if self.current_branch()!=base_branch:raise WorkspaceError('MAIN_BRANCH_CHANGED','main workspace branch changed')
        if self.head()!=base_sha:raise WorkspaceError('MAIN_MOVED','main HEAD changed since DevTask creation')
        names,patch=self.prepare_patch(worktree,allowed_paths)
        if not names:raise WorkspaceError('NO_CHANGES','DevTask has no changes to merge')
        check=run(['git','-C',str(self.repo),'apply','--check','--index','--binary','-'],input=patch,stdout=PIPE,stderr=PIPE)
        if check.returncode:raise WorkspaceError('MERGE_CONFLICT',check.stderr.decode('utf-8','replace')[:1000])
        applied=run(['git','-C',str(self.repo),'apply','--index','--binary','-'],input=patch,stdout=PIPE,stderr=PIPE)
        if applied.returncode:raise WorkspaceError('MERGE_FAILED',applied.stderr.decode('utf-8','replace')[:1000])
        commit=run(['git','-C',str(self.repo),'commit','-m',message],stdout=PIPE,stderr=PIPE)
        if commit.returncode:raise WorkspaceError('COMMIT_FAILED',commit.stderr.decode('utf-8','replace')[:1000])
        return {'commit':self.head(),'files':names,'pushed':False,'branch':base_branch}


__all__=['WorkspaceError','GitWorkspace']
