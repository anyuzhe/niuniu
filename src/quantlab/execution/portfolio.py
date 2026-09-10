"""Causal signal selection and target-weight risk controls, independent of fill mechanics."""
from dataclasses import dataclass
import math
import polars as pl
from quantlab.data.industry import IndustryHistory


@dataclass(frozen=True)
class PortfolioConfig:
    weighting: str = 'equal'
    max_position: float = 1.
    max_exposure: float = 1.
    max_turnover: float | None = None
    volatility_lookback: int = 20
    sector_limit: float | None = None
    industry_events: list | None = None

    def __post_init__(self):
        if self.weighting not in ('equal','score','inverse_volatility'):raise ValueError('weighting must be equal, score or inverse_volatility')
        if type(self.volatility_lookback) is not int or self.volatility_lookback<2:raise ValueError('volatility_lookback must be >= 2')
        if self.sector_limit is not None and (type(self.sector_limit) not in (int,float) or not math.isfinite(self.sector_limit) or not 0<self.sector_limit<=1):raise ValueError('Invalid sector limit')
        IndustryHistory(self.industry_events)
        for key in ('max_position','max_exposure'):
            v=getattr(self,key)
            if type(v) not in (float,int) or not math.isfinite(v) or not 0<v<=1:raise ValueError(key+' must be in (0,1]')
        if self.max_turnover is not None and (type(self.max_turnover) not in (float,int) or not math.isfinite(self.max_turnover) or not 0<=self.max_turnover<=2):
            raise ValueError('max_turnover must be null or in [0,2]')


class TargetWeightBuilder:
    def __init__(self,config=None):self.config=config or PortfolioConfig()
    def build(self,observations,bars,*,top_n,threshold,exposure):
        cfg=self.config;symbols=sorted(bars['symbol'].unique().to_list())
        industry=IndustryHistory(cfg.industry_events)
        volatility={}
        if cfg.weighting=='inverse_volatility':
            history=bars.sort('symbol','datetime').with_columns(pl.col('close').pct_change().over('symbol').alias('_return'))
            history=history.with_columns(pl.col('_return').rolling_std(cfg.volatility_lookback).over('symbol').alias('_volatility'))
            volatility={(r['symbol'],r['datetime']):r['_volatility'] for r in history.iter_rows(named=True)}
        values={key[0]:group for key,group in observations.group_by('datetime')}
        rows=[];audit=[];previous={s:0. for s in symbols}
        for dt in sorted(bars['datetime'].unique()):
            frame=values.get(dt);scores={};eligible=set();signals=[]
            if frame is not None:
                if frame.filter(pl.col('available_at')>pl.col('datetime')).height:raise ValueError('Delayed factor cannot be used as a same-close target')
                if frame['symbol'].n_unique()!=frame.height:raise ValueError('Duplicate signal symbol at a decision time')
                for row in frame.iter_rows(named=True):
                    symbol=row['symbol'];value=row['value'];valid=bool(row.get('eligible',True))
                    if symbol not in previous:raise ValueError('Signal outside bar universe')
                    if valid:eligible.add(symbol)
                    finite=value is not None and math.isfinite(value)
                    signals.append({'symbol':symbol,'score':value if finite else None,'eligible':valid})
                    if valid and finite and value>threshold:scores[symbol]=value
            sectors={s:industry.at(s,dt) for s in symbols}
            if cfg.sector_limit is not None:
                eligible={s for s in eligible if sectors[s] is not None}
                scores={s:v for s,v in scores.items() if s in eligible}
            if cfg.weighting=='inverse_volatility':
                scores={s:v for s,v in scores.items() if volatility.get((s,dt)) is not None and math.isfinite(volatility[(s,dt)]) and volatility[(s,dt)]>0}
            chosen=sorted(scores,key=lambda s:(-scores[s],s))[:top_n]
            if cfg.weighting=='score' and any(scores[s]<=0 for s in chosen):
                raise ValueError('Score weights require strictly positive selected scores')
            magnitudes={s:scores[s]/max(scores[c] for c in chosen) if cfg.weighting=='score' else 1. for s in chosen}
            if cfg.weighting=='inverse_volatility' and chosen:
                smallest=min(volatility[(s,dt)] for s in chosen)
                magnitudes={s:smallest/volatility[(s,dt)] for s in chosen}
            denominator=sum(magnitudes.values())
            raw={s:(exposure*magnitudes[s]/denominator if s in chosen else 0.) for s in symbols}
            scale=min(1.,cfg.max_exposure/exposure) if exposure else 1.
            capped={s:min(cfg.max_position,w*scale) for s,w in raw.items()}
            def sector_cap(weights):
                result=dict(weights)
                if cfg.sector_limit is not None:
                    for sector in set(sectors.values()):
                        members=[s for s in symbols if sectors[s]==sector]
                        total=sum(result[s] for s in members)
                        limit=cfg.sector_limit if sector is not None else 0.
                        if total>limit:
                            for s in members:result[s]*=limit/total
                return result
            capped=sector_cap(capped)
            # Eligibility exits take priority. Other turnover is a target-to-target budget,
            # not a guarantee on turnover or constraints of actual T+1-constrained holdings.
            base={s:previous[s] if s in eligible else 0. for s in symbols}
            forced=sum(abs(base[s]-previous[s]) for s in symbols)
            requested=sum(abs(capped[s]-base[s]) for s in symbols)
            fraction=1.
            if cfg.max_turnover is not None and requested:
                fraction=min(1.,max(0.,cfg.max_turnover-forced)/requested)
            final={s:base[s]+fraction*(capped[s]-base[s]) for s in symbols}
            before_sector=final;final=sector_cap(final)
            reasons=[]
            if final!=before_sector:reasons.append('sector_reclassification_overrides_turnover')
            if raw!=capped:reasons.append('position_or_exposure_cap')
            if fraction<1:reasons.append('target_turnover_budget')
            if forced:reasons.append('eligibility_exit_priority')
            for symbol in symbols:rows.append({'symbol':symbol,'datetime':dt,'available_at':dt,'weight':final[symbol]})
            audit.append({'available_at':dt,'signals':signals,'selected':chosen,'raw_weights':raw,'capped_weights':capped,
                'weights':final,'target_turnover':sum(abs(final[s]-previous[s]) for s in symbols),
                'forced_exit_turnover':forced,'sectors':sectors if cfg.sector_limit is not None else {},'reasons':reasons})
            previous=final
        return pl.DataFrame(rows),audit
