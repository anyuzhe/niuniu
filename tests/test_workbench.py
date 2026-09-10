import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import polars as pl
from quantlab.workbench.server import ArtifactCatalog, make_server


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ids = [str(uuid4()), str(uuid4())]
        for i, run_id in enumerate(self.ids):
            directory = self.root / run_id
            directory.mkdir()
            record = {'run_id':run_id,'status':'completed' if i==0 else 'failed',
                'created_at':str(i),'manifest':{'config':{'research_question':f'test {i}',
                'factor_id':'BASE.MOMENTUM','data':{'timeframe':'1d'}}}}
            (directory/'experiment.json').write_text(json.dumps(record))
            (directory/'report.md').write_text('# Report\n')
            pl.DataFrame({'symbol':['A','B','A'],'value':[1.,2.,3.]}).write_parquet(directory/'observations.parquet')
        self.server = make_server(self.root,0)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def get(self,path,**kwargs):
        return urlopen(Request(self.url+path,**kwargs),timeout=5)

    def test_list_filters_and_bad_records(self):
        bad=self.root/str(uuid4());bad.mkdir();(bad/'experiment.json').write_text('{')
        with self.get('/api/runs?status=completed&q=test&limit=1') as response:
            data=json.load(response)
        self.assertEqual(data['total'],1)
        self.assertEqual(data['counts'],{'total':2,'completed':1,'failed':1,'skipped':1})
        self.assertEqual(data['runs'][0]['run_id'],self.ids[0])
        with self.get('/api/runs?offset=2') as response:
            self.assertEqual(json.load(response)['runs'],[])

    def test_detail_children_data_and_download(self):
        path=self.root/self.ids[0]/'experiment.json'
        record=json.loads(path.read_text())
        record['children']=[{'run_id':self.ids[1],'artifact_path':str(self.root/self.ids[1])}]
        path.write_text(json.dumps(record))
        with self.get('/api/runs/'+self.ids[0]) as response:
            self.assertEqual(json.load(response)['children'][0]['run_id'],self.ids[1])
        with self.get(f'/api/runs/{self.ids[0]}/observations?symbol=A&offset=1&limit=1') as response:
            data=json.load(response)
            self.assertEqual(data['total'],2)
            self.assertEqual(data['rows'],[{'symbol':'A','value':3.}])
        with self.get(f'/files/{self.ids[0]}/report.md') as response:
            self.assertIn('attachment',response.headers['Content-Disposition'])
            self.assertEqual(response.read(),b'# Report\n')

    def test_static_catalog_and_access_boundaries(self):
        for path in ['/', '/app.js', '/style.css', '/api/catalog']:
            with self.get(path) as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read())
        for path,kw,status in [('/api/runs?limit=201',{},400),
                ('/api/runs',{'headers':{'Host':'evil.test'}},403),
                ('/api/runs',{'headers':{'Origin':'https://evil.test'}},403),
                ('/api/runs',{'method':'POST'},403),
                (f'/files/{self.ids[0]}/secret.txt',{},400),
                ('/files/%2e%2e/README.md',{},400)]:
            with self.subTest(path=path,kw=kw):
                with self.assertRaises(HTTPError) as raised:
                    self.get(path,**kw)
                self.assertEqual(raised.exception.code,status)
                raised.exception.close()
        report=self.root/self.ids[0]/'report.md'
        report.unlink()
        report.symlink_to(self.root/self.ids[1]/'report.md')
        with self.assertRaises(FileNotFoundError):
            ArtifactCatalog(self.root).file(self.ids[0],'report.md')
