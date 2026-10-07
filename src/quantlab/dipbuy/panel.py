"""全市场日线面板：从数据清单里 READY 的前复权日线 + 日状态拼成 (日期 x 股票) 矩阵。

输入只来自 DATA 清单：
  * qfq_published_f24        前复权日线 (date, open, high, low, close, volume, amount, factor)
  * security_status_baostock_v2  日状态 (date, tradestatus, isST；'0'/'1' 字符串)
  * reference_snapshot_baostock_20260923  股票名称（可选，仅用来显示）
  * stock_delisted_daily_bs  已退市股票的不复权日线 + 前复权日线（可选；READY 才并入，否则面板只含现存股票）
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
DELISTED_DATASET = 'stock_delisted_daily_bs'
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
    isdel: np.ndarray | None = None   # bool [nc] 该列是已退市股票（并入的）；None 表示面板只含现存股票
    meta: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict, repr=False)

    @property
    def shape(self):
        return self.c.shape

    @property
    def n_delisted(self) -> int:
        return 0 if self.isdel is None else int(np.asarray(self.isdel).sum())

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
        extra = {} if self.isdel is None else {'isdel': np.asarray(self.isdel, bool)}
        np.savez_compressed(tmp, dates=self.dates, codes=self.codes, o=self.o, c=self.c, f=self.f, a=self.a,
                            st=self.st, ts=self.ts, **extra)
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
                       f=z['f'], a=z['a'], st=z['st'].astype(bool), ts=z['ts'], meta=dict(meta or {}),
                       isdel=z['isdel'].astype(bool) if 'isdel' in z.files else None)


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


def ready_delisted_dirs(catalog_path=None) -> tuple[Path, Path] | None:
    """退市股日线（不复权目录, 前复权目录）。数据清单没开放（或路径读不到）就返回 None，面板只含现存股票。"""
    try:
        source = get_ready_data_source(catalog_path, dataset_id=DELISTED_DATASET)
    except DataCatalogError:
        return None
    paths = source['technical_check']['paths']
    if len(paths) < 2:
        return None
    return Path(paths[0]['path']), Path(paths[1]['path'])


def source_signature(qfq_dir: Path, status_dir: Path, extra=()) -> str:
    """文件数 + 总大小 + 最新修改时间。便宜（只 stat），任何一只股票的文件变了都会变。"""
    h = hashlib.sha256()
    for directory in (qfq_dir, status_dir, *extra):
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
                limit: int | None = None, delisted=None) -> Panel:
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
    dkeys = _delisted_keys(delisted, {p.stem for p in files}, limit)
    nx = len(dkeys)
    arrays = {k: np.full((nd, nc + nx), np.nan, np.float32) for k in ('o', 'c', 'f', 'a')}
    st = np.zeros((nd, nc + nx), bool)
    ts = np.full((nd, nc + nx), -1, np.int8)
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
    skipped = _fill_delisted(cal, dkeys, delisted, nc, arrays, st, ts, codes) if nx else []
    dates = cal.astype('datetime64[D]').astype(str).astype('<U10')
    isdel = np.concatenate([np.zeros(nc, bool), np.ones(nx, bool)]) if nx else None
    meta = dict(start=start, first_date=str(dates[0]), last_date=str(dates[-1]), n_days=int(nd), n_stocks=int(nc + nx),
                n_status=int(n_status), qfq_dir=str(qfq_dir), status_dir=str(status_dir),
                n_delisted=int(nx - len(skipped)), delisted_skipped=skipped,
                delisted_dirs=[str(delisted[0]), str(delisted[1])] if nx else None,
                signature=(source_signature(qfq_dir, status_dir, delisted if nx else ()) if not limit else f'limit{limit}'))
    if progress:
        progress(total * 2, total * 2, '完成')
    return Panel(dates=dates, codes=np.array(codes), st=st, ts=ts, isdel=isdel, meta=meta, **arrays)


def _delisted_keys(delisted, listed_stems, limit=None) -> list[str]:
    """不复权与前复权两份都有、且不和现存股票重名的退市股文件名（排序后）。"""
    if not delisted:
        return []
    raw_dir, qfq_dir = Path(delisted[0]), Path(delisted[1])
    both = {p.stem for p in _parquet_files(raw_dir)} & {p.stem for p in _parquet_files(qfq_dir)}
    keys = sorted(both - set(listed_stems))
    return keys[:limit] if limit else keys


def _fill_delisted(cal, keys, delisted, nc, arrays, st, ts, codes) -> list[str]:
    """把退市股并到面板后面的列。原始价来自 baostock 不复权，前复权价与因子 = 前复权收盘 / 不复权收盘；
    停牌或价格无效的日子留空（NaN），退市后没有数据的日子也是 NaN。两份文件对不上的股票整列留空并记入 skipped。"""
    import pandas as pd
    raw_dir, qfq_dir = Path(delisted[0]), Path(delisted[1])
    nd = len(cal)
    skipped = []
    for k, key in enumerate(keys):
        j = nc + k
        codes.append(_stem_code(key))
        r = pd.read_parquet(raw_dir / f'{key}.parquet')
        q = pd.read_parquet(qfq_dir / f'{key}.parquet')
        if len(r) != len(q) or not (r['date'].astype(str).values == q['date'].astype(str).values).all():
            skipped.append(codes[-1])
            continue
        d = pd.to_datetime(r['date']).values.astype('datetime64[D]')
        idx = np.searchsorted(cal, d)
        ok = idx < nd
        ok[ok] &= cal[idx[ok]] == d[ok]
        if not ok.any():
            continue
        ii = idx[ok]
        trad = (r['tradestatus'].astype(str).values == '1')[ok]
        rc = r['close'].values[ok].astype(np.float64)
        qc = q['close'].values[ok].astype(np.float64)
        qo = q['open'].values[ok].astype(np.float64)
        with np.errstate(invalid='ignore', divide='ignore'):
            fac = np.where((rc > 0) & np.isfinite(rc), qc / np.where(rc > 0, rc, np.nan), np.nan)
        live = trad & np.isfinite(qc) & (qc > 0) & np.isfinite(qo) & (qo > 0)
        arrays['o'][ii, j] = np.where(live, qo, np.nan)
        arrays['c'][ii, j] = np.where(live, qc, np.nan)
        arrays['f'][ii, j] = np.where(live, fac, np.nan)
        arrays['a'][ii, j] = np.where(live, pd.to_numeric(r['amount'], errors='coerce').values[ok], np.nan)
        st[ii, j] = (r['isST'].astype(str).values == '1')[ok]
        ts[ii, j] = np.where(trad, 1, 0)
    return skipped


def survivorship_caveats(caveats, panel, detail='') -> list[str]:
    """面板并入了退市股时，把“只含现存股票（幸存者偏差）”那一条换成实际口径的说明；没并入就原样返回。"""
    caveats = list(caveats)
    n = panel.n_delisted
    if not n:
        return caveats
    note = (f'面板已并入 {n} 只已退市股票（baostock 日线，2006 年起）：后来退市的票现在也在样本里，这是更接近实盘的口径。'
            '退市股按退市前最后一个有成交的收盘价平仓，退市整理期实际卖不出，结果仍略偏乐观。' + detail)
    out, done = [], False
    for c in caveats:
        if '幸存者' in c:
            if not done:
                out.append(note)
                done = True
        else:
            out.append(c)
    return out if done else out + [note]


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


def current_sources(catalog_path=None):
    """READY 清单当前指向的数据：(前复权日线目录, 日状态目录, 退市股目录或 None, 源数据指纹)。便宜（只 stat）。"""
    qfq_dir, status_dir = ready_dirs(catalog_path)
    for d in (qfq_dir, status_dir):
        if not d.is_dir():
            raise DipDataError(f'数据目录不存在：{d}')
    delisted = ready_delisted_dirs(catalog_path)
    if delisted and not all(d.is_dir() for d in delisted):
        delisted = None
    return qfq_dir, status_dir, delisted, source_signature(qfq_dir, status_dir, delisted or ())


def load_panel(output, catalog_path=None, *, progress=None, stop=None, force=False) -> Panel:
    """有缓存且源数据没变就直接读缓存；否则按 READY 清单重建并写缓存。"""
    qfq_dir, status_dir, delisted, signature = current_sources(catalog_path)
    meta = cached_meta(output)
    directory = cache_dir(output)
    if not force and meta and meta.get('signature') == signature and (directory / 'panel.npz').is_file():
        return Panel.from_npz(directory / 'panel.npz', meta)
    panel = build_panel(qfq_dir, status_dir, progress=progress, stop=stop, delisted=delisted)
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
