"""Explicit cash-dividend entitlements, ex-date receivables and payment ledger.

Tax is a supplied fixed assumption, not an investor-specific tax-law engine.
Optional explicit stock distributions accrue at ex-date and become tradable at list_at.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from fractions import Fraction


def _validate_fractional_settlement(value):
    if not isinstance(value,dict) or set(value)-{'pay_at'}!={'price','tax_rate','fee'}:
        raise ValueError('Fractional settlement requires explicit price, tax_rate and fee')
    if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) for k in ('price','tax_rate','fee')):raise ValueError('Invalid fractional settlement amounts')
    if value['price']<=0 or not 0<=value['tax_rate']<=1 or value['fee']<0:raise ValueError('Invalid fractional settlement price/tax/fee')
    if 'pay_at' in value:
        at=datetime.fromisoformat(value['pay_at']) if isinstance(value['pay_at'],str) else value['pay_at']
        if not isinstance(at,datetime) or at.tzinfo is None:raise ValueError('Fractional payment time requires timezone')
    if Decimal(str(value['fee']))!=Decimal(str(value['fee'])).quantize(Decimal('.01')):raise ValueError('Fractional settlement fee requires cent precision')


def _fractional_cash(fraction, settlement):
    cent=lambda v:float(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    gross=cent(fraction*Decimal(str(settlement['price'])))
    tax=cent(Decimal(str(gross))*Decimal(str(settlement['tax_rate'])))
    fee=settlement['fee'] if fraction else 0.
    if gross-tax<fee:raise ValueError('Fractional settlement fee exceeds proceeds')
    return {'fractional_gross':gross,'fractional_tax':tax,'fractional_fee':fee,'fractional_cash':cent(Decimal(str(gross))-Decimal(str(tax))-Decimal(str(fee)))}


class CashDividends:
    def __init__(self, records=None, mode='strict'):
        if mode not in ('strict','retrospective'):raise ValueError('Unknown corporate action mode')
        self.mode=mode;self.records=[];self.entitlements={};self.accrued=set();self.paid=set();self.ledger=[];self.stock_accrued=set();self.listed=set();self.fractional_paid=set()
        fields={'action_id','symbol','record_at','ex_at','pay_at','available_at','cash_per_share','tax_rate','source'}
        seen=set()
        for raw in records or []:
            supplied=set(raw)-{'entitled_pending_actions','fractional_settlement','entitlement_quantity','holding_tax'}
            if supplied not in (fields,fields|{'stock_per_share','list_at','fractional_policy'}):raise ValueError('Dividend fields must match the documented cash or stock schema')
            r=dict(raw)
            for name in ('record_at','ex_at','pay_at','available_at'):
                if isinstance(r[name],str):r[name]=datetime.fromisoformat(r[name])
                if not isinstance(r[name],datetime) or r[name].tzinfo is None:raise ValueError('Dividend timestamps require timezone')
            if not r['record_at']<r['ex_at']<=r['pay_at']:raise ValueError('Require record_at < ex_at <= pay_at')
            for name in ('action_id','symbol','source'):
                if not isinstance(r[name],str) or not r[name].strip():raise ValueError('Dividend needs identity and provenance')
            if r['action_id'] in seen:raise ValueError('Duplicate cash dividend action_id')
            if 'entitled_pending_actions' in r:
                pending=r['entitled_pending_actions']
                if not isinstance(pending,list) or any(not isinstance(v,str) or not v.strip() for v in pending) or len(set(pending))!=len(pending):
                    raise ValueError('entitled_pending_actions must be a list of distinct action ids')
                r['entitled_pending_actions']=list(pending)
            for name in ('cash_per_share','tax_rate'):
                if type(r[name]) not in (int,float) or not math.isfinite(r[name]):raise ValueError('Invalid dividend amount/tax')
            if r['cash_per_share']<0 or not 0<=r['tax_rate']<=1:raise ValueError('Invalid dividend amount/tax')
            if 'stock_per_share' in r:
                if type(r['stock_per_share']) not in (int,float) or not math.isfinite(r['stock_per_share']) or r['stock_per_share']<=0:raise ValueError('Stock distribution ratio must be positive and finite')
                if isinstance(r['list_at'],str):r['list_at']=datetime.fromisoformat(r['list_at'])
                if not isinstance(r['list_at'],datetime) or r['list_at'].tzinfo is None or r['list_at']<r['ex_at']:raise ValueError('Stock listing must be timezone-aware and at/after ex-date')
                if r['fractional_policy'] not in ('reject','floor'):raise ValueError('Explicit fractional_policy must be reject or floor')
            if 'entitlement_quantity' in r and (type(r['entitlement_quantity']) is not int or r['entitlement_quantity']<0):raise ValueError('Explicit entitlement_quantity must be a nonnegative integer')
            if 'fractional_settlement' in r:
                if 'stock_per_share' not in r or r['fractional_policy']!='floor':raise ValueError('Fractional settlement requires a floor stock distribution')
                _validate_fractional_settlement(r['fractional_settlement'])
                r['fractional_settlement']=dict(r['fractional_settlement'])
                if 'pay_at' in r['fractional_settlement']:
                    value=r['fractional_settlement']['pay_at'];value=datetime.fromisoformat(value) if isinstance(value,str) else value
                    if value<r['ex_at']:raise ValueError('Fractional payment cannot precede ex-time')
                    r['fractional_settlement']['pay_at']=value
            from quantlab.execution.holding_tax import validate_holding_tax
            validate_holding_tax(r)
            seen.add(r['action_id']);self.records.append(r)
        self.records.sort(key=lambda r:(r['record_at'],r['action_id']))
        by_id={r['action_id']:r for r in self.records}
        for r in self.records:
            for key in r.get('entitled_pending_actions',[]):
                prior=by_id.get(key)
                if (prior is None or prior['symbol']!=r['symbol'] or 'stock_per_share' not in prior
                    or not prior['record_at']<r['record_at'] or not prior['ex_at']<=r['record_at']<prior['list_at']):
                    raise ValueError('Entitled pending action must identify an earlier unlisted stock distribution for the same symbol: '+key)

    @property
    def receivable(self):
        return math.fsum(self.entitlements[key]['net'] for key in sorted(self.accrued-self.paid))+math.fsum(self.entitlements[r['action_id']]['fractional_cash'] for r in self.records if 'pay_at' in r.get('fractional_settlement',{}) and r['action_id'] in self.accrued-self.fractional_paid)

    def pending(self, symbol):
        return sum(self.entitlements[r['action_id']].get('shares',0) for r in self.records
            if r['symbol']==symbol and r['action_id'] in self.stock_accrued-self.listed)

    def capture(self, at, symbols, quantity):
        for r in self.records:
            key=r['action_id']
            if r['record_at']==at and r['symbol'] in symbols:
                pending_sources={prior['action_id']:self.entitlements[prior['action_id']].get('shares',0)
                    for prior in self.records if prior['symbol']==r['symbol'] and prior['action_id'] in self.stock_accrued-self.listed}
                if any(pending_sources.values()) and 'entitled_pending_actions' not in r and 'entitlement_quantity' not in r:
                    raise ValueError('Overlapping entitlement before stock listing requires explicit entitlement data')
                chosen=r.get('entitled_pending_actions',[])
                missing=[key for key in chosen if key not in self.entitlements]
                if missing:raise ValueError('Missing record-date entitlement for pending source: '+', '.join(missing))
                tradable=quantity(r['symbol']);included=sum(pending_sources.get(key,0) for key in chosen)
                n=r.get('entitlement_quantity',tradable+included)
                rounded=lambda x:float(Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                gross=rounded(n*r['cash_per_share']);tax=rounded(gross*r['tax_rate'])
                self.entitlements[key]={'quantity':n,'gross':gross,'tax':tax,'net':gross-tax}
                if 'entitlement_quantity' in r:self.entitlements[key]['explicit_entitlement_quantity']=n
                if 'entitled_pending_actions' in r:
                    self.entitlements[key]['entitlement_basis']={'held_shares':tradable,
                        'included_pending_shares':included,'pending_sources':pending_sources,
                        'entitled_pending_actions':list(chosen),'policy':'explicit pending action ids; unlisted sources not named are excluded'}
                if 'stock_per_share' in r:
                    exact=Decimal(n)*Decimal(str(r['stock_per_share']));whole=int(exact)
                    if exact!=whole and r['fractional_policy']=='reject':raise ValueError('Fractional stock entitlement requires an explicit allocation rule: '+key)
                    self.entitlements[key].update(shares=whole,fractional_discarded=float(exact-whole),fractional_policy=r['fractional_policy'])
                    if 'fractional_settlement' in r:
                        settlement=_fractional_cash(exact-whole,r['fractional_settlement'])
                        self.entitlements[key].update(settlement)
                        if 'pay_at' not in r['fractional_settlement']:self.entitlements[key]['net']=rounded(self.entitlements[key]['net']+settlement['fractional_cash'])

    def advance(self, at, bar_end, first_bar, symbols, deliver_shares=None):
        cash=0.
        for r in self.records:
            key=r['action_id']
            if r['symbol'] not in symbols or at<r['ex_at'] or (key in self.paid and ('stock_per_share' not in r or key in self.listed) and ('pay_at' not in r.get('fractional_settlement',{}) or key in self.fractional_paid)):continue
            if r['record_at']<first_bar:continue # Account starts flat; no pre-inception entitlement.
            if key not in self.entitlements:raise ValueError('Missing exact record-date close for dividend '+key)
            if self.mode=='strict' and r['available_at']>r['ex_at']:
                raise ValueError('Dividend historical availability is later than ex-date: '+key)
            entitlement=self.entitlements[key]
            base={'action_id':key,'symbol':r['symbol'],'at':at,'bar_end':bar_end,**entitlement,
                'source':r['source'],'mode':self.mode}
            if key not in self.accrued:
                self.accrued.add(key);self.ledger.append({**base,'kind':'dividend_accrual','cash_delta':0.,'receivable_delta':entitlement['net']})
                if 'pay_at' in r.get('fractional_settlement',{}):self.ledger.append({**base,'kind':'fractional_accrual','cash_delta':0.,'receivable_delta':entitlement['fractional_cash']})
            if 'stock_per_share' in r:
                if key not in self.stock_accrued:
                    self.stock_accrued.add(key)
                    self.ledger.append({**base,'kind':'stock_accrual','cash_delta':0.,'receivable_delta':0.,'pending_share_delta':entitlement['shares'],'position_delta':0})
                if at>=r['list_at'] and key not in self.listed:
                    if deliver_shares is None:raise ValueError('Stock distributions require a position delivery callback')
                    deliver_shares(r['symbol'],entitlement['shares'],at)
                    self.listed.add(key)
                    self.ledger.append({**base,'kind':'stock_listing','cash_delta':0.,'receivable_delta':0.,'pending_share_delta':-entitlement['shares'],'position_delta':entitlement['shares']})
            if at>=r['pay_at'] and key not in self.paid:
                self.paid.add(key);cash+=entitlement['net']
                self.ledger.append({**base,'kind':'dividend_payment','cash_delta':entitlement['net'],'receivable_delta':-entitlement['net']})
            if 'pay_at' in r.get('fractional_settlement',{}) and at>=r['fractional_settlement']['pay_at'] and key not in self.fractional_paid:
                self.fractional_paid.add(key);cash+=entitlement['fractional_cash']
                self.ledger.append({**base,'kind':'fractional_payment','cash_delta':entitlement['fractional_cash'],'receivable_delta':-entitlement['fractional_cash']})
        return cash


class StockSplits:
    """Explicit share-unit conversion, preserving each lot's acquisition date.

    Ratio is new shares / old shares. Explicit floor allocation is per acquisition
    lot with explicitly dated cash-in-lieu. Pending conversions require named
    entitlement bindings and explicit allocation for fractional quantities.
    """
    def __init__(self, records=None, mode='strict'):
        if mode not in ('strict','retrospective'):raise ValueError('Unknown split mode')
        self.records=[];self.applied=set();self.ledger=[];self.mode=mode;self.unpaid={};seen=set();times=set()
        fields={'action_id','symbol','effective_at','available_at','numerator','denominator','fractional_policy','source'}
        for raw in records or []:
            if set(raw)-{'fractional_settlement','convert_entitlements','entitlement_allocations'}!=fields:raise ValueError('Split fields must match the documented schema')
            r=dict(raw)
            for key in ('action_id','symbol','source'):
                if not isinstance(r[key],str) or not r[key].strip():raise ValueError('Split requires identity and provenance')
            for key in ('effective_at','available_at'):
                if isinstance(r[key],str):r[key]=datetime.fromisoformat(r[key])
                if not isinstance(r[key],datetime) or r[key].tzinfo is None:raise ValueError('Split timestamps require timezone')
            if any(type(r[k]) is not int or r[k]<=0 for k in ('numerator','denominator')) or r['numerator']==r['denominator']:raise ValueError('Split ratio requires distinct positive integers')
            if r['fractional_policy'] not in ('reject','floor'):raise ValueError('Split fractional_policy requires reject or floor')
            if r['fractional_policy']=='floor':
                if 'fractional_settlement' not in r:raise ValueError('Floor split requires explicit fractional settlement at effective time')
                _validate_fractional_settlement(r['fractional_settlement'])
            elif 'fractional_settlement' in r:raise ValueError('Fractional settlement requires floor allocation')
            if 'pay_at' in r.get('fractional_settlement',{}):
                r['fractional_settlement']=dict(r['fractional_settlement']);value=r['fractional_settlement']['pay_at']
                value=datetime.fromisoformat(value) if isinstance(value,str) else value
                if value<r['effective_at']:raise ValueError('Split cash payment cannot precede conversion')
                r['fractional_settlement']['pay_at']=value
            if 'convert_entitlements' in r:
                ids=r['convert_entitlements']
                if not isinstance(ids,list) or any(not isinstance(v,str) or not v for v in ids) or len(ids)!=len(set(ids)):raise ValueError('convert_entitlements requires distinct action IDs')
            if 'entitlement_allocations' in r:
                allocations=r['entitlement_allocations']
                if not isinstance(allocations,dict) or set(allocations)-set(r.get('convert_entitlements',[])):raise ValueError('Entitlement allocations must name explicitly converted actions')
                for value in allocations.values():
                    if not isinstance(value,dict) or set(value)!={'shares','cash','principal_reduction'} or type(value['shares']) is not int or value['shares']<0:raise ValueError('Entitlement allocation requires whole shares, cash and principal reduction')
                    for field in ('cash','principal_reduction'):
                        v=value[field]
                        if type(v) not in (int,float) or not math.isfinite(v) or v<0 or Decimal(str(v))!=Decimal(str(v)).quantize(Decimal('.01')):raise ValueError('Entitlement settlement requires nonnegative cent amounts')
            key=(r['symbol'],r['effective_at'])
            if r['action_id'] in seen or key in times:raise ValueError('Duplicate split identity or simultaneous conversion')
            seen.add(r['action_id']);times.add(key);self.records.append(r)
        self.records.sort(key=lambda r:(r['effective_at'],r['action_id']))

    def validate_bindings(self,dividends,rights,traded_rights):
        candidates=[r for r in dividends.records if 'stock_per_share' in r]+rights.records+[r for r in traded_rights.records if 'exercise' in r]
        for split in self.records:
            for key in split.get('convert_entitlements',[]):
                matches=[r for r in candidates if r['action_id']==key]
                if len(matches)!=1:raise ValueError('Split entitlement reference is missing or ambiguous: '+key)
                r=matches[0];end=r['exercise']['listing_at'] if 'exercise' in r else r['list_at']
                if r['symbol']!=split['symbol'] or not r['record_at']<split['effective_at']<=end:raise ValueError('Split reference must name an unlisted entitlement for the same underlying')

    @property
    def receivable(self):return math.fsum(self.unpaid.values())

    def settle(self,at,bar_end,matcher=None):
        cash=0.
        for r in self.records:
            key=r['action_id']
            if key not in self.unpaid or at<r['fractional_settlement']['pay_at']:continue
            amount=self.unpaid.pop(key);cash+=amount
            self.ledger.append({'action_id':key,'symbol':r['symbol'],'kind':'split_cash_payment','at':at,'bar_end':bar_end,
                'cash_delta':amount,'receivable_delta':-amount,'source':r['source'],'mode':self.mode})
        if cash and matcher:matcher.cash_distribution(cash)
        return cash

    def advance(self, at, bar_end, lots, prices, marks, last_close, dividends, matcher=None, rights=None, holding_tax=None, traded_rights=None):
        cash=0.
        for r in self.records:
            key=r['action_id'];symbol=r['symbol']
            if key in self.applied or symbol not in lots or r['effective_at']>at:continue
            held=sum(q for _,q in lots[symbol])
            if r['effective_at']<at:
                if held:raise ValueError('Missing exact effective-time bar for held split stock: '+key)
                self.applied.add(key);continue
            if self.mode=='strict' and r['available_at']>at:raise ValueError('Split historical availability is later than effective time: '+key)
            if held and symbol not in prices:raise ValueError('Missing split valuation bar: '+key)
            active=[('distribution',d) for d in dividends.records if d['symbol']==symbol and 'stock_per_share' in d and d['record_at']<=at<=d['list_at'] and d['action_id'] not in dividends.listed]
            if rights:active += [('rights',d) for d in rights.records if d['symbol']==symbol and d['record_at']<=at<=d['list_at'] and d['action_id'] not in rights.listed|rights.cancelled]
            if traded_rights:active += [('tradable_rights',d) for d in traded_rights.records if d['symbol']==symbol and 'exercise' in d and d['record_at']<=at<=d['exercise']['listing_at'] and d['action_id'] not in traded_rights.listed]
            if any(d['action_id'] not in r.get('convert_entitlements',[]) for _,d in active):raise ValueError('Split overlapping stock distribution or rights requires explicit conversion rules: '+key)
            changes=[]
            for kind,d in active:
                target=d['action_id']
                if target not in (dividends.entitlements if kind=='distribution' else traded_rights.basis if kind=='tradable_rights' else rights.entitlements):continue
                if kind=='distribution':
                    value=dividends.entitlements[target];before=value['shares'];pending=target in dividends.stock_accrued
                elif kind=='tradable_rights':
                    before=traded_rights.exercised.get(target,traded_rights.converted_shares.get(target,d['exercise']['rights_quantity']*d['exercise']['shares_per_right']));pending=target in traded_rights.exercised
                else:
                    value=rights.subscribed.get(target)
                    before=value['shares'] if value is not None else rights.converted_shares.get(target,d['subscription_shares'])
                    pending=target in rights.exercised
                after,remainder=divmod(before*r['numerator'],r['denominator'])
                allocation=r.get('entitlement_allocations',{}).get(target)
                if remainder and allocation is None:raise ValueError('Pending entitlement conversion must have an explicit whole-share allocation: '+target)
                extra={}
                if allocation is not None:
                    after=allocation['shares'];reduction=allocation['principal_reduction']
                    if reduction and (kind!='rights' or target not in rights.subscribed or reduction>rights.subscribed[target]['cost']):raise ValueError('Principal reduction requires an existing sufficient paid subscription')
                    extra={**allocation,'prepaid_delta':-reduction if kind=='rights' and target not in rights.exercised else 0.}
                changes.append({'action_id':target,'kind':kind,'before_quantity':before,'after_quantity':after,'pending_share_delta':after-before if pending else 0,**extra})
            converted=[];fraction=Decimal(0)
            for acquired,quantity in lots[symbol]:
                whole,remainder=divmod(quantity*r['numerator'],r['denominator'])
                if remainder and r['fractional_policy']=='reject':raise ValueError('Fractional split lot requires explicit allocation: '+key)
                fraction+=Decimal(remainder)/Decimal(r['denominator'])
                converted.append([acquired,whole])
            settlement=_fractional_cash(fraction,r['fractional_settlement']) if 'fractional_settlement' in r else {}
            # Validate every conversion before mutating any entitlement.
            for change in changes:
                target=change['action_id']
                if change['kind']=='distribution':dividends.entitlements[target]['shares']=change['after_quantity']
                elif change['kind']=='tradable_rights':
                    if target in traded_rights.exercised:traded_rights.exercised[target]=change['after_quantity']
                    else:traded_rights.converted_shares[target]=change['after_quantity']
                else:
                    rights.unit_factors[target]=rights.unit_factors.get(target,Fraction(1))*Fraction(r['numerator'],r['denominator'])
                    if target in rights.subscribed:
                        rights.subscribed[target]['shares']=change['after_quantity'];rights.subscribed[target]['cost']-=change.get('principal_reduction',0.)
                    else:rights.converted_shares[target]=change['after_quantity']
            amount=settlement.get('fractional_cash',0.)+math.fsum(c.get('cash',0.) for c in changes);receivable=amount if 'pay_at' in r.get('fractional_settlement',{}) else 0.
            if 'pay_at' in r.get('fractional_settlement',{}):self.unpaid[key]=receivable;amount=0.
            cash+=amount
            if holding_tax:holding_tax.convert(symbol,lots[symbol],converted,r['numerator'],r['denominator'],at,bar_end)
            after=sum(q for _,q in converted);lots[symbol]=converted
            if matcher:
                matcher.stock_distribution(symbol,after-held)
                if amount:matcher.cash_distribution(amount)
            factor=r['denominator']/r['numerator']
            for values in (marks,last_close):
                if symbol in values:values[symbol]*=factor
            self.applied.add(key)
            self.ledger.append({**r,'kind':'stock_split','at':at,'bar_end':bar_end,'before_quantity':held,'after_quantity':after,
                'position_delta':after-held,'cash_delta':amount,'mode':self.mode,'lot_dates_preserved':True,
                **({'fractional_discarded':float(fraction),**settlement} if settlement else {}),
                **({'receivable_delta':receivable} if 'pay_at' in r.get('fractional_settlement',{}) else {}),
                **({'entitlement_conversions':changes} if 'convert_entitlements' in r else {}),
                **({'prepaid_delta':math.fsum(c.get('prepaid_delta',0.) for c in changes)} if 'entitlement_allocations' in r else {})})
        return cash


class RightsIssues:
    """Explicit nontransferable subscription instructions; no automatic election.

    Paid subscriptions are carried at cost until ex_at, then at the underlying
    share mark while unlisted. Unexercised rights carry no modeled market value.
    """
    def __init__(self, records=None, mode='strict'):
        if mode not in ('strict','retrospective'):raise ValueError('Unknown rights mode')
        self.mode=mode;self.records=[];self.entitlements={};self.subscribed={};self.exercised=set();self.listed=set();self.ledger=[];self.cancelled=set();self.refunded=set();self.converted_shares={};self.unit_factors={};self.allocated=set();self.allocation_unpaid={};self.refund_amounts={}
        fields={'action_id','symbol','record_at','subscribe_at','ex_at','list_at','available_at','numerator','denominator',
            'subscription_price','subscription_shares','insufficient_cash','fractional_policy','source'}
        seen=set()
        for raw in records or []:
            if set(raw)-{'subscription_fee','cancellation','entitlement_quantity','allocation','allow_oversubscription'}!=fields:raise ValueError('Rights fields must match the documented schema')
            r=dict(raw)
            for name in ('action_id','symbol','source'):
                if not isinstance(r[name],str) or not r[name].strip():raise ValueError('Rights issue requires identity and provenance')
            if r['action_id'] in seen:raise ValueError('Duplicate rights action_id')
            for name in ('record_at','subscribe_at','ex_at','list_at','available_at'):
                if isinstance(r[name],str):r[name]=datetime.fromisoformat(r[name])
                if not isinstance(r[name],datetime) or r[name].tzinfo is None:raise ValueError('Rights timestamps require timezone')
            if not r['record_at']<r['subscribe_at']<=r['ex_at']<=r['list_at']:raise ValueError('Require record < subscribe <= ex <= listing')
            if any(type(r[k]) is not int or r[k]<=0 for k in ('numerator','denominator')):raise ValueError('Rights ratio requires positive integers')
            if type(r['subscription_shares']) is not int or r['subscription_shares']<0:raise ValueError('Explicit subscription_shares must be a nonnegative integer')
            if type(r['subscription_price']) not in (int,float) or not math.isfinite(r['subscription_price']) or r['subscription_price']<=0:raise ValueError('Invalid subscription price')
            if r['fractional_policy'] not in ('reject','floor') or r['insufficient_cash'] not in ('skip','error'):raise ValueError('Require fractional_policy=reject/floor and insufficient_cash=skip/error')
            if 'entitlement_quantity' in r and (type(r['entitlement_quantity']) is not int or r['entitlement_quantity']<0):raise ValueError('Explicit entitlement_quantity must be a nonnegative integer')
            fee=r.get('subscription_fee',0.)
            if type(fee) not in (int,float) or not math.isfinite(fee) or fee<0:raise ValueError('Subscription fee must be finite and nonnegative')
            if Decimal(str(fee))!=Decimal(str(fee)).quantize(Decimal('.01')):raise ValueError('Subscription fee requires cent precision')
            if type(r.get('allow_oversubscription',False)) is not bool:raise ValueError('allow_oversubscription must be boolean')
            if r.get('allow_oversubscription') and 'allocation' not in r:raise ValueError('Oversubscription requires an explicit allocation result')
            if 'allocation' in r:
                a=r['allocation']
                if not isinstance(a,dict) or set(a)!={'shares','at','available_at','refund_at','fee_refund','source'}:raise ValueError('Allocation requires shares, times, fee_refund and provenance')
                a=dict(a);r['allocation']=a
                for field in ('at','available_at','refund_at'):
                    if isinstance(a[field],str):a[field]=datetime.fromisoformat(a[field])
                    if not isinstance(a[field],datetime) or a[field].tzinfo is None:raise ValueError('Allocation timestamps require timezone')
                if not r['subscribe_at']<=a['at']<=r['ex_at'] or a['refund_at']<a['at']:raise ValueError('Allocation must follow payment and precede ex-time; refund cannot precede allocation')
                if type(a['shares']) is not int or not 0<=a['shares']<=r['subscription_shares']:raise ValueError('Allocated shares must be between zero and requested subscription')
                if not isinstance(a['source'],str) or not a['source'].strip():raise ValueError('Allocation requires provenance')
                v=a['fee_refund']
                if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=fee or Decimal(str(v))!=Decimal(str(v)).quantize(Decimal('.01')):raise ValueError('Invalid allocation fee refund')
            if 'cancellation' in r:
                c=r['cancellation']
                if not isinstance(c,dict) or set(c)-{'recovery'}!={'cancel_at','refund_at','available_at','fee_refund','source'}:raise ValueError('Cancellation requires explicit times, fee_refund and source')
                c=dict(c);r['cancellation']=c
                for name in ('cancel_at','refund_at','available_at'):
                    if isinstance(c[name],str):c[name]=datetime.fromisoformat(c[name])
                    if not isinstance(c[name],datetime) or c[name].tzinfo is None:raise ValueError('Cancellation timestamps require timezone')
                if c['cancel_at']<r['subscribe_at'] or c['refund_at']<c['cancel_at']:raise ValueError('Cancellation must occur after subscription; refund cannot precede cancellation')
                if c['cancel_at']>r['list_at']:
                    recovery=c.get('recovery')
                    if not isinstance(recovery,dict) or set(recovery)!={'shares','missing_share_price','source'}:raise ValueError('Cancellation after listing requires explicit recovery terms')
                    if type(recovery['shares']) is not int or recovery['shares']<0:raise ValueError('Recovery shares must be nonnegative integer')
                    if type(recovery['missing_share_price']) not in (int,float) or not math.isfinite(recovery['missing_share_price']) or recovery['missing_share_price']<0:raise ValueError('Invalid missing-share recovery price')
                    if not isinstance(recovery['source'],str) or not recovery['source'].strip():raise ValueError('Recovery requires provenance')
                elif c['cancel_at']==r['list_at']:raise ValueError('Cancellation at listing time requires choosing before or after listing')
                elif 'recovery' in c:raise ValueError('Recovery terms apply only to listed rights')
                if 'allocation' in r and c['cancel_at']<r['allocation']['at']:raise ValueError('Cancellation cannot precede a configured allocation result')
                if not isinstance(c['source'],str) or not c['source'].strip():raise ValueError('Cancellation requires provenance')
                refund=c['fee_refund']
                if type(refund) not in (int,float) or not math.isfinite(refund) or not 0<=refund<=fee-r.get('allocation',{}).get('fee_refund',0.) or Decimal(str(refund))!=Decimal(str(refund)).quantize(Decimal('.01')):raise ValueError('Fee refund must be a cent amount between zero and subscription fee')
            if any(p['symbol']==r['symbol'] and max(p['record_at'],r['record_at'])<=min(p['list_at'],r['list_at']) and not ('entitlement_quantity' in p and 'entitlement_quantity' in r) for p in self.records):raise ValueError('Overlapping rights issues require explicit allocation rules')
            seen.add(r['action_id']);self.records.append(r)
        self.records.sort(key=lambda r:(r['subscribe_at'],r['action_id']))

    def validate_other_actions(self, dividends, splits):
        for r in self.records:
            if any(d['symbol']==r['symbol'] and max(d['record_at'],r['record_at'])<=min(max(d['pay_at'],d.get('list_at',d['pay_at'])),r['list_at']) and not ('entitlement_quantity' in d and 'entitlement_quantity' in r) for d in dividends.records):
                raise ValueError('Rights overlapping dividends/distributions require explicit entitlement rules')
            if any(s['symbol']==r['symbol'] and r['record_at']<=s['effective_at']<=r['list_at'] and r['action_id'] not in s.get('convert_entitlements',[]) for s in splits.records):
                raise ValueError('Rights overlapping splits require explicit conversion rules')

    @property
    def prepaid(self):
        return math.fsum(v['cost'] for key,v in self.subscribed.items() if key not in self.exercised and key not in self.cancelled) + math.fsum(
            self.refund_amounts[r['action_id']] for r in self.records if r['action_id'] in self.cancelled-self.refunded)+math.fsum(self.allocation_unpaid.values())

    def pending(self,symbol):
        return sum(self.subscribed[r['action_id']]['shares'] for r in self.records if r['symbol']==symbol and r['action_id'] in self.exercised-self.listed-self.cancelled)

    def capture(self, at, symbols, quantity):
        for r in self.records:
            if at!=r['record_at'] or r['symbol'] not in symbols:continue
            held=quantity(r['symbol']);basis=r.get('entitlement_quantity',held);whole,remainder=divmod(basis*r['numerator'],r['denominator'])
            if remainder and r['fractional_policy']=='reject':raise ValueError('Fractional rights entitlement requires explicit allocation: '+r['action_id'])
            if r['subscription_shares']>whole and not r.get('allow_oversubscription',False):raise ValueError('Requested subscription exceeds record-date entitlement: '+r['action_id'])
            self.entitlements[r['action_id']]={'held_shares':held,'entitled_shares':whole}
            if 'entitlement_quantity' in r:self.entitlements[r['action_id']]['explicit_entitlement_quantity']=basis
            if r['fractional_policy']=='floor':self.entitlements[r['action_id']].update(fractional_discarded=remainder/r['denominator'],fractional_policy='floor')

    def advance(self, at, bar_end, first_bar, symbols, prices, cash, deliver, recover=None):
        delta=0.
        for r in self.records:
            key=r['action_id'];symbol=r['symbol']
            if symbol not in symbols or r['record_at']<first_bar or at<r['subscribe_at']:continue
            if key not in self.entitlements:raise ValueError('Missing exact record-date close for rights '+key)
            if self.mode=='strict' and r['available_at']>r['subscribe_at']:raise ValueError('Rights availability is later than subscription: '+key)
            base={'action_id':key,'symbol':symbol,'at':at,'bar_end':bar_end,'source':r['source'],'mode':self.mode,**self.entitlements[key]}
            if key not in self.subscribed:
                if at!=r['subscribe_at']:raise ValueError('Missing exact subscription-time bar: '+key)
                shares=self.converted_shares.get(key,r['subscription_shares']);cost=float((Decimal(r['subscription_shares'])*Decimal(str(r['subscription_price']))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                reason='subscribed' if shares else 'declined';fee=r.get('subscription_fee',0.) if shares else 0.
                if cost+fee>cash+delta:
                    if r['insufficient_cash']=='error':raise ValueError('Insufficient cash for rights subscription: '+key)
                    shares=0;cost=0.;fee=0.;reason='insufficient_cash'
                self.subscribed[key]={'shares':shares,'cost':cost,'paid':reason=='subscribed'};delta-=cost+fee
                self.ledger.append({**base,'kind':'rights_subscription','shares':shares,'cost':cost,**({'fee':fee} if 'subscription_fee' in r else {}),'cash_delta':-(cost+fee),'prepaid_delta':cost,'pending_share_delta':0,'position_delta':0,'status':reason})
            value=self.subscribed[key]
            allocation=r.get('allocation')
            if allocation and at>=allocation['at']:
                if key not in self.allocated:
                    if at!=allocation['at']:raise ValueError('Missing exact allocation-time bar: '+key)
                    if self.mode=='strict' and allocation['available_at']>at:raise ValueError('Allocation availability is later than allocation: '+key)
                    subscribed=value['paid']
                    exact=Fraction(allocation['shares'])*self.unit_factors.get(key,Fraction(1)) if subscribed else Fraction(0)
                    if exact.denominator!=1:raise ValueError('Allocated entitlement conversion requires whole shares: '+key)
                    shares=int(exact)
                    allocated=allocation['shares'] if subscribed else 0
                    original_cost=float((Decimal(r['subscription_shares'])*Decimal(str(r['subscription_price']))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if subscribed else 0.
                    reduction=Decimal(str(original_cost))-Decimal(str(value['cost']))
                    cost=float((Decimal(allocated)*Decimal(str(r['subscription_price']))-(reduction*Decimal(allocated)/Decimal(r['subscription_shares']) if r['subscription_shares'] else 0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                    returned_fee=allocation['fee_refund'] if subscribed else 0.
                    refund=value['cost']-cost+returned_fee
                    self.allocation_unpaid[key]=refund;self.allocated.add(key);value.update(shares=shares,cost=cost)
                    self.ledger.append({**base,'kind':'rights_allocation','source':allocation['source'],'shares':shares,'cost':cost,'refund_amount':refund,'fee_refund':returned_fee,
                        'cash_delta':0.,'prepaid_delta':returned_fee,'pending_share_delta':0,'position_delta':0})
                if at>=allocation['refund_at'] and key in self.allocation_unpaid:
                    if at!=allocation['refund_at']:raise ValueError('Missing exact allocation refund-time bar: '+key)
                    amount=self.allocation_unpaid.pop(key);delta+=amount
                    self.ledger.append({**base,'kind':'rights_allocation_refund','source':allocation['source'],'shares':value['shares'],'cash_delta':amount,'prepaid_delta':-amount,'pending_share_delta':0,'position_delta':0})
            cancellation=r.get('cancellation')
            if cancellation and at>=cancellation['cancel_at']:
                if key not in self.cancelled:
                    if at!=cancellation['cancel_at']:raise ValueError('Missing exact cancellation-time bar: '+key)
                    if self.mode=='strict' and cancellation['available_at']>at:raise ValueError('Cancellation availability is later than cancellation: '+key)
                    refund_fee=cancellation['fee_refund'] if value['paid'] else 0.
                    was_listed=key in self.listed;recovered=0;replacement=0.
                    if 'recovery' in cancellation:
                        if recover is None:raise ValueError('Post-listing cancellation requires a recovery callback')
                        requested=cancellation['recovery']['shares'] if value['paid'] else 0
                        recovered=recover(symbol,requested,at)
                        replacement=float((Decimal(requested-recovered)*Decimal(str(cancellation['recovery']['missing_share_price']))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                    pending=-value['shares'] if key in self.exercised and not was_listed else 0
                    amount=value['cost']+refund_fee-replacement;self.refund_amounts[key]=amount
                    prepaid=amount if key in self.exercised else refund_fee-replacement
                    self.cancelled.add(key)
                    self.ledger.append({**base,'source':cancellation['source'],'kind':'rights_cancellation','shares':value['shares'],
                        'cash_delta':0.,'prepaid_delta':prepaid,'pending_share_delta':pending,'position_delta':-recovered,'fee_refund':refund_fee,
                        **({'recovery_shares':recovered,'replacement_cash':replacement} if 'recovery' in cancellation else {})})
                if at>=cancellation['refund_at'] and key not in self.refunded:
                    if at!=cancellation['refund_at'] and not self.refund_amounts.get(key,0.)<0:raise ValueError('Missing exact refund-time bar: '+key)
                    amount=self.refund_amounts[key]
                    if amount<0:amount=max(amount,-max(0.,cash+delta))
                    self.refund_amounts[key]-=amount
                    if abs(self.refund_amounts[key])<1e-8:self.refunded.add(key)
                    delta+=amount
                    self.ledger.append({**base,'source':cancellation['source'],'kind':'rights_refund','shares':value['shares'],
                        'cash_delta':amount,'prepaid_delta':-amount,'pending_share_delta':0,'position_delta':0})
                continue
            if at>=r['ex_at'] and key not in self.exercised:
                if at!=r['ex_at']:raise ValueError('Missing exact rights ex-time bar: '+key)
                if value['shares'] and symbol not in prices:raise ValueError('Missing rights ex-date valuation bar: '+key)
                self.exercised.add(key)
                self.ledger.append({**base,'kind':'rights_ex','shares':value['shares'],'cash_delta':0.,'prepaid_delta':-value['cost'],'pending_share_delta':value['shares'],'position_delta':0})
            if at>=r['list_at'] and key not in self.listed:
                if at!=r['list_at']:raise ValueError('Missing exact rights listing-time bar: '+key)
                self.listed.add(key);deliver(symbol,value['shares'],at)
                self.ledger.append({**base,'kind':'rights_listing','shares':value['shares'],'cash_delta':0.,'prepaid_delta':0.,'pending_share_delta':-value['shares'],'position_delta':value['shares']})
        return delta
