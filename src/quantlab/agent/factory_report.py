"""Bounded, read-only projection of saved Alpha Factory evidence."""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import stat
from pathlib import Path
from uuid import UUID, uuid5

from quantlab.agent.alpha_factory import AlphaFactoryStore, canonical_id, plan_candidate_ids
from quantlab.agent.model_config import strict_json, ModelError
from quantlab.storage.codec import digest
from quantlab.workbench.server import ArtifactCatalog

MAX_PARENT_BYTES = 8 * 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 12
MAX_TEXT = 1000
MAX_JSON = 64 * 1024


def _no_symlink(path: Path, *, must_exist=True):
    path = Path(os.path.abspath(path))
    # Check managed path components explicitly; OS ancestors may legitimately be
    # mounted through system aliases (e.g. /private/var on macOS).
    if path.is_symlink():
        raise ValueError('Factory报告路径不能经过符号链接')
    if must_exist and not path.exists():
        raise ValueError('Factory报告来源不存在')
    return path


def _bounded(value, limit=MAX_TEXT):
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    return {'text': value[:limit], 'truncated': True, 'original_length': len(value)}


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Factory报告来源包含非有限数，不能静默改成未知或零')
    if isinstance(value, dict):
        return {str(k): _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def _safe_parameters(value):
    if not isinstance(value, dict):
        return {'value': _bounded(str(value), 500), 'truncated': True}
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
    if len(raw) <= 2000:
        return _finite(value)
    return {'json': raw[:1800], 'truncated': True, 'original_length': len(raw)}


def _read_limited(path, maximum):
    path = _no_symlink(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('Factory来源超过读取上限或不是普通文件')
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('Factory来源超过读取上限')
    return raw


def _parse_object(raw):
    try:
        value = strict_json(raw.decode('utf-8'))
    except (ValueError, UnicodeError, ModelError, RecursionError) as exc:
        raise ValueError('Factory来源JSON无效、字段重复或含非有限数') from exc
    if not isinstance(value, dict):
        raise ValueError('Factory来源必须为JSON对象')
    return value


def _state_bytes(store, proposal_id):
    _no_symlink(store.root)
    folder = _no_symlink(store.root / proposal_id)
    state_path = folder / 'state.json'
    before = _read_limited(state_path, MAX_STATE_BYTES)
    receipt = _parse_object(before)
    state = {k:v for k,v in receipt.items() if k != 'checksum'}
    # Keep the existing campaign receipt checksum contract, without an unbounded second JSON read.
    if receipt.get('checksum') != digest(state):
        raise ValueError('Factory状态checksum不匹配')
    if before != _read_limited(state_path, MAX_STATE_BYTES):
        raise ValueError('Factory状态读取期间发生变化')
    if state.get('proposal_id') != proposal_id:
        raise ValueError('Factory状态身份不一致')
    return state, hashlib.sha256(before).hexdigest()


def _parent_record(output, run_id, state, prepared):
    catalog = ArtifactCatalog(output)
    _no_symlink(catalog.root / run_id)
    path = _no_symlink(catalog.root / run_id / 'experiment.json')
    if path.stat().st_size > MAX_PARENT_BYTES:
        raise ValueError('Factory完成父归档超过8MiB读取上限')
    before = _read_limited(path, MAX_PARENT_BYTES)
    record = _parse_object(before)
    after = _read_limited(path, MAX_PARENT_BYTES)
    if before != after:
        raise ValueError('Factory父归档读取期间发生变化')
    if (record.get('run_id') != run_id or record.get('kind') != 'alpha_factory' or
            record.get('status') != 'completed'):
        raise ValueError('Factory完成父归档身份/类型/状态不匹配')
    if run_id != str(uuid5(UUID(state['proposal_id']), 'alpha-factory-result')):
        raise ValueError('Factory结果run_id与proposal身份不匹配')
    manifest = record.get('manifest')
    if not isinstance(manifest, dict) or record.get('experiment_id') != digest(manifest):
        raise ValueError('Factory父归档manifest digest不匹配')
    if not isinstance(manifest, dict) or manifest.get('prepared_digest') != state.get('prepared_digest'):
        raise ValueError('Factory父归档prepared_digest不匹配')
    if manifest.get('plan') != prepared.get('plan'):
        raise ValueError('Factory父归档冻结计划与状态不匹配')
    if manifest.get('format') != prepared.get('format'):
        raise ValueError('Factory父归档格式与状态不匹配')
    for key, expected in (('source_fingerprints', prepared.get('sources')),
                          ('selection_rule', prepared.get('selection_rule')),
                          ('job_ids', [row['job_id'] for row in state.get('jobs', [])])):
        if manifest.get(key) != expected:
            raise ValueError('Factory父归档来源与冻结状态不匹配：' + key)
    summary = record.get('summary')
    if not isinstance(summary, dict) or not isinstance(summary.get('tests'), list) or not isinstance(summary.get('decisions'), list):
        raise ValueError('Factory父归档缺少检验/决策数据')
    if state.get('tests') != summary['tests'] or state.get('decisions') != summary['decisions']:
        raise ValueError('Factory父归档检验/决策与当前状态不匹配')
    if (summary.get('recommended_candidate_ids') != state.get('recommended_candidate_ids') or
            summary.get('selection_rule') != prepared.get('selection_rule') or
            summary.get('alpha') != prepared['plan']['alpha']):
        raise ValueError('Factory父归档建议或筛选口径与状态不匹配')
    expected = prepared.get('planned_tests', [])
    if summary.get('planned_tests') != len(expected) or summary.get('planned_candidates') != len(prepared.get('candidates', [])):
        raise ValueError('Factory父归档固定测试族计数不匹配')
    return record, hashlib.sha256(before).hexdigest()


def _scope(prepared):
    candidate = (prepared.get('candidates') or [{}])[0]
    spec = candidate.get('factor_spec') or {}
    symbols = spec.get('symbols') or []
    return {
        'symbols': {'count': len(symbols) if isinstance(symbols, list) else None,
                    'sample': symbols[:20] if isinstance(symbols, list) else [],
                    'truncated': isinstance(symbols, list) and len(symbols) > 20},
        'start': spec.get('start'), 'end': spec.get('end'), 'timeframe': spec.get('timeframe'),
        'adjustment': spec.get('adjustment'), 'train_end': prepared.get('plan', {}).get('train_end'),
        'evaluation_start': prepared.get('plan', {}).get('evaluation_start'),
        'horizon': prepared.get('plan', {}).get('horizon'),
        'qualification': spec.get('qualification', 'not_declared'),
        'execution_cost_requested': bool(prepared.get('plan', {}).get('require_net_return')),
    }


def build_factory_report(output, proposal_id, *, offset=0, limit=6, expected_digest=None) -> dict:
    proposal_id = canonical_id(proposal_id)
    if type(offset) is not int or offset < 0 or offset > 100000:
        raise ValueError('offset须为0–100000整数')
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('limit须为1–12')
    if expected_digest not in (None, '') and (not isinstance(expected_digest, str) or not re.fullmatch('[a-f0-9]{64}', expected_digest)):
        raise ValueError('expected_digest无效')
    output = _no_symlink(Path(output))
    store = AlphaFactoryStore(output)
    _no_symlink(store.root, must_exist=False)
    state, state_sha = _state_bytes(store, proposal_id)
    prepared = state.get('prepared')
    if not isinstance(prepared, dict) or state.get('prepared_digest') != digest(prepared):
        raise ValueError('Factory prepared_digest与prepared内容不匹配')
    candidates = prepared.get('candidates')
    planned = prepared.get('planned_tests')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES or not isinstance(planned, list):
        raise ValueError('Factory冻结候选/检验计划无效')
    if len(planned) > MAX_CANDIDATES * 2:
        raise ValueError('Factory冻结检验槽位超界')
    if not all(isinstance(row, dict) for row in candidates + planned):
        raise ValueError('Factory候选和检验槽位须为对象')
    if prepared.get('planned_test_count') != len(planned):
        raise ValueError('Factory冻结检验计数不匹配')
    candidate_ids = plan_candidate_ids(prepared.get('plan', {}))
    if candidate_ids != [item.get('candidate_id') for item in candidates]:
        raise ValueError('Factory冻结候选顺序与计划不匹配')
    expected_slots = [(cid, test_id) for cid in candidate_ids for test_id in
                      (['residual_ic', 'net_return_increment'] if prepared.get('plan', {}).get('require_net_return') else ['residual_ic'])]
    if [(row.get('candidate_id'), row.get('id')) for row in planned] != expected_slots:
        raise ValueError('Factory冻结检验槽位与计划不匹配')
    status = state.get('status')
    parent = None
    parent_sha = None
    if status == 'completed':
        run_id = state.get('result_run_id')
        if not isinstance(run_id, str):
            raise ValueError('完成状态缺少result_run_id')
        run_id = canonical_id(run_id)
        parent, parent_sha = _parent_record(output, run_id, state, prepared)
    else:
        if status not in ('pending', 'admitting', 'submitted', 'running', 'failed', 'cancelled'):
            raise ValueError('未知Factory保存状态')
        if state.get('result_run_id'):
            raise ValueError('非完成状态不得携带Factory结果归档')

    result = parent.get('summary', {}) if parent else {}
    actual_tests = result.get('tests', []) if parent else state.get('tests', [])
    actual_decisions = result.get('decisions', []) if parent else state.get('decisions', [])
    if not isinstance(actual_tests, list) or not isinstance(actual_decisions, list):
        raise ValueError('Factory保存的检验与决策必须为数组')
    if len(actual_tests) > len(planned) or len(actual_decisions) > len(candidates):
        raise ValueError('Factory结果数量超过冻结范围，拒绝截取有利结果')
    # Preserve every frozen slot, and expose duplicate/unplanned/absent rows rather than selecting one.
    slot_map = {}
    unexpected = []
    for row in actual_tests:
        if not isinstance(row, dict):
            raise ValueError('Factory检验结果必须为对象')
        key = (row.get('candidate_id'), row.get('id'))
        if key not in expected_slots or key in slot_map:
            raise ValueError('Factory检验出现重复或非计划槽位')
        for name in ('estimate', 'p_value', 'p_holm'):
            value = row.get(name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('Factory检验数值无效：' + name)
            if name != 'estimate' and value is not None and not 0 <= value <= 1:
                raise ValueError('Factory检验概率超界')
        if row.get('reject') is not None and type(row['reject']) is not bool:
            raise ValueError('Factory检验reject须为布尔值或未知')
        slot_map[key] = [row]
    slots = []
    for frozen in planned:
        key = (frozen.get('candidate_id'), frozen.get('id'))
        rows = slot_map.pop(key, [])
        for candidate in candidates:
            if candidate.get('candidate_id') != key[0]:
                continue
            if len(rows) != 1:
                slots.append({'candidate_id': key[0], 'id': key[1], 'kind': frozen.get('kind'),
                              'status': 'unknown', 'error': 'missing_or_duplicate_result_slot',
                              'slot_anomaly': 'missing' if not rows else 'duplicate'})
            else:
                row = rows[0]
                slots.append({k: _finite(_bounded(row.get(k), 500) if k == 'error' else row.get(k))
                              for k in ('candidate_id','id','kind','status','estimate','p_value','p_holm','reject','error','run_id','test_status')})
            break
    for rows in slot_map.values():
        unexpected.extend(rows)
    errors = [e for e in unexpected]
    decisions_by_id = {}
    duplicate_decisions = set()
    for row in actual_decisions:
        if not isinstance(row, dict):raise ValueError('Factory决策必须为对象')
        cid = row.get('candidate_id')
        if cid not in candidate_ids or cid in decisions_by_id:
            raise ValueError('Factory决策出现重复或非计划候选')
        if type(row.get('recommended_for_watchlist')) is not bool or not isinstance(row.get('checks'), dict):
            raise ValueError('Factory决策建议或检查项无效')
        if any(type(value) is not bool for value in row['checks'].values()):
            raise ValueError('Factory决策检查项不是布尔值')
        decisions_by_id[cid] = row
    summaries = []
    for candidate in candidates:
        cid = candidate.get('candidate_id')
        decision = decisions_by_id.get(cid)
        candidate_slots = [s for s in slots if s['candidate_id'] == cid]
        if decision is None or any(row.get('slot_anomaly') for row in candidate_slots):
            decision_view = {'status': 'unknown', 'error': 'missing_or_duplicate_decision', 'checks': {}}
        else:
            decision_view = {'status': 'saved', 'recommended_for_watchlist': decision.get('recommended_for_watchlist'),
                             'checks': _finite(decision.get('checks') or {}),
                             'common_finite_ratio': _finite(decision.get('common_finite_ratio')),
                             'mean_absolute_signal_correlation': _finite(decision.get('mean_absolute_signal_correlation')),
                             'paired_rank_ic_difference': _finite(decision.get('paired_rank_ic_difference'))}
        ref = candidate.get('candidate_ref') or {}
        summaries.append({'id': _bounded(cid, 100), 'name': _bounded(candidate.get('name', ''), 200),
                          'factor_id': _bounded(candidate.get('factor_id') or ref.get('factor_id') or 'DSL.RESTRICTED', 200),
                          'version': _bounded(candidate.get('version') or ref.get('version') or '1.0.0', 100),
                          'parameters': _safe_parameters(candidate.get('parameters', {})),
                          'factor_run_id': _bounded((result.get('runs', {}).get(cid) or {}).get('factor_run_id'), 100),
                          'execution_run_id': _bounded((result.get('runs', {}).get(cid) or {}).get('execution_run_id'), 100),
                          'tests': candidate_slots, 'decision': decision_view,
                          'suggestion': ('观察建议（不是Alpha/交易许可）' if decision_view.get('recommended_for_watchlist') is True else '不建议/未知；按保存决策与槽位核对')})
    if len(errors) > 40:
        errors = errors[:40] + [{'truncated': True, 'omitted_count': len(errors)-40}]
    counts = {'planned_candidates': len(candidates), 'planned_tests': len(planned),
              'obtained_tests': sum(s.get('status') == 'completed' for s in slots),
              'failed_tests': sum(s.get('status') == 'failed' for s in slots),
              'unknown_tests': sum(s.get('status') == 'unknown' for s in slots),
              'anomalies': len(errors) + len(duplicate_decisions)}
    counts['anomalies'] += sum(bool(s.get('slot_anomaly')) for s in slots)
    counts['obtained_p_values'] = sum(s.get('p_value') is not None for s in slots)
    counts['missing_decisions'] = len(candidates) - len(decisions_by_id)
    cost_slots = [s for s in slots if s['id'] == 'net_return_increment']
    cost_evidence = {'requested':bool(prepared['plan'].get('require_net_return')),
                     'planned_tests':len(cost_slots),
                     'completed_tests':sum(s.get('status') == 'completed' for s in cost_slots),
                     'tests_with_p_value':sum(s.get('p_value') is not None for s in cost_slots),
                     'failed_tests':sum(s.get('status') == 'failed' for s in cost_slots),
                     'note':'是否配置成本检验与实际获得结果分别报告；未取得结果不算已验证交易收益。'}
    total = len(summaries)
    next_offset = offset + limit if offset + limit < total else None
    verification = {'level': 'saved_parent_identity_checked' if parent else 'saved_state_only',
                    'state_sha256': state_sha, 'parent_experiment_sha256': parent_sha,
                    'deep_verified': False, 'parquet_revalidated': False,
                    'note': '未完整复算，也未重验底层Parquet；不证明源数据当前正确。'}
    base = {'format': 'alpha-factory-report-v1', 'proposal_id': proposal_id, 'status': status,
            'name': _bounded(prepared.get('plan', {}).get('name', ''), 200),
            'prepared_digest': state['prepared_digest'], 'result_run_id': state.get('result_run_id'),
            'baseline_run_id': prepared['plan']['baseline_run_id'],
            'control_run_ids': list(prepared['plan']['control_run_ids']),
            'baseline_execution_run_id': prepared['plan'].get('baseline_execution_run_id'),
            'scope': _scope(prepared), 'screening_rules': _finite(prepared.get('selection_rule', {})),
            'counts': counts, 'cost_evidence': cost_evidence,
            'count_definitions': {'planned_candidates': '冻结候选全集数量',
                                  'planned_tests': '冻结检验槽位全集数量，失败/未知仍占位',
                                  'obtained_tests': '存在唯一结果记录且status=completed的槽位；不代表p值存在',
                                  'failed_tests': '结果槽位status=failed数量',
                                  'unknown_tests': '缺失/重复结果或未获得结果的冻结槽位数量',
                                  'anomalies': '缺失结果槽位数；重复或非计划结果拒绝读取',
                                  'obtained_p_values': '已记录有效p值的槽位数，不代表通过检验',
                                  'missing_decisions': '尚未保存候选决策的数量'},
            'candidates': summaries[offset:offset+limit],
            'offset': offset, 'next_offset': next_offset, 'has_more': next_offset is not None,
            'total_candidates': total, 'limitations': list(prepared.get('limitations', [])) +
                (list(result.get('limitations', [])) if parent else ['仅反映最后保存状态；pending/running不自动同步。']),
            'verification': verification,
            'sources': [{'kind': 'alpha_factory', 'proposal_id': proposal_id, 'sha256': state_sha},
                        *([{'kind': 'experiment', 'run_id': state['result_run_id'], 'sha256': parent_sha}] if parent else [])],
            'slot_anomalies': errors}
    # report digest is independent of pagination and wall-clock; raw source byte hashes bind the view.
    identity = {'format': base['format'], 'proposal_id': proposal_id, 'status': status,
                'prepared_digest': state['prepared_digest'], 'state_sha256': state_sha,
                'result_run_id': state.get('result_run_id'), 'parent_sha256': parent_sha}
    base['report_digest'] = digest(identity)
    encoded = json.dumps(base, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_JSON:
        raise ValueError('Factory报告超过输出硬上限；拒绝静默裁剪证据')
    if expected_digest and expected_digest != base['report_digest']:
        raise ValueError('Factory报告指纹已变化，请重新读取完整报告')
    # Refuse a state/parent pair that changed while this report was assembled.
    _, current_state_sha = _state_bytes(store, proposal_id)
    if current_state_sha != state_sha:
        raise ValueError('Factory报告读取期间状态变化，请重新读取')
    if parent:
        _, current_parent_sha = _parent_record(output, state['result_run_id'], state, prepared)
        if current_parent_sha != parent_sha:
            raise ValueError('Factory报告读取期间父归档变化，请重新读取')
    return base


def render_factory_report_markdown(report) -> str:
    """Render the same bounded report, including pagination and unavailable results."""
    def cell(value):
        if value is None:text = '未知 / 未取得'
        elif type(value) is bool:text = '是' if value else '否'
        elif isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        else:text = str(value)
        text = html.escape(text.replace('\r', ' ').replace('\n', ' '), quote=True)
        # Prevent external content from creating links/images, HTML or new table cells.
        for character in ('|', '`', '[', ']', '*', '!', '\\'):
            text = text.replace(character, '&#'+str(ord(character))+';')
        return text
    scope = report.get('scope', {});counts = report.get('counts', {});cost = report.get('cost_evidence', {})
    symbols = scope.get('symbols') or {};rules = report.get('screening_rules') or {}
    lines = ['# Alpha Factory 只读研究报告', '',
             '本报告来自保存的研究证据，不是AI结论，也不是Alpha或交易许可。', '',
             '## 研究身份与范围',
             '- 名称：'+cell(report.get('name')),
             '- Factory提案：'+cell(report.get('proposal_id')),
             '- 基准实验：'+cell(report.get('baseline_run_id'))+'；控制因子实验：'+cell(report.get('control_run_ids')),
             '- 成本后执行基准：'+cell(report.get('baseline_execution_run_id'))+'；数据资格声明：'+cell(scope.get('qualification')),
             '- 保存状态：'+cell(report.get('status'))+'；结果父 run ID：'+cell(report.get('result_run_id')),
             '- 报告指纹：'+cell(report.get('report_digest')),
             '- 日期：'+cell(scope.get('start'))+' 至 '+cell(scope.get('end'))+'；周期：'+cell(scope.get('timeframe'))+'；价格口径：'+cell(scope.get('adjustment')),
             '- 证券数：'+cell(symbols.get('count'))+'；列出的样例：'+cell(symbols.get('sample'))+'；样例已截断：'+cell(symbols.get('truncated')),
             '- 训练截止：'+cell(scope.get('train_end'))+'；评价起点：'+cell(scope.get('evaluation_start'))+'；持有期（根）：'+cell(scope.get('horizon')),
             '- 本页候选：'+str(len(report.get('candidates', [])))+' / '+cell(report.get('total_candidates'))+'；起始位置：'+cell(report.get('offset'))+'；仍有下一页：'+cell(report.get('has_more')),
             '', '## 固定筛选口径与完成情况',
             '- 冻结候选：'+cell(counts.get('planned_candidates'))+'；检验槽位：'+cell(counts.get('planned_tests'))+'；完成槽位：'+cell(counts.get('obtained_tests'))+'；有p值：'+cell(counts.get('obtained_p_values'))+'；失败：'+cell(counts.get('failed_tests'))+'；未知：'+cell(counts.get('unknown_tests')),
             '- 最低共同样本比例：'+cell(rules.get('min_common_finite_ratio'))+'；最大绝对信号相关：'+cell(rules.get('max_abs_signal_corr')),
             '- 配对IC差值须为正：'+cell(rules.get('require_positive_paired_ic_difference'))+'；残差Holm p上限：'+cell(rules.get('residual_holm_p_at_most'))+'；残差估计须为正：'+cell(rules.get('residual_estimate_must_be_positive')),
             '- 是否要求成本后增量：'+cell(cost.get('requested'))+'；预定成本槽位：'+cell(cost.get('planned_tests'))+'；实际完成：'+cell(cost.get('completed_tests'))+'；有p值：'+cell(cost.get('tests_with_p_value'))+'；失败：'+cell(cost.get('failed_tests')),
             '- 配置过成本检验不等于取得可执行收益证据；完成状态也不等于通过统计检验。']
    test_names = {'residual_ic':'样本外残差IC', 'net_return_increment':'成本后净收益增量'}
    check_names = {'common_finite_ratio':'共同样本比例', 'signal_correlation':'信号相关',
                   'paired_ic_direction':'配对IC方向', 'residual_increment':'残差信息增量', 'net_return_increment':'净收益增量'}
    for row in report.get('candidates', []):
        lines += ['', '## 候选：'+cell(row.get('name')), '- 候选ID：'+cell(row.get('id')),
                  '- 因子 / 版本：'+cell(row.get('factor_id'))+' @ '+cell(row.get('version')),
                  '- 参数：'+cell(row.get('parameters')),
                  '- 因子实验：'+cell(row.get('factor_run_id'))+'；执行实验：'+cell(row.get('execution_run_id')),
                  '', '| 固定检验 | 保存状态 | 估计值 | 原始 p | Holm p | 错误 / 未获得原因 |', '|---|---|---|---|---|---|']
        for test in row.get('tests', []):
            lines.append('| '+' | '.join(cell(value) for value in (test_names.get(test.get('id'),test.get('id')),
                test.get('status'),test.get('estimate'),test.get('p_value'),test.get('p_holm'),test.get('error'))) + ' |')
        decision = row.get('decision') or {}
        checks = ['%s：%s' % (cell(check_names.get(key,key)), cell(value)) for key,value in (decision.get('checks') or {}).items()]
        lines += ['', '- 保存的检查项：'+'；'.join(checks), '- 保存的建议：'+cell(row.get('suggestion'))]
        if decision.get('error'):lines.append('- 建议未确认原因：'+cell(decision['error']))
        for test in row.get('tests', []):
            lines.append('- '+cell(test_names.get(test.get('id'),test.get('id')))+'证据 run ID：'+cell(test.get('run_id')))
    lines += ['', '## 限制与核验']
    for item in report.get('limitations', []):lines.append('- '+cell(item))
    lines += ['- 核验说明：'+cell(report.get('verification')),
              '- 所有失败与缺失槽位继续占用固定检验族；不重新计算显著性、不替换候选。',
              '- 本报告是确定性结构化证据投影，不是AI结论；观察建议不构成Alpha或交易许可。']
    if report.get('has_more') or report.get('offset'):
        lines.append('- 这是分页片段，不是完整候选报告；继续读取必须绑定同一个报告指纹。')
    return '\n'.join(lines)+'\n'
