"""Point-in-time, explicitly supplied per-session execution rules. No inferred board history."""
from datetime import datetime
import math
from quantlab.storage.codec import digest


class MarketRules:
    def __init__(self,records):
        required={'symbol','effective_at','available_at','expires_at','suspended','st','limit_up','limit_down',
            'commission_bps','minimum_commission','sell_tax_bps','transfer_bps','source'}
        self.records=[]; seen=set()
        for raw in records:
            if set(raw)!=required:raise ValueError('Market rule fields must match the documented schema')
            r=dict(raw)
            for key in ('effective_at','available_at','expires_at'):
                if isinstance(r[key],str):r[key]=datetime.fromisoformat(r[key])
                if not isinstance(r[key],datetime) or r[key].tzinfo is None:raise ValueError('Rule times require timezone')
            if r['expires_at']<=r['effective_at']:raise ValueError('Invalid rule lifetime')
            if not isinstance(r['symbol'],str) or not r['symbol'] or not isinstance(r['source'],str) or not r['source'].strip():raise ValueError('Rule requires symbol and provenance')
            if any(type(r[k]) is not bool for k in ('suspended','st')):raise ValueError('ST and suspension must be explicit booleans')
            for k in ('commission_bps','minimum_commission','sell_tax_bps','transfer_bps'):
                if type(r[k]) not in (float,int) or not math.isfinite(r[k]) or r[k]<0:raise ValueError('Invalid rule fee')
            for k in ('limit_up','limit_down'):
                if r[k] is not None and (type(r[k]) not in (int,float) or not math.isfinite(r[k]) or r[k]<=0):raise ValueError('Invalid official price bound')
            if (r['limit_up'] is None)!=(r['limit_down'] is None):raise ValueError('Use two bounds or two nulls for explicitly unbounded session')
            if r['limit_up'] is not None and r['limit_up']<=r['limit_down']:raise ValueError('Inverted price bounds')
            key=(r['symbol'],r['effective_at'],r['available_at'])
            if key in seen:raise ValueError('Duplicate rule revision')
            seen.add(key); self.records.append(r)
        self.snapshot_id=digest(self.records)

    def at(self,symbol,at):
        candidates=[r for r in self.records if r['symbol']==symbol and r['effective_at']<=at and r['available_at']<=at]
        latest=max(candidates,key=lambda r:(r['effective_at'],r['available_at'])) if candidates else None
        # Expiration of a replacement does not resurrect an older rule.
        return latest if latest and at<latest['expires_at'] else None
