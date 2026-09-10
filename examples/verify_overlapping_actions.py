"""Real MQC bars + explicit synthetic overlapping actions; no return claim."""
from datetime import date
from pathlib import Path
import json
import polars as pl
from quantlab.data.base import DataRequest
from quantlab.data.mqc import MQCParquetProvider
from quantlab.domain import Timeframe
from quantlab.execution.backtest import ExecutionConfig,OpenExecutionBacktester
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.execution.reconcile import reconcile_account
from quantlab.adapters.vnpy import compare_backends
from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
from quantlab.storage.codec import encode


def main():
    output=Path('artifacts/overlapping-actions-acceptance/real-bars')
    output.mkdir(parents=True,exist_ok=False)
    symbol='sh.600000'
    batch=MQCParquetProvider(Path('/Volumes/Lexar/MQC-DATA'),'raw').load(DataRequest((symbol,),Timeframe.DAILY,date(2026,8,3),date(2026,8,14)))
    bars=batch.bars;dates=bars['datetime'].to_list();assert len(dates)==10
    opening=lambda i:dates[i].replace(hour=9,minute=30)
    source='synthetic overlapping entitlement assumption on real MQC bars; not an actual corporate action'
    first={'action_id':'synthetic-first','symbol':symbol,'record_at':dates[1],
        'ex_at':opening(2),'pay_at':dates[2],'available_at':dates[0],
        'cash_per_share':0.,'tax_rate':0.,'source':source,
        'stock_per_share':.1,'list_at':opening(7),'fractional_policy':'floor'}
    second={**first,'action_id':'synthetic-second','record_at':dates[3],
        'ex_at':opening(4),'pay_at':dates[6],'cash_per_share':.05,
        'list_at':opening(8),'entitled_pending_actions':['synthetic-first']}
    config=ExecutionConfig(initial_cash=100000,corporate_actions=[first,second])
    targets=bars.select('symbol','datetime','available_at').with_columns(pl.Series('weight',[.5,.5]+[0.]*8))
    rules=MarketRules([{'symbol':symbol,'effective_at':dates[0].replace(hour=0),
        'available_at':dates[0].replace(hour=0),'expires_at':dates[-1].replace(hour=23),
        'suspended':False,'st':False,'limit_up':None,'limit_down':None,'commission_bps':3.,
        'minimum_commission':5.,'sell_tax_bps':5.,'transfer_bps':0.,'source':'explicit synthetic integration rule fixture'}])
    bars.write_parquet(output/'bars.parquet');targets.write_parquet(output/'targets.parquet')
    (output/'rules.json').write_text(encode(rules.records));(output/'execution.json').write_text(encode(config))
    reference=OpenExecutionBacktester(config,rules).run(targets,bars)
    native=VnpyRulesBacktester(config,rules).run(targets,bars)
    comparison=compare_backends(reference,native);assert comparison['status']=='matched'
    account=PaperAccount(output/'paper.json')
    partial=account.advance(bars.head(6),targets.head(6),rules,config,'vnpy_rules')
    partial_check=reconcile_account(output/'paper.json');assert partial_check['status']=='matched'
    final=account.advance(bars,targets,rules,config,'vnpy_rules')
    assert final==account.advance(bars,targets,rules,config,'vnpy_rules')
    check=reconcile_account(output/'paper.json');assert check['status']=='matched'
    assert check['checked_overlap_entitlements']==1
    second_accrual=next(r for r in final['summary']['corporate_action_ledger'] if r['action_id']=='synthetic-second' and r['kind']=='dividend_accrual')
    assert second_accrual['entitlement_basis']['included_pending_shares']>0
    assert final['summary']['pending_stock_positions']=={}
    result={'source':batch.snapshot,'bars':bars.height,'backend_comparison':comparison,
        'partial_revision':partial['revision'],'final_revision':final['revision'],
        'partial_check':partial_check,'final_check':check,'second_entitlement':second_accrual,
        'scope':source+'; verifies accounting and restore, not historical corporate-action or performance validity'}
    (output/'verification.json').write_text(encode(result))
    print(json.dumps({'bars':bars.height,'native':comparison['status'],'account':check['status'],
        'overlap_checks':check['checked_overlap_entitlements'],'fills':check['checked_fills'],
        'included_pending_shares':second_accrual['entitlement_basis']['included_pending_shares']}))

if __name__=='__main__':main()
