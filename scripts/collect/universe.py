"""Universe resolution for the collectors in this package.

The old one-off collectors took their symbol list from whatever analysis
artifact happened to be at hand — ``d4/rights-issue-adjustment-gaps.csv`` for
cninfo, a hand-built ``collect-universe.json`` for THS. That is how the cninfo
pull ended up 114 symbols short of the population it was supposed to cover: the
universe silently inherited the filter of an upstream analysis.

Here the universe is always one of a small number of **named presets** resolved
from durable lake data, or an explicit file the operator passes with
``--universe``. Either way the run prints and records which one it used, so the
coverage question can be answered from the receipt alone.
"""
from __future__ import annotations

from pathlib import Path

LAKE = Path('/Volumes/Lexar/niuniu-data/lake/bronze')
CATALOG = Path('/Volumes/Lexar/niuniu-data/catalog/mqc.duckdb')

PRESETS = {
    'stocks': 'baostock stock_basic 中 type=1 的全部 A 股，含已退市（status=0）',
    'stocks-listed': 'baostock stock_basic 中 type=1 且 status=1 的在市 A 股',
    'tdx-rights': 'TDX 除权除息记录中 c4（配股比例）> 0 的证券，即历史上确有配股的标的',
}


def _baostock_stocks(listed_only: bool) -> list[str]:
    import pandas as pd
    p = LAKE / 'provider=baostock' / 'stock_basic' / 'stock_basic.parquet'
    if not p.exists():
        raise FileNotFoundError('缺少 baostock stock_basic：%s' % p)
    df = pd.read_parquet(p)
    for col in ('code', 'type', 'status'):
        if col not in df.columns:
            raise ValueError('stock_basic 缺列 %s，实得 %s' % (col, list(df.columns)))
    sel = df[df['type'].astype(str) == '1']
    if listed_only:
        sel = sel[sel['status'].astype(str) == '1']
    return sorted(str(c) for c in sel['code'].dropna().unique())


def _tdx_rights() -> list[str]:
    import duckdb
    if not CATALOG.exists():
        raise FileNotFoundError('缺少 TDX 目录库：%s' % CATALOG)
    con = duckdb.connect(str(CATALOG), read_only=True)
    try:
        rows = con.execute(
            "select distinct code from tdx_capital_changes "
            "where json_extract_string(record_json,'category_name') = '除权除息' "
            "  and try_cast(json_extract_string(record_json,'c4_value') as double) > 0 "
            "order by code").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def resolve(preset: str) -> list[str]:
    """Return the symbol list for a named preset. Raises on an unknown name."""
    if preset == 'stocks':
        codes = _baostock_stocks(listed_only=False)
    elif preset == 'stocks-listed':
        codes = _baostock_stocks(listed_only=True)
    elif preset == 'tdx-rights':
        codes = _tdx_rights()
    else:
        raise ValueError('未知的 universe 预设 %r，可选：%s' % (preset, ', '.join(PRESETS)))
    if not codes:
        raise ValueError('universe 预设 %r 解析出 0 只证券，拒绝继续' % preset)
    return codes


def describe(preset: str) -> str:
    return PRESETS.get(preset, '(自定义)')


def known_limitations() -> str:
    return (
        'baostock stock_basic 的退市股仅 337 只，1990 年代摘牌的标的多半不在其中；'
        '需要覆盖早年退市股时请用 --universe 显式给清单，不要假设预设即全集。')
