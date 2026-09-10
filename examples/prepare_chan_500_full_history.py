"""Freeze a new, disjoint, full-window daily universe; never modify MQC source."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import hashlib, io, json, random
import polars as pl

ROOT=Path('/Volumes/Lexar/MQC-DATA')
OUT=Path('artifacts/chan-500-full-ten-year-qfq')
START=date(2016,9,5); END=date(2026,9,4); SEED=20260910
RAW=ROOT/'lake/bronze/provider=baostock/stock_kline_daily'
QFQ=ROOT/'lake/silver/qfq_kline_daily'
FIELDS=['open','high','low','close','volume','amount']
old=set(json.loads(Path('artifacts/chan-500-ten-year/sample-manifest.json').read_text())['symbols'])
# Observed full-market trading dates from the preceding frozen daily archive.
calendar=pl.read_parquet('artifacts/chan-500-ten-year/runs/b7c5836a-817c-4e9a-8cc2-c3a2c9de7ad3/bars.parquet',columns=['datetime'])['datetime'].dt.date().unique().sort().to_list()
assert calendar[0]==START and calendar[-1]==END and len(calendar)==2428

def valid(frame):
    finite=pl.all_horizontal([pl.col(c).is_not_null() & pl.col(c).cast(pl.Float64).is_finite() for c in FIELDS])
    return frame.filter(finite & (pl.col('volume')>0) & (pl.col('amount')>=0) &
        (pl.col('low')>0) & (pl.col('high')>=pl.max_horizontal('open','close','low')) &
        (pl.col('low')<=pl.min_horizontal('open','close')))

def inspect(path):
    symbol=path.stem.replace('_','.')
    item={'symbol':symbol,'in_previous_sample':symbol in old}
    try:
        raw=pl.read_parquet(path).filter(pl.col('date').is_between(START,END)).sort('date')
        qfq=pl.read_parquet(QFQ/path.name).filter(pl.col('date').is_between(START,END)).sort('date')
        item.update(raw_rows=raw.height,qfq_rows=qfq.height,
            raw_first=str(raw['date'].min()),raw_last=str(raw['date'].max()),
            qfq_first=str(qfq['date'].min()),qfq_last=str(qfq['date'].max()))
        usable_raw=valid(raw);usable_qfq=valid(qfq)
        item.update(valid_raw_rows=usable_raw.height,valid_qfq_rows=usable_qfq.height)
        item['full_window']=(usable_raw['date'].to_list()==calendar and usable_qfq['date'].to_list()==calendar
            and usable_raw['code'].to_list()==[symbol]*len(calendar) and usable_qfq['code'].to_list()==[symbol]*len(calendar)
            and usable_raw['adjustflag'].to_list()==['3']*len(calendar))
        item['eligible']=item['full_window'] and symbol not in old
    except Exception as exc:item.update(eligible=False,error=f'{type(exc).__name__}: {exc}')
    return item

OUT.mkdir(parents=True,exist_ok=True)
with ThreadPoolExecutor(max_workers=6) as pool:
    rows=[]
    for n,item in enumerate(pool.map(inspect,sorted(RAW.glob('*.parquet'))),1):
        rows.append(item)
        if n%500==0:print(json.dumps({'scanned':n,'eligible':sum(r['eligible'] for r in rows)}),flush=True)
(OUT/'coverage-inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
eligible=sorted(r['symbol'] for r in rows if r['eligible'])
print(json.dumps({'files':len(rows),'eligible_disjoint_full_window':len(eligible)}),flush=True)
if len(eligible)<500:raise ValueError('Fewer than 500 disjoint complete-window stocks; do not silently relax selection')
symbols=sorted(random.Random(SEED).sample(eligible,500))
manifest={'seed':SEED,'start':str(START),'end':str(END),'trading_days':len(calendar),'pool_size':len(eligible),
    'selection':'Uniform without replacement; excludes all previous 500; both qfq and raw have a valid positive-volume daily bar on every one of the 2428 observed market dates in the window.',
    'calendar_source':'Union of observed dates in preceding 500-stock archive, not an authoritative exchange calendar.',
    'limitations':'Conditioning on complete ten-year history creates survival/continuous-trading selection bias; not a historical point-in-time universe.',
    'symbols':symbols}
(OUT/'sample-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
(OUT/'symbols.txt').write_text('\n'.join(symbols)+'\n')
(OUT/'trading-dates.json').write_text(json.dumps([str(d) for d in calendar]))
provenance=[]
for symbol in symbols:
    for adjustment,base,relative in [('raw',RAW,'lake/bronze/provider=baostock/stock_kline_daily'),('qfq',QFQ,'lake/silver/qfq_kline_daily')]:
        src=base/(symbol.replace('.','_')+'.parquet');payload=src.read_bytes()
        frame=pl.read_parquet(io.BytesIO(payload)).filter(pl.col('date').is_between(START,END)).sort('date')
        assert valid(frame)['date'].to_list()==calendar
        dest=OUT/'data'/relative/src.name;dest.parent.mkdir(parents=True,exist_ok=True);frame.write_parquet(dest)
        provenance.append({'symbol':symbol,'adjustment':adjustment,'rows':frame.height,'source':str(src),
            'source_sha256':hashlib.sha256(payload).hexdigest(),'snapshot':str(dest.resolve()),
            'snapshot_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
(OUT/'snapshot-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
spec=json.loads(Path('artifacts/chan-500-ten-year/client-spec.json').read_text())
spec.update(question='经典缠论 · 新500股完整十年 · 前复权 · 20260909',symbols=symbols,adjustment='qfq')
(OUT/'client-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
print(json.dumps({'prepared_symbols':len(symbols),'bars_per_price_basis':500*len(calendar),'overlap_previous':len(set(symbols)&old)}),flush=True)
