"""Host CLI for configured dialogue; it is not a model-facing execution tool."""
import argparse
import json
from contextlib import contextmanager
from threading import RLock
from dataclasses import replace
from pathlib import Path
from quantlab.agent.model_config import load_model_config
from quantlab.agent.chat_runtime import ChatRuntime,probe_model


@contextmanager
def headless_chat_runtime(output, data_root=None, *, allow_granted_research=False, **runtime_options):
    """Own one lazy research queue; opt-in never creates a Research Session Grant.

    Every submission still passes the existing scope, budget, expiry and input-freeze
    checks. On exit, drain and close only this host's queue, including after errors.
    """
    if type(allow_granted_research) is not bool:
        raise ValueError('allow_granted_research 必须为布尔值')
    if allow_granted_research and (data_root is None or not Path(data_root).is_dir()):
        raise ValueError('后台授权研究需要有效 --data-root')
    queue = None
    lock = RLock()

    def get_queue():
        nonlocal queue
        with lock:
            if queue is None:
                from quantlab.workbench.jobs import JobQueue
                queue = JobQueue(output, data_root)
            return queue

    try:
        yield ChatRuntime(output, data_root,
            queue_factory=get_queue if allow_granted_research else None, **runtime_options)
    finally:
        if queue is not None:
            queue.close()


def main(argv=None):
    p=argparse.ArgumentParser(description='牛牛 AI 研究助手；凭据由 Codex 或指定环境变量管理')
    p.add_argument('--output',required=True);p.add_argument('--data-root')
    p.add_argument('--provider',choices=['codex_cli','responses','chat_completions'])
    p.add_argument('--model');p.add_argument('--base-url');p.add_argument('--effort');p.add_argument('--codex-path')
    p.add_argument('--session');p.add_argument('--ask');p.add_argument('--probe',action='store_true')
    p.add_argument('--list-sessions',action='store_true');p.add_argument('--gui',action='store_true')
    p.add_argument('--accept-model-service',action='store_true',help='明确允许向所选服务发送对话与工具摘要')
    p.add_argument('--allow-granted-research',action='store_true',help='仅接入后台共享任务队列；仍须已有有效 Research Session Grant，不创建授权')
    a=p.parse_args(argv)
    if a.allow_granted_research and (not a.data_root or not a.ask or a.gui or a.probe or a.list_sessions):
        p.error('--allow-granted-research 仅用于带 --data-root 和 --ask 的后台对话')
    root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    if a.gui:
        from quantlab.desktop.agent_chat import launch_chat
        return launch_chat(root,a.data_root)
    try:
        config=load_model_config(root)
        config=replace(config,**{k:getattr(a,k) for k in ('provider','model','base_url','effort','codex_path') if getattr(a,k) is not None})
        if a.probe:result=probe_model(config,allow_send=a.accept_model_service)
        else:
            with headless_chat_runtime(root,a.data_root,allow_granted_research=a.allow_granted_research) as runtime:
                if a.list_sessions:result={'conversations':runtime.store.conversations()}
                else:
                    if not a.ask:p.error('提供 --ask、--probe、--list-sessions 或 --gui')
                    cid=a.session or runtime.store.create(a.ask[:60])
                    result=runtime.send(cid,a.ask,config,allow_send=a.accept_model_service)
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False,allow_nan=False));return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
