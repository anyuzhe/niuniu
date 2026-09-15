"""Historical membership: retrospective listing dates OR timestamped PIT decisions."""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from quantlab.data.base import ExplicitUniverse
from quantlab.storage.codec import digest


@dataclass(frozen=True)
class UniverseConfig:
    mode: str = 'explicit'
    min_listed_days: int = 0
    reference_manifest: str | None = None

    def __post_init__(self):
        if self.mode not in {'explicit','listing','pit'}:
            raise ValueError('universe mode must be explicit, listing or pit')
        if type(self.min_listed_days) is not int or self.min_listed_days < 0:
            raise ValueError('min_listed_days must be a nonnegative integer')
        if self.mode != 'listing' and self.min_listed_days:
            raise ValueError('min_listed_days only applies to listing mode')
        if self.reference_manifest is not None and (self.mode!='listing' or not isinstance(self.reference_manifest,str) or not self.reference_manifest.strip()):
            raise ValueError('Baostock reference archives support retrospective listing eligibility only; verified historical publication times are required for PIT')


class HistoricalUniverse:
    def __init__(self, symbols, frame, config, metadata=None):
        self.symbols = tuple(symbols)
        self.config = config
        self.universe_id = 'historical_' + config.mode
        self.metadata = metadata or {}
        if config.mode == 'listing':
            selected = frame.filter(pl.col('code').is_in(symbols)).select(
                pl.col('code').alias('symbol'),
                pl.col('ipoDate').replace('',None).str.to_date(strict=True).alias('listed'),
                pl.col('outDate').replace('',None).str.to_date(strict=True).alias('delisted'))
            if selected['symbol'].n_unique()!=selected.height or selected['listed'].null_count():
                raise ValueError('Listing metadata must be unique with known IPO dates')
            if set(selected['symbol']) != set(symbols):
                raise ValueError('Listing metadata missing requested symbols')
            if selected.filter(pl.col('delisted')<=pl.col('listed')).height:
                raise ValueError('Delisting must follow listing date')
            self.frame = selected
            self.metadata = {**self.metadata, 'knowledge_policy':'retrospective_listing_dates_NOT_point_in_time',
                'limitations':'Current status ignored; historical ST/suspension/tradability not supplied.'}
        elif config.mode == 'pit':
            selected = frame.select('symbol','effective_at','available_at','eligible')
            for column in ('effective_at','available_at'):
                if not isinstance(selected.schema[column],pl.Datetime) or selected.schema[column].time_zone is None:
                    raise ValueError('PIT timestamps must have an explicit timezone')
            if selected.schema['eligible'] != pl.Boolean or any(selected[c].null_count() for c in selected.columns):
                raise ValueError('PIT records require nonnull timestamps, symbols and boolean eligibility')
            if selected.select(pl.struct('symbol','effective_at','available_at').is_duplicated().any()).item():
                raise ValueError('Duplicate PIT revision')
            self.frame = selected.sort('symbol','available_at','effective_at')
            self.metadata = {**self.metadata,'knowledge_policy':'effective_at <= bar time AND available_at <= bar availability; unknown excluded'}
        else:
            raise ValueError('HistoricalUniverse requires listing or pit mode')
        self.version = '1.0.0:' + digest({'frame':self.frame.write_json(),'config':config,'metadata':self.metadata})

    def mask(self,bars):
        if self.config.mode == 'listing':
            frame=bars.join(self.frame,on='symbol',how='left',validate='m:1')
            day=pl.col('datetime').dt.date()
            return frame.select('symbol','datetime',(
                pl.col('symbol').is_in(self.symbols) &
                (day >= pl.col('listed') + pl.duration(days=self.config.min_listed_days)) &
                (pl.col('delisted').is_null() | (day < pl.col('delisted')))
            ).fill_null(False).alias('eligible'))
        decisions=[]
        by_symbol={key[0]:group.to_dicts() for key,group in self.frame.group_by('symbol')}
        for key,group in bars.sort('symbol','available_at','datetime').group_by('symbol',maintain_order=True):
            symbol=key[0];events=by_symbol.get(symbol,[]);index=0;known={}
            for row in group.iter_rows(named=True):
                while index<len(events) and events[index]['available_at']<=row['available_at']:
                    event=events[index];known[event['effective_at']]=event;index+=1
                applicable=[event for time,event in known.items() if time<=row['datetime']]
                latest=max(applicable,key=lambda e:e['effective_at']) if applicable else None
                decisions.append({'symbol':symbol,'datetime':row['datetime'],
                    'eligible':bool(symbol in self.symbols and latest and latest['eligible'])})
        if not decisions:
            return bars.select('symbol','datetime',pl.lit(False).alias('eligible'))
        return pl.DataFrame(decisions).sort('symbol','datetime')


def build_universe(root, symbols, config=None):
    config = config or UniverseConfig()
    from quantlab.storage.approval_inputs import is_approval_freeze_root,frozen_universe
    if is_approval_freeze_root(root):
        return frozen_universe(root,symbols,config)
    if config.mode == 'explicit':
        return ExplicitUniverse(symbols)
    if config.reference_manifest:
        from quantlab.data.reference_archive import listing_reference
        frame,metadata=listing_reference(config.reference_manifest,symbols)
        return HistoricalUniverse(symbols,frame,config,metadata)
    relative = 'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet' if config.mode=='listing' else 'research/universe_events.parquet'
    path=Path(root)/relative
    payload=path.read_bytes()
    return HistoricalUniverse(symbols,pl.read_parquet(io.BytesIO(payload)),config,
        {'path':str(path.resolve()),'sha256':hashlib.sha256(payload).hexdigest()})
