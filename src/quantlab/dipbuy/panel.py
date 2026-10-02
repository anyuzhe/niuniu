"""全市场日线面板：从数据清单里 READY 的前复权日线 + 日状态拼成 (日期 x 股票) 矩阵。

输入只来自 DATA 清单：
  * qfq_published_f24        前复权日线 (date, open, high, low, close, volume, amount, factor)
  * security_status_baostock_v2  日状态 (date, tradestatus, isST；'0'/'1' 字符串)
  * reference_snapshot_baostock_20260923  股票名称（可选，仅用来显示）
价格 = 原始价 x factor，所以不复权价 = 前复权价 / factor。

建面板要读 5000 多个文件，所以结果缓存到 <output>/_dipbuy/panel/，
源目录的文件数/大小/修改时间一变就重建，不会静默用旧数据。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from quantlab.data.dataset_catalog import DataCatalogError, get_ready_data_source

PANEL_FORMAT = 'niuniu-dipbuy-panel-v1'
QFQ_DATASET = 'qfq_published_f24'
STATUS_DATASET = 'security_status_baostock_v2'
REFERENCE_DATASET = 'reference_snapshot_baostock_20260923'
DEFAULT_START = '2007-01-01'
MIN_STOCKS_PER_DAY = 200       # 一天里有行情的股票少于这个数，不算交易日（防止个别文件里的杂散日期混进日历）
PRICE_COLUMNS = ('open', 'close', 'factor', 'amount')


class DipDataError(ValueError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Panel:
    dates: np.ndarray          # '<U10' 升序
    codes: np.ndarray          # 'sh.600000'
    o: np.ndarray              # float32 [nd, nc] 前复权开盘
    c: np.ndarray              # float32 前复权收盘
    f: np.ndarray              # float32 复权因子（原始价 = 前复权价 / f）
    a: np.ndarray              # float32 成交额（元，原始）
    st: np.ndarray             # bool  ST
    ts: np.ndarray             # int8  1=可交易 0=停牌 -1=无状态行
    meta: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict, repr=False)

    @property
    def shape(self):
        return self.c.shape

    @property
    def last_date(self) -> str:
        return str(self.dates[-1])

    def index_of(self, day: str) -> int:
        i = int(np.searchsorted(self.dates, day))
        if i >= len(self.dates) or str(self.dates[i]) != day:
            raise DipDataError(f'{day} 不在面板日历里')
        return i

    def save(self, directory) -> Path:
        directory = Path(directory)
        if directory.is_symlink():
            raise DipDataError('缓存目录不能是符号链接')
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / 'panel.tmp.npz'
        np.savez_compressed(tmp, dates=self.dates, codes=self.codes, o=self.o, c=self.c, f=self.f, a=self.a,
                            st=self.st, ts=self.ts)
        os.replace(tmp, directory / 'panel.npz')
        meta = dict(self.meta, format=PANEL_FORMAT)
        tmp_meta = directory / 'panel.tmp.json'
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp_meta, directory / 'panel.json')
        return directory

    @classmethod
    def from_npz(cls, path, meta=None) -> 'Panel':
        with np.load(path, allow_pickle=False) as z:
            return cls(dates=z['dates'].astype('<U10'), codes=z['codes'].astype(str), o=z['o'], c=z['c'],
                       f=z['f'], a=z['a'], st=z['st'].astype(bool), ts=z['ts'], meta=dict(meta or {}))


def _stem_code(stem: str) -> str:
    return stem.replace('_', '.', 1)


def _parquet_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob('*.parquet') if not p.name.startswith('._'))


def ready_dirs(catalog_path=None) -> tuple[Path, Path]:
    """READY 清单里的前复权日线目录与日状态目录。清单没开放就报错，不找替代数据。"""
    out = []
    for dataset in (QFQ_DATASET, STATUS_DATASET):
        try:
            source = get_ready_data_source(catalog_path, dataset_id=dataset)
        except DataCatalogError as exc:
            raise DipDataError(f'数据侧尚未交付 {dataset}：{exc}') from exc
        paths = source['technical_check']['paths']
        if not paths:
            raise DipDataError(f'{dataset} 在数据清单中没有文件路径')
        out.append(Path(paths[0]['path']))
    return out[0], out[1]


def source_signature(qfq_dir: Path, status_dir: Path) -> str:
    """文件数 + 总大小 + 最新修改时间。便宜（只 stat），任何一只股票的文件变了都会变。"""
    h = hashlib.sha256()
    for directory in (qfq_dir, status_dir):
        files = _parquet_files(directory)
        total = 0
        newest = 0
        for p in files:
            s = p.stat()
            total += s.st_size
            newest = max(newest, s.st_mtime_ns)
        h.update(f'{directory.name}|{len(files)}|{total}|{newest}'.encode())
    return h.hexdigest()[:16]


def build_panel(qfq_dir, status_dir, *, start: str = DEFAULT_START, progress=None, stop: threading.Event | None = None,
                limit: int | None = None) -> Panel:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    qfq_dir, status_dir = Path(qfq_dir), Path(status_dir)
    files = _parquet_files(qfq_dir)
    if limit:
        files = files[:limit]
    if not files:
        raise DipDataError(f'{qfq_dir} 里没有日线文件')
    total = len(files)
    start64 = np.datetime64(start)

    def check(done, label):
        if stop is not None and stop.is_set():
            raise Cancelled()
        if progress:
            progress(done, total * 2, label)

    # 第一遍：只读日期列，合成交易日历
    day_arrays = []
    for i, p in enumerate(files):
        d = pq.read_table(p, columns=['date']).column('date').to_numpy(zero_copy_only=False)
        d = d.astype('datetime64[D]')
        day_arrays.append(d[d >= start64].astype(np.int32))
        if i % 200 == 0:
            check(i, '读取日历')
    allday = np.concatenate(day_arrays) if day_arrays else np.zeros(0, np.int32)
    del day_arrays
    uniq, cnt = np.unique(allday, return_counts=True)
    cal = uniq[cnt >= MIN_STOCKS_PER_DAY].astype('datetime64[D]')
    if len(cal) < 300:
        raise DipDataError(f'日历只有 {len(cal)} 天，不足以回测')
    nd, nc = len(cal), len(files)
    arrays = {k: np.full((nd, nc), np.nan, np.float32) for k in ('o', 'c', 'f', 'a')}
    st = np.zeros((nd, nc), bool)
    ts = np.full((nd, nc), -1, np.int8)
    codes = []
    n_status = 0
    for j, p in enumerate(files):
        codes.append(_stem_code(p.stem))
        t = pq.read_table(p, columns=['date', 'open', 'close', 'amount', 'factor'])
        d = t.column('date').to_numpy(zero_copy_only=False).astype('datetime64[D]')
        idx = np.searchsorted(cal, d)
        ok = idx < nd
        ok[ok] &= cal[idx[ok]] == d[ok]
        if ok.any():
            ii = idx[ok]
            for key, col in (('o', 'open'), ('c', 'close'), ('f', 'factor'), ('a', 'amount')):
                arrays[key][ii, j] = t.column(col).to_numpy(zero_copy_only=False)[ok]
        sp = status_dir / p.name
        if sp.is_file():
            s = pq.read_table(sp, columns=['date', 'tradestatus', 'isST'])
            sd = np.array(s.column('date').to_pylist(), dtype='datetime64[D]') if len(s) else np.zeros(0, 'datetime64[D]')
            si = np.searchsorted(cal, sd)
            sok = si < nd
            sok[sok] &= cal[si[sok]] == sd[sok]
            if sok.any():
                jj = si[sok]
                st[jj, j] = pc.equal(s.column('isST'), '1').to_numpy(zero_copy_only=False)[sok]
                ts[jj, j] = np.where(pc.equal(s.column('tradestatus'), '1').to_numpy(zero_copy_only=False)[sok], 1, 0)
                n_status += 1
        if j % 200 == 0:
            check(total + j, '读取行情与状态')
    if n_status < total * 0.5:
        raise DipDataError(f'只有 {n_status}/{total} 只股票有日状态文件，不能判断停牌与 ST，不继续')
    dates = cal.astype('datetime64[D]').astype(str).astype('<U10')
    meta = dict(start=start, first_date=str(dates[0]), last_date=str(dates[-1]), n_days=int(nd), n_stocks=int(nc),
                n_status=int(n_status), qfq_dir=str(qfq_dir), status_dir=str(status_dir),
                signature=source_signature(qfq_dir, status_dir) if not limit else f'limit{limit}')
    if progress:
        progress(total * 2, total * 2, '完成')
    return Panel(dates=dates, codes=np.array(codes), st=st, ts=ts, meta=meta, **arrays)


def cache_dir(output) -> Path:
    return Path(output).resolve() / '_dipbuy' / 'panel'


def cached_meta(output) -> dict | None:
    path = cache_dir(output) / 'panel.json'
    if not path.is_file() or path.is_symlink():
        return None
    try:
        meta = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) and meta.get('format') == PANEL_FORMAT else None


def load_panel(output, catalog_path=None, *, progress=None, stop=None, force=False) -> Panel:
    """有缓存且源数据没变就直接读缓存；否则按 READY 清单重建并写缓存。"""
    qfq_dir, status_dir = ready_dirs(catalog_path)
    for d in (qfq_dir, status_dir):
        if not d.is_dir():
            raise DipDataError(f'数据目录不存在：{d}')
    signature = source_signature(qfq_dir, status_dir)
    meta = cached_meta(output)
    directory = cache_dir(output)
    if not force and meta and meta.get('signature') == signature and (directory / 'panel.npz').is_file():
        return Panel.from_npz(directory / 'panel.npz', meta)
    panel = build_panel(qfq_dir, status_dir, progress=progress, stop=stop)
    panel.save(directory)
    return panel


def load_names(catalog_path=None) -> dict[str, str]:
    """股票名称（只用 09-23 参考快照，读不到就返回空，页面显示代码）。"""
    try:
        import polars as pl
        source = get_ready_data_source(catalog_path, dataset_id=REFERENCE_DATASET)
        root = Path(source['technical_check']['paths'][0]['path'])
        frame = pl.read_parquet(root / 'stock_basic.parquet', columns=['code', 'code_name'])
        return {str(a): str(b) for a, b in frame.iter_rows() if a}
    except Exception:
        return {}
