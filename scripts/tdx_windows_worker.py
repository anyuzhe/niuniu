"""Current-user Windows TDX supervisor. Never elevates or clears stop markers.

The preferred long-run mode is offline-only: collect the assigned shard locally
without requiring Mac connectivity, then export verified result bundles later for
physical transfer. Continuous transfer remains available only when explicitly configured.
"""
from __future__ import annotations
import argparse,http.client,json,os,re,subprocess,sys,time
from pathlib import Path,PureWindowsPath

def validate_config(c):
    fields={'machine_name','code_root','data_root','control_root','identity_file','known_hosts_file','cluster_id','shard_id','allow_tunnel_start','offline_only'}
    if not isinstance(c,dict) or set(c)!=fields:raise ValueError('Configuration fields differ')
    if (c['machine_name'],c['shard_id']) not in (('homepc',1),('601',2)):raise ValueError('Machine/shard mismatch')
    if type(c['allow_tunnel_start']) is not bool:raise ValueError('Explicit tunnel-start permission required')
    if type(c['offline_only']) is not bool:raise ValueError('Explicit offline-only flag required')
    if c['machine_name']=='homepc' and c['allow_tunnel_start'] and not c['offline_only']:raise ValueError('HomePc requires operator-started tunnel')
    if not re.fullmatch('[a-f0-9]{64}',c['cluster_id']):raise ValueError('Invalid cluster identity')
    for k in ('code_root','data_root','control_root','identity_file','known_hosts_file'):
        s=c[k]
        if not isinstance(s,str) or '\x00' in s or not PureWindowsPath(s).is_absolute() or s.startswith(('\\\\','//')):raise ValueError('Local absolute path required: '+k)
    return c

def stop_reason(data,control):
    if (Path(control)/'SUPERVISOR_STOP').exists():return 'SUPERVISOR_STOP'
    base=Path(data)/'lake/bronze/provider=tdx'
    if (base/'STOP').exists():return 'USER_STOP'
    if (base/'AUTO_HALT.json').exists():return 'AUTO_HALTED'
    return None

def tunnel_command(c,system_root):
    return [str(PureWindowsPath(system_root)/'System32/OpenSSH/ssh.exe'),'-N','-T','-i',c['identity_file'],
        '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+c['known_hosts_file'],'-o','ExitOnForwardFailure=yes',
        '-o','ConnectTimeout=15','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
        '-L','127.0.0.1:18943:127.0.0.1:18943','tdx-transfer@8.136.98.55']

def worker_command(c):
    python=str(PureWindowsPath(c['code_root'])/'.venv/Scripts/python.exe')
    if c['offline_only']:
        return [python,'-u','-m','quantlab.agent.tdx_collection_cli','--data-root',c['data_root'],'autoresume',
            '--personal-research-only','--seconds','86400','--max-requests','1000000','--max-new-gib','500','--workers','2']
    return [python,'-u','-m','quantlab.agent.tdx_worker_service',
        '--data-root',c['data_root'],'--server-url','http://127.0.0.1:18943','--personal-research-only',
        '--seconds','86400','--max-requests','200000','--max-new-gib','100','--cycle-seconds','120']

def health(cluster):
    con=http.client.HTTPConnection('127.0.0.1',18943,timeout=5)
    try:
        con.request('GET','/health');r=con.getresponse();b=r.read(65537)
        if r.status!=200 or len(b)>65536:return False
        value=json.loads(b)
        if value.get('cluster_id')!=cluster:raise ValueError('Wrong cluster on transfer port')
        return value.get('history_complete') is False
    except (OSError,http.client.HTTPException):return False
    finally:con.close()

def supervise(c):
    validate_config(c)
    if os.name!='nt':raise RuntimeError('Windows supervisor only')
    data=Path(c['data_root']);control=Path(c['control_root']);repo=Path(c['code_root'])
    reason=stop_reason(data,control)
    if reason:return {'state':reason,'started_processes':0}
    if not (data/'catalog/tdx_ingestion.sqlite3').is_file():return {'state':'WAITING_FOR_BOOTSTRAP','started_processes':0}
    sys.path[:0]=[str(repo/'src'),str(control/'runtime-3.2.2')]
    from quantlab.data.tdx_lake import TdxLake,write_json,now
    from quantlab.agent.tdx_distributed import worker_status
    from quantlab.agent.tdx_collection_cli import writer_lease
    from types import SimpleNamespace
    actual=worker_status(TdxLake(data))
    if any(actual[k]!=c[k] for k in ('machine_name','shard_id','cluster_id')):raise ValueError('Installed worker identity mismatch')
    scope=control/'supervisor';scope.mkdir(exist_ok=True)
    env=dict(os.environ,PYTHONUTF8='1',PYTHONPATH=os.pathsep.join(sys.path[:2]))
    ssh=None;worker=None;attempts=0;next_attempt=0.;started=0
    with writer_lease(SimpleNamespace(root=control.resolve(),base=scope.resolve())),(scope/'service.log').open('ab',buffering=0) as log:
        def record(state,**extra):
            value={'state':state,'observed_at':now(),'pid':os.getpid(),'started_processes':started,
                'worker_pid':worker.pid if worker and worker.poll() is None else None,
                'ssh_pid':ssh.pid if ssh and ssh.poll() is None else None,**extra}
            write_json(scope/'state.json',value);return value
        def spawn(command):
            return subprocess.Popen(command,cwd=repo,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while True:
                reason=stop_reason(data,control)
                if reason:return record(reason)
                if c['offline_only']:
                    if worker is None:worker=spawn(worker_command(c));started+=1
                    if worker.poll() is not None:return record('WORKER_EXIT',exit_code=worker.returncode)
                    record('RUNNING_OFFLINE');time.sleep(5);continue
                ready=health(c['cluster_id'])
                if not ready and (ssh is None or ssh.poll() is not None) and time.monotonic()>=next_attempt:
                    if not c['allow_tunnel_start']:
                        record('WAITING_FOR_OPERATOR_TUNNEL');time.sleep(15);continue
                    if attempts>=6:return record('TUNNEL_RETRY_BUDGET')
                    ssh=spawn(tunnel_command(c,os.environ['SystemRoot']));started+=1;attempts+=1
                    next_attempt=time.monotonic()+min(300,30*2**(attempts-1))
                if ready and worker is None:worker=spawn(worker_command(c));started+=1
                if worker is not None and worker.poll() is not None:return record('WORKER_EXIT',exit_code=worker.returncode)
                record('RUNNING' if ready and worker else 'WAITING_FOR_TRANSFER');time.sleep(5)
        finally:
            if worker is not None and worker.poll() is None:
                if stop_reason(data,control):
                    try:worker.wait(timeout=120)
                    except subprocess.TimeoutExpired:worker.terminate()
                else:worker.terminate()
                try:worker.wait(timeout=15)
                except subprocess.TimeoutExpired:worker.kill();worker.wait()
            if ssh is not None and ssh.poll() is None:ssh.terminate();ssh.wait(timeout=15)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args(argv)
    c=validate_config(json.loads(a.config.read_text(encoding='utf-8-sig')));control=Path(c['control_root'])
    try:result=supervise(c)
    except Exception as e:
        (control/'supervisor-error.json').write_text(json.dumps({'state':'SUPERVISOR_ERROR','error':type(e).__name__+': '+str(e),'observed_at':time.time()}),encoding='utf-8');return 1
    (control/'supervisor-last-exit.json').write_text(json.dumps(result),encoding='utf-8');return 0

if __name__=='__main__':raise SystemExit(main())
