"""Observation-only execution diagnostics; never feeds back into orders."""


class ExecutionAudit:
    def __init__(self,initial_cash):
        self.initial_cash=initial_cash;self.previous_equity=initial_cash
        self.attempts=[];self.bars=[];self.days={};self.previous_attempt={}

    def attempt(self,at,decision,symbol,buying,requested,filled,reason,capacity=None):
        side='buy' if buying else 'sell'
        previous=self.previous_attempt.get(symbol)
        retry=previous if previous and previous['decision_at']==decision and previous['side']==side and previous['unfilled']>0 else None
        row={'attempt_id':len(self.attempts)+1,'at':at,'decision_at':decision,'symbol':symbol,'side':side,
            'requested':requested,'filled':filled,'unfilled':requested-filled,'reason':reason if filled<requested else None,
            'retry_of':retry['attempt_id'] if retry else None}
        self.attempts.append(row);self.previous_attempt[symbol]=row
        if capacity is not None:row['capacity']=capacity

    def close(self,at,decision,weights,positions,pending,marks,fresh_symbols,equity,cash,receivable,fills):
        # Only the target actually consumed at this bar's open is compared.
        # A target becoming available at the close belongs to a later opening.
        actual={s:(positions[s]+pending[s])*marks.get(s,0)/equity if equity>0 else None for s in sorted(positions)}
        gaps={s:actual[s]-weights[s] if weights and actual[s] is not None else None for s in actual}
        notional={side:sum(f['quantity']*f['price'] for f in fills if f['side']==side) for side in ('buy','sell')}
        day=self.days.setdefault(at.date(),{'date':at.date(),'starting_equity':self.previous_equity,'buy_notional':0.,'sell_notional':0.})
        for side in notional:day[side+'_notional']+=notional[side]
        gross=notional['buy']+notional['sell']
        self.bars.append({'at':at,'decision_at':decision,'target_weights':dict(weights),'actual_weights':actual,'weight_gaps':gaps,
            'stock_weight_gap_l1':sum(abs(v) for v in gaps.values()) if weights and equity>0 else None,
            'positions':dict(positions),'pending_stock_positions':{s:q for s,q in pending.items() if q},
            'stale_held_marks':[s for s in sorted(positions) if positions[s]+pending[s] and s not in fresh_symbols],
            'cash_weight':cash/equity if equity>0 else None,'receivable_weight':receivable/equity if equity>0 else None,
            'gross_traded_notional':gross,'gross_turnover_previous_close':gross/self.previous_equity if self.previous_equity>0 else None})
        self.previous_equity=equity

    def result(self):
        daily=[{**r,'gross_turnover':(r['buy_notional']+r['sell_notional'])/r['starting_equity'] if r['starting_equity']>0 else None} for r in self.days.values()]
        gaps=[r['stock_weight_gap_l1'] for r in self.bars if r['stock_weight_gap_l1'] is not None]
        retries=[r for r in self.attempts if r['retry_of'] is not None]
        summary={'buy_notional':sum(r['buy_notional'] for r in daily),'sell_notional':sum(r['sell_notional'] for r in daily),
            'daily_gross_turnover_sum':sum(r['gross_turnover'] for r in daily if r['gross_turnover'] is not None),
            'unavailable_turnover_days':sum(r['gross_turnover'] is None for r in daily),
            'max_stock_weight_gap_l1':max(gaps,default=None),'mean_stock_weight_gap_l1':sum(gaps)/len(gaps) if gaps else None,
            'attempts':len(self.attempts),'retry_attempts':len(retries),'retry_attempts_with_fills':sum(r['filled']>0 for r in retries),
            'partial_or_unfilled_attempts':sum(r['unfilled']>0 for r in self.attempts)}
        return summary,{'version':'1.0.0','attempts':self.attempts,'bars':self.bars,'daily_turnover':daily,
            'definitions':{'weight_gap':'close economic stock weight (including pending shares) minus target consumed at opening; L1 excludes cash/receivables; missing held bars use last mark and are flagged',
                'retry':'same decision timestamp and side after a partially/unfilled attempt; each open recomputes size, not a resting order; a new target snapshot supersedes the old decision',
                'turnover':'gross BUY+SELL executed notional, no fees, divided by previous session close equity (initial cash for first session); no half-turnover convention or capacity claim'}}
