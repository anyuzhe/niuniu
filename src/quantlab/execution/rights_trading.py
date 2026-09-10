"""Explicit transferable rights as a separate quoted security.

Trades use the existing execution engine. Delivery, exercise, pending underlying
shares and expiry are modeled here; no unquoted right value is invented.
"""
from datetime import datetime
from decimal import Decimal,ROUND_HALF_UP
import math

class RightsTrading:
    def __init__(self,records=None,mode='strict'):
        if mode not in ('strict','retrospective'):raise ValueError('Unknown transferable-rights mode')
        self.mode=mode;self.records=[];self.basis={};self.delivered=set();self.exercised={};self.listed=set();self.expired=set();self.ledger=[]
        self.converted_shares={}
        required={'action_id','symbol','rights_symbol','record_at','deliver_at','expires_at','available_at','numerator','denominator','fractional_policy','source'}
        ids=set();instruments=set()
        for raw in records or []:
            if set(raw)-{'exercise','entitlement_quantity'}!=required:raise ValueError('Transferable rights fields must match the documented schema')
            r=dict(raw)
            for field in ('record_at','deliver_at','expires_at','available_at'):
                if isinstance(r[field],str):r[field]=datetime.fromisoformat(r[field])
                if not isinstance(r[field],datetime) or r[field].tzinfo is None:raise ValueError('Rights trading timestamps require timezone')
            if not r['record_at']<r['deliver_at']<r['expires_at']:raise ValueError('Require record < rights delivery < expiry')
            for field in ('action_id','symbol','rights_symbol','source'):
                if not isinstance(r[field],str) or not r[field].strip():raise ValueError('Transferable rights require identity and source')
            if r['symbol']==r['rights_symbol'] or r['action_id'] in ids or r['rights_symbol'] in instruments:raise ValueError('Transferable rights require a distinct, unique quoted instrument')
            if any(type(r[k]) is not int or r[k]<=0 for k in ('numerator','denominator')):raise ValueError('Rights delivery ratio requires positive integers')
            if r['fractional_policy'] not in ('floor','reject'):raise ValueError('Rights delivery fractional_policy requires floor/reject')
            if 'entitlement_quantity' in r and (type(r['entitlement_quantity']) is not int or r['entitlement_quantity']<0):raise ValueError('Invalid explicit rights entitlement')
            if 'exercise' in r:
                e=dict(r['exercise']);r['exercise']=e
                if set(e)!={'at','listing_at','available_at','rights_quantity','shares_per_right','subscription_price','fee','insufficient_assets','source'}:raise ValueError('Rights exercise requires explicit quantity, subscription terms, dates and source')
                for field in ('at','listing_at','available_at'):
                    if isinstance(e[field],str):e[field]=datetime.fromisoformat(e[field])
                    if not isinstance(e[field],datetime) or e[field].tzinfo is None:raise ValueError('Exercise timestamps require timezone')
                if not r['deliver_at']<=e['at']<r['expires_at'] or e['listing_at']<e['at']:raise ValueError('Exercise must be within rights lifetime and before underlying listing')
                if type(e['rights_quantity']) is not int or e['rights_quantity']<0 or type(e['shares_per_right']) is not int or e['shares_per_right']<=0:raise ValueError('Exercise quantities require nonnegative rights and positive integer shares per right')
                if any(type(e[k]) not in (int,float) or not math.isfinite(e[k]) for k in ('subscription_price','fee')) or e['subscription_price']<=0 or e['fee']<0:raise ValueError('Invalid exercise price or fee')
                if Decimal(str(e['fee']))!=Decimal(str(e['fee'])).quantize(Decimal('.01')):raise ValueError('Exercise fee requires cent precision')
                if e['insufficient_assets'] not in ('skip','error'):raise ValueError('Exercise insufficient_assets requires skip/error')
                if not isinstance(e['source'],str) or not e['source'].strip():raise ValueError('Exercise requires provenance')
            ids.add(r['action_id']);instruments.add(r['rights_symbol']);self.records.append(r)
        self.records.sort(key=lambda r:(r['deliver_at'],r['action_id']))

    def pending(self,symbol):return sum(self.exercised[r['action_id']] for r in self.records if r['symbol']==symbol and r['action_id'] in self.exercised and r['action_id'] not in self.listed)

    def capture(self,at,symbols,quantity,pending):
        for r in self.records:
            if r['record_at']!=at or r['symbol'] not in symbols:continue
            if pending(r['symbol']) and 'entitlement_quantity' not in r:raise ValueError('Transferable rights overlapping pending shares require explicit entitlement_quantity')
            held=quantity(r['symbol']);basis=r.get('entitlement_quantity',held);n,remainder=divmod(basis*r['numerator'],r['denominator'])
            if remainder and r['fractional_policy']=='reject':raise ValueError('Fractional transferable right requires explicit floor allocation')
            self.basis[r['action_id']]={'held_shares':held,'entitlement_quantity':basis,'rights_quantity':n,'fractional_discarded':remainder/r['denominator']}

    def advance(self,at,end,first_bar,symbols,prices,cash,quantity,deliver,recover):
        delta=0.
        for r in self.records:
            key=r['action_id']
            if r['symbol'] not in symbols or r['record_at']<first_bar or at<r['deliver_at']:continue
            if key not in self.basis:raise ValueError('Missing transferable-right record close: '+key)
            base={'action_id':key,'symbol':r['symbol'],'rights_symbol':r['rights_symbol'],'at':at,'bar_end':end,'source':r['source'],'mode':self.mode}
            if key not in self.delivered:
                if at!=r['deliver_at']:raise ValueError('Missing exact rights delivery bar: '+key)
                if self.mode=='strict' and r['available_at']>at:raise ValueError('Rights delivery information unavailable: '+key)
                n=self.basis[key]['rights_quantity']
                if r['rights_symbol'] not in symbols or (n and r['rights_symbol'] not in prices):raise ValueError('Transferable rights require their own quoted delivery bar')
                deliver(r['rights_symbol'],n,at);self.delivered.add(key)
                self.ledger.append({**base,**self.basis[key],'kind':'tradable_rights_delivery','cash_delta':0.,'rights_position_delta':n,'position_delta':0,'pending_share_delta':0})
            e=r.get('exercise')
            if e and at>=e['at'] and key not in self.exercised:
                if at!=e['at']:raise ValueError('Missing exact exercise bar: '+key)
                if self.mode=='strict' and e['available_at']>at:raise ValueError('Exercise information unavailable: '+key)
                n=e['rights_quantity'];original_shares=n*e['shares_per_right'];shares=self.converted_shares.get(key,original_shares)
                cost=float((Decimal(original_shares)*Decimal(str(e['subscription_price']))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP));fee=e['fee'] if n else 0.
                status='exercised' if n else 'declined'
                if quantity(r['rights_symbol'])<n or cash+delta<cost+fee:
                    if e['insufficient_assets']=='error':raise ValueError('Insufficient rights or cash for exercise: '+key)
                    n=shares=0;cost=fee=0.;status='insufficient_assets'
                if shares and r['symbol'] not in prices:raise ValueError('Exercise requires underlying valuation bar')
                if recover(r['rights_symbol'],n,at)!=n:raise ValueError('Rights exercise recovery mismatch')
                self.exercised[key]=shares;delta-=cost+fee
                self.ledger.append({**base,'kind':'tradable_rights_exercise','source':e['source'],'rights_quantity':n,'shares':shares,'cost':cost,'fee':fee,'status':status,
                    'cash_delta':-(cost+fee),'rights_position_delta':-n,'position_delta':0,'pending_share_delta':shares})
            if e and at>=e['listing_at'] and key in self.exercised and key not in self.listed:
                if at!=e['listing_at']:raise ValueError('Missing exact exercised-share listing bar: '+key)
                n=self.exercised[key];deliver(r['symbol'],n,at);self.listed.add(key)
                self.ledger.append({**base,'kind':'tradable_rights_listing','source':e['source'],'shares':n,'cash_delta':0.,'rights_position_delta':0,'position_delta':n,'pending_share_delta':-n})
            if at>=r['expires_at'] and key not in self.expired:
                if at!=r['expires_at']:raise ValueError('Missing exact rights expiry bar: '+key)
                n=quantity(r['rights_symbol']);recover(r['rights_symbol'],n,at);self.expired.add(key)
                self.ledger.append({**base,'kind':'tradable_rights_expiry','cash_delta':0.,'rights_position_delta':-n,'position_delta':0,'pending_share_delta':0,'rights_quantity':n})
        return delta
