"""Offline Pi bridge checks: real Node process, fake model runtime, no credentials/network."""
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch
from quantlab.agent.model_config import ModelConfig, ModelError, ChatStopped
from quantlab.devstudio.pi_provider import PiProvider, resolve_pi, safe_error
from quantlab.devstudio.team import DOMAINS, load_team_models

SDK = '''
export class ModelRuntime {
 static async create(){return new ModelRuntime();}
 getModel(provider,id){return id==='absent'?undefined:{provider,id,api:'fake'};}
 async getAvailable(){return [{id:'unit'}];}
 async completeSimple(model,context,options){
  if(context.systemPrompt==='wait')await new Promise(r=>setTimeout(r,30000));
  this.n=(this.n||0)+1;
  const shell=context.systemPrompt==='unknown';
  const call=this.n===1||context.systemPrompt==='loop'||context.systemPrompt==='duplicate';
  if(context.systemPrompt==='duplicate')this.n=1;
  return {role:'assistant',provider:model.provider,model:context.systemPrompt==='wrong'?'other':model.id,
   api:'fake',usage:{input:1,output:1,totalTokens:2},timestamp:Date.now(),
   stopReason:context.systemPrompt==='error'?'error':'stop',errorMessage:'simulated provider failure',
   content:call?[{type:'toolCall',id:'c'+this.n,name:shell?'bash':'echo',arguments:{value:'sample'}}]:
   [{type:'text',text:context.messages.at(-1).content[0].text}]};
 }
}
'''
TOOL={'name':'echo','description':'echo', 'parameters':{'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}}

class PiProviderTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:cls.node=resolve_pi()[0]
  except ModelError:
   import shutil
   cls.node=shutil.which('node')
  if not cls.node:raise unittest.SkipTest('Node required for bridge tests')
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.sdk=Path(self.tmp.name)/'fake.mjs';self.sdk.write_text(SDK)
  self.patcher=patch('quantlab.devstudio.pi_provider.resolve_pi',return_value=(self.node,str(self.sdk)));self.patcher.start();self.addCleanup(self.patcher.stop)
  self.calls=[];self.events=[]
 def run_pi(self,system='normal',stop=None,**kwargs):
  cfg=ModelConfig(provider='pi_sdk',model='fake/unit',timeout_seconds=10,max_rounds=4,**kwargs)
  def dispatch(n,a,i):self.calls.append((n,a,i));return {'ok':True,'data':a['value']}
  return PiProvider(cfg).run(system,[{'role':'user','content':'check'}],[TOOL],dispatch,lambda k,v:self.events.append((k,v)),stop or Event())
 def test_roundtrip_identity_and_host_tools(self):
  result=self.run_pi();self.assertEqual(result['model'],'unit');self.assertEqual(result['pi_provider'],'fake')
  self.assertEqual(len(self.calls),1);self.assertIn('sample',result['text'])
  identity=next(v for k,v in self.events if k=='pi_identity');self.assertFalse(identity['builtin_tools']);self.assertFalse(identity['extensions'])
 def test_unknown_tool_never_dispatches(self):
  with self.assertRaisesRegex(ModelError,'Unknown'):self.run_pi('unknown')
  self.assertEqual(self.calls,[])
 def test_wrong_model_rejected_before_tools(self):
  with self.assertRaisesRegex(ModelError,'different model'):self.run_pi('wrong')
  self.assertEqual(self.calls,[])
 def test_duplicate_call_rejected(self):
  with self.assertRaisesRegex(ModelError,'duplicate'):self.run_pi('duplicate')
  self.assertEqual(len(self.calls),1)
 def test_tool_budget_enforced(self):
  with self.assertRaisesRegex(ModelError,'budget'):self.run_pi('loop',max_tool_calls=1)
  self.assertEqual(len(self.calls),1)
 def test_provider_error_not_success(self):
  with self.assertRaisesRegex(ModelError,'simulated'):self.run_pi('error')
  self.assertEqual(self.calls,[])
 def test_pre_stopped_never_launches(self):
  stop=Event();stop.set()
  with patch('quantlab.devstudio.pi_provider.subprocess.Popen') as popen:
   with self.assertRaises(ChatStopped):self.run_pi(stop=stop)
   popen.assert_not_called()
 def test_stop_terminates_child(self):
  stop=Event();timer=Timer(.4,stop.set);timer.start();self.addCleanup(timer.cancel)
  with self.assertRaises(ChatStopped):self.run_pi('wait',stop=stop)
  self.assertEqual(self.calls,[])
 def test_initial_context_budget(self):
  with self.assertRaisesRegex(ModelError,'上下文'):self.run_pi('x'*3000,max_context_chars=2000)
 def test_absent_model_not_fallback(self):
  cfg=ModelConfig(provider='pi_sdk',model='fake/absent')
  with self.assertRaisesRegex(ModelError,'not found'):PiProvider(cfg).probe()
 def test_model_configuration_validation(self):
  for name in ['gpt-6-luna','/gpt-6-luna','openai-codex/','openai-codex/bad model']:
   with self.assertRaises(ValueError):ModelConfig(provider='pi_sdk',model=name)
  self.assertEqual(ModelConfig(provider='pi_sdk',model='custom/custom-model').model,'custom/custom-model')
 def test_error_redacts_credentials(self):
  self.assertNotIn('very-secret',safe_error('Bearer very-secret'))
  self.assertNotIn('sk-abcdefghijklmnop',safe_error('sk-abcdefghijklmnop'))
 def test_profile_copy_and_save_six_roles(self):
  os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
  from PyQt6.QtWidgets import QApplication
  from quantlab.desktop.dev_team import DevTeamModelsDialog
  app=QApplication.instance() or QApplication([])
  dialog=DevTeamModelsDialog(None,Path(self.tmp.name))
  fields=dialog.fields['LEAD'];fields['provider'].setCurrentText('pi_sdk');fields['model'].setText('openai-codex/gpt-6-luna')
  fields['pi_path'].setText('/test/pi');dialog.copy_to_all();dialog.save()
  configs=load_team_models(self.tmp.name)
  self.assertEqual(set(configs),set(DOMAINS))
  for cfg in configs.values():self.assertEqual((cfg['provider'],cfg['model'],cfg['pi_path']),('pi_sdk','openai-codex/gpt-6-luna','/test/pi'))
  dialog.close()

if __name__=='__main__':unittest.main()
