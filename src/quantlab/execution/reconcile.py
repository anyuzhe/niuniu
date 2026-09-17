"""Rebuild cash, positions and close valuation from the committed paper ledger."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
import math
from quantlab.execution.fees import effective_fee_bps
from quantlab.execution.paper import PaperAccount
from quantlab.storage.codec import digest
from quantlab.execution.holding_tax_audit import TaxReconstruction


def reconcile_account(path,tolerance=1e-6):
    state=PaperAccount(path).read();cash=state['identity']['config']['initial_cash'];positions={};marks={};daily={};errors=[];lots={}
    fills=sorted(state['fills'],key=lambda f:datetime.fromisoformat(f['bar_end']));index=0
    actions=state['summary'].get('corporate_action_ledger',[]);action_index=0;receivable=0.;pending={}
    overlap=[r for r in state['identity']['config'].get('corporate_actions') or [] if 'entitled_pending_actions' in r]
    pending_by_action={};expected_entitlements={};checked_overlap=0
    split_ledger=state['summary'].get('split_ledger',[]);split_index=0;checked_splits=0;seen_splits=set()
    split_receivable=0.;split_unpaid={};stock_quantities={};rights_converted={};rights_factors={};allocation_refunds={};cancel_refunds={}
    split_config={r['action_id']:r for r in state['identity']['config'].get('stock_splits') or []}
    rights_rules=sorted(state['identity']['config'].get('rights_issues') or [],key=lambda r:(datetime.fromisoformat(r['subscribe_at']),r['action_id']))
    rights_ledger=state['summary'].get('rights_ledger',[]);rights_index=0;rights_basis={};rights_paid={};rights_success={};prepaid=0.;checked_rights=0
    dividend_rules={r['action_id']:r for r in state['identity']['config'].get('corporate_actions') or []}
    traded_rules=sorted(state['identity']['config'].get('rights_trading') or [],key=lambda r:(datetime.fromisoformat(r['deliver_at']),r['action_id']))
    traded_basis={};traded_exercised={};traded_converted={};traded_index=0;traded_ledger=state['summary'].get('rights_trading_ledger',[])
    dividend_basis={};dividend_seen=set();tax_audit=TaxReconstruction(list(dividend_rules.values()))
    def cent(value):return float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    def fractional_amount(fraction,rule):
        gross=cent(fraction*Decimal(str(rule['price'])));tax=cent(Decimal(str(gross))*Decimal(str(rule['tax_rate'])));fee=rule['fee'] if fraction else 0.
        return {'fractional_gross':gross,'fractional_tax':tax,'fractional_fee':fee,'fractional_cash':cent(Decimal(str(gross))-Decimal(str(tax))-Decimal(str(fee)))}
    def check_dividend(action):
        key=action['action_id'];kind=action['kind'];rule=dividend_rules.get(key);basis=dividend_basis.get(key)
        if rule is None or basis is None or (key,kind) in dividend_seen:
            errors.append({'reason':'unknown_duplicate_or_missing_dividend_basis','action_id':key});return
        dividend_seen.add((key,kind));n=basis
        gross=cent(n*rule['cash_per_share']);tax=cent(gross*rule['tax_rate']);net=gross-tax
        expected={'quantity':n,'gross':gross,'tax':tax,'symbol':rule['symbol'],'source':rule['source']}
        shares=0
        if 'entitlement_quantity' in rule:expected['explicit_entitlement_quantity']=n
        if 'stock_per_share' in rule:
            exact=Decimal(n)*Decimal(str(rule['stock_per_share']));shares=int(exact)
            expected.update(shares=shares,fractional_discarded=float(exact-shares),fractional_policy=rule['fractional_policy'])
            if 'fractional_settlement' in rule:
                settlement=fractional_amount(exact-shares,rule['fractional_settlement']);expected.update(settlement)
                if 'pay_at' not in rule['fractional_settlement']:net=cent(net+settlement['fractional_cash'])
            shares=stock_quantities.get(key,shares);expected['shares']=shares
        expected['net']=net
        changes={'dividend_accrual':(0.,net,0,0),'dividend_payment':(net,-net,0,0),'stock_accrual':(0.,0.,shares,0),'stock_listing':(0.,0.,-shares,shares),'fractional_accrual':(0.,expected.get('fractional_cash',0.),0,0),'fractional_payment':(expected.get('fractional_cash',0.),-expected.get('fractional_cash',0.),0,0)}
        if kind not in changes:errors.append({'reason':'unknown_dividend_kind','action_id':key});return
        cash_delta,receivable_delta,pending_delta,position_delta=changes[kind]
        expected.update(cash_delta=cash_delta,receivable_delta=receivable_delta)
        if kind.startswith('stock_'):expected.update(pending_share_delta=pending_delta,position_delta=position_delta)
        if any(action.get(k)!=v for k,v in expected.items()):errors.append({'reason':'dividend_ledger_mismatch','action_id':key,'kind':kind})
    bars={}
    for row in state['bars']:bars.setdefault(datetime.fromisoformat(row['datetime']),[]).append(row)
    account_symbols={r['symbol'] for r in state['bars']};first_bar=min(bars)
    def apply_splits(at,through):
        nonlocal split_index,checked_splits,cash,split_receivable,prepaid
        while split_index<len(split_ledger) and datetime.fromisoformat(split_ledger[split_index]['bar_end'])<=at and datetime.fromisoformat(split_ledger[split_index]['at'])<=through:
            entry=split_ledger[split_index];split_index+=1;key=entry['action_id'];rule=split_config.get(key)
            if entry.get('kind')=='split_cash_payment':
                amount=split_unpaid.pop(key,None)
                if amount is None or rule is None:
                    errors.append({'reason':'unknown_or_duplicate_split_payment','action_id':key});continue
                expected={'cash_delta':amount,'receivable_delta':-amount,'source':rule['source'],'symbol':rule['symbol']}
                if any(entry.get(k)!=v for k,v in expected.items()) or datetime.fromisoformat(entry['at'])<datetime.fromisoformat(rule['fractional_settlement']['pay_at']):errors.append({'reason':'split_payment_mismatch','action_id':key})
                cash+=amount;split_receivable-=amount;continue
            if rule is None or key in seen_splits:
                errors.append({'reason':'unknown_or_duplicate_split','action_id':key});continue
            seen_splits.add(key);checked_splits+=1;symbol=rule['symbol'];before=positions.get(symbol,0)
            converted=[];fraction=Decimal(0);invalid_fraction=False
            for acquired,quantity in lots.get(symbol,[]):
                whole,remainder=divmod(quantity*rule['numerator'],rule['denominator'])
                invalid_fraction=invalid_fraction or bool(remainder and rule['fractional_policy']=='reject')
                fraction+=Decimal(remainder)/Decimal(rule['denominator']);converted.append([acquired,whole])
            tax_audit.conversion(symbol,lots.get(symbol,[]),converted,rule['numerator'],rule['denominator'],datetime.fromisoformat(entry['at']),at)
            after=sum(q for _,q in converted);lots[symbol]=converted
            settlement=fractional_amount(fraction,rule['fractional_settlement']) if 'fractional_settlement' in rule else {}
            amount=settlement.get('fractional_cash',0.)
            if settlement and (entry.get('fractional_discarded')!=float(fraction) or any(entry.get(k)!=v for k,v in settlement.items())):errors.append({'reason':'split_fractional_settlement_mismatch','action_id':key})
            if 'pay_at' in rule.get('fractional_settlement',{}):
                split_unpaid[key]=amount;split_receivable+=amount
                amount=0.
            cash+=amount
            expected_conversions=[]
            for target in rule.get('convert_entitlements',[]):
                dividend=dividend_rules.get(target);right=next((r for r in rights_rules if r['action_id']==target),None)
                if dividend is not None and target in dividend_basis:
                    before_shares=stock_quantities.get(target,int(Decimal(dividend_basis[target])*Decimal(str(dividend['stock_per_share']))))
                    after_shares,remainder=divmod(before_shares*rule['numerator'],rule['denominator'])
                    if target in rule.get('entitlement_allocations',{}):after_shares=rule['entitlement_allocations'][target]['shares']
                    stock_quantities[target]=after_shares
                    delta=after_shares-before_shares if target in pending_by_action else 0
                    if target in pending_by_action:pending_by_action[target]+=delta
                    kind='distribution'
                elif right is not None and target in rights_basis:
                    if right.get('cancellation') and datetime.fromisoformat(right['cancellation']['cancel_at'])<datetime.fromisoformat(rule['effective_at']):continue
                    before_shares=rights_paid[target][0] if target in rights_paid else rights_converted.get(target,right['subscription_shares'])
                    after_shares,remainder=divmod(before_shares*rule['numerator'],rule['denominator'])
                    if target in rule.get('entitlement_allocations',{}):after_shares=rule['entitlement_allocations'][target]['shares']
                    rights_factors[target]=rights_factors.get(target,Fraction(1))*Fraction(rule['numerator'],rule['denominator'])
                    if target in rights_paid:rights_paid[target]=(after_shares,rights_paid[target][1])
                    else:rights_converted[target]=after_shares
                    delta=after_shares-before_shares if datetime.fromisoformat(right['ex_at'])<datetime.fromisoformat(rule['effective_at']) else 0
                    kind='rights'
                else:
                    traded=next((r for r in traded_rules if r['action_id']==target),None)
                    if traded is None or target not in traded_basis:continue
                    before_shares=traded_exercised.get(target,traded_converted.get(target,traded['exercise']['rights_quantity']*traded['exercise']['shares_per_right']))
                    after_shares,remainder=divmod(before_shares*rule['numerator'],rule['denominator'])
                    if target in rule.get('entitlement_allocations',{}):after_shares=rule['entitlement_allocations'][target]['shares']
                    delta=after_shares-before_shares if target in traded_exercised else 0
                    if target in traded_exercised:traded_exercised[target]=after_shares
                    else:traded_converted[target]=after_shares
                    kind='tradable_rights'
                extra={};allocation=rule.get('entitlement_allocations',{}).get(target)
                if allocation is not None:
                    reduction=allocation['principal_reduction'];prepaid_delta=0.
                    if kind=='rights':
                        if target in rights_paid:rights_paid[target]=(rights_paid[target][0],rights_paid[target][1]-reduction)
                        if datetime.fromisoformat(right['ex_at'])>=datetime.fromisoformat(rule['effective_at']):prepaid_delta=-reduction
                    extra={**allocation,'prepaid_delta':prepaid_delta};prepaid+=prepaid_delta
                elif remainder:errors.append({'reason':'fractional_pending_conversion','action_id':key})
                pending[symbol]=pending.get(symbol,0)+delta
                expected_conversions.append({'action_id':target,'kind':kind,'before_quantity':before_shares,'after_quantity':after_shares,'pending_share_delta':delta,**extra})
            extra_cash=math.fsum(c.get('cash',0.) for c in expected_conversions)
            if 'pay_at' in rule.get('fractional_settlement',{}):
                split_unpaid[key]+=extra_cash;split_receivable+=extra_cash
                if entry.get('receivable_delta')!=split_unpaid[key]:errors.append({'reason':'split_receivable_mismatch','action_id':key})
            else:amount+=extra_cash;cash+=extra_cash
            if 'entitlement_allocations' in rule and entry.get('prepaid_delta')!=math.fsum(c.get('prepaid_delta',0.) for c in expected_conversions):errors.append({'reason':'split_prepaid_mismatch','action_id':key})
            if 'convert_entitlements' in rule and sorted(entry.get('entitlement_conversions',[]),key=lambda v:(v['kind'],v['action_id']))!=sorted(expected_conversions,key=lambda v:(v['kind'],v['action_id'])):errors.append({'reason':'pending_conversion_mismatch','action_id':key})
            if (invalid_fraction or entry['symbol']!=symbol or entry['before_quantity']!=before or entry['after_quantity']!=after
                or entry['position_delta']!=after-before or entry['cash_delta']!=amount
                or datetime.fromisoformat(entry['at'])!=datetime.fromisoformat(rule['effective_at'])
                or any(entry.get(k)!=rule[k] for k in ('numerator','denominator','fractional_policy','source'))):
                errors.append({'reason':'split_conversion_mismatch','action_id':key})
            positions[symbol]=after
    for nav in state['nav']:
        at=datetime.fromisoformat(nav['datetime'])
        opening=at.replace(hour=9,minute=30,second=0,microsecond=0) if bars[at][0]['timeframe']=='1d' else at-timedelta(minutes=int(bars[at][0]['timeframe'][:-1]))
        apply_splits(at,opening)
        for key,rule in split_config.items():
            group=bars.get(at,[])
            if not group or rule['symbol'] not in account_symbols:continue
            tf=group[0]['timeframe']
            opening=at.replace(hour=9,minute=30,second=0,microsecond=0) if tf=='1d' else at-timedelta(minutes=int(tf[:-1]))
            if datetime.fromisoformat(rule['effective_at'])==opening and key not in seen_splits:
                errors.append({'reason':'missing_split_entry','action_id':key})
        group=bars.get(at,[])
        opening=(at.replace(hour=9,minute=30,second=0,microsecond=0) if group[0]['timeframe']=='1d' else at-timedelta(minutes=int(group[0]['timeframe'][:-1]))) if group else None
        while action_index<len(actions) and datetime.fromisoformat(actions[action_index]['bar_end'])<=at and datetime.fromisoformat(actions[action_index]['at'])<=opening:
            action=actions[action_index];check_dividend(action);cash+=action['cash_delta'];receivable+=action['receivable_delta'];action_index+=1
            symbol=action['symbol'];positions[symbol]=positions.get(symbol,0)+action.get('position_delta',0)
            if action.get('position_delta',0):lots.setdefault(symbol,[]).append([datetime.fromisoformat(action['at']).date()-timedelta(days=1),action['position_delta']])
            pending[symbol]=pending.get(symbol,0)+action.get('pending_share_delta',0)
            key=action['action_id'];pending_by_action[key]=pending_by_action.get(key,0)+action.get('pending_share_delta',0)
            if action['kind']=='dividend_accrual' and any(r['action_id']==key for r in overlap):
                checked_overlap+=1
                expected=expected_entitlements.get(key)
                if expected is None or action['quantity']!=expected['quantity'] or action.get('entitlement_basis')!=expected['basis']:
                    errors.append({'reason':'overlap_entitlement_mismatch','action_id':key,'expected':expected})
        for rule in rights_rules:
            key=rule['action_id'];symbol=rule['symbol']
            if symbol not in account_symbols or datetime.fromisoformat(rule['record_at'])<first_bar:continue
            cancellation=rule.get('cancellation')
            events=[(rule['subscribe_at'],'rights_subscription')]
            allocation=rule.get('allocation')
            if allocation:events.extend([(allocation['at'],'rights_allocation'),(allocation['refund_at'],'rights_allocation_refund')])
            for field,kind in (('ex_at','rights_ex'),('list_at','rights_listing')):
                if not cancellation or datetime.fromisoformat(rule[field])<datetime.fromisoformat(cancellation['cancel_at']):events.append((rule[field],kind))
            if cancellation:
                events.extend([(cancellation['cancel_at'],'rights_cancellation'),(cancellation['refund_at'],'rights_refund')])
                if cancel_refunds.get(key,0.)<0 and datetime.fromisoformat(cancellation['refund_at'])<opening:events.append((opening.isoformat(),'rights_refund'))
            for event_at,kind in events:
                if datetime.fromisoformat(event_at)!=opening:continue
                basis=rights_basis.get(key)
                if basis is None:
                    errors.append({'reason':'missing_rights_entitlement','action_id':key});continue
                expected={'kind':kind,'action_id':key,'symbol':symbol,'at':opening.isoformat(),'bar_end':at.isoformat(),
                    'held_shares':basis[0],'entitled_shares':basis[1],'source':rule['source'],'mode':state['identity']['config'].get('corporate_action_mode','strict'),'cash_delta':0.,'prepaid_delta':0.,'pending_share_delta':0,'position_delta':0}
                if 'entitlement_quantity' in rule:expected['explicit_entitlement_quantity']=rule['entitlement_quantity']
                if rule['fractional_policy']=='floor':expected.update(fractional_discarded=(rule.get('entitlement_quantity',basis[0])*rule['numerator']%rule['denominator'])/rule['denominator'],fractional_policy='floor')
                if kind=='rights_subscription':
                    shares=rights_converted.get(key,rule['subscription_shares']);cost=float((Decimal(rule['subscription_shares'])*Decimal(str(rule['subscription_price']))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                    status='subscribed' if shares else 'declined';fee=rule.get('subscription_fee',0.) if shares else 0.
                    if rule['subscription_shares']>basis[1] and not rule.get('allow_oversubscription',False):errors.append({'reason':'rights_exceeds_entitlement','action_id':key})
                    if cost+fee>cash:
                        if rule['insufficient_cash']=='error':errors.append({'reason':'rights_insufficient_cash','action_id':key})
                        shares=0;cost=0.;fee=0.;status='insufficient_cash'
                    rights_paid[key]=(shares,cost);rights_success[key]=status=='subscribed';expected.update(shares=shares,cost=cost,status=status,cash_delta=-(cost+fee),prepaid_delta=cost)
                    if 'subscription_fee' in rule:expected['fee']=fee
                else:
                    shares,cost=rights_paid.get(key,(0,0.));expected['shares']=shares
                    if kind=='rights_allocation':
                        subscribed=rights_success.get(key,False);allocated=allocation['shares'] if subscribed else 0
                        exact=Fraction(allocated)*rights_factors.get(key,Fraction(1));shares=int(exact)
                        if exact.denominator!=1:errors.append({'reason':'fractional_rights_allocation','action_id':key})
                        original_cost=cent(Decimal(rule['subscription_shares'])*Decimal(str(rule['subscription_price']))) if subscribed else 0.
                        reduction=Decimal(str(original_cost))-Decimal(str(cost))
                        new_cost=cent(Decimal(allocated)*Decimal(str(rule['subscription_price']))-(reduction*Decimal(allocated)/Decimal(rule['subscription_shares']) if rule['subscription_shares'] else 0));fee_refund=allocation['fee_refund'] if subscribed else 0.
                        refund=cost-new_cost+fee_refund;rights_paid[key]=(shares,new_cost);allocation_refunds[key]=refund
                        expected.update(source=allocation['source'],shares=shares,cost=new_cost,refund_amount=refund,fee_refund=fee_refund,prepaid_delta=fee_refund)
                    elif kind=='rights_allocation_refund':
                        refund=allocation_refunds.pop(key,0.);expected.update(source=allocation['source'],cash_delta=refund,prepaid_delta=-refund)
                    elif kind=='rights_ex':expected.update(prepaid_delta=-cost,pending_share_delta=shares)
                    elif kind=='rights_listing':expected.update(pending_share_delta=-shares,position_delta=shares)
                    else:
                        fee_refund=cancellation['fee_refund'] if rights_success.get(key,False) else 0.
                        expected['source']=cancellation['source']
                        if kind=='rights_cancellation':
                            exercised=datetime.fromisoformat(rule['ex_at'])<opening;listed=datetime.fromisoformat(rule['list_at'])<opening
                            recovered=0;replacement=0.
                            if 'recovery' in cancellation:
                                requested=cancellation['recovery']['shares'] if rights_success.get(key,False) else 0
                                recovered=min(requested,positions.get(symbol,0));replacement=cent(Decimal(requested-recovered)*Decimal(str(cancellation['recovery']['missing_share_price'])))
                                expected.update(recovery_shares=recovered,replacement_cash=replacement,position_delta=-recovered)
                            amount=cost+fee_refund-replacement;cancel_refunds[key]=amount
                            expected.update(prepaid_delta=amount if exercised else fee_refund-replacement,pending_share_delta=-shares if exercised and not listed else 0,fee_refund=fee_refund)
                        else:
                            amount=cancel_refunds.get(key,0.)
                            if amount<0:amount=max(amount,-max(0.,cash))
                            cancel_refunds[key]=cancel_refunds.get(key,0.)-amount
                            expected.update(cash_delta=amount,prepaid_delta=-amount)
                entry=rights_ledger[rights_index] if rights_index<len(rights_ledger) else {}
                if any(entry.get(k)!=v for k,v in expected.items()):errors.append({'reason':'rights_ledger_mismatch','action_id':key,'kind':kind})
                rights_index+=1;checked_rights+=1
                cash+=expected['cash_delta'];prepaid+=expected['prepaid_delta']
                if expected['position_delta']>0:lots.setdefault(symbol,[]).append([opening.date()-timedelta(days=1),expected['position_delta']])
                elif expected['position_delta']<0:
                    remaining=-expected['position_delta'];disposed=[]
                    for lot in lots.get(symbol,[]):
                        used=min(lot[1],remaining);lot[1]-=used;remaining-=used
                        if used:disposed.append((lot[0],used))
                    tax_audit.disposal(symbol,disposed,opening,at,'recovery')
                pending[symbol]=pending.get(symbol,0)+expected['pending_share_delta'];positions[symbol]=positions.get(symbol,0)+expected['position_delta']
        for rule in traded_rules:
            key=rule['action_id'];symbol=rule['symbol'];instrument=rule['rights_symbol']
            if symbol not in account_symbols or datetime.fromisoformat(rule['record_at'])<first_bar:continue
            events=[(rule['deliver_at'],'tradable_rights_delivery')];exercise=rule.get('exercise')
            if exercise:events.extend([(exercise['at'],'tradable_rights_exercise'),(exercise['listing_at'],'tradable_rights_listing')])
            events.append((rule['expires_at'],'tradable_rights_expiry'))
            for event_at,kind in events:
                if datetime.fromisoformat(event_at)!=opening:continue
                expected={'action_id':key,'symbol':symbol,'rights_symbol':instrument,'at':opening.isoformat(),'bar_end':at.isoformat(),'source':rule['source'],
                    'mode':state['identity']['config'].get('corporate_action_mode','strict'),'kind':kind,'cash_delta':0.,'rights_position_delta':0,'position_delta':0,'pending_share_delta':0}
                if kind=='tradable_rights_delivery':
                    basis=traded_basis.get(key,{})
                    if not basis:errors.append({'reason':'missing_tradable_rights_basis','action_id':key})
                    expected.update(basis);expected['rights_position_delta']=basis.get('rights_quantity',0)
                elif kind=='tradable_rights_exercise':
                    n=exercise['rights_quantity'];original=n*exercise['shares_per_right'];shares=traded_converted.get(key,original)
                    cost=cent(Decimal(original)*Decimal(str(exercise['subscription_price'])));fee=exercise['fee'] if n else 0.;status='exercised' if n else 'declined'
                    if positions.get(instrument,0)<n or cash<cost+fee:
                        if exercise['insufficient_assets']=='error':errors.append({'reason':'insufficient_exercise_assets','action_id':key})
                        n=shares=0;cost=fee=0.;status='insufficient_assets'
                    traded_exercised[key]=shares
                    expected.update(source=exercise['source'],rights_quantity=n,shares=shares,cost=cost,fee=fee,status=status,cash_delta=-(cost+fee),rights_position_delta=-n,pending_share_delta=shares)
                elif kind=='tradable_rights_listing':
                    n=traded_exercised.get(key,0);expected.update(source=exercise['source'],shares=n,position_delta=n,pending_share_delta=-n)
                else:
                    n=positions.get(instrument,0);expected.update(rights_quantity=n,rights_position_delta=-n)
                entry=traded_ledger[traded_index] if traded_index<len(traded_ledger) else {};traded_index+=1
                if entry!=expected:errors.append({'reason':'tradable_rights_ledger_mismatch','action_id':key,'kind':kind})
                n=expected['rights_position_delta']
                if n>0:lots.setdefault(instrument,[]).append([opening.date()-timedelta(days=1),n])
                elif n<0:
                    remaining=-n;disposed=[]
                    for lot in lots.get(instrument,[]):
                        used=min(lot[1],remaining);lot[1]-=used;remaining-=used
                        if used:disposed.append((lot[0],used))
                    tax_audit.disposal(instrument,disposed,opening,at,'recovery')
                positions[instrument]=positions.get(instrument,0)+n
                if expected['position_delta']:lots.setdefault(symbol,[]).append([opening.date()-timedelta(days=1),expected['position_delta']])
                positions[symbol]=positions.get(symbol,0)+expected['position_delta'];pending[symbol]=pending.get(symbol,0)+expected['pending_share_delta'];cash+=expected['cash_delta']
        cash+=tax_audit.collect(opening,at,cash,'opening')
        while index<len(fills) and datetime.fromisoformat(fills[index]['bar_end'])<=at:
            f=fills[index]
            if any(r['rights_symbol']==f['symbol'] and not datetime.fromisoformat(r['deliver_at'])<=datetime.fromisoformat(f['filled_at'])<datetime.fromisoformat(r['expires_at']) for r in traded_rules):errors.append({'reason':'right_traded_outside_lifetime','symbol':f['symbol']})
            sign=1 if f['side']=='buy' else -1
            positions[f['symbol']]=positions.get(f['symbol'],0)+sign*f['quantity']
            held_lots=lots.setdefault(f['symbol'],[]);fill_day=datetime.fromisoformat(f['filled_at']).date()
            if sign==1:held_lots.append([fill_day,f['quantity']])
            else:
                remaining=f['quantity'];disposed=[]
                for lot in held_lots:
                    if state['identity']['config'].get('t_plus_one',True) and lot[0]>=fill_day:continue
                    used=min(lot[1],remaining);lot[1]-=used;remaining-=used
                    if used:disposed.append((lot[0],used))
                if remaining:errors.append({'reason':'sell_exceeds_settled_lots','symbol':f['symbol']})
            filled_at=datetime.fromisoformat(f['filled_at'])
            candidates=[r for r in state['rules'] if r['symbol']==f['symbol'] and datetime.fromisoformat(r['effective_at'])<=filled_at<datetime.fromisoformat(r['expires_at']) and datetime.fromisoformat(r['available_at'])<=filled_at]
            rule=max(candidates,key=lambda r:(datetime.fromisoformat(r['effective_at']),datetime.fromisoformat(r['available_at']))) if candidates else None
            if rule is None:errors.append({'reason':'missing_fill_fee_rule','symbol':f['symbol'],'at':f['filled_at']})
            terms=rule or state['identity']['config'];notional=f['quantity']*f['price'];precision=state['identity']['config'].get('fee_decimals')
            tax_bps,transfer_bps=effective_fee_bps(terms,filled_at,state['identity']['config'].get('statutory_fees',False))
            expected_fees={'commission':max(terms['minimum_commission'],notional*terms['commission_bps']/10000),
                'tax':notional*tax_bps/10000 if sign<0 else 0.,'transfer_fee':notional*transfer_bps/10000}
            if precision is not None:expected_fees={k:float(Decimal(str(v)).quantize(Decimal(1).scaleb(-precision),rounding=ROUND_HALF_UP)) for k,v in expected_fees.items()}
            if any(abs(f.get(k,0.)-v)>tolerance for k,v in expected_fees.items()) or (rule is not None and f.get('rule_snapshot')!=digest(rule)):
                errors.append({'reason':'fill_fee_mismatch','symbol':f['symbol'],'at':f['filled_at'],'expected':expected_fees})
            cash-=sign*notional+sum(expected_fees.values())
            if sign<0:
                tax_audit.disposal(f['symbol'],disposed,filled_at,at)
                cash+=tax_audit.collect(filled_at,at,cash,'sale')
            index+=1
        apply_splits(at,at)
        while action_index<len(actions) and datetime.fromisoformat(actions[action_index]['bar_end'])<=at:
            action=actions[action_index];check_dividend(action);cash+=action['cash_delta'];receivable+=action['receivable_delta'];action_index+=1
            symbol=action['symbol'];positions[symbol]=positions.get(symbol,0)+action.get('position_delta',0)
            if action.get('position_delta',0):lots.setdefault(symbol,[]).append([datetime.fromisoformat(action['at']).date()-timedelta(days=1),action['position_delta']])
            pending[symbol]=pending.get(symbol,0)+action.get('pending_share_delta',0)
            key=action['action_id'];pending_by_action[key]=pending_by_action.get(key,0)+action.get('pending_share_delta',0)
            if action['kind']=='dividend_accrual' and any(r['action_id']==key for r in overlap):
                checked_overlap+=1
                expected=expected_entitlements.get(key)
                if expected is None or action['quantity']!=expected['quantity'] or action.get('entitlement_basis')!=expected['basis']:
                    errors.append({'reason':'overlap_entitlement_mismatch','action_id':key,'expected':expected})
        cash+=tax_audit.collect(at,at,cash,'close')
        for rule in rights_rules:
            if datetime.fromisoformat(rule['record_at'])==at and rule['symbol'] in account_symbols:
                held=positions.get(rule['symbol'],0);entitled,remainder=divmod(rule.get('entitlement_quantity',held)*rule['numerator'],rule['denominator'])
                if remainder and rule['fractional_policy']=='reject':errors.append({'reason':'fractional_rights_entitlement','action_id':rule['action_id']})
                rights_basis[rule['action_id']]=(held,entitled)
        for r in dividend_rules.values():
            if datetime.fromisoformat(r['record_at'])==at and r['symbol'] in account_symbols:
                dividend_basis[r['action_id']]=r.get('entitlement_quantity',positions.get(r['symbol'],0)+sum(pending_by_action.get(k,0) for k in r.get('entitled_pending_actions',[])))
        for rule in traded_rules:
            if datetime.fromisoformat(rule['record_at'])==at and rule['symbol'] in account_symbols:
                held=positions.get(rule['symbol'],0);basis=rule.get('entitlement_quantity',held);n,remainder=divmod(basis*rule['numerator'],rule['denominator'])
                traded_basis[rule['action_id']]={'held_shares':held,'entitlement_quantity':basis,'rights_quantity':n,'fractional_discarded':remainder/rule['denominator']}
        tax_audit.capture(at,lots,dividend_basis)
        for r in overlap:
            if datetime.fromisoformat(r['record_at'])==at:
                sources={a['action_id']:pending_by_action.get(a['action_id'],0)
                    for a in state['identity']['config']['corporate_actions']
                    if a['symbol']==r['symbol'] and 'stock_per_share' in a
                    and datetime.fromisoformat(a['ex_at'])<=at<datetime.fromisoformat(a['list_at'])
                    and a['action_id'] in pending_by_action}
                held=positions.get(r['symbol'],0);included=sum(sources.get(key,0) for key in r['entitled_pending_actions'])
                expected_entitlements[r['action_id']]={'quantity':r.get('entitlement_quantity',held+included),'basis':{
                    'held_shares':held,'included_pending_shares':included,'pending_sources':sources,
                    'entitled_pending_actions':r['entitled_pending_actions'],
                    'policy':'explicit pending action ids; unlisted sources not named are excluded'}}
        for row in bars.get(at,[]):marks[row['symbol']]=row['close']
        pending_value=sum(q*marks.get(s,0) for s,q in pending.items())
        value=sum(q*marks.get(s,0) for s,q in positions.items())+pending_value;equity=cash+value+receivable+prepaid+split_receivable-tax_audit.payable
        differences={'cash':cash-nav['cash'],'position_value':value-nav['position_value'],'equity':equity-nav['equity']}
        if 'pending_stock_value' in nav:differences['pending_stock_value']=pending_value-nav['pending_stock_value']
        if 'dividend_tax_payable' in nav:differences['dividend_tax_payable']=tax_audit.payable-nav['dividend_tax_payable']
        if 'split_receivable' in nav:differences['split_receivable']=split_receivable-nav['split_receivable']
        if 'subscription_receivable' in nav:differences['subscription_receivable']=prepaid-nav['subscription_receivable']
        if 'dividend_receivable' in nav:differences['dividend_receivable']=receivable-nav['dividend_receivable']
        if any(abs(v)>tolerance for v in differences.values()):errors.append({'at':at,'differences':differences})
        daily[at.date()]={'date':at.date(),'cash':cash,'equity':equity,'positions':{s:q for s,q in positions.items() if q},'dividend_receivable':receivable,'subscription_receivable':prepaid,'pending_stock_positions':{s:q for s,q in pending.items() if q}}
    if state['nav']:
        last_at=datetime.fromisoformat(state['nav'][-1]['datetime'])
        for key,rule in dividend_rules.items():
            if rule['symbol'] not in account_symbols or datetime.fromisoformat(rule['record_at'])<first_bar:continue
            phases=[('ex_at','dividend_accrual'),('pay_at','dividend_payment')]
            if 'pay_at' in rule.get('fractional_settlement',{}):
                if datetime.fromisoformat(rule['ex_at'])<=last_at and (key,'fractional_accrual') not in dividend_seen:errors.append({'reason':'missing_fractional_accrual','action_id':key})
                if datetime.fromisoformat(rule['fractional_settlement']['pay_at'])<=last_at and (key,'fractional_payment') not in dividend_seen:errors.append({'reason':'missing_fractional_payment','action_id':key})
            if 'stock_per_share' in rule:phases.extend([('ex_at','stock_accrual'),('list_at','stock_listing')])
            for field,kind in phases:
                if datetime.fromisoformat(rule[field])<=last_at and (key,kind) not in dividend_seen:errors.append({'reason':'missing_dividend_entry','action_id':key,'kind':kind})
    if traded_index!=len(traded_ledger):errors.append({'reason':'unmatched_tradable_rights_ledger'})
    if tax_audit.events!=state['summary'].get('dividend_tax_ledger',[]) or abs(tax_audit.payable-state['summary'].get('dividend_tax_payable',0.))>tolerance:errors.append({'reason':'dividend_tax_reconstruction_mismatch'})
    if abs(split_receivable-state['summary'].get('split_receivable',0.))>tolerance:errors.append({'reason':'unmatched_split_receivable'})
    final={s:q for s,q in positions.items() if q}
    if index!=len(fills) or action_index!=len(actions) or split_index!=len(split_ledger) or final!=state['summary']['ending_positions']:errors.append({'reason':'unmatched_fills_or_ending_positions'})
    if {s:q for s,q in pending.items() if q}!=state['summary'].get('pending_stock_positions',{}):errors.append({'reason':'unmatched_pending_stock_positions'})
    if rights_index!=len(rights_ledger) or abs(prepaid-state['summary'].get('subscription_receivable',0.))>tolerance:errors.append({'reason':'unmatched_rights_ledger_or_prepaid'})
    return {'status':'matched' if not errors else 'different','account_revision':state['revision'],'days':list(daily.values()),
        'checked_tradable_rights_entries':traded_index,'checked_tax_entries':len(tax_audit.events),'checked_fee_entries':index,'checked_rights_entries':checked_rights,'checked_stock_splits':checked_splits,'checked_corporate_actions':action_index,'checked_overlap_entitlements':checked_overlap,'checked_nav_points':len(state['nav']),'checked_fills':index,'errors':errors,'tolerance':tolerance,
        'scope':'Internal committed ledger reconciliation; overlapping quantities checked against record-close holdings and explicitly named pending distributions. No broker statement or official entitlement-source certification.'}
