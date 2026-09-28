import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch
from quantlab.devstudio.pi_provider import resolve_pi,PiProvider
from quantlab.agent.model_config import ModelConfig

HELPER=Path(__file__).resolve().parents[1]/'src/quantlab/devstudio/pi_runtime_cache.mjs'
class PiCatalogCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.node=resolve_pi()[0]
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.agent=self.root/'agent';self.agent.mkdir();self.work=self.root/'work';self.work.mkdir()
        self.cache=self.agent/'models-store.json'
    def invoke(self,mode='copy'):
        code="""import {pathToFileURL} from 'node:url';const h=await import(pathToFileURL(process.argv[1]).href);try{let r;if(process.argv[4]==='legacy')r=await h.isolatedModelCatalog({},process.argv[3]);else r=await h.isolatedModelCatalog({getAgentDir:()=>process.argv[2]},process.argv[3]);console.log(JSON.stringify({ok:true,...r}));}catch(e){console.log(JSON.stringify({ok:false,message:e.message}));}"""
        p=subprocess.run([self.node,'--input-type=module','-e',code,str(HELPER),str(self.agent),str(self.work),mode],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
    def test_catalog_is_exact_private_copy_not_user_config_or_credentials(self):
        self.cache.write_text('{"fake":{"models":[]}}');raw=self.cache.read_bytes()
        (self.agent/'auth.json').write_text('fixture auth do not copy');(self.agent/'models.json').write_text('fixture config do not copy')
        result=self.invoke();self.assertTrue(result['ok']);self.assertEqual((self.work/'models-store.json').read_bytes(),raw)
        self.assertEqual(list(p.name for p in self.work.iterdir()),['models-store.json'])
        self.assertEqual(self.cache.read_bytes(),raw)
        # Removable volumes may expose owner execute even for open(mode=0600).
        # The security boundary is no group/other access, not owner execute.
        mode=(self.work/'models-store.json').stat().st_mode
        self.assertEqual(mode & 0o077,0);self.assertEqual(mode & 0o600,0o600)
        self.assertFalse(result['options']['allowModelNetwork']);self.assertTrue(result['receipt']['seeded'])
    def test_missing_catalog_is_empty_local_store_not_new_model(self):
        result=self.invoke();self.assertTrue(result['ok']);self.assertFalse(result['receipt']['seeded'])
        self.assertEqual(json.loads((self.work/'models-store.json').read_text()),{})
        self.assertFalse(self.cache.exists())
    def test_legacy_sdk_preserves_old_options(self):
        result=self.invoke('legacy');self.assertEqual(result['options'],{'allowModelNetwork':False});self.assertFalse(list(self.work.iterdir()))
    def test_symlink_and_directory_fail_closed(self):
        source=self.root/'catalog';source.write_text('{}');self.cache.symlink_to(source)
        self.assertFalse(self.invoke()['ok']);self.assertFalse(list(self.work.iterdir()))
        self.cache.unlink();self.cache.mkdir();self.assertFalse(self.invoke()['ok'])
    def test_oversized_source_is_refused_without_copy(self):
        with self.cache.open('wb') as f:f.truncate(16*1024*1024+1)
        self.assertFalse(self.invoke()['ok']);self.assertFalse(list(self.work.iterdir()))
    def test_existing_destination_never_overwritten(self):
        self.cache.write_text('{}');(self.work/'models-store.json').write_text('existing')
        self.assertFalse(self.invoke()['ok']);self.assertEqual((self.work/'models-store.json').read_text(),'existing')
    def test_error_classes_do_not_expose_sdk_raw_message(self):
        js="""import {pathToFileURL} from 'node:url';const h=await import(pathToFileURL(process.argv[1]).href);console.log(JSON.stringify(['Availability refresh: ENOSPC private-secret','Invalid models.json schema private-secret',''].map(x=>h.modelLookupError({getError:()=>x},'fake/unit'))));"""
        p=subprocess.run([self.node,'--input-type=module','-e',js,str(HELPER)],capture_output=True,text=True,check=True)
        rows=json.loads(p.stdout);self.assertIn('PI_LOCAL_STORAGE_FULL',rows[0]);self.assertIn('PI_CATALOG_UNAVAILABLE',rows[1]);self.assertIn('not found',rows[2]);self.assertNotIn('private-secret',p.stdout)
    def test_transport_uses_isolated_catalog_and_removes_it_after_probe(self):
        self.cache.write_text('{"fake":{"models":[]}}');raw=self.cache.read_bytes();trace=self.root/'trace.json'
        fixture=self.root/'sdk.mjs'
        fixture.write_text("""import {readFile,writeFile} from 'node:fs/promises';export const getAgentDir=()=>process.env.PI_TEST_AGENT;export class ModelRuntime{static async create(options){await readFile(options.modelsStorePath);await writeFile(process.env.PI_TEST_TRACE,JSON.stringify(options));await writeFile(options.modelsStorePath,'local mutation');return new ModelRuntime()}getModel(provider,id){return{provider,id,api:'fake'}}async getAvailable(){return[{id:'unit'}]}}""")
        with patch('quantlab.devstudio.pi_provider.resolve_pi',return_value=(self.node,str(fixture))),patch.dict(os.environ,{'PI_TEST_AGENT':str(self.agent),'PI_TEST_TRACE':str(trace)}):
            result=PiProvider(ModelConfig(provider='pi_sdk',model='fake/unit',timeout_seconds=10)).probe()
        self.assertTrue(result['available']);self.assertEqual(self.cache.read_bytes(),raw)
        options=json.loads(trace.read_text());self.assertFalse(Path(options['modelsStorePath']).exists())
        self.assertEqual(result['catalog_cache']['mode'],'isolated_catalog_copy')
if __name__=='__main__':unittest.main()
