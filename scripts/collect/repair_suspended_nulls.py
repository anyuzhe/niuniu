"""停牌日 volume / amount 为空 → 记 0（数据侧修复，用户 2026-10-17 授权）。

背景：Baostock 历史批量导入时，停牌日的日K行有时 volume/amount 为空、有时为 0（退市股文件里还有
volume=0 而 amount 为空的变体）。研究加载器按"缺失数量不补不删"整只拒绝有空值的证券。
增量采集（bars_incremental.py）早已不写停牌行，所以空值只存在于历史行。

规则（只动同时满足的行）：
  * volume 或 amount 任一为空；
  * 该日为停牌：在 daily_status_v2 里 tradestatus=0，或文件自带的 tradestatus=0（退市股），
    或开高低收全部等于前一行收盘（供应商停牌占位）。
  → 空的那个字段记 0；其它列、行数不变（coverage.parquet 的 rows_raw / rows_qfq 不受影响）。
不满足条件（交易日却无量）的空值保留并写进回执，由人决定。
原文件先复制到 catalog/repair-20261017/backup/，可整体回滚。

目录：在市不复权、在市 qfq v2、退市不复权、退市前复权孪生。
用法：
  /Volumes/Lexar/niuniu/.venv/bin/python repair_suspended_nulls.py --dry-run   # 只报告
  /Volumes/Lexar/niuniu/.venv/bin/python repair_suspended_nulls.py             # 写回
回执：catalog/repair-20261017/suspended-nulls-<时间>.json
"""
from __future__ import annotations
import argparse, json, shutil, time
from pathlib import Path
import polars as pl

DEFAULT_ROOT = '/Volumes/Lexar/niuniu-data'
DIRS = {
    'raw_daily': 'lake/bronze/provider=baostock/stock_kline_daily',
    'qfq_v2': 'lake/silver/qfq_kline_daily_v2',
    'delisted_raw': 'lake/bronze/provider=baostock/stock_kline_daily_delisted',
    'delisted_qfq_bs': 'lake/bronze/provider=baostock/stock_kline_daily_delisted_qfq_bs',
}
STATUS = 'lake/bronze/provider=baostock/daily_status_v2'


def suspended_dates(root: Path, stem: str, frame: pl.DataFrame) -> set:
    if 'tradestatus' in frame.columns:
        return set(frame.filter(pl.col('tradestatus').cast(pl.String) == '0')['date'].to_list())
    path = root / STATUS / (stem + '.parquet')
    if not path.exists():
        return set()
    st = pl.read_parquet(path, columns=['date', 'tradestatus'])
    if st['date'].dtype != pl.Date:
        st = st.with_columns(pl.col('date').str.to_date())
    return set(st.filter(pl.col('tradestatus').cast(pl.String) == '0')['date'].to_list())


def repair_file(root: Path, path: Path, backup: Path, dry_run: bool):
    frame = pl.read_parquet(path)
    if 'volume' not in frame.columns or 'amount' not in frame.columns:
        return None
    anynull = frame['volume'].is_null() | frame['amount'].is_null()
    if not anynull.any():
        return None
    frame = frame.sort('date')
    anynull = frame['volume'].is_null() | frame['amount'].is_null()
    susp = suspended_dates(root, path.stem, frame)
    by_status = pl.Series([d in susp for d in frame['date'].to_list()])
    prev = pl.col('close').shift(1)
    placeholder = frame.select(((pl.col('open') == prev) & (pl.col('high') == prev) & (pl.col('low') == prev)
                                & (pl.col('close') == prev)).fill_null(False)).to_series()
    fix = anynull & (by_status | placeholder)
    keep = anynull & ~fix
    row = {'file': path.name, 'null_rows': int(anynull.sum()), 'fixed': int(fix.sum()), 'unfixed': int(keep.sum()),
           'unfixed_dates': [str(d) for d in frame.filter(keep)['date'].to_list()][:10]}
    if fix.any() and not dry_run:
        vd, ad = frame.schema['volume'], frame.schema['amount']
        mask = pl.Series(fix)
        fixed = frame.with_columns(
            pl.when(mask & pl.col('volume').is_null()).then(pl.lit(0).cast(vd)).otherwise(pl.col('volume')).alias('volume'),
            pl.when(mask & pl.col('amount').is_null()).then(pl.lit(0.0).cast(ad)).otherwise(pl.col('amount')).alias('amount'))
        assert fixed.height == frame.height and fixed.schema == frame.schema
        assert int((fixed['volume'].is_null() | fixed['amount'].is_null()).sum()) == int(keep.sum())
        dst = backup / path.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        tmp = path.with_name(path.name + '.tmp')
        fixed.write_parquet(tmp)
        tmp.replace(path)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-root', default=DEFAULT_ROOT)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', nargs='*', choices=sorted(DIRS))
    a = ap.parse_args()
    root = Path(a.data_root).resolve()
    repair = root / 'catalog' / 'repair-20261017'
    backup = repair / 'backup'
    report = {'format': 'niuniu-repair-suspended-nulls-v2', 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'dry_run': a.dry_run, 'rule': __doc__.split('规则')[1].split('目录')[0].strip(),
              'authorized_by': '用户 2026-10-17「你直接替数据侧干吧」「你帮我执行吧」', 'dirs': {}}
    for key in (a.only or sorted(DIRS)):
        d = root / DIRS[key]
        if not d.is_dir():
            report['dirs'][key] = {'missing': True}
            continue
        files = sorted(d.glob('*.parquet'))
        rows = [r for r in (repair_file(root, p, backup, a.dry_run) for p in files) if r]
        report['dirs'][key] = {'dir': DIRS[key], 'files_scanned': len(files),
                               'files_changed': len([r for r in rows if r['fixed']]),
                               'rows_fixed': sum(r['fixed'] for r in rows), 'rows_unfixed': sum(r['unfixed'] for r in rows),
                               'unfixed_files': [r for r in rows if r['unfixed']][:50], 'files': rows}
        print(key, {k: v for k, v in report['dirs'][key].items() if k not in ('files', 'unfixed_files')}, flush=True)
    repair.mkdir(parents=True, exist_ok=True)
    out = repair / f'suspended-nulls-{time.strftime("%Y%m%dT%H%M%S")}{"-dryrun" if a.dry_run else ""}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('回执', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
