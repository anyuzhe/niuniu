"""Inventory genuine local metadata, retaining provenance and availability gaps."""
from pathlib import Path
import hashlib
import pyarrow.parquet as pq


def historical_coverage(root):
    base=Path(root)/'lake/bronze/provider=baostock';items=[]
    for kind in ('stock_basic','trade_calendar','industry','corporate_actions_dividend'):
        for path in sorted((base/kind).glob('*.parquet')):
            pf=pq.ParquetFile(path)
            items.append({'kind':kind,'path':str(path),'rows':pf.metadata.num_rows,'fields':pf.schema_arrow.names,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'sources':items,'missing_required_sources':['historical ST events with available_at','historical suspension/resumption events with available_at',
        'official per-session upper/lower price bounds','historical industry changes with available_at','continuous fresh bar producer'],
        'available_but_not_execution_ready':{'industry':'Single update-date snapshot; no historical membership or first-available timestamps.',
        'corporate_actions_dividend':'Raw source records inventoried; announcement/record/ex dates must be normalized and entitlements modeled before raw-price execution adjustments.'},
        'status':'incomplete_real_market_coverage'}
