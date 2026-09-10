"""Read-only prefix verification of four frozen qfq stocks, not another backtest."""
from pathlib import Path
import json,time
from quantlab.data.mqc import MQCParquetProvider
from quantlab.workbench.jobs import prepare
from quantlab.data.base import DataRequest
from quantlab.adapters.chan_classic import analyze_classic

root=Path('artifacts/chan-500-full-ten-year-qfq')
spec=json.loads((root/'client-spec.json').read_text());request=prepare(spec).config.data
symbols=spec['symbols'];results=[]
for symbol in [symbols[i] for i in (0,166,333,499)]:
    started=time.monotonic()
    bars=MQCParquetProvider(root/'data','qfq').load(DataRequest((symbol,),request.timeframe,request.start,request.end)).bars
    matrix,events=analyze_classic(bars)
    for length in (250,1000,2000):
        prefix,prefix_events=analyze_classic(bars.head(length));cutoff=bars['available_at'][length-1]
        assert prefix.equals(matrix.head(length))
        assert prefix_events==[e for e in events if e.available_at<=cutoff]
    result={'symbol':symbol,'bars':bars.height,'adjustment':'qfq','prefix_lengths':[250,1000,2000],
        'seconds':time.monotonic()-started};results.append(result);print(json.dumps(result),flush=True)
(root/'classic-prefix-verification.json').write_text(json.dumps(results,indent=2))
