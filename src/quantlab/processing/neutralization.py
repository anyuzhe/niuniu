"""Contemporaneous cross-sectional OLS residuals using explicitly available controls.

Industry fixed effects are removed by group demeaning. For joint neutralization,
both the factor and log market cap are demeaned within industry before regression.
No return labels or future observations enter these cross-sectional projections.
"""
from datetime import datetime
import math
import polars as pl
from quantlab.data.industry import IndustryHistory


class SizeHistory:
    def __init__(self, records=None):
        self.records=[];seen=set()
        for raw in records or []:
            if set(raw)!={'symbol','market_cap','effective_at','available_at','expires_at','source'}:
                raise ValueError('Size record requires symbol, market_cap, effective_at, available_at, expires_at and source')
            r=dict(raw)
            for key in ('effective_at','available_at','expires_at'):
                if isinstance(r[key],str):r[key]=datetime.fromisoformat(r[key])
                if not isinstance(r[key],datetime) or r[key].tzinfo is None:raise ValueError('Size timestamps require timezone')
            if r['expires_at']<=r['effective_at']:raise ValueError('Size record has invalid lifetime')
            if any(not isinstance(r[k],str) or not r[k].strip() for k in ('symbol','source')):raise ValueError('Size record needs symbol and provenance')
            if type(r['market_cap']) not in (int,float) or not math.isfinite(r['market_cap']) or r['market_cap']<=0:
                raise ValueError('Market cap must be positive and finite, in a consistent currency/unit')
            key=(r['symbol'],r['effective_at'],r['available_at'])
            if key in seen:raise ValueError('Duplicate size revision')
            seen.add(key);self.records.append(r)

    def at(self,symbol,at):
        # Choose the latest known effective revision before checking its expiry;
        # an expired newer observation must not resurrect an older stale value.
        rows=[r for r in self.records if r['symbol']==symbol and r['effective_at']<=at and r['available_at']<=at]
        if not rows:return None
        r=max(rows,key=lambda r:(r['effective_at'],r['available_at']))
        return r['market_cap'] if at<r['expires_at'] else None


class CrossSectionNeutralizer:
    def __init__(self,industry_events=None,size_events=None):
        self.industry=IndustryHistory(industry_events);self.size=SizeHistory(size_events)

    def transform(self,values,mask,method):
        use_industry=method in ('industry_neutralization','neutralization')
        use_size=method in ('size_neutralization','neutralization')
        if not use_industry and not use_size:raise ValueError('Unknown neutralization method')
        frame=values.join(mask.select('symbol','datetime','eligible'),on=['symbol','datetime'],how='left',validate='1:1')
        if frame['eligible'].null_count():raise ValueError('Universe must cover every neutralization row')
        if values.filter(pl.col('available_at')!=pl.col('datetime')).height:
            raise ValueError('Neutralization requires close-available factors; delayed factors cannot be backdated')
        output=[];audit=[]
        for key,group in frame.sort('datetime','symbol').group_by('datetime',maintain_order=True):
            at=key[0];selected=[];missing_industry=0;missing_size=0
            for row in group.iter_rows(named=True):
                if not row['eligible'] or row['value'] is None:continue
                if not math.isfinite(row['value']):raise ValueError('Nonfinite neutralization input; use replace_inf first')
                sector=self.industry.at(row['symbol'],at) if use_industry else 'ALL'
                cap=self.size.at(row['symbol'],at) if use_size else 1.
                missing_industry+=sector is None;missing_size+=cap is None
                if sector is not None and cap is not None:selected.append((row['symbol'],sector,row['value'],math.log(cap)))
            groups={}
            for row in selected:groups.setdefault(row[1],[]).append(row)
            centered=[]
            for members in groups.values():
                ymean=math.fsum(r[2] for r in members)/len(members);xmean=math.fsum(r[3] for r in members)/len(members)
                centered.extend((r[0],r[2]-ymean,r[3]-xmean) for r in members)
            residuals={};status='computed';slope=None
            degrees=len(selected)-len(groups)-int(use_size)
            if degrees<=0:status='insufficient_degrees_of_freedom'
            elif use_size:
                scale=max(abs(r[2]) for r in centered)
                if scale<=1e-12:status='constant_or_industry_collinear_size'
                else:
                    # Normalize the log-cap residual to avoid squaring tiny scales.
                    xs=[r[2]/scale for r in centered]
                    slope_scaled=math.fsum(x*r[1] for x,r in zip(xs,centered))/math.fsum(x*x for x in xs)
                    slope=slope_scaled/scale
                    residuals={r[0]:r[1]-slope_scaled*x for x,r in zip(xs,centered)}
            else:residuals={r[0]:r[1] for r in centered}
            # Exact linear fits should not become spurious rank factors through roundoff.
            tolerance=1e-12*max((abs(r[2]) for r in selected),default=0.)
            residuals={s:0. if abs(v)<=tolerance else v for s,v in residuals.items()}
            for row in group.iter_rows(named=True):
                output.append({'symbol':row['symbol'],'datetime':at,'available_at':row['available_at'],'value':residuals.get(row['symbol'])})
            audit.append({'datetime':at,'method':method,'status':status,'eligible_rows':group.filter(pl.col('eligible')).height,
                'used_rows':len(selected),'output_rows':len(residuals),'missing_industry_rows':missing_industry,'missing_size_rows':missing_size,
                'industry_groups':len(groups) if use_industry else None,'residual_degrees_of_freedom':degrees,'log_cap_slope':slope})
        return pl.DataFrame(output,schema=values.select('symbol','datetime','available_at','value').schema).sort('symbol','datetime'),audit
