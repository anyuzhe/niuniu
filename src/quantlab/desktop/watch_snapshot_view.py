"""Pure display projections for immutable Watch snapshots; never computes metrics."""
from copy import deepcopy


def snapshot_projection(snapshot):
    """Return saved preview/monitor fields without filling nulls or deriving values."""
    if not isinstance(snapshot, dict):
        raise ValueError('快照不是对象')
    preview = snapshot.get('preview')
    if not isinstance(preview, dict):
        raise ValueError('快照缺少原始 preview')
    return {
        'snapshot_id': snapshot.get('snapshot_id'),
        'watch_id': snapshot.get('watch_id'),
        'created_at': snapshot.get('created_at'),
        'source_run_id': snapshot.get('source_run_id'),
        'as_of': preview.get('as_of'),
        'change': deepcopy(snapshot.get('change')),
        'preview': {
            'windows': deepcopy(preview.get('windows')),
            'watermarks': deepcopy(preview.get('watermarks')),
        },
        'baseline_differences': deepcopy(snapshot.get('baseline_differences')),
        'sequential_monitor': deepcopy(snapshot.get('sequential_monitor')),
        'alerts': deepcopy(snapshot.get('alerts')),
        'limitations': deepcopy(snapshot.get('limitations')),
    }


def snapshot_source_label(result):
    """Describe integrity of this exact selected snapshot only."""
    integrity = result.get('source_integrity')
    if integrity == 'verified':
        return '此快照来源已核对一致；不表示数据资格或结论认证。'
    if integrity == 'source_changed':
        return '此快照来源已变化：不是当前有效证据。'
    if integrity == 'unavailable':
        return '此快照来源不可读取：不是当前有效证据。'
    return '此快照来源状态未知：不是当前有效证据。'


STATUS_LABELS = {
    'computed':'达到有效日期门槛（描述性）','insufficient_mature_dates':'成熟有效日期不足',
    'LEGACY_NOT_CONFIGURED':'旧观察池未配置序贯监测',
    'HISTORICAL_REVISION_BLOCKED':'历史输入修订，序贯解释已阻断',
    'INSUFFICIENT':'样本不足','INSUFFICIENT_BASELINE':'基线有效日期不足',
    'INSUFFICIENT_NEW_DATES':'新增成熟日期或完整块不足',
    'NO_DECISIVE_CHANGE':'尚无决定性变化证据',
    'DEGRADATION_EVIDENCE':'出现相对经验基线的衰减证据，需人工复核',
}


def sequential_status_label(status):
    return STATUS_LABELS.get(status,str(status) if status is not None else '未知')


def _pair(left,right):
    return str(left if left is not None else '未知')+' / '+str(right if right is not None else '未知')


def maturity_rows(snapshot):
    rows=[]
    for window,item in snapshot['preview'].get('windows',{}).items():
        for horizon,entry in item.get('horizons',{}).items():
            metrics=entry.get('metrics') or {}
            difference=((snapshot.get('baseline_differences') or {}).get(window) or {}).get(horizon) or {}
            rows.append([_pair(window,horizon),entry.get('mature_observations'),entry.get('pending_observations'),
                entry.get('valid_ic_sessions'),sequential_status_label(entry.get('status')),
                metrics.get('rank_ic'),difference.get('rank_ic_difference')])
    return rows


def sequential_rows(snapshot):
    seq=snapshot.get('sequential_monitor') or {}
    return [[horizon,sequential_status_label(item.get('status')),item.get('new_mature_sessions'),
        _pair(item.get('complete_blocks'),item.get('pending_block_sessions')),
        _pair(item.get('current_e_value'),item.get('max_e_value')),item.get('evidence_threshold')]
        for horizon,item in seq.get('horizons',{}).items()]

