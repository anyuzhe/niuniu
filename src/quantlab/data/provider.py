"""Select a verified managed dataset explicitly, or retain the MQC adapter."""
from pathlib import Path
from quantlab.data.mqc import MQCParquetProvider


def local_data_provider(root, adjustment='raw'):
    supplied = Path(root)
    root = supplied.resolve()
    archived = root/'archived-daily-dataset.json'
    if archived.is_symlink() or archived.exists():
        # An explicit host-created dataset is never guessed from raw archive folders.
        for name in ('manifest.json', 'baostock-series.json', 'baostock-dataset.json'):
            marker = root/name
            if marker.is_symlink() or marker.exists():
                raise ValueError('Conflicting managed dataset markers; select one explicit input root')
        from quantlab.data.archived_daily_dataset import ArchivedDailyDatasetProvider
        return ArchivedDailyDatasetProvider(supplied, adjustment)
    from quantlab.storage.approval_inputs import is_approval_freeze_root,ApprovalFrozenDataProvider
    if is_approval_freeze_root(root):
        return ApprovalFrozenDataProvider(root,adjustment)
    series = root/'baostock-series.json'
    if series.is_symlink() or series.exists():
        from quantlab.data.baostock_series import BaostockSeriesProvider
        return BaostockSeriesProvider(root, adjustment)
    marker = root/'baostock-dataset.json'
    if marker.is_symlink() or marker.exists():
        from quantlab.data.baostock_provider import BaostockSnapshotProvider
        # A malformed marker is an error, never permission to silently fall back.
        return BaostockSnapshotProvider(root, adjustment)
    # Raw daily resolves the opt-in pointer lazily, and only if a request extends
    # beyond an MQC full-file cutoff.  Thus qfq/minute and in-trunk identities remain
    # independent of an unused retrospective source.
    retro_tail = None
    if adjustment == 'raw':
        from quantlab.data.retro_tail import RetroTail
        retro_tail = RetroTail(supplied)
    return MQCParquetProvider(root, adjustment, retro_tail=retro_tail)
