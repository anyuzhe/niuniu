"""Recovery/accounting exercise with real bars and explicitly synthetic trading rules."""
import json
from datetime import date
from pathlib import Path
import polars as pl
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.storage.codec import encode

if __name__=='__main__':
    out=Path('artifacts/phase4-acceptance')
    result=json.loads((out/'cash-execution-result.json').read_text());source=Path(result['artifact_path'])
    bars=pl.read_parquet(source/'bars.parquet');targets=pl.read_parquet(source/'targets.parquet')
    cfg=ExecutionConfig(**json.loads((out/'cash-execution.json').read_text()))
    rules=MarketRules([{'symbol':'sh.600000','effective_at':'2025-01-01T00:00:00+08:00',
        'available_at':'2025-01-01T00:00:00+08:00','expires_at':'2026-09-05T00:00:00+08:00',
        'suspended':False,'st':False,'limit_up':None,'limit_down':None,
        'commission_bps':cfg.commission_bps,'minimum_commission':cfg.minimum_commission,
        'sell_tax_bps':cfg.sell_tax_bps,'transfer_bps':cfg.transfer_bps,
        'source':'SYNTHETIC_ACCOUNTING_ONLY: assumed tradable/unbounded, not official historical rules'}])
    account=PaperAccount('artifacts/paper/phase4-dividend-accounting.json')
    if account.path.exists():raise FileExistsError(account.path)
    first=account.advance(bars.filter(pl.col('datetime').dt.date()<=date(2025,7,16)),
        targets.filter(pl.col('datetime').dt.date()<=date(2025,7,16)),rules,cfg,'vnpy_rules')
    final=PaperAccount(account.path).advance(bars,targets,rules,cfg,'vnpy_rules')
    repeated=PaperAccount(account.path).advance(bars,targets,rules,cfg,'vnpy_rules')
    if final!=repeated:raise AssertionError('Duplicate delivery changed ledger')
    reconciliation=reconcile_account(account.path)
    if reconciliation['status']!='matched':raise AssertionError(reconciliation)
    (out/'paper-dividend-reconciliation.json').write_text(encode(reconciliation))
    (out/'paper-dividend-validation.json').write_text(encode({'first_revision':first['revision'],'final_revision':final['revision'],
        'duplicate_unchanged':final==repeated,'summary':final['summary'],'account':account.path,
        'scope':'Actual historical bars and retrospective cash records; fixed tax 0; synthetic tradability rules. Not continuous live acceptance.'}))
    print(encode({'status':reconciliation['status'],'days':len(reconciliation['days']),
        'fills':reconciliation['checked_fills'],'actions':reconciliation['checked_corporate_actions']}))
