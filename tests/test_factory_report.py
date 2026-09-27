from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import unittest

import test_core
from test_restricted_dsl import sample_ast
from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.agent.alpha_factory_tools import AlphaFactoryAPI
from quantlab.agent.factory_report import build_factory_report, render_factory_report_markdown
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.app import build_runner
from quantlab.experiments.config import ExperimentConfig
from quantlab.storage.codec import digest
from quantlab.workbench.jobs import JobQueue


class FactoryReportTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_core.CoreTests(); self.fx.setUp(); self.addCleanup(self.fx.tearDown)
        self.output = self.fx.root / 'factory-report-runs'; self.output.mkdir()
        cfg = ExperimentConfig('Factory report baseline', self.fx.request, 'BASE.MOMENTUM',
                               parameters={'lookback': 2}, horizons=(1,), quantiles=3, replay=True)
        self.baseline = build_runner(self.fx.root, self.output, self.fx.symbols).run(cfg)
        dsl = DslCandidateService(self.output); request = str(uuid4())
        draft = dsl.propose(request, '报告测试DSL', sample_ast(), self.baseline.run_id)
        self.candidate = dsl.register(request, draft['plan_digest'], confirmed=True)['candidate_id']
        self.service = AlphaFactoryService(self.output, self.fx.root)
        self.plan = {'name': '报告 <Factory>|&', 'candidate_ids': [self.candidate],
            'baseline_run_id': self.baseline.run_id, 'control_run_ids': [self.baseline.run_id],
            'baseline_execution_run_id': None, 'train_end': '2025-01-06',
            'evaluation_start': '2025-01-07', 'horizon': 1, 'alpha': .05,
            'min_common_finite_ratio': .5, 'max_abs_signal_corr': 1.0,
            'require_positive_paired_ic_difference': False, 'require_net_return': False}

    def _complete(self, plan=None):
        proposal = self.service.propose(str(uuid4()), plan or self.plan)
        queue = JobQueue(self.output, self.fx.root)
        try:
            self.service.submit(proposal['proposal_id'], proposal['prepared_digest'], lambda: queue, confirmed=True)
        finally:
            queue.close()
        state = self.service.sync(proposal['proposal_id'])
        return state, self.output / '_alpha_factory' / proposal['proposal_id'] / 'state.json'

    def test_complete_report_is_read_only_paginated_and_stable(self):
        state, state_path = self._complete()
        parent = self.output / state['result_run_id'] / 'experiment.json'
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (state_path, parent)}
        first = build_factory_report(self.output, state['proposal_id'], limit=1)
        second = build_factory_report(self.output, state['proposal_id'], offset=0, limit=12)
        self.assertEqual(first['report_digest'], second['report_digest'])
        self.assertEqual(first['prepared_digest'], state['prepared_digest'])
        self.assertEqual(first['verification']['deep_verified'], False)
        self.assertEqual(first['sources'][-1]['run_id'], state['result_run_id'])
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (state_path, parent)}
        self.assertEqual(before, after)

    def test_registered_factor_v2_complete_report(self):
        plan = dict(self.plan)
        plan.pop('candidate_ids')
        plan['format'] = 'alpha-factory-plan-v2'
        plan['candidate_refs'] = [{'kind': 'registered_factor', 'factor_id': 'BASE.MOMENTUM',
                                   'version': '1.0.0', 'parameters': {'lookback': 3}, 'name': 'V2 registered'}]
        state, _ = self._complete(plan)
        report = build_factory_report(self.output, state['proposal_id'])
        candidate = report['candidates'][0]
        self.assertEqual(candidate['factor_id'], 'BASE.MOMENTUM')
        self.assertEqual(candidate['version'], '1.0.0')
        self.assertEqual(candidate['name'], 'V2 registered')
        self.assertEqual(report['counts']['planned_tests'], 1)

    def test_expected_digest_rejects_changed_state(self):
        state, state_path = self._complete()
        report = build_factory_report(self.output, state['proposal_id'])
        state['last_sync_at'] = 'changed-state-bytes'
        from quantlab.experiments.campaign_state import write_checked
        write_checked(state_path, state)
        with self.assertRaisesRegex(ValueError, '指纹已变化'):
            build_factory_report(self.output, state['proposal_id'], expected_digest=report['report_digest'])

    def test_missing_failed_and_p_less_slots_remain_explicit(self):
        state, state_path = self._complete()
        state['tests'][0].update(status='failed', p_value=None, estimate=None, error='bad|<br>\n')
        state['tests'][0].pop('p_holm', None); state['tests'][0].pop('reject', None)
        from quantlab.experiments.campaign_state import write_checked
        write_checked(state_path, state)
        # A completed result must agree byte-for-byte with its parent; disagreement fails closed.
        with self.assertRaisesRegex(ValueError, '不匹配'):
            build_factory_report(self.output, state['proposal_id'])
        pending = self.service.propose(str(uuid4()), self.plan)
        pending_state = self.service.get(pending['proposal_id'])
        pending_state['tests'] = [{'candidate_id': self.candidate, 'id': 'residual_ic', 'kind': 'residual_alpha',
                                  'status': 'failed', 'p_value': None, 'estimate': None, 'error': 'bad|<br>\n'}]
        self.service.store.save(pending_state)
        report = build_factory_report(self.output, pending['proposal_id'])
        slot = report['candidates'][0]['tests'][0]
        self.assertIsNone(slot['p_value']); self.assertEqual(slot['error'], 'bad|<br>\n')

    def test_parent_archive_missing_mismatch_oversize_and_symlink_rejected(self):
        state, _ = self._complete(); parent = self.output / state['result_run_id'] / 'experiment.json'
        data = parent.read_bytes(); parent.unlink()
        with self.assertRaisesRegex(ValueError, '不存在'):
            build_factory_report(self.output, state['proposal_id'])
        parent.write_bytes(data + b' ' * (8 * 1024 * 1024))
        with self.assertRaisesRegex(ValueError, '8MiB'):
            build_factory_report(self.output, state['proposal_id'])
        parent.write_bytes(data)
        record = json.loads(data); record['manifest']['prepared_digest'] = '0' * 64
        record['experiment_id'] = digest(record['manifest'])
        parent.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'prepared_digest'):
            build_factory_report(self.output, state['proposal_id'])
        parent.unlink(); parent.symlink_to(self.output / 'missing')
        with self.assertRaisesRegex(ValueError, '符号链接'):
            build_factory_report(self.output, state['proposal_id'])

    def test_bad_state_digest_or_symlink_root_rejected(self):
        proposal = self.service.propose(str(uuid4()), self.plan)
        state_path = self.output / '_alpha_factory' / proposal['proposal_id'] / 'state.json'
        state = self.service.get(proposal['proposal_id']); state['prepared']['plan']['name'] = 'tampered'
        from quantlab.experiments.campaign_state import write_checked
        write_checked(state_path, state)
        with self.assertRaisesRegex(ValueError, 'prepared_digest'):
            build_factory_report(self.output, proposal['proposal_id'])
        link = self.fx.root / 'output-link'; link.symlink_to(self.output)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            build_factory_report(link, proposal['proposal_id'])

    def test_tool_and_peer_review_api_contract_is_read_only(self):
        state, _ = self._complete(); api = AlphaFactoryAPI(self.output, self.fx.root)
        tool = next(item for item in api.schemas() if item['name'] == 'get_alpha_factory_report')
        self.assertIn('get_alpha_factory_report', [x['name'] for x in api.schemas()])
        args = {'proposal_id': state['proposal_id'], 'offset': 0, 'limit': 6, 'expected_digest': ''}
        result = api.call(tool['name'], args)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['result_run_id'], state['result_run_id'])
        self.assertEqual([x['kind'] for x in result['evidence']], ['alpha_factory', 'experiment'])
        self.assertFalse(api.call('execute_alpha_factory', {})['ok'])
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        review = ReviewReadOnlyAPI(self.output, self.fx.root)
        # Review API only exposes its static allowlist; no writes/execute are introduced.
        self.assertNotIn('get_alpha_factory_report', [x['name'] for x in review.schemas()])
        self.assertFalse(review.call('get_alpha_factory_report', args)['ok'])
        self.assertEqual(self.service.get(state['proposal_id'])['status'], 'completed')

    def test_markdown_escapes_untrusted_values_and_empty_report_has_no_conclusion(self):
        pending = self.service.propose(str(uuid4()), self.plan)
        report = build_factory_report(self.output, pending['proposal_id'])
        markdown = render_factory_report_markdown(report)
        self.assertIn('&lt;Factory&gt;', markdown); self.assertIn('&#124;', markdown); self.assertIn('&amp;', markdown)
        self.assertIn('报告指纹', markdown); self.assertIn('不是AI结论', markdown)
        self.assertIsNone(report['result_run_id'])
        self.assertEqual(report['verification']['level'], 'saved_state_only')
        self.assertTrue(all(candidate['decision']['status'] == 'unknown' for candidate in report['candidates']))


if __name__ == '__main__':
    unittest.main()
