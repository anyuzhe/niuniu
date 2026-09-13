import json
import unittest
from pathlib import Path


class PlaybookGitContractTests(unittest.TestCase):
    def setUp(self):
        self.repo=Path(__file__).resolve().parents[1]

    def test_qimofenshu_pilot_cannot_silently_become_formal_rule(self):
        path=self.repo/'playbooks'/'qimofenshu'/'definition.json'
        value=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(value['schema_version'],'playbook-git-v1')
        self.assertEqual(value['playbook_key'],'qimofenshu')
        self.assertEqual(value['status'],'SOURCE_REQUIRED')
        self.assertIsNone(value['formal_definition_id'])
        self.assertGreaterEqual(len(value['source_requirements']),4)
        self.assertTrue(all(rule is None for rule in value['rules'].values()))

    def test_playbook_policy_requires_full_candidates_and_real_execution_audit(self):
        text=(self.repo/'playbooks'/'README.md').read_text(encoding='utf-8')
        self.assertIn('完整候选全集',text)
        self.assertIn('HOLDOUT / WALK_FORWARD',text)
        self.assertIn('T+1',text)
        self.assertIn('不等于牛牛已经获得 Alpha',text)

    def test_raw_expert_material_is_not_tracked_by_git_policy(self):
        ignore=(self.repo/'.gitignore').read_text(encoding='utf-8')
        self.assertIn('playbooks/**/source_raw/',ignore)
        note=(self.repo/'playbooks'/'qimofenshu'/'notes'/'trade_log_audit_summary_20260913.md').read_text(encoding='utf-8')
        self.assertIn('用户',note);self.assertIn('SHA256',note)


if __name__=='__main__':unittest.main()
