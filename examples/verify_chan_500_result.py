"""Read-only verification of the completed client-submitted 500-stock run."""
import json,math
from pathlib import Path
from collections import defaultdict,deque
from datetime import datetime
import polars as pl

root=Path('artifacts/chan-500-ten-year');job=json.loads((root/'runs/_jobs/b9664310-b39c-4017-8fa0-506c44a104d4.json').read_text())
assert job['status']=='completed',job['status']
run=root/'runs'/job['run_id'];record=json.loads((run/'experiment.json').read_text());sample=json.loads((root/'sample-manifest.json').read_text())
assert sorted(record['manifest']['config']['data']['symbols'])==sorted(sample['symbols'])
source=root/'runs'/record['children'][0]['run_id'];bars=pl.read_parquet(run/'bars.parquet');curve=pl.read_parquet(run/'observations.parquet')
assert bars['symbol'].n_unique()==500;assert bars.height==965834
fills=record['fills'];by_end=defaultdict(list)
for fill in fills:
    assert datetime.fromisoformat(fill['decision_at'])<datetime.fromisoformat(fill['filled_at'])<=datetime.fromisoformat(fill['bar_end'])
    by_end[datetime.fromisoformat(fill['bar_end'])].append(fill)
closes={key[0]:frame for key,frame in bars.group_by('datetime')};positions=defaultdict(int);lots=defaultdict(deque);marks={};cash=record['execution']['initial_cash'];maximum_error=0.;fees=defaultdict(float)
for row in curve.iter_rows(named=True):
    for fill in by_end[row['datetime']]:
        symbol=fill['symbol'];quantity=fill['quantity'];notional=quantity*fill['price'];day=datetime.fromisoformat(fill['filled_at']).date()
        for key in ('commission','tax','transfer_fee','slippage_cost'):fees[key]+=fill[key]
        if fill['side']=='buy':
            cash-=notional+fill['commission']+fill['transfer_fee'];positions[symbol]+=quantity;lots[symbol].append([day,quantity])
        else:
            left=quantity
            while left:
                assert lots[symbol] and lots[symbol][0][0]<day,'T+1 violation'
                amount=min(left,lots[symbol][0][1]);left-=amount;lots[symbol][0][1]-=amount
                if not lots[symbol][0][1]:lots[symbol].popleft()
            positions[symbol]-=quantity;assert positions[symbol]>=0
            cash+=notional-fill['commission']-fill['tax']-fill['transfer_fee']
    for symbol,close in closes[row['datetime']].select('symbol','close').iter_rows():marks[symbol]=close
    equity=cash+sum(quantity*marks.get(symbol,0) for symbol,quantity in positions.items())
    error=max(abs(equity-row['equity']),abs(cash-row['cash']));maximum_error=max(maximum_error,error)
    assert error<1e-5,(row['datetime'],error)
assert math.isclose(record['execution']['final_equity'],curve['equity'][-1],abs_tol=1e-6)
for summary_key,fee_key in [('commission','commission'),('sell_tax','tax'),('slippage_cost','slippage_cost'),('transfer_fee','transfer_fee')]:
    assert math.isclose(record['execution'][summary_key],fees[fee_key],abs_tol=1e-6)
check={'job_id':job['job_id'],'run_id':job['run_id'],'source_run_id':record['children'][0]['run_id'],
    'symbols':500,'bars':bars.height,'daily_ledger_checks':curve.height,'fill_time_and_t1_checks':len(fills),
    'maximum_cash_equity_error':maximum_error,'fee_checks':4,'execution':record['execution']}
(root/'independent-ledger-verification.json').write_text(json.dumps(check,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in check.items() if k!='execution'},ensure_ascii=False))
