"""Read-only parameterized DuckDB queries over selected MQC Parquet files."""
from pathlib import Path
import re
import hashlib
import duckdb
from quantlab.domain import Timeframe


def source_paths(root,request,adjustment='raw'):
    if adjustment not in ('raw','qfq'):raise ValueError('Unknown adjustment')
    suffix='daily' if request.timeframe==Timeframe.DAILY else 'min5'
    base=Path(root)/('lake/bronze/provider=baostock' if adjustment=='raw' else 'lake/silver')/(('stock_kline_' if adjustment=='raw' else 'qfq_kline_')+suffix)
    if any(not re.fullmatch(r'(sh|sz|bj)\.\d{6}',s) for s in request.symbols):raise ValueError('Invalid symbol')
    return [base/(s.replace('.','_')+'.parquet') for s in sorted(request.symbols)]


def query_bars(root,request,adjustment='raw'):
    paths=source_paths(root,request,adjustment)
    before=[(p.stat().st_size,p.stat().st_mtime_ns) for p in paths]
    with duckdb.connect(':memory:') as db:
        result=db.execute('SELECT * FROM read_parquet(?, union_by_name=true) WHERE date BETWEEN ? AND ? ORDER BY code,date'+(',time' if request.timeframe==Timeframe.MIN5 else ''),
            [[str(p) for p in paths],request.start,request.end]).pl()
        missing_dates={str(Path(name).resolve()):count for name,count in db.execute('SELECT filename, count(*) FILTER (WHERE date IS NULL) FROM read_parquet(?, union_by_name=true, filename=true) GROUP BY filename',[[str(p) for p in paths]]).fetchall()}
    files=[]
    for p,state in zip(paths,before):
        h=hashlib.sha256()
        with p.open('rb') as f:
            while block:=f.read(1024*1024):h.update(block)
        if state!=(p.stat().st_size,p.stat().st_mtime_ns):raise ValueError('Source changed during query; retry against a stable snapshot')
        files.append({'path':str(p.resolve()),'bytes':state[0],'sha256':h.hexdigest(),'null_date_rows_in_source':missing_dates.get(str(p.resolve()),0)})
    return result,files
