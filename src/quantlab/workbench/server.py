"""Loopback workbench: artifact views and optional validated research execution."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

import polars as pl

from quantlab.app import default_registry
from quantlab.storage.codec import encode
from quantlab.theory.templates import templates
from quantlab.workbench.jobs import JobQueue, prepare
from quantlab.sequence.replay import replay_page


FILES = {'reproduction.json':'application/json','experiment.json':'application/json', 'summary.json':'application/json', 'detail.json':'application/json', 'report.md':'text/markdown; charset=utf-8',
         'targets.parquet':'application/octet-stream','observations.parquet':'application/octet-stream','bars.parquet':'application/octet-stream'}


class ArtifactCatalog:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('Artifact directory does not exist')
        self._record_cache=None

    def file(self, run_id, name):
        if str(UUID(run_id)) != run_id or name not in FILES:
            raise ValueError('Invalid artifact identifier')
        directory = self.root / run_id
        path = directory / name
        if directory.is_symlink() or path.is_symlink() or path.resolve().parent != directory or not path.is_file():
            raise FileNotFoundError('Artifact not found')
        return path

    def record(self, run_id):
        path=self.file(run_id,'experiment.json');stat=path.stat()
        key=(run_id,stat.st_size,stat.st_mtime_ns)
        if self._record_cache is not None and self._record_cache[0]==key:return self._record_cache[1]
        record = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(record,dict) or record.get('run_id') != run_id or 'manifest' not in record:
            raise ValueError('Invalid experiment record')
        self._record_cache=(key,record)
        return record

    def summary(self,run_id):
        path=self.file(run_id,'experiment.json');stat=path.stat()
        try:
            item=json.loads(self.file(run_id,'summary.json').read_text(encoding='utf-8'))
            if (item['source_size'],item['source_mtime_ns'])!=(stat.st_size,stat.st_mtime_ns):raise ValueError('Stale summary')
            record=item['record']
            if record['run_id']!=run_id:raise ValueError('Wrong summary identity')
            return {**record,'manifest':{'config':item['config']}}
        except (OSError,ValueError,KeyError,TypeError):
            return self.record(run_id)

    def list(self, query='', status='', kind='', offset=0, limit=30):
        records, skipped = [], 0
        for path in self.root.glob('*/experiment.json'):
            try:
                record = self.summary(path.parent.name)
                config = record['manifest'].get('config',{})
                data = config.get('data',{})
                records.append({'run_id':record['run_id'],'experiment_id':record.get('experiment_id',''),
                    'created_at':record.get('created_at',''),'status':record.get('status','unknown'),
                    'kind':record.get('kind','factor'),'question':config.get('research_question','未命名实验'),
                    'factor_id':config.get('factor_id','多因子关系'),'theory_id':(config.get('theory_origin') or {}).get('template_id',''),'timeframe':data.get('timeframe',''),
                    'start':data.get('start',''),'end':data.get('end',''), 'symbols':data.get('symbols',[])})
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                skipped += 1
        records.sort(key=lambda r:(r['created_at'],r['run_id']),reverse=True)
        counts = {'total':len(records),'completed':sum(r['status']=='completed' for r in records),
            'failed':sum(r['status']=='failed' for r in records),'skipped':skipped}
        kinds = sorted({r['kind'] for r in records})
        selected = [r for r in records if (not status or r['status']==status) and (not kind or r['kind']==kind)
            and (not query or query.casefold() in json.dumps(r,ensure_ascii=False).casefold())]
        return {'runs':selected[offset:offset+limit],'total':len(selected),'counts':counts,'kinds':kinds}

    def detail(self, run_id, *, lightweight=False):
        record = None
        if lightweight:
            try:
                source = self.file(run_id, 'experiment.json').stat()
                cached = json.loads(self.file(run_id, 'detail.json').read_text())
                if (cached['source_size'], cached['source_mtime_ns']) == (source.st_size, source.st_mtime_ns) and cached['record']['run_id'] == run_id:
                    record = cached['record']
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if record is None:
            record = self.record(run_id)
        links = {}
        def visit(value):
            if isinstance(value,dict):
                if 'artifact_path' in value and 'run_id' in value:
                    try:
                        path = Path(value['artifact_path']).resolve()
                        self.file(value['run_id'],'experiment.json')
                        if self.summary(value['run_id'])['run_id'] == value['run_id']:
                            links[value['run_id']] = {'run_id':value['run_id'],
                                'label':str(value.get('name',value.get('removed',value.get('fold','子实验')))),
                                'parameters':value.get('parameters')}
                    except (ValueError,OSError,TypeError):
                        pass
                for key, child in value.items():
                    if key in ('children','periods','folds'):
                        visit(child)
            elif isinstance(value,list):
                for item in value:
                    visit(item)
        visit(record)
        files = []
        for name in FILES:
            try:
                self.file(run_id,name)
                files.append(name)
            except FileNotFoundError:
                pass
        return {'record':record,'children':list(links.values()),'files':files}

    def observations(self, run_id, offset, limit, symbol=''):
        frame = pl.scan_parquet(self.file(run_id,'observations.parquet'))
        if symbol and 'symbol' not in frame.collect_schema().names():
            raise ValueError('This artifact has no symbol column')
        if symbol:
            frame = frame.filter(pl.col('symbol')==symbol)
        total = frame.select(pl.len()).collect().item()
        page = frame.slice(offset,limit).collect()
        return {'columns':page.columns,'rows':page.to_dicts(),'total':total,'offset':offset}


def make_server(root, port=8765, data_root=None):
    catalog = ArtifactCatalog(root)
    static = Path(__file__).parent/'static'

    class Handler(BaseHTTPRequestHandler):
        def local_request(self, write=False):
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            return self.headers.get('Host') in hosts and (
                origin in {f'http://{h}' for h in hosts} if write or origin else True)

        def log_message(self, *args):
            pass

        def respond(self, data, content_type='application/json; charset=utf-8', status=200, download=None):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if download:
                self.send_header('Content-Disposition',f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.local_request():
                self.respond(b'{"error":"Local access only"}',status=403)
                return
            try:
                url = urlsplit(self.path)
                route = unquote(url.path)
                query = parse_qs(url.query)
                arg = lambda key,default='': query.get(key,[default])[0]
                offset, limit = int(arg('offset','0')), int(arg('limit','30'))
                if offset < 0 or not 1 <= limit <= 200:
                    raise ValueError('Invalid page bounds')
                assets = {'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/replay.js':('replay.js','text/javascript; charset=utf-8'),'/launcher.js':('launcher.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
                assets.update({'/workspace.js':('workspace.js','text/javascript; charset=utf-8'),
                    '/assets/niuniu_logo_icon.png':('assets/niuniu_logo_icon.png','image/png'),
                    '/assets/niuniu_mascot_banner.png':('assets/niuniu_mascot_banner.png','image/png')})
                if route in assets:
                    name, mime = assets[route]
                    self.respond((static/name).read_bytes(),mime)
                    return
                if route == '/api/runs':
                    result = catalog.list(arg('q'),arg('status'),arg('kind'),offset,limit)
                elif route == '/api/paper':
                    paper_root=catalog.root/'paper'
                    accounts=[]
                    if paper_root.is_dir() and not paper_root.is_symlink():
                        for path in sorted(paper_root.glob('*.json')):
                            if path.is_symlink():continue
                            try:
                                state=json.loads(path.read_text())
                                accounts.append({'name':path.stem,**{k:state[k] for k in ('mode','revision','watermark','summary','limitations')},
                                    'orders':state['orders'][offset:offset+limit],'total_orders':len(state['orders'])})
                            except (ValueError,KeyError,OSError):continue
                    result={'accounts':accounts,'offset':offset}
                elif route == '/api/catalog':
                    result = {'factors':default_registry().describe(),'theories':templates()}
                elif route == '/api/settings':
                    result = {'execution_enabled': self.server.jobs is not None,
                        'data_root': str(self.server.jobs.data_root) if self.server.jobs else None}
                elif route == '/api/jobs':
                    jobs = self.server.jobs.list() if self.server.jobs else []
                    result = {'jobs': jobs[offset:offset+limit], 'total': len(jobs)}
                else:
                    parts = route.strip('/').split('/')
                    if len(parts)==3 and parts[:2]==['api','runs']:
                        result = catalog.detail(parts[2])
                    elif len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='regime':
                        from quantlab.workbench.research_views import regime_view
                        result = regime_view(catalog,parts[2])
                    elif len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='replay':
                        record=catalog.record(parts[2]);replay_id=parts[2]
                        if record.get('manifest',{}).get('signal_data_snapshot',{}).get('adjustment','raw')!='raw':
                            replay_id=record['children'][0]['run_id']
                        result = replay_page(pl.read_parquet(catalog.file(replay_id,'bars.parquet')),record,arg('symbol'),int(arg('at','0')),limit)
                    elif len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='observations':
                        result = catalog.observations(parts[2],offset,limit,arg('symbol'))
                    elif len(parts)==3 and parts[:2]==['api','jobs']:
                        jobs = self.server.jobs.list() if self.server.jobs else []
                        result = next((j for j in jobs if j['job_id']==parts[2]), None)
                        if result is None:
                            raise FileNotFoundError()
                    elif len(parts)==3 and parts[0]=='files':
                        path = catalog.file(parts[1],parts[2])
                        self.respond(path.read_bytes(),FILES[parts[2]],download=parts[2])
                        return
                    elif len(parts)==3 and parts[0]=='reports' and parts[2]=='text':
                        result = {'text':catalog.file(parts[1],'report.md').read_text(encoding='utf-8')}
                    else:
                        raise FileNotFoundError()
                self.respond(encode(result).encode('utf-8'))
            except FileNotFoundError:
                self.respond(b'{"error":"Artifact not found"}',status=404)
            except (ValueError,KeyError,TypeError):
                self.respond(b'{"error":"Invalid request or artifact"}',status=400)
            except Exception:
                self.respond(b'{"error":"Unable to read artifact"}',status=500)

        def do_POST(self):
            if not self.local_request(write=True):
                self.respond(b'{"error":"Same-origin local requests only"}', status=403)
                return
            if self.path not in {'/api/jobs', '/api/validate'}:
                self.respond(b'{"error":"Unknown endpoint"}', status=404)
                return
            if self.server.jobs is None:
                self.respond(encode({'error':'只读模式；启动时指定 --data-root 才能提交研究'}).encode(), status=403)
                return
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                self.respond(b'{"error":"JSON body with Content-Length required"}', status=415)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('请求体必须在 1–65536 字节之间')
                self.connection.settimeout(10)
                payload = json.loads(self.rfile.read(length))
                if self.path == '/api/validate':
                    result = prepare(payload).preview()
                else:
                    if not isinstance(payload, dict) or set(payload) != {'job_id', 'spec'}:
                        raise ValueError('提交需要 job_id 和 spec')
                    result = self.server.jobs.submit(payload['job_id'], payload['spec'])
                self.respond(encode(result).encode('utf-8'), status=202 if self.path=='/api/jobs' else 200)
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
                self.respond(encode({'error':str(error)}).encode('utf-8'), status=400)
            except Exception:
                self.respond(encode({'error':'任务提交失败；请查看运行任务确认是否已接收。'}).encode('utf-8'), status=500)

    class Server(ThreadingHTTPServer):
        jobs = None

        def server_close(self):
            super().server_close()
            if self.jobs is not None:
                self.jobs.close()
                self.jobs = None

    server = Server(('127.0.0.1',port),Handler)
    try:
        if data_root is not None:
            server.jobs = JobQueue(catalog.root, data_root)
    except Exception:
        server.server_close()
        raise
    return server


def serve(root, port=8765, data_root=None):
    with make_server(root,port,data_root) as server:
        print(f'QuantLab 工作台：http://127.0.0.1:{server.server_address[1]}',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
