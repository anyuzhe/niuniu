"""Explicit calendar-month dividend tax bands and FIFO disposal assessments.

No investor identity or historical statutory rate is inferred. Tax is assessed
on disposal and collected no earlier than dividend payment, subject to cash.
"""
import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
import math


def validate_holding_tax(record):
    policy=record.get('holding_tax')
    if policy is None:return
    if not isinstance(policy,dict) or set(policy)-{'lots'}!={'basis_per_share','bands','available_at','source'}:raise ValueError('holding_tax requires explicit basis, calendar-month bands, availability and source')
    if record['tax_rate']!=0:raise ValueError('Holding-period tax requires tax_rate=0 to avoid double withholding')
    basis=policy['basis_per_share']
    if type(basis) not in (int,float) or not math.isfinite(basis) or basis<0:raise ValueError('Invalid holding-tax basis')
    at=datetime.fromisoformat(policy['available_at']) if isinstance(policy['available_at'],str) else policy['available_at']
    if not isinstance(at,datetime) or at.tzinfo is None:raise ValueError('Holding-tax availability requires timezone')
    if not isinstance(policy['source'],str) or not policy['source'].strip():raise ValueError('Holding-tax source is required')
    bands=policy['bands'];last=0
    if not isinstance(bands,list) or not bands:raise ValueError('Holding-tax bands cannot be empty')
    for i,band in enumerate(bands):
        if not isinstance(band,dict) or set(band)!={'months','rate'}:raise ValueError('Each tax band requires months and rate')
        months=band['months'];rate=band['rate']
        if months is None:
            if i!=len(bands)-1:raise ValueError('Unbounded tax band must be last')
        elif type(months) is not int or months<=last:raise ValueError('Tax month bands must strictly increase')
        else:last=months
        if type(rate) not in (int,float) or not math.isfinite(rate) or not 0<=rate<=1:raise ValueError('Invalid holding-tax rate')
    if bands[-1]['months'] is not None:raise ValueError('Holding-tax bands require an unbounded final band')
    if 'lots' in policy:
        if not isinstance(policy['lots'],list):raise ValueError('Tax lots must be a list')
        for lot in policy['lots']:
            if not isinstance(lot,dict) or set(lot)!={'acquired_at','quantity'} or type(lot['quantity']) is not int or lot['quantity']<0:raise ValueError('Explicit tax lots require acquisition date and nonnegative quantity')
            acquired=date.fromisoformat(lot['acquired_at'])
            if acquired>record['record_at'].date():raise ValueError('Tax lot cannot be acquired after entitlement record')


class HoldingTax:
    def __init__(self,records,mode='strict'):
        self.records=[r for r in records if 'holding_tax' in r];self.mode=mode
        self.claims={};self.debts=[];self.ledger=[]

    @property
    def payable(self):return math.fsum(d['remaining'] for d in self.debts)

    def capture(self,at,lots,entitlements):
        for r in self.records:
            key=r['action_id'];policy=r['holding_tax']
            if r['record_at']!=at or key not in entitlements:continue
            supplied=policy.get('lots')
            source=[(date.fromisoformat(v['acquired_at']),v['quantity']) for v in supplied] if supplied is not None else lots.get(r['symbol'],[])
            if sum(q for _,q in source)!=entitlements[key]['quantity']:raise ValueError('Tax lots must match recorded entitlement quantity: '+key)
            grouped={}
            for acquired,q in source:grouped[acquired]=grouped.get(acquired,0)+q
            held={}
            for acquired,q in lots.get(r['symbol'],[]):held[acquired]=held.get(acquired,0)+q
            if any(q>held.get(day,0) for day,q in grouped.items()):
                raise ValueError('Tax lots must identify existing position acquisition dates and quantities: '+key)
            self.claims[key]=[{'acquired':day,'quantity':Fraction(q),'gross':Decimal(q)*Decimal(str(policy['basis_per_share']))} for day,q in sorted(grouped.items()) if q]

    def _assess(self,r,claim,quantity,at,bar_end,phase):
        if not quantity:return
        policy=r['holding_tax'];known=policy['available_at'];known=datetime.fromisoformat(known) if isinstance(known,str) else known
        if self.mode=='strict' and known>at:raise ValueError('Holding-tax rule unavailable at disposal: '+r['action_id'])
        acquired=claim['acquired'];rate=None
        for band in policy['bands']:
            months=band['months']
            if months is None:rate=band['rate'];break
            serial=acquired.year*12+acquired.month-1+months;year,month=divmod(serial,12);month+=1
            boundary=date(year,month,min(acquired.day,calendar.monthrange(year,month)[1]))
            if at.date()<boundary:rate=band['rate'];break
        proportion=quantity/claim['quantity'];gross=claim['gross']*Decimal(proportion.numerator)/Decimal(proportion.denominator)
        tax=float((gross*Decimal(str(rate))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        claim['gross']-=gross;claim['quantity']-=quantity
        due=max(at,r['pay_at']);debt_id=len(self.debts)
        self.debts.append({'remaining':tax,'due':due,'action_id':r['action_id'],'symbol':r['symbol'],'source':policy['source']})
        self.ledger.append({'kind':'dividend_tax_assessment','action_id':r['action_id'],'symbol':r['symbol'],'at':at,'bar_end':bar_end,'phase':phase,
            'acquired_at':acquired,'quantity':float(quantity),'taxable_gross':float(gross),'rate':rate,'tax':tax,'due_at':due,'debt_id':debt_id,
            'cash_delta':0.,'payable_delta':tax,'source':policy['source']})

    def dispose(self,symbol,disposed,at,bar_end,phase='sale'):
        grouped={}
        for day,q in disposed:grouped[day]=grouped.get(day,0)+q
        for r in self.records:
            if r['symbol']!=symbol:continue
            available=dict(grouped)
            for claim in self.claims.get(r['action_id'],[]):
                q=min(claim['quantity'],Fraction(available.get(claim['acquired'],0)))
                self._assess(r,claim,q,at,bar_end,phase);available[claim['acquired']]=Fraction(available.get(claim['acquired'],0))-q

    def convert(self,symbol,before,after,numerator,denominator,at,bar_end):
        old={};new={}
        for day,q in before:old[day]=old.get(day,0)+q
        for day,q in after:new[day]=new.get(day,0)+q
        ratio=Fraction(numerator,denominator)
        for r in self.records:
            if r['symbol']!=symbol:continue
            for claim in self.claims.get(r['action_id'],[]):
                day=claim['acquired'];held=old.get(day,0)
                if not held or not claim['quantity']:continue
                kept=Fraction(new.get(day,0),held)/ratio
                self._assess(r,claim,claim['quantity']*(1-kept),at,bar_end,'split')
                claim['quantity']*=ratio

    def settle(self,at,bar_end,cash,phase):
        delta=0.
        for debt_id,debt in enumerate(self.debts):
            if debt['due']>at or debt['remaining']<=0:continue
            paid=min(debt['remaining'],max(0.,cash+delta));paid=math.floor((paid+1e-9)*100)/100
            if not paid:continue
            debt['remaining']=round(debt['remaining']-paid,2);delta-=paid
            self.ledger.append({'kind':'dividend_tax_payment','action_id':debt['action_id'],'symbol':debt['symbol'],'at':at,'bar_end':bar_end,'phase':phase,
                'debt_id':debt_id,'cash_delta':-paid,'payable_delta':-paid,'source':debt['source']})
        return delta
