"""File-only data plane bound to loopback behind existing authenticated SSH tunnels.

No public bind, credentials, commands, shared database files or arbitrary paths.
Transfers stage as .part; only a verified canonical MERGED receipt acknowledges data.
"""
from __future__ import annotations
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from quantlab.data.tdx_lake import TdxLake, encode, now, safe, write_json
from quantlab.data.tdx_sharding import read_role, checked
from quantlab.agent.tdx_distributed import (
    import_results, BundleConflict, BundleDeferred, file_sha, require_disk,
)

MAX_UPLOAD = 512 * 1024**2
ID = r'[a-f0-9]{64}'


def endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or not parsed.port or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Only a loopback HTTP endpoint inside an authenticated SSH tunnel is permitted')
    return parsed.hostname, parsed.port


def connection(url, timeout=60):
    host, port = endpoint(url)
    return http.client.HTTPConnection(host, port, timeout=timeout)


def json_get(url, path):
    con = connection(url)
    try:
        con.request('GET', path)
        response = con.getresponse()
        data = response.read(1024**2+1)
        if len(data)>1024**2:
            raise ValueError('Oversized transfer response')
        return response.status, json.loads(data)
    finally:
        con.close()


def download_bootstrap(url, receipt, destination):
    endpoint(url)
    bid, expected = receipt['bundle_id'], receipt['sha256']
    if not re.fullmatch(ID, bid) or not re.fullmatch(ID, expected):
        raise ValueError('Invalid bootstrap identity')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = safe(destination, destination/(bid+'.tar'))
    partial = safe(destination, destination/(bid+'.part'))
    if target.exists():
        if file_sha(target)!=expected:raise BundleConflict('Local bootstrap hash differs')
        return target
    offset = partial.stat().st_size if partial.exists() else 0
    if offset>receipt['bytes']:raise ValueError('Partial bootstrap exceeds expected size')
    require_disk(destination, receipt['bytes']-offset)
    if offset<receipt['bytes']:
        con = connection(url, timeout=90)
        try:
            headers = {'Range': 'bytes='+str(offset)+'-'} if offset else {}
            con.request('GET', '/bootstrap/'+bid+'.tar', headers=headers)
            response = con.getresponse()
            if response.status != (206 if offset else 200):
                raise ConnectionError('Bootstrap HTTP status '+str(response.status))
            if response.getheader('X-TDX-SHA256')!=expected:
                raise BundleConflict('Bootstrap transport hash header differs')
            if int(response.getheader('Content-Length', '-1'))!=receipt['bytes']-offset:
                raise ValueError('Bootstrap length differs')
            if offset and response.getheader('Content-Range')!=f"bytes {offset}-{receipt['bytes']-1}/{receipt['bytes']}":
                raise ValueError('Bootstrap resume range differs')
            with partial.open('ab') as output:
                while True:
                    block=response.read(1024**2)
                    if not block:break
                    output.write(block)
        finally:
            con.close()
    if partial.stat().st_size!=receipt['bytes'] or file_sha(partial)!=expected:
        raise BundleConflict('Downloaded bootstrap bytes do not match canonical receipt')
    partial.rename(target)
    return target


def send_result(url, receipt):
    bid=receipt['bundle_id']; path=Path(receipt['path'])
    if not re.fullmatch(ID,bid):raise ValueError('Invalid result identity')
    code, ack=json_get(url,'/receipt/'+bid)
    if code==200:
        return validate_ack(ack,receipt)
    if code!=404:raise ConnectionError('Receipt HTTP status '+str(code))
    if not path.is_file() or path.stat().st_size!=receipt['bytes'] or file_sha(path)!=receipt['sha256']:
        raise BundleConflict('Outgoing result changed after export')
    if path.stat().st_size>MAX_UPLOAD:raise ValueError('Result exceeds transport budget')
    con=connection(url,timeout=120)
    try:
        with path.open('rb') as stream:
            con.request('PUT','/result/'+receipt['machine_name']+'/'+bid+'.tar',body=stream,
                headers={'Content-Length':str(receipt['bytes']),'X-TDX-SHA256':receipt['sha256']})
            response=con.getresponse(); response.read(1024**2)
            if response.status not in (200,202):raise ConnectionError('Upload HTTP status '+str(response.status))
    finally:con.close()
    # The same bundle remains pending until import finishes. No re-export or cursor reset.
    code,ack=json_get(url,'/receipt/'+bid)
    return validate_ack(ack,receipt) if code==200 else None


def validate_ack(ack,receipt):
    if (ack.get('state')!='MERGED' or ack.get('bundle_id')!=receipt['bundle_id']
            or ack.get('sha256')!=receipt['sha256'] or ack.get('sequence_no')!=receipt['sequence_no']
            or ack.get('machine_name')!=receipt['machine_name'] or ack.get('history_complete') is not False):
        raise BundleConflict('Canonical acknowledgement identity/state mismatch')
    return ack


class TransferServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

    def __init__(self,address,lake,exchange):
        if address[0]!='127.0.0.1':raise ValueError('Public transfer bind is prohibited')
        role=read_role(lake)
        if not role or role.get('role')!='coordinator':raise ValueError('Canonical coordinator required')
        self.lake=lake
        self.cluster=checked(role['cluster'])
        self.exchange=Path(exchange).resolve(); self.exchange.mkdir(parents=True,exist_ok=True)
        self.incoming=self.exchange/'incoming'; self.incoming.mkdir(exist_ok=True)
        self.bootstrap={b['bundle_id']:b for b in self.cluster['bundles']}
        self.machines={a['machine_name'] for a in self.cluster['assignments']}
        self.io_lock=threading.Lock()
        super().__init__(address,Handler)
        self.timeout=1

    def merge_pending(self):
        for meta in sorted(self.incoming.glob('*/*.transfer.json')):
            failure=meta.with_suffix('.failed.json')
            if failure.exists():continue
            item=json.loads(meta.read_text(encoding='utf-8'))
            path=safe(self.exchange,Path(item['path']))
            receipt_path=self.lake.base/'distributed-receipts'/(item['bundle_id']+'.json')
            if receipt_path.exists():
                ack=json.loads(receipt_path.read_text(encoding='utf-8'))
                if ack['sha256']!=item['sha256']:raise BundleConflict('Receipt and received file differ')
                if path.exists():path.unlink()
                continue
            try:
                ack=import_results(self.lake,path,item['sha256'])
                print(encode({'phase':'merge',**ack}),flush=True)
                # Canonical raw/Parquet files and durable receipt now exist; remove only this verified transfer copy.
                if path.exists():path.unlink()
            except BundleDeferred:
                continue
            except BundleConflict as exc:
                write_json(failure,{'state':'QUARANTINE','error':str(exc),'observed_at':now()})
                print(encode({'phase':'merge_conflict','bundle_id':item['bundle_id'],'error':str(exc)}),flush=True)
            except ValueError as exc:
                if 'writer lease' not in str(exc):raise


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'

    def log_message(self,*args):
        pass

    def setup(self):
        super().setup(); self.connection.settimeout(120)

    def reply(self,code,body):
        data=encode(body).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Connection','close')
        self.end_headers();self.wfile.write(data)
        self.close_connection=True

    def do_GET(self):
        if self.path=='/health':
            return self.reply(200,{'cluster_id':self.server.cluster['cluster_id'],'history_complete':False})
        match=re.fullmatch('/receipt/('+ID+')',self.path)
        if match:
            path=self.server.lake.base/'distributed-receipts'/(match[1]+'.json')
            if path.is_file():return self.reply(200,json.loads(path.read_text(encoding='utf-8')))
            return self.reply(404,{'state':'NOT_MERGED'})
        match=re.fullmatch('/bootstrap/('+ID+')[.]tar',self.path)
        if not match:return self.reply(404,{'error':'not_found'})
        receipt=self.server.bootstrap.get(match[1])
        if receipt is None:
            from quantlab.agent.tdx_checkpoint_witness import transport_variant
            try:receipt=transport_variant(self.server.exchange,match[1],self.server.bootstrap)
            except (ValueError,KeyError,OSError):return self.reply(409,{'error':'invalid_bootstrap_variant'})
        if receipt is None:return self.reply(404,{'error':'not_found'})
        path=Path(receipt['path'])
        if not path.is_file() or path.stat().st_size!=receipt['bytes']:
            return self.reply(409,{'error':'bootstrap_missing_or_changed'})
        offset=0
        if self.headers.get('Range'):
            bounds=re.fullmatch(r'bytes=(\d+)-',self.headers['Range'])
            if not bounds or int(bounds[1])>=receipt['bytes']:return self.reply(416,{'error':'invalid_range'})
            offset=int(bounds[1])
        self.send_response(206 if offset else 200)
        self.send_header('Content-Length',str(receipt['bytes']-offset))
        self.send_header('X-TDX-SHA256',receipt['sha256'])
        self.send_header('Connection','close')
        if offset:self.send_header('Content-Range',f"bytes {offset}-{receipt['bytes']-1}/{receipt['bytes']}")
        self.end_headers();self.close_connection=True
        try:
            with path.open('rb') as stream:
                stream.seek(offset)
                shutil.copyfileobj(stream,self.wfile,1024**2)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_PUT(self):
        match=re.fullmatch('/result/([a-zA-Z0-9_-]{1,64})/('+ID+')[.]tar',self.path)
        if not match or match[1] not in self.server.machines:return self.reply(404,{'error':'not_found'})
        machine,bid=match.groups();expected=self.headers.get('X-TDX-SHA256','')
        try:length=int(self.headers.get('Content-Length','-1'))
        except ValueError:return self.reply(400,{'error':'invalid_length'})
        if not re.fullmatch(ID,expected) or not 0<length<=MAX_UPLOAD:
            return self.reply(400,{'error':'invalid_size_or_hash'})
        folder=safe(self.server.exchange,self.server.incoming/machine)
        folder.mkdir(exist_ok=True)
        partial=safe(self.server.exchange,folder/('.'+str(uuid4())+'.part'))
        target=safe(self.server.exchange,folder/(bid+'.tar'))
        try:
            require_disk(folder,length)
            digest=hashlib.sha256();remaining=length
            with partial.open('xb') as output:
                while remaining:
                    block=self.rfile.read(min(1024**2,remaining))
                    if not block:raise ConnectionError('Truncated upload')
                    output.write(block);digest.update(block);remaining-=len(block)
            if digest.hexdigest()!=expected:return self.reply(400,{'error':'transport_hash_mismatch'})
            with self.server.io_lock:
                if target.exists():
                    if file_sha(target)!=expected:return self.reply(409,{'error':'result_identity_conflict'})
                else:partial.rename(target)
                write_json(folder/(bid+'.transfer.json'),{'bundle_id':bid,'sha256':expected,'path':str(target),'bytes':length,'received_at':now()})
            return self.reply(202,{'state':'RECEIVED_NOT_YET_MERGED','bundle_id':bid})
        except BundleDeferred:
            return self.reply(507,{'error':'disk_reserve'})
        except (OSError,ConnectionError) as exc:
            try:return self.reply(503,{'error':type(exc).__name__})
            except OSError:pass
        finally:partial.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--exchange',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18943)
    parser.add_argument('--personal-research-only',action='store_true')
    args=parser.parse_args(argv)
    if not args.personal_research_only:parser.error('Explicit personal research authorization required')
    if not 1024<=args.port<=65535:parser.error('Invalid loopback port')
    lake=TdxLake(args.data_root)
    with TransferServer(('127.0.0.1',args.port),lake,args.exchange) as server:
        print(encode({'state':'LISTENING_LOOPBACK_ONLY','port':args.port,'cluster_id':server.cluster['cluster_id']}),flush=True)
        while not (args.exchange/'SYNC_STOP').exists():
            server.handle_request()
            try:server.merge_pending()
            except Exception as exc:
                write_json(args.exchange/'merge-error.json',{'error':type(exc).__name__+': '+str(exc),'observed_at':now()})
                raise
    return 0


if __name__=='__main__':
    raise SystemExit(main())
