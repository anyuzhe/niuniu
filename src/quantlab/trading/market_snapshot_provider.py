"""P8.7 extension: explicit MarketSnapshot provider capabilities/readiness.

No network provider is shipped here. Manual imports remain offline evidence and
must never be presented as an implemented live provider.
"""
from __future__ import annotations
from typing import Protocol

FRAMES=('AUCTION','R1','R2','R3')
FORMAT='niuniu-market-snapshot-provider-v1'

_MANUAL={'format':FORMAT,'provider_id':'manual-import-v1','provider':'manual-json-import',
    'implemented':True,'live_channel':False,'network':False,'frames':list(FRAMES),
    'full_snapshot':True,'source_hash_required':True,'credentials_required':False,
    'automatic_capture':False}


class MarketSnapshotProvider(Protocol):
    def capabilities(self)->dict: ...
    def capture(self,trading_day:str,frame:str,symbols:list[str])->dict: ...


class MarketSnapshotProviderRegistry:
    def __init__(self,profiles=None):
        rows=profiles or [_MANUAL];self._profiles={row['provider_id']:dict(row) for row in rows}
    def list(self):return [dict(self._profiles[key]) for key in sorted(self._profiles)]
    def get(self,provider_id):return dict(self._profiles[provider_id]) if provider_id in self._profiles else None
    def live(self,frame=''):
        rows=[row for row in self.list() if row.get('implemented') and row.get('live_channel')]
        return [row for row in rows if not frame or frame in row.get('frames',[])]


class MarketSnapshotProviderReadiness:
    def __init__(self,registry=None):self.registry=registry or MarketSnapshotProviderRegistry()
    def build(self):
        profiles=self.registry.list();live={frame:self.registry.live(frame) for frame in FRAMES}
        missing=[frame for frame,rows in live.items() if not rows]
        return {'format':'niuniu-market-snapshot-provider-readiness-v1',
            'status':'BLOCKED' if missing else 'READY',
            'live_provider_available':not missing,'missing_live_frames':missing,
            'profiles':profiles,'automatic_capture_available':any(row.get('automatic_capture') for row in profiles if row.get('live_channel')),
            'write_model':False,'scope':'Provider capability/readiness only; no network capture or credentials are added by this service.',
            'next_required_decision':'Choose and implement an audited live provider adapter.' if missing else ''}


def manual_import_capabilities():return dict(_MANUAL)


__all__=['FRAMES','FORMAT','MarketSnapshotProvider','MarketSnapshotProviderRegistry',
    'MarketSnapshotProviderReadiness','manual_import_capabilities']
