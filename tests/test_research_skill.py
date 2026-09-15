from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest

from quantlab.knowledge.research_skill import (
    FORMAT, REQUIRED_POLICY, ResearchSkillError, audit_research_skill,
)


class ResearchSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'manager-skill'
        (self.root / 'references').mkdir(parents=True)
        (self.root / 'scripts').mkdir()
        self.resources = []
        self.add('behavior', 'SKILL.md', 'BEHAVIOR_CONTRACT', 'read-only contract')
        self.add('method', 'method.md', 'METHOD', 'quote != inference != fact')
        self.add('scorecard', 'scorecard.md', 'SCORECARD', 'style similarity, not alpha')
        self.add('script-policy', 'scripts/README.md', 'SCRIPT_POLICY', 'never auto execute')
        self.add('query-script', 'scripts/query.py', 'SCRIPT', "raise RuntimeError('audit must never execute me')")
        self.add('statement', 'references/interview.txt', 'PRIMARY_STATEMENT', '看好产业景气',
            locator='https://example.org/interview', published_at='2025-01-02T10:00:00+08:00',
            available_at='2025-01-02T10:05:00+08:00', timing_class='PUBLICATION_VERIFIED')
        self.add('holding', 'references/holding.csv', 'DISCLOSED_ACTION', 'period,symbol\n2025Q1,000001',
            locator='https://example.org/holding', published_at='2025-04-20T18:00:00+08:00',
            available_at='2025-04-20T18:10:00+08:00', timing_class='PUBLICATION_VERIFIED')
        self.add('outcome', 'references/outcome.csv', 'REALIZED_OUTCOME', 'symbol,return\n000001,0.10',
            locator='https://example.org/outcome', available_at='2025-05-01T16:00:00+08:00',
            timing_class='RETROSPECTIVE_REFERENCE')
        self.manifest = {
            'format': FORMAT, 'skill_key': 'manager-a', 'title': '机构投资者 A', 'version': 'draft-1',
            'status': 'DRAFT', 'strategy_source_kind': 'TRADER',
            'summary': '测试说、做、结果分离以及只生成来源预览。',
            'keywords': ['机构投资者', '行业景气'], 'resources': self.resources,
            'claims': [{'claim_id': 'industry-view', 'kind': 'DIRECT_QUOTE', 'text': '看好产业景气',
                'resource_ids': ['statement']}],
            'alignments': [{'alignment_id': 'view-holding-outcome', 'statement_claim_id': 'industry-view',
                'action_resource_ids': ['holding'], 'outcome_resource_ids': ['outcome'],
                'assessment': 'CONSISTENT', 'notes': '只表示披露对照，不证明因果。'}],
            'hypotheses': [{'hypothesis_key': 'cycle-recovery', 'title': '景气修复候选假设',
                'status': 'DRAFT', 'claim_ids': ['industry-view'],
                'feature_candidates': ['行业利润变化'], 'required_data': ['PIT 行业利润'],
                'target_horizon': 'MEDIUM_TERM', 'playbook_key': '',
                'score_semantics': 'RESEARCH_HYPOTHESIS_NOT_ALPHA'}],
            'policy': deepcopy(REQUIRED_POLICY),
        }
        self.write_manifest()

    def add(self, resource_id, relative, role, content, *, locator='', published_at=None,
            available_at=None, timing_class='NOT_APPLICABLE'):
        path = self.root / relative
        path.write_text(content, encoding='utf-8')
        payload = path.read_bytes()
        self.resources.append({'resource_id': resource_id, 'path': relative, 'role': role,
            'sha256': sha256(payload).hexdigest(), 'bytes': len(payload), 'locator': locator,
            'published_at': published_at, 'available_at': available_at, 'timing_class': timing_class})

    def write_manifest(self):
        (self.root / 'skill.yml').write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_full_say_do_outcome_package_is_only_a_partial_source_preview(self):
        audit = audit_research_skill(self.root)
        self.assertTrue(audit['valid'])
        self.assertEqual(audit['counts']['complete_say_do_outcome_triads'], 1)
        self.assertEqual(audit['counts']['scripts'], 1)
        self.assertTrue(audit['readiness']['source_layer_ready'])
        self.assertFalse(audit['readiness']['source_identity_verified'])
        self.assertTrue(audit['readiness']['say_do_ready'])
        self.assertTrue(audit['readiness']['outcome_linked'])
        self.assertTrue(audit['readiness']['playbook_draft_candidate_ready'])
        self.assertFalse(audit['readiness']['quant_validation_completed'])
        self.assertEqual(audit['blockers'], [
            'publication_time_unverified_resources', 'source_authenticity_host_review_required'])
        self.assertEqual(audit['strategy_source_preview']['completeness'], 'PARTIAL')
        self.assertIsNone(audit['strategy_source_preview']['published_at'])
        self.assertFalse(any(audit['boundaries'][key] for key in (
            'automatic_store_write', 'automatic_playbook_creation', 'scripts_executed', 'network_used',
            'direct_trade_eligible', 'daily_scanner_eligible', 'strict_pit_eligible', 'alpha_claimed')))

    def test_resource_tamper_and_symlink_fail_closed(self):
        (self.root / 'references/interview.txt').write_text('changed', encoding='utf-8')
        with self.assertRaises(ResearchSkillError) as changed:
            audit_research_skill(self.root)
        self.assertEqual(changed.exception.code, 'RESOURCE_HASH_MISMATCH')
        (self.root / 'references/interview.txt').write_text('看好产业景气', encoding='utf-8')
        (self.root / 'references/leak').symlink_to(self.root / 'method.md')
        with self.assertRaises(ResearchSkillError) as linked:
            audit_research_skill(self.root)
        self.assertEqual(linked.exception.code, 'PATH_INVALID')

    def test_claim_roles_and_no_trade_policy_are_enforced(self):
        self.manifest['claims'][0]['resource_ids'] = ['holding']
        self.write_manifest()
        with self.assertRaises(ResearchSkillError) as claim:
            audit_research_skill(self.root)
        self.assertEqual(claim.exception.code, 'CLAIM_SOURCE_INVALID')
        self.manifest['claims'][0]['resource_ids'] = ['statement']
        self.manifest['policy']['direct_trade_eligible'] = True
        self.write_manifest()
        with self.assertRaises(ResearchSkillError) as policy:
            audit_research_skill(self.root)
        self.assertEqual(policy.exception.code, 'POLICY_VIOLATION')

    def test_direct_quote_must_exist_verbatim_in_primary_statement(self):
        self.manifest['claims'][0]['text'] = '不存在的原话'
        self.write_manifest()
        with self.assertRaises(ResearchSkillError) as quote:
            audit_research_skill(self.root)
        self.assertEqual(quote.exception.code, 'DIRECT_QUOTE_NOT_FOUND')

    def test_zhengxi_control_package_is_valid_but_source_required(self):
        package = Path(__file__).resolve().parents[1] / 'research_skills/zhengxi'
        audit = audit_research_skill(package)
        self.assertEqual(audit['status'], 'SOURCE_REQUIRED')
        self.assertEqual(audit['package_snapshot'],
            '7185219deebfe271d28e8f77abb72fc9077246ae2a7ddb69bd560de454a9dd6f')
        self.assertEqual(audit['counts']['resources'], 6)
        self.assertEqual(audit['counts']['primary_statements'], 0)
        self.assertEqual(audit['counts']['hypotheses'], 5)
        self.assertFalse(audit['readiness']['source_layer_ready'])
        self.assertFalse(audit['readiness']['playbook_draft_candidate_ready'])
        self.assertEqual(audit['strategy_source_preview']['completeness'], 'PENDING')
        self.assertIn('primary_statement_missing', audit['blockers'])
        self.assertFalse(audit['boundaries']['quarterly_data_intraday_eligible'])


if __name__ == '__main__':
    unittest.main()
