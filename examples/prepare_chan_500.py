"""Prepare a read-only-source, audited daily snapshot for the frozen 500 symbols.

No signal or backtest execution. Source files are never changed. Null/nonfinite
OHLCV and zero-volume rows are excluded, not filled or replaced with other stocks.
"""
from pathlib import Path
from datetime import date
import hashlib,json
import polars as pl
from quantlab.data.validation import validate_bars

root=Path('/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/stock_kline_daily')
out=Path('artifacts/chan-500-ten-year');manifest=json.loads((out/'sample-manifest.json').read_text())
dest=out/'data/lake/bronze/provider=baostock/stock_kline_daily';dest.mkdir(parents=True,exist_ok=True)
reports=[];excluded=[]
for symbol in manifest['symbols']:
    source=root/(symbol.replace('.','_')+'.parquet');payload=source.read_bytes()
    import io
    frame=pl.read_parquet(io.BytesIO(payload)).filter(pl.col('date').is_between(date.fromisoformat(manifest['start']),date.fromisoformat(manifest['end'])))
    fields=['open','high','low','close','volume','amount']
    bad=pl.any_horizontal([pl.col(k).is_null()|~pl.col(k).cast(pl.Float64).is_finite() for k in fields])
    no_trade=pl.col('volume')<=0
    for row in frame.filter(bad|no_trade).to_dicts():
        excluded.append({'symbol':symbol,'date':str(row['date']),'reason':'missing_or_nonfinite' if any(row[k] is None for k in fields) else 'nonpositive_volume',
            **{k:row[k] for k in fields}})
    clean=frame.filter(~bad & ~no_trade)
    if clean.is_empty():raise ValueError(f'No usable history for selected symbol {symbol}; do not resample')
    target=dest/source.name;clean.write_parquet(target)
    reports.append({'symbol':symbol,'source':str(source),'source_sha256':hashlib.sha256(payload).hexdigest(),
        'snapshot':str(target.resolve()),'snapshot_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'input_rows':frame.height,'kept_rows':clean.height,'excluded_rows':frame.height-clean.height})
(out/'snapshot-provenance.json').write_text(json.dumps({'start':manifest['start'],'end':manifest['end'],'seed':manifest['seed'],
    'policy':'Exclude missing/nonfinite OHLCV and nonpositive volume; do not infer executable open for these rows; preserve original source and frozen symbol selection.',
    'limitations':'No authoritative historical suspension flag in source. This is an audited data-quality exclusion, not proof of point-in-time tradability. No corporate-action cash/stock entitlements applied.',
    'files':reports},ensure_ascii=False,indent=2))
(out/'excluded-bars.json').write_text(json.dumps(excluded,ensure_ascii=False,indent=2))
print(json.dumps({'symbols':len(reports),'input_rows':sum(r['input_rows'] for r in reports),'kept_rows':sum(r['kept_rows'] for r in reports),'excluded':len(excluded)},ensure_ascii=False))
