"""MarketSnapshot provider capabilities/readiness.

The live implementation is a low-cost public-web consensus adapter. It remains
separate from Strict PIT and from any future broker/exchange-grade market feed.
"""
from __future__ import annotations
from typing import Protocol

FRAMES=('AUCTION','R1','R2','R3')
FORMAT='niuniu-market-snapshot-provider-v1'

_MANUAL={'format':FORMAT,'provider_id':'manual-import-v1','provider':'manual-json-import',
    'implemented':True,'live_channel':False,'network':False,'frames':list(FRAMES),
    'full_snapshot':True,'source_hash_required':True,'credentials_required':False,
    'automatic_capture':False}
_PUBLIC_WEB={'format':FORMAT,'provider_id':'public-web-consensus-v1','provider':'Tencent + Eastmoney + Sina consensus',
    'implemented':True,'live_channel':True,'network':True,'frames':list(FRAMES),
    'full_snapshot':True,'source_hash_required':True,'credentials_required':False,
    'automatic_capture':True,'strict_pit_source_verified':False,
    'source_roles':{'tencent':'primary','eastmoney':'secondary','sina':'fallback_validation'},
    'scope':'Public webpage quotes for research/self-use; no exchange-feed SLA or Strict PIT certification.'}


class MarketSnapshotProvider(Protocol):
    def capabilities(self)->dict: ...
    def capture(self,trading_day:str,frame:str,symbols:list[str])->dict: ...


class MarketSnapshotProviderRegistry:
    def __init__(self,profiles=None,*,data_catalog_path=None,enforce_data_catalog=True):
        rows=profiles or [_MANUAL,_PUBLIC_WEB];self._profiles={row['provider_id']:dict(row) for row in rows}
        self.data_catalog_path=data_catalog_path;self.enforce_data_catalog=enforce_data_catalog
    def data_catalog_status(self):
        if not self.enforce_data_catalog:return 'BYPASSED_FOR_TEST'
        from quantlab.data.dataset_catalog import DataCatalogError,get_data_catalog_entry
        try:return get_data_catalog_entry(self.data_catalog_path,dataset_id='market_snapshot')['status']
        except (DataCatalogError,OSError):return 'NOT_READY'
    def list(self):
        status=self.data_catalog_status();rows=[]
        for key in sorted(self._profiles):
            row=dict(self._profiles[key])
            if row.get('live_channel'):row['data_catalog_status']=status
            rows.append(row)
        return rows
    def get(self,provider_id):
        row=dict(self._profiles[provider_id]) if provider_id in self._profiles else None
        if row is not None and row.get('live_channel'):row['data_catalog_status']=self.data_catalog_status()
        return row
    def live(self,frame=''):
        if self.enforce_data_catalog and self.data_catalog_status()!='READY':return []
        rows=[row for row in self.list() if row.get('implemented') and row.get('live_channel')]
        return [row for row in rows if not frame or frame in row.get('frames',[])]


class MarketSnapshotProviderReadiness:
    def __init__(self,registry=None):self.registry=registry or MarketSnapshotProviderRegistry()
    def build(self):
        profiles=self.registry.list();live={frame:self.registry.live(frame) for frame in FRAMES}
        missing=[frame for frame,rows in live.items() if not rows];catalog_status=self.registry.data_catalog_status()
        live_rows=[row for rows in live.values() for row in rows]
        return {'format':'niuniu-market-snapshot-provider-readiness-v1',
            'status':'BLOCKED' if missing else 'READY',
            'live_provider_available':not missing,'missing_live_frames':missing,
            'data_catalog_status':catalog_status,
            'profiles':profiles,'automatic_capture_available':any(row.get('automatic_capture') for row in live_rows),
            'write_model':False,'scope':'Provider capability/readiness only. DATA catalog must mark market_snapshot READY before any live public-web provider is usable.',
            'next_required_decision':('DATA must mark market_snapshot READY after interface review.' if catalog_status!='READY' else
                'Restore an implemented live provider adapter.' if missing else 'Future broker/exchange-grade feed may replace public-web consensus as primary.')}


def manual_import_capabilities():return dict(_MANUAL)


__all__=['FRAMES','FORMAT','MarketSnapshotProvider','MarketSnapshotProviderRegistry',
    'MarketSnapshotProviderReadiness','manual_import_capabilities']
