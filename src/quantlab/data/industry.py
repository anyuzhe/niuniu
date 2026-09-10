"""Explicit point-in-time industry membership; no current-snapshot backfill."""
from datetime import datetime


class IndustryHistory:
    def __init__(self,records):
        self.records=[];seen=set()
        for raw in records or []:
            if set(raw)!={'symbol','sector','effective_at','available_at','source'}:raise ValueError('Invalid industry fields')
            r=dict(raw)
            for key in ('effective_at','available_at'):
                if isinstance(r[key],str):r[key]=datetime.fromisoformat(r[key])
                if not isinstance(r[key],datetime) or r[key].tzinfo is None:raise ValueError('Industry time requires timezone')
            if any(not isinstance(r[k],str) or not r[k].strip() for k in ('symbol','sector','source')):raise ValueError('Industry membership requires provenance')
            key=(r['symbol'],r['effective_at'],r['available_at'])
            if key in seen:raise ValueError('Duplicate industry revision')
            seen.add(key);self.records.append(r)
    def at(self,symbol,at):
        rows=[r for r in self.records if r['symbol']==symbol and r['effective_at']<=at and r['available_at']<=at]
        return max(rows,key=lambda r:(r['effective_at'],r['available_at']))['sector'] if rows else None
