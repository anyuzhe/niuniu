"""Public SDK imports run in their own process; originals are never overwritten."""
from datetime import datetime, timezone, date
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import json
import socket
import subprocess
import sys
import time
from quantlab.data.baostock_catalog import import_plan, LIMITATIONS
from quantlab.storage.codec import encode, digest


def write_json(path, value):
    temporary=path.with_name('.'+str(uuid4())+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as stream:stream.write(encode(value))
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def import_root(output):
    output=Path(output).resolve();root=output/'_market_data'/'baostock'
    if any(p.is_symlink() for p in (output/'_market_data',root)):
        raise ValueError('市场数据目录不能是符号链接')
    root.mkdir(parents=True,exist_ok=True);return root


def collect(spec, directory, sdk=None, *, interval=.25, max_seconds=240):
    plan,calls=import_plan(spec);directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False);(directory/'raw').mkdir()
    if sdk is None:
        import baostock as sdk
    from importlib.metadata import version
    manifest={'format':'baostock-import-v1','import_id':directory.name,'plan':plan,
        'sdk_version':version('baostock'),'created_at':datetime.now(timezone.utc).isoformat(),
        'status':'running','responses':[],'dataset_ready':False,'limitations':LIMITATIONS}
    old_timeout=socket.getdefaulttimeout();socket.setdefaulttimeout(12)
    logged=False;deadline=time.monotonic()+max_seconds;total_rows=0
    def flush():write_json(directory/'manifest.json',manifest)
    flush()
    try:
        result=sdk.login()
        if result.error_code!='0':raise ValueError('Baostock登录失败：'+str(result.error_msg))
        logged=True
        for index,call in enumerate(calls):
            if time.monotonic()>deadline:raise TimeoutError('本批数据抓取达到总时限')
            record={'query':call,'fields':[],'rows':[],
                'requested_at':datetime.now(timezone.utc).isoformat(),
                'historical_available_at':None,'status':'running'}
            try:
                function=getattr(sdk,call['method'],None)
                if function is None:raise ValueError('本机SDK未提供 '+call['method'])
                result=function(**call['params'])
                if result.error_code!='0':raise ValueError(str(result.error_code)+': '+str(result.error_msg))
                fields=list(result.fields)
                if not fields or len(set(fields))!=len(fields) or any(not isinstance(f,str) for f in fields):
                    raise ValueError('供应商返回无效列名')
                record['fields']=fields
                while result.next():
                    if time.monotonic()>deadline:raise TimeoutError('抓取达到时限')
                    if result.error_code!='0':raise ValueError('响应分页失败：'+str(result.error_msg))
                    values=result.get_row_data()
                    if len(values)!=len(fields) or any(not isinstance(v,str) for v in values):
                        raise ValueError('响应行与列定义不一致')
                    row=dict(zip(fields,values))
                    if call['symbol'] and row.get('code')!=call['symbol']:raise ValueError('响应证券不一致')
                    if call['kind'] in ('daily_raw','daily_qfq'):
                        if not plan['start']<=row.get('date','')<=plan['end']:raise ValueError('行情日期超出请求')
                        if row.get('adjustflag')!=call['params']['adjustflag']:raise ValueError('复权口径不一致')
                    if call['kind'] in ('daily_market','daily_etf') and row.get('date')!=call['params']['date']:
                        raise ValueError('每日更新返回非所选日期')
                    record['rows'].append(row);total_rows+=1
                    if len(record['rows'])>25000 or total_rows>1_000_000:raise ValueError('响应超过行数预算')
                if result.error_code!='0':raise ValueError('响应未完整接收：'+str(result.error_msg))
                record['status']='received' if record['rows'] else 'no_data'
            except Exception as error:
                record.update(status='failed',error=type(error).__name__+': '+str(error)[:400])
            record['fetched_at']=datetime.now(timezone.utc).isoformat()
            filename=f'raw/{index:04d}-{call["kind"]}.json';write_json(directory/filename,record)
            raw=(directory/filename).read_bytes()
            manifest['responses'].append({'file':filename,'kind':call['kind'],'symbol':call['symbol'],
                'status':record['status'],'rows':len(record['rows']),'sha256':hashlib.sha256(raw).hexdigest()})
            flush();print('DATA',index+1,len(calls),call['kind'],record['status'],len(record['rows']),flush=True)
            time.sleep(interval)
        manifest['status']='completed_with_errors' if any(r['status']=='failed' for r in manifest['responses']) else 'completed'
    except Exception as error:
        manifest.update(status='failed',error=type(error).__name__+': '+str(error)[:400])
    finally:
        try:
            if logged:sdk.logout()
        except Exception as error:
            manifest['logout_warning']=type(error).__name__
        finally:socket.setdefaulttimeout(old_timeout)
        manifest['finished_at']=datetime.now(timezone.utc).isoformat();flush()
    if manifest['status']!='failed':
        from quantlab.data.baostock_dataset import build_dataset
        try:manifest['dataset']=build_dataset(directory,manifest);manifest['dataset_ready']=manifest['dataset']['ready']
        except Exception as error:manifest['normalization_error']=type(error).__name__+': '+str(error)[:400]
    flush();return manifest


def run_import(output,spec,*,stop=None,timeout=300):
    """Host-only downloader. A dedicated subprocess isolates SDK global sessions."""
    plan,_=import_plan(spec)
    if type(timeout) not in (int,float) or not 1<=timeout<=600:
        raise ValueError('数据导入时限必须为1–600秒')
    if stop is not None and stop.is_set():
        raise ValueError('数据导入已取消，未启动下载进程')
    root=import_root(output);identifier=str(uuid4())
    request=root/(identifier+'.request.json');write_json(request,plan)
    destination=root/identifier
    with (root/(identifier+'.log')).open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','quantlab.data.baostock_ingest',
            '--worker',str(request),str(destination)],stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+timeout;interrupted=None
        try:
            while process.poll() is None:
                if stop is not None and stop.is_set():interrupted='cancelled';break
                if time.monotonic()>deadline:interrupted='timed_out';break
                time.sleep(.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
    if interrupted:
        destination.mkdir(exist_ok=True)
        path=destination/'manifest.json'
        value=json.loads(path.read_text()) if path.is_file() else {'format':'baostock-import-v1','import_id':identifier,'plan':plan,'responses':[]}
        value.update(status=interrupted,dataset_ready=False);write_json(path,value)
        return value
    if not (destination/'manifest.json').is_file():raise ValueError('数据进程未生成可核验回执；请查看本批日志')
    result=json.loads((destination/'manifest.json').read_text())
    if process.returncode!=0:
        result.update(status='failed',dataset_ready=False,worker_exit_code=process.returncode)
        write_json(destination/'manifest.json',result)
    return result


def load_import(output,identifier):
    if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:raise ValueError('无效数据批次编号')
    directory=Path(output).resolve()/'_market_data'/'baostock'/identifier
    if directory.is_symlink() or not directory.resolve().is_relative_to(Path(output).resolve()):raise ValueError('数据批次路径无效')
    path=directory/'manifest.json'
    if path.is_symlink() or path.stat().st_size>2_000_000:raise ValueError('无效导入清单')
    manifest=json.loads(path.read_text())
    if manifest.get('format')!='baostock-import-v1' or manifest.get('import_id')!=identifier:raise ValueError('批次清单身份不匹配')
    return directory,manifest


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--worker':raise SystemExit('Internal data worker requires an exact request and destination')
    value=collect(json.loads(Path(sys.argv[2]).read_text()),sys.argv[3])
    raise SystemExit(0 if value['status'] in ('completed','completed_with_errors') else 2)
