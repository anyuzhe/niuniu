"""Coverage at every requested session open, including sessions with no orders."""
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
from quantlab.storage.codec import digest


def audit_market_rules(rules,symbols,trading_dates):
    gaps=[];covered=0;late=0;unbounded=0;sources=set()
    for day in sorted(set(trading_dates)):
        opening=datetime.combine(day,time(9,30),ZoneInfo('Asia/Shanghai'))
        closing=opening.replace(hour=15)
        for symbol in sorted(set(symbols)):
            rule=rules.at(symbol,opening)
            if rule is None:
                reason='missing_rule'
                if any(r['symbol']==symbol and r['effective_at']<=opening<r['expires_at'] and r['available_at']>opening for r in rules.records):
                    reason='not_available_at_open';late+=1
                gaps.append({'symbol':symbol,'session':day,'reason':reason});continue
            # A rule expiring during the session cannot establish full-session coverage.
            if rule['expires_at']<=closing:
                gaps.append({'symbol':symbol,'session':day,'reason':'expires_before_session_end'});continue
            covered+=1;sources.add(rule['source']);unbounded+=rule['limit_up'] is None
    expected=len(set(symbols))*len(set(trading_dates))
    return {'status':'covered' if expected and not gaps else 'incomplete','expected_symbol_sessions':expected,
        'covered_symbol_sessions':covered,'late_available_sessions':late,'explicitly_unbounded_sessions':unbounded,
        'gaps':gaps,'rule_snapshot':rules.snapshot_id,'sources':sorted(sources),
        'scope':'Schema and supplied time coverage only. Does not certify that prices/status/provenance are official; missing rules are never inferred from a percentage.'}
