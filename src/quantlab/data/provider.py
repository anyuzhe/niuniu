"""Select a verified managed dataset explicitly, or retain the MQC adapter."""
from pathlib import Path
from quantlab.data.mqc import MQCParquetProvider


def local_data_provider(root, adjustment='raw'):
    root = Path(root).resolve()
    series = root/'baostock-series.json'
    if series.is_symlink() or series.exists():
        from quantlab.data.baostock_series import BaostockSeriesProvider
        return BaostockSeriesProvider(root, adjustment)
    marker = root/'baostock-dataset.json'
    if marker.is_symlink() or marker.exists():
        from quantlab.data.baostock_provider import BaostockSnapshotProvider
        # A malformed marker is an error, never permission to silently fall back.
        return BaostockSnapshotProvider(root, adjustment)
    return MQCParquetProvider(root, adjustment)
