"""Bounded read-only discovery/profile of the host-selected local market-data root."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib
import io
import json
import re
import polars as pl
import pyarrow.parquet as pq
from quantlab.agent.catalog import schema, TEXT, LIMIT, OFFSET
from quantlab.data.base import DataRequest
from quantlab.data.provider import local_data_provider
from quantlab.domain import Timeframe
from quantlab.storage.codec import encode

SYMBOL = re.compile(r'(?:sh|sz|bj)\.\d{6}')
FILE = re.compile(r'(?:sh|sz|bj)_\d{6}\.parquet')
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILE_ROWS = 2_000_000
MAX_PROFILE_ROWS = 250_000
COMMON = {'timeframe': TEXT, 'adjustment': TEXT}
TOOLS = [
    schema('list_local_market_data', '只读发现宿主配置的本地MQC日线/5m文件，分页返回真实证券、覆盖日期、行数和SHA256；文件存在不认证PIT或日历完整。timeframe=1d/5m，adjustment=raw/qfq；不接受路径、不下载。',
           {**COMMON, 'offset': OFFSET, 'limit': LIMIT}),
    schema('inspect_local_market_data', '只读检查指定本地行情范围，返回字段质量、统计摘要、可加载性与IC截面数；不填空、不删行、不研究。symbols为逗号/空格分隔的1–20个实际代码，start/end为YYYY-MM-DD。先从list_local_market_data或有效Grant读取实际范围。',
           {**COMMON, 'symbols': {'type': 'string', 'maxLength': 300}, 'start': TEXT, 'end': TEXT}),
]
NAMES = {t['name'] for t in TOOLS}
WARNING = '本地文件/摘要不认证PIT、交易日历完整、可交易股票池或Alpha；缺失不填零，异常不得靠改参数隐去。'

def adjustment_review_notice(adjustment):
    if adjustment != 'qfq':
        return {}
    return {'adjustment_review': {
        'status': 'supplier_adjustment_not_verified',
        'corporate_actions_complete_verified': False,
        'known_issue_list_status': 'not_bound',
        'read_only_review_tool': 'inspect_corporate_action_sources',
        'note': '可加载和SHA256只证明所读字节，不证明公司行动完整、复权正确或历史当时可得。候选对账不修正价格；未核验不等于全部有错。',
    }}


class LocalMarketDataTools:
    def __init__(self, data_root):
        self.root = Path(data_root).resolve() if data_root else None

    def _safe(self, path):
        if self.root is None or not self.root.is_dir():
            raise ValueError('LOCAL_DATA_NOT_CONFIGURED：宿主未配置有效行情目录')
        if not path.is_relative_to(self.root):
            raise ValueError('LOCAL_DATA_PATH_REJECTED')
        current = path
        while current != self.root:
            if current.is_symlink():
                raise ValueError('LOCAL_DATA_SYMLINK_REJECTED')
            current = current.parent
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('LOCAL_DATA_PATH_REJECTED')
        return path

    def _directory(self, timeframe, adjustment):
        if timeframe not in ('1d', '5m') or adjustment not in ('raw', 'qfq'):
            raise ValueError('timeframe仅支持1d/5m，adjustment仅支持raw/qfq')
        if self.root is None:
            raise ValueError('LOCAL_DATA_NOT_CONFIGURED')
        # Do not treat a managed/frozen marker as permission to bypass its contract.
        for marker in ('baostock-series.json', 'baostock-dataset.json', 'manifest.json', 'archived-daily-dataset.json'):
            if self._safe(self.root/marker).exists():
                raise ValueError('MANAGED_DISCOVERY_UNSUPPORTED：当前入口是受管理/冻结数据，须使用对应批次/通道工具；禁止回退MQC发现')
        suffix = 'daily' if timeframe == '1d' else 'min5'
        directory = (self.root/'lake/silver'/('qfq_kline_'+suffix) if adjustment == 'qfq' else
                     self.root/'lake/bronze/provider=baostock'/('stock_kline_'+suffix))
        return self._safe(directory)

    def _read(self, path, budget, columns=None):
        self._safe(path)
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or size > budget[0]:
            raise ValueError('LOCAL_DATA_READ_BUDGET：缩小证券数量或使用管理数据入口')
        payload = path.read_bytes()
        if len(payload) > MAX_FILE_BYTES or len(payload) > budget[0]:
            raise ValueError('LOCAL_DATA_READ_BUDGET')
        budget[0] -= len(payload)
        meta = pq.ParquetFile(io.BytesIO(payload)).metadata
        if meta.num_rows > MAX_FILE_ROWS:
            raise ValueError('LOCAL_DATA_ROW_BUDGET')
        frame = pl.read_parquet(io.BytesIO(payload), columns=columns)
        if not {'date', 'code'} <= set(frame.columns):
            raise ValueError('LOCAL_DATA_SCHEMA：缺少date/code')
        return frame, {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
                       'relative_file': path.relative_to(self.root).as_posix()}

    def inventory(self, args):
        directory = self._directory(args['timeframe'], args['adjustment'])
        files = sorted(p for p in directory.glob('*.parquet') if FILE.fullmatch(p.name))
        selected = files[args['offset']:args['offset']+args['limit']]
        rows, refs, budget = [], [], [MAX_TOTAL_BYTES]
        for path in selected:
            symbol = path.stem.replace('_', '.')
            row = {'symbol': symbol}
            try:
                frame, source = self._read(path, budget, columns=['date', 'code'])
                valid_dates = frame['date'].drop_nulls()
                row.update(status='present', rows=frame.height, first_date=str(valid_dates.min()) if len(valid_dates) else None,
                           last_date=str(valid_dates.max()) if len(valid_dates) else None, source=source)
                refs.append({'kind': 'local_market_data', 'symbol': symbol, **source})
            except (OSError, ValueError, pl.exceptions.PolarsError) as error:
                row.update(status='unreadable', error=type(error).__name__+': '+str(error).replace(str(self.root), '<data-root>')[:240])
            rows.append(row)
        offset = args['offset']+len(selected)
        return {'provider': 'mqc_parquet', 'timeframe': args['timeframe'], 'adjustment': args['adjustment'],
                'records': rows, 'total': len(files), 'offset': args['offset'],
                'next_offset': offset if offset < len(files) else None, 'calendar_completeness_verified': False,
                **adjustment_review_notice(args['adjustment'])}, refs

    def profile(self, args):
        directory = self._directory(args['timeframe'], args['adjustment'])
        symbols = args['symbols'].replace(',', ' ').split()
        if not 1 <= len(symbols) <= 20 or len(set(symbols)) != len(symbols) or any(not SYMBOL.fullmatch(s) for s in symbols):
            raise ValueError('symbols须为1–20个不同实际证券代码')
        start, end = date.fromisoformat(args['start']), date.fromisoformat(args['end'])
        if start > end or (end-start).days > 3660:
            raise ValueError('日期范围无效或超过3660天')
        rows, refs, successful, budget, read_rows = [], [], [], [MAX_TOTAL_BYTES], 0
        for symbol in symbols:
            path = directory/(symbol.replace('.', '_')+'.parquet')
            row = {'symbol': symbol, 'loadable': False}
            try:
                raw, source = self._read(path, budget)
                frame = raw.filter(pl.col('date').is_between(start, end))
                read_rows += frame.height
                if read_rows > MAX_PROFILE_ROWS:
                    raise ValueError('LOCAL_PROFILE_ROW_BUDGET：缩小日期或证券范围')
                cols = [c for c in ('open','high','low','close','volume','amount','date','code') if c in frame.columns]
                row.update(rows=frame.height, null_counts={c: frame[c].null_count() for c in cols}, source=source)
                refs.append({'kind': 'local_market_data', 'symbol': symbol, **source})
                request = DataRequest((symbol,), Timeframe(args['timeframe']), start, end)
                batch = local_data_provider(self.root, args['adjustment']).load(request)
                if not any(item.get('sha256') == source['sha256'] for item in batch.snapshot.files):
                    raise ValueError('SOURCE_CHANGED：检查期间实际输入变化')
                bars = batch.bars
                successful.append(bars.select('symbol','datetime'))
                def mean(expr):
                    value = bars.select(expr).item()
                    return float(value) if value is not None else None
                row.update(loadable=True, normalized_rows=bars.height, snapshot_id=batch.snapshot.snapshot_id,
                           first_date=str(bars['datetime'].min().date()), last_date=str(bars['datetime'].max().date()),
                           zero_volume_rows=bars.filter(pl.col('volume') == 0).height,
                           mean_close=mean(pl.col('close').mean()), median_volume=mean(pl.col('volume').median()),
                           median_intraday_range=mean(((pl.col('high')-pl.col('low'))/pl.col('close')).median()),
                           columns=list(bars.columns))
            except (OSError, ValueError, pl.exceptions.PolarsError) as error:
                row['error'] = type(error).__name__+': '+str(error).replace(str(self.root), '<data-root>')[:240]
            rows.append(row)
        counts = pl.concat(successful).group_by('datetime').len() if successful else None
        ready = 0 if counts is None else counts.filter(pl.col('len') >= 3).height
        return {'timeframe': args['timeframe'], 'adjustment': args['adjustment'], 'start': args['start'], 'end': args['end'],
                'records': rows, 'request_loadable': all(r['loadable'] for r in rows),
                'ic_min_symbols_per_timestamp': 3, 'timestamps_with_at_least_3_bars': ready,
                'ic_ready_note': '只检查行情截面数量；因子预热、常数截面和未来标签成熟度仍可能使IC不可计算。',
                'calendar_completeness_verified': False, 'qualification': 'not_certified',
                **adjustment_review_notice(args['adjustment'])}, refs

    def call(self, name, arguments):
        try:
            definition = next(t for t in TOOLS if t['name'] == name)
            props = definition['parameters']['properties']
            if not isinstance(arguments, dict) or set(arguments) != set(props):
                raise ValueError('本地数据工具字段必须与Schema一致')
            for key, rule in props.items():
                value = arguments[key]
                valid = (isinstance(value, str) and len(value) <= rule['maxLength']) if rule['type']=='string' else (
                    type(value) is int and rule['minimum'] <= value <= rule['maximum'])
                if not valid:
                    raise ValueError('本地数据工具参数无效：'+key)
            data, refs = (self.inventory(arguments) if name == 'list_local_market_data' else self.profile(arguments))
            return json.loads(encode({'ok': True, 'tool': name, 'data': data, 'evidence': refs, 'warnings': [WARNING], 'error': None}))
        except (StopIteration, OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as error:
            message = str(error).replace(str(self.root), '<data-root>')[:300]
            return {'ok': False, 'tool': name, 'data': None, 'evidence': [], 'warnings': [WARNING],
                    'error': {'code': 'LOCAL_DATA_READ_FAILED', 'message': type(error).__name__+': '+message}}
