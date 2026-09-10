"""Reconcile the archived E2E targets with native vn.py, without mixing Qt bindings."""
import argparse,json
from pathlib import Path
import polars as pl
from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester
from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
from quantlab.adapters.vnpy import compare_backends
from quantlab.storage.codec import encode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    record=json.loads((a.run/'experiment.json').read_text());config=ExecutionConfig(**record['manifest']['execution'])
    targets=pl.read_parquet(a.run/'targets.parquet');bars=pl.read_parquet(a.run/'bars.parquet')
    reference=OpenExecutionBacktester(config).run(targets,bars)
    assert reference[0].equals(pl.read_parquet(a.run/'observations.parquet'))
    assert encode(reference[1])==encode(record['fills'])
    adapter=VnpyRulesBacktester(config,None);candidate=adapter.run(targets,bars)
    comparison=compare_backends(reference,candidate)
    result={'comparison':comparison,'diagnostics':adapter.diagnostics,
        'scope':'Same frozen raw bars, targets and configured rules. Native vn.py matching/cash/positions; shared platform rule preparation. No live orders.'}
    a.output.write_text(encode(result));print(encode(result))
    assert comparison['status']=='matched',comparison
    assert not comparison['fill_mismatches']
    assert adapter.diagnostics['cash_error']==0
    assert len(adapter.diagnostics['native_trades'])==len(record['fills'])
