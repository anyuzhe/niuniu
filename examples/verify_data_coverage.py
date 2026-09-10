"""Read-only sample audit of MQC and previously published bar archives."""
import argparse
from datetime import date
from pathlib import Path
from quantlab.data.audit import audit_market
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.storage.codec import encode

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--calendar-file',type=Path,required=True)
    parser.add_argument('--symbols',nargs='+',required=True)
    parser.add_argument('--start',type=date.fromisoformat,required=True)
    parser.add_argument('--end',type=date.fromisoformat,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    summary=[]
    for tf in (Timeframe.DAILY,Timeframe.MIN5):
        result=audit_market(args.data_root,DataRequest(tuple(args.symbols),tf,args.start,args.end),calendar_file=args.calendar_file)
        (args.output/f'{tf.value}.json').write_text(encode(result))
        summary.append({'timeframe':tf.value,'symbols':len(args.symbols),'rows':sum(r['rows'] for r in result['results']),
            'expected_symbol_sessions':result['expected_symbol_sessions'],'complete_symbol_sessions':result['complete_symbol_sessions'],
            'missing_symbol_sessions':sum(s['status']=='missing' for r in result['results'] for s in r['session_coverage']),
            'incomplete_symbol_sessions':sum(s['status']=='incomplete' for r in result['results'] for s in r['session_coverage']),
            'calendar_missing_dates':result['calendar_missing_dates'],'status':result['status']})
        print(encode(summary[-1]),flush=True)
    (args.output/'summary.json').write_text(encode(summary))
