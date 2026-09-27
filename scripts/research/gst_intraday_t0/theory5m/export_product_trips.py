"""Export trips of the page strategies from the engine result files (res2_<key>_None.json, written by the engine runs on
the virtual machine) to mm_product.csv, re-priced to 万1 免五 + current stamp duty (+8 bp before 2023-08-28, +3 bp after).
Research only."""
import json, csv, os, sys
H=os.environ['HOME']; out=sys.argv[1] if len(sys.argv)>1 else 'mm_product.csv'
with open(out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['strategy','date','symbol','entry','exit','bp','direction'])
    for k in ('morning_score','intraday_score','weak_close','close_score','gap_rebound'):
        for t in json.load(open(f'{H}/res2_{k}_None.json'))['trips']:
            adj=3.0 if t['date']>='2023-08-28' else 8.0
            w.writerow([k,t['date'],t['symbol'],t['entry_minute'],t['exit_minute'],t['bps']+adj,t['direction']])
