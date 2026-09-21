"""Code-backed template discovery and exact-version proposals, without data acquisition."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.proposal_tools import ResearchProposalAPI
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from quantlab.theory.templates import templates, resolve_template

class ResearchTemplateToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = ReadOnlyResearchAPI(self.root)

    def test_paged_catalog_exactly_matches_code_not_strategy_count(self):
        expected = templates()
        actual = []
        for offset in range(0, len(expected), 3):
            result = self.api.call('list_research_templates', {'query': '', 'offset': offset, 'limit': 3})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['data']['total'], len(expected))
            self.assertFalse(result['data']['complete_trading_strategy'])
            actual.extend(result['data']['templates'])
        self.assertEqual([r['template_id'] for r in actual], [r['template_id'] for r in expected])
        for args in ({'query': '', 'offset': 0, 'limit': 0}, {'query': '', 'offset': True, 'limit': 2}):
            self.assertFalse(self.api.call('list_research_templates', args)['ok'])
        self.assertEqual(self.api.call('list_research_templates',
            {'query': 'no-such-template-xyz', 'offset': 0, 'limit': 20})['data']['total'], 0)

    def test_every_template_uses_unchanged_rules_and_existing_proposal_preview(self):
        proposals = ResearchProposalAPI(self.root, self.root)
        for template in templates():
            args = {'template_id': template['template_id'], 'version': template['version']}
            result = self.api.call('get_research_template', args)
            self.assertTrue(result['ok'], result)
            data = result['data']
            parameters, origin = resolve_template(template['template_id'], self.api.registry, template['version'])
            self.assertEqual(data['template']['parameters'], parameters)
            self.assertEqual(data['template']['code_hash'], origin['code_hash'])
            self.assertFalse(data['execution_authorized'])
            spec = {'question': 'synthetic template wiring', 'symbols': ['sh.600000', 'sz.000001', 'sh.600519'],
                'start': '2025-01-01', 'end': '2025-06-30', 'timeframe': '1d', 'adjustment': 'qfq',
                'horizons': [1], 'replay': True, **data['submission_fields']}
            preview = proposals.call('preview_experiment', {'spec_json': json.dumps(spec)})
            self.assertTrue(preview['ok'], preview)
            self.assertFalse((self.root / '_jobs').exists())
            conflict = {**spec, 'factor': 'BASE.MOMENTUM'}
            self.assertFalse(proposals.call('preview_experiment', {'spec_json': json.dumps(conflict)})['ok'])

    def test_versions_and_returned_mutations_cannot_change_templates(self):
        template = templates()[0]
        for version in ('', 'latest', '9.9.9'):
            result = self.api.call('get_research_template', {'template_id': template['template_id'], 'version': version})
            self.assertFalse(result['ok']); self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
        args = {'template_id': template['template_id'], 'version': template['version']}
        first = self.api.call('get_research_template', args)['data']
        before = first['template_digest']
        first['template']['parameters']['inputs'].clear()
        second = self.api.call('get_research_template', args)['data']
        self.assertEqual(second['template_digest'], before)
        self.assertEqual(len(second['template']['parameters']['inputs']), 2)

    def test_chat_reviewer_and_strict_spec_keep_distinct_permissions(self):
        names = {'list_research_templates', 'get_research_template'}
        chat = ChatRuntime(self.root, local_data_only=True)
        reviewer = ReviewReadOnlyAPI(self.root)
        for api in (chat.api, reviewer):
            self.assertTrue(names <= {s['name'] for s in api.schemas()})
        # This isolates the permission wrapper, not a real QM50 import or qualification claim.
        with patch('quantlab.agent.research_spec_tools.ResearchSpecStore.get'):
            strict = ResearchSpecAPI(self.api, self.root, active_spec='synthetic-bound-spec')
        self.assertFalse(names & {s['name'] for s in strict.schemas()})
        for name in names:
            self.assertEqual(strict.call(name, {})['error']['code'], 'SPEC_SUBSTITUTION_REJECTED')
        self.assertNotIn('submit_granted_experiment', {s['name'] for s in reviewer.schemas()})

if __name__ == '__main__':
    unittest.main()
