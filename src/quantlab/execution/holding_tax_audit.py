"""Independent tax reconstruction from committed lots and dated policy inputs.

Deliberately does not import the execution tax engine or replay the backtester.
"""
import calendar
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP
from fractions import Fraction
import math

class TaxReconstruction:
    def __init__(self,records):
        self.records=[r for r in records if 'holding_tax' in r];self.claims={};self.debts=[];self.events=[]

    @property
    def payable(self):return math.fsum(d[0] for d in self.debts)

    def capture(self,at,lots,basis):
        for r in self.records:
            key=r['action_id']
            if datetime.fromisoformat(r['record_at'])!=at or key not in basis:continue
            source=[(date.fromisoformat(v['acquired_at']),v['quantity']) for v in r['holding_tax']['lots']] if 'lots' in r['holding_tax'] else lots.get(r['symbol'],[])
            grouped={}
            for acquired,n in source:grouped[acquired]=grouped.get(acquired,0)+n
            held={}
            for acquired,n in lots.get(r['symbol'],[]):held[acquired]=held.get(acquired,0)+n
            if sum(grouped.values())!=basis[key] or any(n>held.get(day,0) for day,n in grouped.items()):
                raise ValueError('Tax basis does not identify committed position lots: '+key)
            self.claims[key]=[[day,Fraction(n),Decimal(n)*Decimal(str(r['holding_tax']['basis_per_share']))] for day,n in sorted(grouped.items()) if n]

    def assess(self,r,c,n,at,end,phase):
        if not n:return
        rate=r['holding_tax']['bands'][-1]['rate']
        for band in r['holding_tax']['bands'][:-1]:
            year,month=divmod(c[0].year*12+c[0].month-1+band['months'],12);month+=1
            bound=date(year,month,min(c[0].day,calendar.monthrange(year,month)[1]))
            if at.date()<bound:rate=band['rate'];break
        share=n/c[1];gross=c[2]*Decimal(share.numerator)/Decimal(share.denominator)
        amount=float((gross*Decimal(str(rate))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP));c[1]-=n;c[2]-=gross
        due=max(at,datetime.fromisoformat(r['pay_at']));debt_id=len(self.debts);self.debts.append([amount,due,r])
        self.events.append({'kind':'dividend_tax_assessment','action_id':r['action_id'],'symbol':r['symbol'],'at':at.isoformat(),'bar_end':end.isoformat(),'phase':phase,
            'acquired_at':c[0].isoformat(),'quantity':float(n),'taxable_gross':float(gross),'rate':rate,'tax':amount,'due_at':due.isoformat(),'debt_id':debt_id,
            'cash_delta':0.,'payable_delta':amount,'source':r['holding_tax']['source']})

    def disposal(self,symbol,disposed,at,end,phase='sale'):
        grouped={}
        for day,n in disposed:grouped[day]=grouped.get(day,0)+n
        for r in self.records:
            if r['symbol']!=symbol:continue
            available=dict(grouped)
            for claim in self.claims.get(r['action_id'],[]):
                n=min(claim[1],Fraction(available.get(claim[0],0)));self.assess(r,claim,n,at,end,phase);available[claim[0]]=available.get(claim[0],0)-n

    def conversion(self,symbol,before,after,numerator,denominator,at,end):
        old={};new={}
        for day,n in before:old[day]=old.get(day,0)+n
        for day,n in after:new[day]=new.get(day,0)+n
        ratio=Fraction(numerator,denominator)
        for r in self.records:
            if r['symbol']!=symbol:continue
            for claim in self.claims.get(r['action_id'],[]):
                if not old.get(claim[0]) or not claim[1]:continue
                kept=Fraction(new.get(claim[0],0),old[claim[0]])/ratio
                self.assess(r,claim,claim[1]*(1-kept),at,end,'split');claim[1]*=ratio

    def collect(self,at,end,cash,phase):
        delta=0.
        for debt_id,d in enumerate(self.debts):
            if d[1]>at or d[0]<=0:continue
            amount=math.floor((min(d[0],max(0.,cash+delta))+1e-9)*100)/100
            if not amount:continue
            d[0]=round(d[0]-amount,2);delta-=amount;r=d[2]
            self.events.append({'kind':'dividend_tax_payment','action_id':r['action_id'],'symbol':r['symbol'],'at':at.isoformat(),'bar_end':end.isoformat(),'phase':phase,
                'debt_id':debt_id,'cash_delta':-amount,'payable_delta':-amount,'source':r['holding_tax']['source']})
        return delta
