"""Offline supervisor boundaries; real Windows startup is a separate deployment test."""
import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('tdx_windows_worker',Path(__file__).resolve().parents[1]/'scripts/tdx_windows_worker.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
class SupervisorTests(unittest.TestCase):
    def config(self):return {'machine_name':'601','code_root':'D:/AI/testData/niuniu','data_root':'D:/AI/testData/niuniu-data','control_root':'D:/AI/testData/tdx-control','identity_file':'C:/Users/PC/.ssh/id_ed25519','known_hosts_file':'D:/AI/ollama-tunnel/known_hosts','cluster_id':'a'*64,'shard_id':2,'allow_tunnel_start':True,'offline_only':True}
    def test_exact_config(self):self.assertEqual(s.validate_config(self.config()),self.config())
    def test_foreign_or_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):s.validate_config({**self.config(),'command':'something'})
    def test_wrong_shard_rejected(self):
        with self.assertRaises(ValueError):s.validate_config({**self.config(),'shard_id':0})
    def test_homepc_platform_denial_not_bypassed(self):
        c={**self.config(),'machine_name':'homepc','shard_id':1,'offline_only':False}
        with self.assertRaisesRegex(ValueError,'operator'):s.validate_config(c)
        self.assertFalse(s.validate_config({**c,'allow_tunnel_start':False})['allow_tunnel_start'])
        self.assertTrue(s.validate_config({**c,'offline_only':True})['offline_only'])
    def test_network_share_path_rejected(self):
        with self.assertRaises(ValueError):s.validate_config({**self.config(),'data_root':r'\\nas\shared'})
    def test_ssh_uses_only_scoped_loopback_forward_and_pinned_host(self):
        cmd=s.tunnel_command({**self.config(),'offline_only':False},'C:/Windows')
        self.assertIn('StrictHostKeyChecking=yes',cmd);self.assertIn('BatchMode=yes',cmd)
        self.assertEqual(cmd[-2: ],['127.0.0.1:18943:127.0.0.1:18943','tdx-transfer@8.136.98.55'])
        self.assertNotIn('-R',cmd);self.assertNotIn('-A',cmd)
    def test_worker_cannot_start_prepare_or_clear_stop(self):
        cmd=s.worker_command(self.config());self.assertIn('quantlab.agent.tdx_collection_cli',cmd)
        self.assertIn('autoresume',cmd);self.assertNotIn('--server-url',cmd);self.assertNotIn('--canonical-root',cmd)
        self.assertEqual(cmd[cmd.index('--data-root')+1],self.config()['data_root'])
        online=s.worker_command({**self.config(),'offline_only':False});self.assertIn('quantlab.agent.tdx_worker_service',online);self.assertIn('--server-url',online)
    def test_markers_have_priority(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d=root/'data';c=root/'control';c.mkdir();base=d/'lake/bronze/provider=tdx';base.mkdir(parents=True)
            self.assertIsNone(s.stop_reason(d,c))
            (base/'AUTO_HALT.json').write_text('{}');self.assertEqual(s.stop_reason(d,c),'AUTO_HALTED')
            (base/'STOP').write_text('user');self.assertEqual(s.stop_reason(d,c),'USER_STOP')
            (c/'SUPERVISOR_STOP').write_text('operator');self.assertEqual(s.stop_reason(d,c),'SUPERVISOR_STOP')
