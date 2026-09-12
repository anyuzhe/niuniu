"""Git-first Markdown operating memory for bounded AI roles."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import subprocess

from quantlab.storage.codec import digest

ROLES=('chief_researcher','market_scanner','skeptic','quant_researcher','developer')
MAX_FILES=40
MAX_FILE_BYTES=64_000
MAX_TOTAL_CHARS=120_000


class AgentMemoryError(ValueError):
    pass


def repository_root():
    root=Path(__file__).resolve().parents[3]
    if not (root/'agent_memory'/'README.md').is_file():
        raise AgentMemoryError('找不到 agent_memory/README.md。')
    return root


def _git_dir(root):
    dot=root/'.git'
    if dot.is_dir():return dot
    if dot.is_file():
        text=dot.read_text(encoding='utf-8').strip()
        if text.startswith('gitdir:'):
            value=Path(text.split(':',1)[1].strip())
            return (root/value).resolve() if not value.is_absolute() else value.resolve()
    return None

def memory_git_status(root):
    if _git_dir(root) is None:return {'tracked':False,'dirty':False,'changes':[]}
    try:
        run=subprocess.run(['git','-C',str(root),'status','--porcelain=v1','--','agent_memory'],capture_output=True,text=True,timeout=5,check=False)
    except (OSError,subprocess.SubprocessError):
        raise AgentMemoryError('无法核对 Agent Memory Git 状态。') from None
    if run.returncode!=0:raise AgentMemoryError('无法核对 Agent Memory Git 状态。')
    changes=[line[:200] for line in run.stdout.splitlines() if line.strip()]
    return {'tracked':True,'dirty':bool(changes),'changes':changes[:20]}


def git_commit(root):
    git=_git_dir(root)
    if git is None:return None
    head=git/'HEAD'
    if not head.is_file() or head.is_symlink():return None
    text=head.read_text(encoding='utf-8').strip()
    if len(text)==40 and all(c in '0123456789abcdef' for c in text.lower()):return text.lower()
    if not text.startswith('ref: '):return None
    ref=text[5:].strip();target=git/ref
    if target.is_file() and not target.is_symlink():
        value=target.read_text(encoding='utf-8').strip().lower()
        if len(value)==40:return value
    packed=git/'packed-refs'
    if packed.is_file() and not packed.is_symlink():
        for line in packed.read_text(encoding='utf-8').splitlines():
            if line.startswith(('#','^')):continue
            parts=line.split(' ',1)
            if len(parts)==2 and parts[1]==ref:return parts[0].lower()
    return None


def _markdown_files(root,role_id):
    memory=(root/'agent_memory').resolve()
    selected=[memory/'README.md']
    for folder in ('rules','architecture'):
        selected.extend(sorted((memory/folder).glob('*.md')))
    selected.append(memory/'roles'/(role_id+'.md'))
    for folder in ('experience','incidents'):
        selected.extend(sorted((memory/folder).glob('*.md')))
    unique=[]
    for path in selected:
        if path not in unique:unique.append(path)
    return memory,unique

class AgentMemoryLoader:
    def __init__(self,root=None):
        self.root=(Path(root).resolve() if root else repository_root())
        self.memory=(self.root/'agent_memory').resolve()

    def load(self,role_id):
        if role_id not in ROLES:raise AgentMemoryError('未知 Agent role。')
        state=memory_git_status(self.root)
        if state['dirty']:raise AgentMemoryError('agent_memory 存在未提交修改；请先 review/commit 再作为正式记忆使用。')
        memory,paths=_markdown_files(self.root,role_id)
        if len(paths)>MAX_FILES:raise AgentMemoryError('Agent Memory 文件数量超过预算。')
        files=[];total=0;parts=[]
        for path in paths:
            if not path.exists():raise AgentMemoryError('缺少 Agent Memory 文件：'+str(path.relative_to(self.root)))
            resolved=path.resolve()
            if path.is_symlink() or not resolved.is_relative_to(memory):raise AgentMemoryError('Agent Memory 路径越界或为符号链接。')
            size=path.stat().st_size
            if size>MAX_FILE_BYTES:raise AgentMemoryError('Agent Memory 单文件超过预算。')
            text=path.read_text(encoding='utf-8')
            total+=len(text)
            if total>MAX_TOTAL_CHARS:raise AgentMemoryError('Agent Memory 总上下文超过预算。')
            rel=str(path.relative_to(self.root))
            file_hash=sha256(path.read_bytes()).hexdigest()
            files.append({'path':rel,'sha256':file_hash,'chars':len(text)})
            parts.append('## MEMORY FILE: '+rel+'\n'+text.strip())
        core={'role_id':role_id,'git_commit':git_commit(self.root),'git_tracked':state['tracked'],'files':files}
        return {**core,'memory_hash':digest(core),'text':'\n\n'.join(parts)}

    def status(self):
        state=memory_git_status(self.root)
        return {'root':str(self.root),'git_commit':git_commit(self.root),'git_tracked':state['tracked'],
            'memory_dirty':state['dirty'],'memory_changes':state['changes'],
            'memory_root':str(self.memory),'roles':list(ROLES),
            'vector_database_authoritative':False,'source_of_truth':'git_markdown'}
