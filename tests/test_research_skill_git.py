from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from quantlab.experiments.campaign_state import read_checked
from quantlab.knowledge.research_skill import FORMAT, REQUIRED_POLICY, ResearchSkillError, audit_research_skill
from quantlab.knowledge.research_skill_git import (
    ARCHIVE_FORMAT, CURATION_FORMAT, archive_git_research_skill,
    audit_git_research_skill_archives, materialize_git_research_skill,
)


class ResearchSkillGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data_root = self.base / 'data'
        self.data_root.mkdir()
        self.repo = self.base / 'upstream'
        self.repo.mkdir()
        self.origin = 'https://github.com/example/manager-skill.git'
        self.executed = self.base / 'external-script-executed'
        files = {
            'LICENSE': 'MIT test license',
            'references/interview.txt': '我的投资以景气为主。',
            'references/holding.json': '{"quarter":"2025Q1","symbol":"000001"}',
            'references/outcome.json': '{"date":"2025-05-01","return":0.1}',
            'scripts/evil.py': f"from pathlib import Path\nPath({str(self.executed)!r}).write_text('bad')\n",
        }
        for relative, content in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self._run('init', '-q')
        self._run('config', 'user.email', 'test@example.com')
        self._run('config', 'user.name', 'Test')
        self._run('add', '.')
        self._run('commit', '-qm', 'fixture')
        self._run('remote', 'add', 'origin', self.origin)
        self.commit = self._output('rev-parse', 'HEAD')
        self.tree = self._output('rev-parse', 'HEAD^{tree}')
        self.control = self.base / 'control'
        self._write_control()
        self.plan = self.base / 'plan.json'
        self._write_plan()

    def _run(self, *arguments):
        subprocess.run(['git', '-C', str(self.repo), *arguments], check=True, capture_output=True)

    def _output(self, *arguments):
        return subprocess.run(['git', '-C', str(self.repo), *arguments], check=True,
            capture_output=True, text=True).stdout.strip()

    def _resource(self, root, resource_id, relative, role, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        payload = path.read_bytes()
        return {'resource_id': resource_id, 'path': relative, 'role': role,
            'sha256': sha256(payload).hexdigest(), 'bytes': len(payload), 'locator': '',
            'published_at': None, 'available_at': None, 'timing_class': 'NOT_APPLICABLE'}

    def _write_control(self):
        self.control.mkdir()
        resources = [
            self._resource(self.control, 'behavior', 'SKILL.md', 'BEHAVIOR_CONTRACT', 'deny execution'),
            self._resource(self.control, 'method', 'method.md', 'METHOD', 'quote then hypothesis'),
            self._resource(self.control, 'scorecard', 'scorecard.md', 'SCORECARD', 'similarity only'),
            self._resource(self.control, 'script-policy', 'scripts/README.md', 'SCRIPT_POLICY', 'never execute'),
        ]
        manifest = {'format': FORMAT, 'skill_key': 'manager-skill', 'title': 'control',
            'version': 'control-1', 'status': 'SOURCE_REQUIRED', 'strategy_source_kind': 'TRADER',
            'summary': 'source-free control package', 'keywords': ['景气'], 'resources': resources,
            'claims': [], 'alignments': [],
            'hypotheses': [{'hypothesis_key': 'cycle', 'title': '景气候选', 'status': 'DRAFT',
                'claim_ids': [], 'feature_candidates': ['景气'], 'required_data': ['PIT data'],
                'target_horizon': 'MEDIUM_TERM', 'playbook_key': '',
                'score_semantics': 'RESEARCH_HYPOTHESIS_NOT_ALPHA'}],
            'policy': deepcopy(REQUIRED_POLICY)}
        (self.control / 'skill.yml').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding='utf-8')

    def _plan_resource(self, resource_id, upstream, target, role):
        payload = (self.repo / upstream).read_bytes()
        return {'resource_id': resource_id, 'upstream_path': upstream, 'target_path': target,
            'role': role, 'sha256': sha256(payload).hexdigest(), 'bytes': len(payload),
            'locator': f'https://github.com/example/manager-skill/blob/{self.commit}/{upstream}'}

    def _write_plan(self, quote='我的投资以景气为主。'):
        plan = {'format': CURATION_FORMAT, 'skill_key': 'manager-skill',
            'control_snapshot': audit_research_skill(self.control)['package_snapshot'],
            'archive_snapshot': '0' * 64, 'version': 'upstream-1', 'status': 'DRAFT',
            'strategy_source_kind': 'TRADER', 'title': 'curated manager skill',
            'summary': 'retrospective fixture only', 'keywords': ['景气', '季度持仓'],
            'resources': [
                self._plan_resource('license', 'LICENSE', 'references/upstream/LICENSE.txt', 'DOCUMENTATION'),
                self._plan_resource('statement', 'references/interview.txt',
                    'references/upstream/interview.txt', 'PRIMARY_STATEMENT'),
                self._plan_resource('holding', 'references/holding.json',
                    'references/upstream/holding.json', 'DISCLOSED_ACTION'),
                self._plan_resource('outcome', 'references/outcome.json',
                    'references/upstream/outcome.json', 'REALIZED_OUTCOME'),
            ],
            'claims': [
                {'claim_id': 'view', 'kind': 'DIRECT_QUOTE', 'text': quote,
                    'resource_ids': ['statement']},
                {'claim_id': 'holding-fact', 'kind': 'FACT_TO_VERIFY', 'text': 'holding to verify',
                    'resource_ids': ['holding']},
            ],
            'alignments': [{'alignment_id': 'say-do-result', 'statement_claim_id': 'view',
                'action_resource_ids': ['holding'], 'outcome_resource_ids': ['outcome'],
                'assessment': 'MIXED', 'notes': 'no causal claim'}],
            'hypotheses': [{'hypothesis_key': 'cycle', 'title': '景气候选', 'status': 'DRAFT',
                'claim_ids': ['view'], 'feature_candidates': ['景气'], 'required_data': ['PIT data'],
                'target_horizon': 'MEDIUM_TERM', 'playbook_key': '',
                'score_semantics': 'RESEARCH_HYPOTHESIS_NOT_ALPHA'}]}
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

    def _archive(self):
        result = archive_git_research_skill(self.data_root, self.repo, 'manager-skill', self.origin,
            self.commit, self.tree, confirm_untrusted_no_exec=True,
            now_fn=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc))
        plan = json.loads(self.plan.read_text())
        plan['archive_snapshot'] = result['archive_snapshot']
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    def test_archive_is_idempotent_and_never_executes_external_script(self):
        with self.assertRaises(ResearchSkillError) as missing_confirmation:
            archive_git_research_skill(self.data_root, self.repo, 'manager-skill', self.origin,
                self.commit, self.tree)
        self.assertEqual(missing_confirmation.exception.code, 'CONFIRMATION_REQUIRED')
        first = self._archive()
        self.assertTrue(first['created'])
        self.assertFalse(self.executed.exists())
        second = archive_git_research_skill(self.data_root, self.repo, 'manager-skill', self.origin,
            self.commit, self.tree, confirm_untrusted_no_exec=True,
            now_fn=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc))
        self.assertFalse(second['created'])
        self.assertEqual(first['archive_snapshot'], second['archive_snapshot'])
        receipt = read_checked(Path(first['path']))
        self.assertEqual(receipt['format'], ARCHIVE_FORMAT)
        self.assertEqual(receipt['observed_at'], '2026-09-16T00:00:00+00:00')
        audit = audit_git_research_skill_archives(self.data_root, 'manager-skill')
        self.assertEqual(audit['verified_receipts'], 1)
        self.assertEqual(audit['invalid_receipts'], 0)
        self.assertFalse(audit['boundaries']['strict_pit_eligible'])

    def test_archive_rejects_wrong_identity_and_dirty_checkout(self):
        with self.assertRaises(ResearchSkillError) as wrong:
            archive_git_research_skill(self.data_root, self.repo, 'manager-skill', self.origin,
                '1' * 40, self.tree, confirm_untrusted_no_exec=True)
        self.assertEqual(wrong.exception.code, 'GIT_IDENTITY_MISMATCH')
        (self.repo / 'untracked.txt').write_text('extra')
        with self.assertRaises(ResearchSkillError) as dirty:
            self._archive()
        self.assertEqual(dirty.exception.code, 'REPOSITORY_DIRTY')
        (self.repo / 'untracked.txt').unlink()
        (self.repo / 'link').symlink_to(self.repo / 'LICENSE')
        with self.assertRaises(ResearchSkillError) as linked:
            self._archive()
        self.assertEqual(linked.exception.code, 'REPOSITORY_DIRTY')

    def test_object_tamper_is_reported(self):
        archived = self._archive()
        receipt = read_checked(Path(archived['path']))
        target = self.data_root / receipt['files'][0]['object_path']
        target.write_bytes(b'tampered')
        audit = audit_git_research_skill_archives(self.data_root, 'manager-skill')
        self.assertEqual(audit['verified_receipts'], 0)
        self.assertEqual(audit['invalid_receipts'], 1)

    def test_empty_tracked_blobs_are_archived_but_never_curated(self):
        for relative in ('pkg/__init__.py', 'logs/.gitkeep'):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'')
        self._run('add', '.')
        self._run('commit', '-qm', 'empty markers')
        self.commit = self._output('rev-parse', 'HEAD')
        self.tree = self._output('rev-parse', 'HEAD^{tree}')
        archived = self._archive()
        receipt = read_checked(Path(archived['path']))
        empty = [item for item in receipt['files'] if item['bytes'] == 0]
        self.assertEqual({item['path'] for item in empty}, {'pkg/__init__.py', 'logs/.gitkeep'})
        self.assertEqual({item['sha256'] for item in empty}, {sha256(b'').hexdigest()})
        audit = audit_git_research_skill_archives(self.data_root, 'manager-skill')
        self.assertEqual((audit['verified_receipts'], audit['invalid_receipts']), (1, 0))
        plan = json.loads(self.plan.read_text())
        plan['resources'].append(self._plan_resource('empty-marker', 'pkg/__init__.py',
            'references/upstream/empty.py', 'DOCUMENTATION'))
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.assertRaises(ResearchSkillError) as empty_resource:
            materialize_git_research_skill(self.data_root, self.control, self.plan,
                confirm_retrospective_only=True)
        self.assertEqual(empty_resource.exception.code, 'BUDGET_EXCEEDED')
        packages = self.data_root / 'research/external_research_skills/packages/manager-skill'
        self.assertEqual(list(packages.iterdir()), [])

    def test_curated_package_is_partial_and_quote_must_exist_verbatim(self):
        self._archive()
        with self.assertRaises(ResearchSkillError) as missing_confirmation:
            materialize_git_research_skill(self.data_root, self.control, self.plan)
        self.assertEqual(missing_confirmation.exception.code, 'CONFIRMATION_REQUIRED')
        result = materialize_git_research_skill(self.data_root, self.control, self.plan,
            confirm_retrospective_only=True)
        self.assertTrue(result['created'])
        self.assertFalse(result['source_authenticity_verified'])
        self.assertFalse(result['source_publication_verified'])
        audit = audit_research_skill(result['path'])
        self.assertEqual(audit['status'], 'DRAFT')
        self.assertEqual(audit['counts']['complete_say_do_outcome_triads'], 1)
        self.assertTrue(audit['readiness']['playbook_draft_candidate_ready'])
        self.assertFalse(audit['readiness']['quant_validation_completed'])
        self.assertEqual(audit['blockers'], [
            'publication_time_unverified_resources', 'source_authenticity_host_review_required'])
        self.assertEqual(audit['strategy_source_preview']['completeness'], 'PARTIAL')
        self.assertFalse(Path(result['path'], 'scripts/evil.py').exists())
        again = materialize_git_research_skill(self.data_root, self.control, self.plan,
            confirm_retrospective_only=True)
        self.assertFalse(again['created'])
        plan = json.loads(self.plan.read_text())
        plan['control_snapshot'] = 'f' * 64
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.assertRaises(ResearchSkillError) as control:
            materialize_git_research_skill(self.data_root, self.control, self.plan,
                confirm_retrospective_only=True)
        self.assertEqual(control.exception.code, 'PACKAGE_IDENTITY_MISMATCH')
        self._write_plan(quote='不存在的伪原话')
        plan = json.loads(self.plan.read_text())
        plan['archive_snapshot'] = result['archive_snapshot']
        self.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.assertRaises(ResearchSkillError) as quote:
            materialize_git_research_skill(self.data_root, self.control, self.plan,
                confirm_retrospective_only=True)
        self.assertEqual(quote.exception.code, 'DIRECT_QUOTE_NOT_FOUND')


if __name__ == '__main__':
    unittest.main()
