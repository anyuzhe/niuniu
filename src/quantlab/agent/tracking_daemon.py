"""Persistent host scheduler for already-authorized tracking plans; no model approval."""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import fcntl
import os
import signal
import time
from quantlab.agent.tracking_scheduler import TrackingScheduler
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.workbench.jobs import JobQueue


def now():return datetime.now(timezone.utc).isoformat()


def daemon_active(output):
    path=Path(output).resolve()/'_tracking_daemon'/'daemon.lock'
    if not path.exists():return False
    if path.is_symlink():raise ValueError('守护进程锁不能是符号链接')
    with path.open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        else:
            fcntl.flock(stream,fcntl.LOCK_UN);return False


def _worker_busy(output):
    path=Path(output).resolve()/'_jobs'/'worker.lock'
    if not path.exists():return False
    if path.is_symlink():raise ValueError('任务锁不能是符号链接')
    with path.open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        else:
            fcntl.flock(stream,fcntl.LOCK_UN);return False


@contextmanager
def daemon_lock(output):
    root=Path(output).resolve()/'_tracking_daemon'
    if root.is_symlink():raise ValueError('守护进程目录不能是符号链接')
    root.mkdir(exist_ok=True);path=root/'daemon.lock'
    if path.is_symlink():raise ValueError('守护进程锁不能是符号链接')
    with path.open('a+b') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('该工作空间已有跟踪守护进程') from None
        try:yield root
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


class TrackingDaemon:
    def __init__(self,output,data_root,poll_seconds=60):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve()
        if not self.output.is_dir():raise ValueError('产物目录不存在')
        if not self.data_root.is_dir():raise ValueError('行情数据目录不存在')
        if type(poll_seconds) not in (int,float) or not 60<=poll_seconds<=3600:
            raise ValueError('守护检查间隔须为60–3600秒')
        self.poll_seconds=float(poll_seconds);self.queue=None;self.root=self.output/'_tracking_daemon'
    def _queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.data_root)
        return self.queue
    def _release_idle_queue(self):
        if self.queue is None:return
        if any(j['status'] in ('queued','running') for j in self.queue.list()):return
        self.queue.close();self.queue=None
    def heartbeat(self,status,result=None,error=None):
        self.root.mkdir(exist_ok=True)
        value={'format':'tracking-daemon-v1','pid':os.getpid(),'status':status,
            'output':str(self.output),'data_root':str(self.data_root),'poll_seconds':self.poll_seconds,
            'updated_at':now(),'result':result,'error':error}
        write_checked(self.root/'heartbeat.json',value);return value
    def tick(self,*,at=None):
        if self.queue is None and _worker_busy(self.output):
            return self.heartbeat('workspace_busy',{'controls':[],'errors':[],'network_requests':0})
        try:
            result=TrackingScheduler(self.output,self.data_root,self._queue).tick(now=at)
            self._release_idle_queue()
            return self.heartbeat('ok',result)
        except (OSError,ValueError,KeyError,TypeError) as error:
            self._release_idle_queue()
            return self.heartbeat('error',error=type(error).__name__+': '+str(error)[:400])
    def close(self):
        if self.queue is not None:self.queue.close();self.queue=None

    def once(self):
        with daemon_lock(self.output):
            first=self.tick()
            if self.queue is not None:
                self.close()  # wait for an admitted job, then reconcile its durable result once
                return self.tick()
            return first
    def run_forever(self):
        stop=False
        def request_stop(*_):
            nonlocal stop;stop=True
        previous={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
        for s in previous:signal.signal(s,request_stop)
        try:
            with daemon_lock(self.output):
                self.heartbeat('starting')
                while not stop:
                    self.tick()
                    deadline=time.monotonic()+self.poll_seconds
                    while not stop and time.monotonic()<deadline:time.sleep(min(.5,max(0,deadline-time.monotonic())))
                self.close();return self.heartbeat('stopped')
        finally:
            for s,handler in previous.items():signal.signal(s,handler)


def daemon_status(output):
    output=Path(output).resolve();path=output/'_tracking_daemon'/'heartbeat.json';active=daemon_active(output)
    if not path.exists():return {'status':'not_started','active':active,'stale':False}
    value=read_checked(path)
    if value.get('format')!='tracking-daemon-v1':raise ValueError('无效守护进程回执')
    return {**value,'active':active,'stale':bool(not active and value.get('status') not in ('stopped','not_started'))}


def write_launchd(path,output,data_root,poll_seconds=60,python=None):
    import plistlib,sys
    path=Path(path).expanduser().resolve();output=Path(output).resolve();data_root=Path(data_root).resolve()
    TrackingDaemon(output,data_root,poll_seconds)  # validate only; does not run or authorize anything
    python=str(Path(python or sys.executable).resolve());label='com.niuniu.quantlab.tracking'
    logs=output/'_tracking_daemon';logs.mkdir(exist_ok=True)
    payload={'Label':label,'ProgramArguments':[python,'-m','quantlab.agent.tracking_daemon',
        '--output',str(output),'--data-root',str(data_root),'--poll-seconds',str(int(poll_seconds))],
        'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'ProcessType':'Background',
        'StandardOutPath':str(logs/'launchd.out.log'),'StandardErrorPath':str(logs/'launchd.err.log')}
    if path.exists():raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(plistlib.dumps(payload,sort_keys=True))
    return {'path':str(path),'label':label,'loaded':False,'authorization_created':False}


def main():
    import argparse
    from quantlab.storage.codec import encode
    parser=argparse.ArgumentParser(description='牛牛受控跟踪守护进程；只执行已存在的宿主授权')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root')
    parser.add_argument('--poll-seconds',type=float,default=60);parser.add_argument('--once',action='store_true')
    parser.add_argument('--status',action='store_true');parser.add_argument('--write-launchd')
    args=parser.parse_args()
    if args.status:
        print(encode(daemon_status(args.output)));return
    if args.data_root is None:parser.error('--data-root is required unless --status')
    if args.write_launchd:
        print(encode(write_launchd(args.write_launchd,args.output,args.data_root,args.poll_seconds)));return
    daemon=TrackingDaemon(args.output,args.data_root,args.poll_seconds)
    result=daemon.once() if args.once else daemon.run_forever()
    if result is not None:print(encode(result))


if __name__=='__main__':main()
