"""Actual historical-provider overlap -> immutable archive -> fixed research input."""
from datetime import date
from pathlib import Path
from dataclasses import asdict
import json
import argparse
import polars as pl
from quantlab.data.archive import BarArchive,ArchivedBarProvider
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.storage.codec import encode

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('artifacts/roadmap-acceptance'))
    parser.add_argument('--fetched',type=Path,default=Path('artifacts/roadmap-acceptance/fetched-daily'))
    parser.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/MQC-DATA'))
    parser.add_argument('--start',type=date.fromisoformat,default=date(2026,8,3))
    parser.add_argument('--seed-end',type=date.fromisoformat,default=date(2026,9,4))
    parser.add_argument('--calendar-file',type=Path)
    args=parser.parse_args();out=args.output;fetched=args.fetched
    source=json.loads((fetched/'source.json').read_text());tf=Timeframe(source['request']['timeframe'])
    request=DataRequest(tuple(source['request']['symbols']),tf,args.start,args.seed_end)
    batch=MQCParquetProvider(args.data_root).load(request)
    # Keep the original source available separately; no mutation in MQC-DATA.
    archive=BarArchive(out/('daily-archive' if tf==Timeframe.DAILY else 'min5-archive'))
    seed=archive.publish(batch.bars,{'adjustment':'raw','source_snapshot':asdict(batch.snapshot)})
    fresh=pl.read_parquet(fetched/'bars.parquet')
    updated=archive.publish(fresh,source,seed['manifest'])
    repeat=archive.publish(fresh,source,updated['manifest'])
    assert repeat['status']=='unchanged'
    old=ArchivedBarProvider(seed['manifest']).all_bars();new=ArchivedBarProvider(updated['manifest']).all_bars()
    if old['datetime'].max()>=new['datetime'].max():raise ValueError('Provider did not advance historical coverage')
    summary={'seed':seed,'updated':updated,'repeat':repeat,'previous_end':old['datetime'].max(),'new_end':new['datetime'].max(),
        'scope':'Historical raw bars only; not official rules or real-time delivery.'}
    if args.calendar_file:
        from quantlab.data.audit import audit_market
        audit=audit_market(args.data_root,DataRequest(request.symbols,tf,args.start,date.fromisoformat(source['request']['end'])),updated['manifest'],args.calendar_file)
        (out/'data-audit.json').write_text(encode(audit))
        summary['data_quality_status']=audit['status']
        summary['expected_symbol_sessions']=audit['expected_symbol_sessions']
        summary['complete_symbol_sessions']=audit['complete_symbol_sessions']
    (out/'archive-update.json').write_text(encode(summary));print(encode(summary))
