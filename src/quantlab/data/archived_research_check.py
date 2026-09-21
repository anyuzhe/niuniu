"""Read-only input compatibility checks for finite F9 packages; never run a study.

This is an explicit diagnostic, not a new approval gate, qualification certificate,
input freeze, or promise of enough warmup/statistical observations. Existing proposal
and approval contracts remain authoritative.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from quantlab.agent.planning import ProposalError, parse_spec, preview_experiment
from quantlab.data.archived_daily_dataset import (
    MARKER, ArchivedDailyDatasetProvider, inspect_archived_daily_dataset,
)
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest, encode

FORMAT = 'niuniu-archived-research-input-check-v1'
LIMITATIONS = [
    '这是当前有限归档输入与明确研究配置的只读核对，不保存提案、不冻结输入、不批准或执行。',
    '不改变证券、日期、因子、资金、复权或资格。缺口不补值、不自动换来源。',
    '只核对行情输入；未计算因子、预热有效样本、统计功效、收益或 Alpha。',
    '按原审批的主输入和背景大区间核对；未逐一证明留出/滚动子窗口拥有足够的交易日或有效观测。',
    '供应商观察与15:00研究对齐时钟不是历史当时可得证明，不能升级Strict PIT。',
    '检查结果不是文件租约；实际批准和读取时仍由原流程重新核验、冻结字节。',
]


def check_archived_daily_research(data_root, spec: dict) -> dict:
    """Check a bounded, caller-specified research spec against one host-selected package.

    Malformed configurations/packages raise. Valid-but-incompatible requests return
    every applicable blocker without silently changing the requested configuration.
    Non-package roots are unsupported, not an instruction to search other sources.
    """
    spec = parse_spec(encode(spec))
    if spec.get('mode') == 'campaign':
        raise ProposalError('UNSUPPORTED_SCOPE', '本工具一次核对一份研究配置；Campaign请逐节点核对，不能据此认证整包。')
    preview = preview_experiment(spec)
    from quantlab.workbench.jobs import prepare
    submission = prepare(preview['spec'])
    if data_root is None:
        raise ProposalError('INPUT_NOT_CONFIGURED', '宿主尚未指定归档日线输入包。')
    marker = Path(data_root) / MARKER
    if not marker.exists() and not marker.is_symlink():
        raise ProposalError('UNSUPPORTED_INPUT_ROOT', '当前根不是F9归档日线输入包；本检查不扫描MQC、TDX或其他来源。')
    package = inspect_archived_daily_dataset(data_root)
    available = {
        'dataset_id': package['dataset_id'], 'capture_id': package['capture_id'],
        'symbols': package['symbols'], 'start': package['start'], 'end': package['end'],
        'timeframe': '1d', 'adjustment': 'raw', 'qualification': 'research_only',
        'rows': package['rows'], 'actual_sessions': package['actual_sessions'],
        'historical_available_at_verified': False,
    }
    blockers = []

    def block(code, role, message, **detail):
        blockers.append({'code': code, 'role': role, 'message': message, **detail})

    if submission.qualification != 'research_only':
        block('QUALIFICATION_NOT_SUPPORTED', 'qualification',
              '本包仅供research_only；严格资格或其他声明不会被自动降低。',
              requested=submission.qualification, available='research_only')
    if submission.universe.mode != 'explicit':
        block('UNIVERSE_NOT_IN_PACKAGE', 'universe',
              '该包没有通用历史Universe输入；供应商基础信息不等于PIT或上市资格源。',
              requested=submission.universe.mode, available='explicit')
    if submission.execution is not None:
        if submission.execution.price_mode != 'research':
            block('ACCOUNT_DEPENDENCIES_NOT_CHECKED', 'execution',
                  '精细账户公司行动及交易规则不在本工具核验范围；不能把行情兼容当账户输入齐备。')
        if submission.execution_backend != 'open' or submission.market_rules is not None:
            block('EXECUTION_DEPENDENCIES_NOT_CHECKED', 'execution',
                  '可选执行后端或逐时点规则需要独立验收；本工具不加载其外部依赖。')

    config = submission.config
    requests = [('signal', config.data, submission.adjustment)]
    if config.context is not None:
        requests.append(('context', config.context.request(config.data), submission.adjustment))
    if submission.execution and submission.execution.price_mode == 'account' and submission.adjustment != 'raw':
        requests.append(('execution', config.data, 'raw'))
    requirements = []
    lo, hi = date.fromisoformat(package['start']), date.fromisoformat(package['end'])
    provider = ArchivedDailyDatasetProvider(data_root, 'raw')
    for role, request, adjustment in requests:
        request_json = {'symbols': list(request.symbols), 'timeframe': request.timeframe.value,
                        'start': request.start.isoformat(), 'end': request.end.isoformat()}
        row = {'role': role, 'adjustment': adjustment, 'request': request_json,
               'status': 'not_loaded', 'rows': None, 'snapshot_id': None}
        first_blocker = len(blockers)
        if adjustment != 'raw':
            block('ADJUSTMENT_MISMATCH', role, '请求前复权qfq，但当前包只有raw；不会自动修改配置或换源。',
                  requested=adjustment, available='raw')
        if request.timeframe != Timeframe.DAILY:
            block('TIMEFRAME_MISMATCH', role, '当前包只有日线，不能代替分钟线或反推分钟数据。',
                  requested=request.timeframe.value, available='1d')
        missing = sorted(set(request.symbols) - set(package['symbols']))
        if missing:
            block('SYMBOLS_OUTSIDE_PACKAGE', role, '请求包含包范围之外的证券；不会删除或替换样本。',
                  missing_symbols=missing)
        if request.start < lo or request.end > hi:
            block('DATES_OUTSIDE_PACKAGE', role, '请求范围超过输入包，包含背景或预热日期时也必须完整覆盖。',
                  requested={'start': request.start.isoformat(), 'end': request.end.isoformat()},
                  available={'start': package['start'], 'end': package['end']})
        if len(blockers) != first_blocker:
            row['status'] = 'incompatible'
        else:
            try:
                batch = provider.load(request)
            except ValueError as error:
                if str(error) != 'No archived calendar trading sessions in requested subrange':
                    raise
                block('NO_TRADING_SESSIONS', role, '所选子范围没有归档交易日；不制造空研究或填充行情。')
                row['status'] = 'incompatible'
            else:
                identities = {entry.get('dataset_id') for entry in batch.snapshot.files}
                if identities != {package['dataset_id']}:
                    raise ValueError('Archived dataset identity changed while checking research inputs')
                row.update(status='verified', rows=batch.bars.height,
                           snapshot_id=batch.snapshot.snapshot_id,
                           first_session=batch.bars['datetime'].min().date().isoformat(),
                           last_session=batch.bars['datetime'].max().date().isoformat())
        requirements.append(row)
    report = {
        'format': FORMAT, 'status': 'blocked' if blockers else 'compatible',
        'compatible': not blockers, 'dataset_id': package['dataset_id'],
        'spec_digest': digest(spec), 'resolved_spec_digest': digest(preview['resolved']),
        'input': available, 'requirements': requirements, 'blockers': blockers,
        'package_bytes_verified': True, 'factor_computed': False,
        'statistical_sufficiency_checked': False, 'research_approved': False,
        'research_executed': False, 'limitations': list(LIMITATIONS),
    }
    report['check_hash'] = digest(report)
    return report
