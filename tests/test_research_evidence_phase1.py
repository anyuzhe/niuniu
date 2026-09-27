import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from quantlab.agent.home_tools import HomeAPI, MAX_RESPONSE_BYTES
from quantlab.desktop.market_pages import candidate_prompt
from quantlab.storage.codec import encode
from quantlab.trading.market_overview import overview_root
from quantlab.trading.research_evidence import archive_research_reference, candidate_rule_evidence, find_factor_evidence


class _Inner:
    def schemas(self): return []
    def call(self, name, args): return {'ok': False}


class ResearchEvidencePhase1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.output = self.root / 'artifacts'; self.output.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_candidate_rule_legacy_validation_adapts_without_run_id(self):
        rule = {'key': 'strong_trend', 'name': '强势趋势', 'description': '原规则', 'count': 2,
                'validation': {'samples': 3, 'text': '旧缓存文本', 'verdict': 'insufficient'}, 'stocks': []}
        evidence = candidate_rule_evidence(rule, trading_day='2026-09-27', caveats=['样本不足'])
        self.assertEqual(evidence['version'], 'niuniu-research-evidence-v1')
        self.assertEqual(evidence['status'], 'research_only_reference')
        self.assertIsNone(evidence['source']['run_id'])
        self.assertEqual(evidence['sample']['non_overlapping_days'], 3)
        self.assertIn('仅名称相同不能认定', evidence['rule_identity']['identity_note'])
        good = str(uuid4())
        with_uuid = candidate_rule_evidence({'key': 'k', 'validation': {'run_id': good}})
        self.assertIsNone(with_uuid['source']['run_id'])
        self.assertEqual(with_uuid['source']['unverified_run_id'], good)
        self.assertIsNone(candidate_rule_evidence({'key': 'k', 'validation': {'run_id': 'not-a-run'}})['source']['unverified_run_id'])

    def test_candidate_warnings_not_truncated_and_valid_uuid_unverified(self):
        rule = {'key': 'k', 'validation': {'run_id': str(uuid4()), 'samples': 1}}
        warnings = [f'warning-{i}' for i in range(13)]
        evidence = candidate_rule_evidence(rule, caveats=warnings)
        self.assertEqual(evidence['source']['run_id'], None)
        self.assertTrue(evidence['source']['unverified_run_id'])
        self.assertGreater(len(evidence['limitations']), 12)
        self.assertTrue(evidence['limitations_meta']['incomplete'])
        self.assertIn('LIMITATIONS_EXCEED', evidence['error'])

    def test_candidate_prompt_uses_structured_evidence_not_text_only(self):
        overview = {'trading_day': '2026-09-27', 'summary': ['市场摘要'], 'sources': {'daily': 'fixture'}}
        rule = {'key': 'k', 'name': '候选', 'description': '精确原规则', 'count': 1,
                'validation': {'samples': 2, 'text': '样本不足', 'verdict': 'insufficient', 'cost': 0.002},
                'stocks': [{'code': 'sh.600001', 'name': '甲', 'reason': '入选'}]}
        prompt = candidate_prompt(overview, rule)
        self.assertIn('```json', prompt)
        self.assertIn('"sample"', prompt)
        self.assertIn('"costs"', prompt)
        self.assertIn('不要自动选择相似因子', prompt)

    def test_home_tool_returns_structured_candidate_evidence_under_budget(self):
        root = overview_root(self.output); root.mkdir(parents=True)
        overview = {'format': 'niuniu-market-overview-v1', 'trading_day': '2026-09-27', 'built_at': '2026-09-27T10:00:00+00:00',
            'summary': ['上涨 1 家'], 'market': {'up_ratio': 0.5}, 'percentile': {}, 'margin': None,
            'caveats': ['描述性统计'], 'ladder': [], 'industries': [], 'reasons': [], 'sources': {'daily': 'fixture'},
            'candidates': [{'key': 'k', 'name': '候选', 'description': '精确原规则', 'count': 1,
                'validation': {'samples': 1, 'text': '样本不足', 'verdict': 'insufficient', 'cost': 0.002},
                'stocks': [{'code': 'sh.600001', 'name': '甲', 'industry': '测试', 'pct': float('nan'), 'reason': '入选'}]}]}
        (root / '2026-09-27.json').write_text(json.dumps(overview, ensure_ascii=False, allow_nan=True), encoding='utf-8')
        result = HomeAPI(_Inner(), self.output).call('get_market_overview', {})
        self.assertTrue(result['ok'])
        self.assertLessEqual(len(encode(result).encode('utf-8')), MAX_RESPONSE_BYTES)
        candidate = result['data']['candidates'][0]
        self.assertIn('evidence_summary', candidate)
        self.assertIsNone(candidate['stocks'][0]['pct'])
        self.assertTrue(result['warnings'])
        self.assertNotIn('validation', candidate)

    def test_factor_evidence_discovery_exact_identity_and_mismatch(self):
        good = str(uuid4()); mismatch = str(uuid4()); bad = str(uuid4())
        for rid, version in [(good, '1.0.0'), (mismatch, '2.0.0')]:
            d = self.output / rid; d.mkdir()
            record = {'run_id': rid, 'experiment_id': 'e-' + rid[:8], 'kind': 'factor', 'status': 'completed',
                'created_at': '2026-09-27T00:00:00Z', 'manifest': {'config': {'research_question': 'q',
                    'factor_id': 'BASE.TEST', 'factor_version': version, 'parameters': {'n': 5},
                    'data': {'start': '2026-01-01', 'end': '2026-02-01', 'timeframe': '1d', 'symbols': ['sh.600001']}}},
                'limitations': ['fixture']}
            (d / 'experiment.json').write_text(json.dumps(record), encoding='utf-8')
        d = self.output / bad; d.mkdir(); (d / 'experiment.json').write_text('{bad json', encoding='utf-8')
        result = find_factor_evidence(self.output, factor_id='BASE.TEST', factor_version='1.0.0', parameters={'n': 5})
        self.assertEqual(result['total_matches'], 1)
        self.assertEqual(result['matches'][0]['source']['run_id'], good)
        self.assertEqual(result['mismatches'][0]['run_id'], mismatch)
        self.assertTrue(result['errors'])
        self.assertEqual(result['scanned'], 3)
        self.assertIsNone(result['next_offset'])

    def test_archive_reference_reads_original_fields_not_metadata_only(self):
        rid = str(uuid4()); d = self.output / rid; d.mkdir()
        record = {'run_id': rid, 'experiment_id': 'e', 'kind': 'factor', 'status': 'completed',
                  'created_at': '2026-09-27T00:00:00Z',
                  'manifest': {'parameters': {'old_cfg': 1}, 'execution': {'engine': 'x'}, 'config': {
                      'factor_id': 'BASE.TEST', 'factor_version': '1', 'parameters': {'n': 3},
                      'resolved_parameters': {'n': 3, 'expanded': True},
                      'data': {'start': '2026-01-01', 'end': '2026-01-02', 'timeframe': '1d', 'symbols': ['s']}}},
                  'parameters': {'runtime': True}, 'execution': {'costs': {'commission': 1}},
                  'limitations': ['real limitation'], 'sources': [{'kind': 'fixture'}]}
        (d / 'experiment.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        ref = archive_research_reference(self.output, rid)
        self.assertTrue(ref['metadata_only'])
        self.assertFalse(ref['deep_verified'])
        self.assertEqual(ref['verification'], 'original_header_sha256_only')
        self.assertEqual(ref['rule_identity']['parameters'], {'n': 3})
        self.assertEqual(ref['rule_identity']['resolved_parameters'], {'old_cfg': 1})
        self.assertEqual(ref['costs']['source'], 'manifest.execution')
        self.assertEqual(ref['costs']['configuration'], {'engine': 'x'})
        self.assertEqual(ref['limitations'], ['real limitation'])
        self.assertIn('sha256', ref['source']['fingerprint'])

    def test_find_factor_evidence_rejects_bool_float_pagination(self):
        with self.assertRaises(ValueError):
            find_factor_evidence(self.output, factor_id='BASE.TEST', offset=True)
        with self.assertRaises(ValueError):
            find_factor_evidence(self.output, factor_id='BASE.TEST', limit=1.5)


if __name__ == '__main__':
    unittest.main()
