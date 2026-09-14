"""Host CLI for P10 Dev Studio. Human merge is explicit; push is intentionally absent."""
from __future__ import annotations

import argparse,json
from pathlib import Path

from quantlab.storage.codec import encode
from quantlab.devstudio.service import DevStudioError,DevStudioService
from quantlab.devstudio.runtime import DevAgentRuntime,DevRuntimeError


def _json(path,maximum=1_000_000):
    target=Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size>maximum:raise ValueError('JSON input invalid or too large')
    value=json.loads(target.read_text())
    if not isinstance(value,dict):raise ValueError('JSON input must be an object')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 P10 Dev Studio；隔离worktree + 动态Subagent + Reviewer + Human Merge Gate')
    parser.add_argument('--output',required=True);parser.add_argument('--repo-root',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    for name in ('create','status','list','run-main','run-ready','run-cycle','diff','merge','cleanup'):
        group.add_argument('--'+name,action='store_true')
    parser.add_argument('--task-id');parser.add_argument('--spec-json');parser.add_argument('--message',default='')
    parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args(argv)
    try:
        service=DevStudioService(Path(args.output),Path(args.repo_root))
        if args.create:
            if not args.spec_json:raise ValueError('--create requires --spec-json')
            data=service.create_task(_json(args.spec_json))
        elif args.list:data={'records':service.list(),'automatic_merge':False,'automatic_push':False}
        else:
            if not args.task_id:raise ValueError('action requires --task-id')
            if args.status:data=service.get(args.task_id)
            elif args.diff:data=service.diff(args.task_id)
            elif args.run_main:data=DevAgentRuntime(service).run_main(args.task_id)
            elif args.run_ready:data=DevAgentRuntime(service).run_ready(args.task_id)
            elif args.run_cycle:data=DevAgentRuntime(service).run_cycle(args.task_id)
            elif args.merge:
                if not args.message.strip():raise ValueError('--merge requires --message')
                data=service.human_merge(args.task_id,args.message.strip(),confirmed=args.confirm)
            else:
                if not args.confirm:raise ValueError('--cleanup requires --confirm')
                data=service.cleanup(args.task_id,force=False)
        print(encode({'ok':True,'data':data}));return 0
    except (DevStudioError,DevRuntimeError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print(encode({'ok':False,'error':{'code':getattr(exc,'code','INVALID_REQUEST'),'message':str(exc)[:800]}}));return 2


if __name__=='__main__':raise SystemExit(main())
