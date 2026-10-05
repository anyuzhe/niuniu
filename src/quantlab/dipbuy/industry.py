"""行业恐慌（申万一级）：某个行业整体被砸得异常狠时，买这个行业里 20 日跌得最多的股票。

规则（研究依据见 docs/archive/testing/20260930-低频抄底扣成本重测与ETF.md §35–§38）：
  行业分 z_g  行业内“前一日可交易”股票的等权日收益，连乘成 20 日涨跌，除以（行业 60 日日波动 x sqrt(20)）。
              阈值沿用大盘的 -1.5，没有为行业单独调过；行业内至少 8 只股票有收益才算。
  闸门        任意一个行业 z_g <= 阈值（不管大盘处于什么状态）。
  候选        触发行业里全部可交易股票（非 ST、上市满 250 日、20 日均成交额 >= 5000 万、原始价 >= 3 元、次日不是一字涨停），
              不要求布林下轨收复；按 20 日跌幅从大到小全局混排，取前 N 只。
  仓位        N 只等权，信号日收盘后决定，次日开盘买，持有 hold_days 个交易日后收盘卖；默认杠杆 1 倍。
行业分类来自 READY 的 sw_industry_history，取每只股票最新一条记录，所以是“今天的分类”套到历史上（轻微前视）。
这里不下单、不写数据根；回测与前向跟踪沿用大盘恐慌策略的同一套引擎和记录格式。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from quantlab.data.dataset_catalog import DataCatalogError, get_ready_data_source
from quantlab.dipbuy.engine import (Candidates, DipConfig, ENGINE_VERSION, Market, compute_features, curve,
                                    drawdown_series, latest_signal, simulate, summarize)
from quantlab.dipbuy.panel import Cancelled, DipDataError, Panel

INDUSTRY_DATASET = 'sw_industry_history'
RET_WINDOW = 20
STD_WINDOW = 60
STD_MIN = 40
MIN_MEMBERS = 8              # 行业当天至少这么多只股票有收益，行业分才算
MIN_MAPPED_SHARE = 0.5       # 面板里至少这个比例的股票能对上行业，否则不继续

SW_L1 = {
    '110000': '农林牧渔', '220000': '基础化工', '230000': '钢铁', '240000': '有色金属', '270000': '电子',
    '280000': '汽车', '330000': '家用电器', '340000': '食品饮料', '350000': '纺织服饰', '360000': '轻工制造',
    '370000': '医药生物', '410000': '公用事业', '420000': '交通运输', '430000': '房地产', '450000': '商贸零售',
    '460000': '社会服务', '480000': '银行', '490000': '非银金融', '510000': '综合', '610000': '建筑材料',
    '620000': '建筑装饰', '630000': '电力设备', '640000': '机械设备', '650000': '国防军工', '710000': '计算机',
    '720000': '传媒', '730000': '通信', '740000': '煤炭', '750000': '石油石化', '760000': '环保', '770000': '美容护理',
}

CAVEATS = (
    '对照实验（文档 §38）：把行业标签随机打乱后再跑同样的规则，年化约 12%、夏普约 0.63（30 次平均）；真实申万一级 17.6%、夏普 0.76，'
    '高于全部 30 次打乱，但差距不大。换成申万二级或证监会行业，反而不如打乱。所以相当一部分收益来自“大盘偏弱时买最弱的股票”，行业信息本身的增量有限。',
    '行业分类用的是今天的申万一级分类，套到历史上有轻微前视；阈值 -1.5 直接沿用大盘，没有为行业调过。',
    '行业恐慌片段约 700 段（平均每个行业二十多段），样本比大盘恐慌多，但同一份数据上试过很多变体，没有做多重检验修正。',
    '面板只含现存股票，“买最弱的”受幸存者偏差影响最大（后来退市的股票当时正是最弱的那批），真实收益大概率低于回测。',
    '成员少于约 60 只的小行业在研究里不起作用；对照实验：行业平静时同样选法是负收益，说明赚的是“行业恐慌”这个条件。',
)


def default_config() -> DipConfig:
    """行业恐慌默认参数：杠杆 1 倍（研究里 1x–1.5x 最合适，2x 以上担保比例逼近平仓线）。"""
    return DipConfig(leverage=1.0)


# ---------------------------------------------------------------- 行业分类
@dataclass
class Classification:
    labels: np.ndarray          # int16 [n_stocks]，第几个行业；-1 = 对不上
    codes: list                 # 申万一级代码
    names: list
    sizes: list                 # 面板里每个行业的股票数
    as_of: str                  # 分类文件日期
    n_mapped: int

    def name_of(self, j: int) -> str:
        k = int(self.labels[j])
        return self.names[k] if k >= 0 else ''


def industry_dir(catalog_path=None) -> Path:
    try:
        source = get_ready_data_source(catalog_path, dataset_id=INDUSTRY_DATASET)
    except DataCatalogError as exc:
        raise DipDataError(f'数据侧尚未交付 {INDUSTRY_DATASET}：{exc}') from exc
    paths = source['technical_check']['paths']
    if not paths:
        raise DipDataError(f'{INDUSTRY_DATASET} 在数据清单中没有文件路径')
    return Path(paths[0]['path'])


def load_classification(directory, panel_codes) -> Classification:
    """读目录里日期最新的 *.parquet（跳过 _raw/_receipts 等子目录和 ._ 文件），每只股票取开始日期最新的一条。"""
    import pandas as pd
    directory = Path(directory)
    files = sorted(p for p in directory.glob('*.parquet') if p.is_file() and not p.name.startswith('._'))
    if not files:
        raise DipDataError(f'{directory} 里没有行业分类文件')
    latest = files[-1]
    frame = pd.read_parquet(latest, columns=['code', 'start_date', 'l1_code'])
    frame = frame.dropna(subset=['code', 'l1_code']).sort_values(['code', 'start_date']).groupby('code').tail(1)
    l1 = dict(zip(frame['code'].astype(str), frame['l1_code'].astype(str)))
    symbols = [str(c).split('.')[-1] for c in panel_codes]
    raw = [l1.get(s, '') for s in symbols]
    codes = sorted({x for x in raw if x})
    index = {c: i for i, c in enumerate(codes)}
    labels = np.array([index.get(x, -1) for x in raw], np.int16)
    n_mapped = int((labels >= 0).sum())
    if n_mapped < len(symbols) * MIN_MAPPED_SHARE:
        raise DipDataError(f'只有 {n_mapped}/{len(symbols)} 只股票对得上申万行业，不继续')
    sizes = [int((labels == i).sum()) for i in range(len(codes))]
    return Classification(labels=labels, codes=codes, names=[SW_L1.get(c, c) for c in codes], sizes=sizes,
                          as_of=latest.stem, n_mapped=n_mapped)


def load_classification_for(panel: Panel, catalog_path=None) -> Classification:
    key = ('industry-class', str(catalog_path))
    if key not in panel.cache:
        panel.cache[key] = load_classification(industry_dir(catalog_path), panel.codes)
    return panel.cache[key]


# ---------------------------------------------------------------- 行业分
@dataclass
class IndustryState:
    z: np.ndarray               # [nd, n_ind] 行业分
    ret20: np.ndarray           # [nd, n_ind] 行业等权 20 日涨跌
    n: np.ndarray               # [nd, n_ind] 当天用来算行业收益的股票数


def compute_state(panel: Panel, cand: Candidates, cls: Classification, *, stop=None) -> IndustryState:
    import pandas as pd
    nd = len(panel.dates)
    ng = len(cls.codes)
    z = np.full((nd, ng), np.nan)
    r20 = np.full((nd, ng), np.nan)
    cnt = np.zeros((nd, ng), np.int32)
    prev_uni = np.vstack([np.zeros((1, panel.shape[1]), bool), cand.uni[:-1]])
    for g in range(ng):
        if stop is not None and stop.is_set():
            raise Cancelled()
        cols = np.nonzero(cls.labels == g)[0]
        if len(cols) == 0:
            continue
        c = panel.c[:, cols].astype(np.float64)
        r = np.full(c.shape, np.nan)
        r[1:] = c[1:] / c[:-1] - 1
        ok = prev_uni[:, cols] & np.isfinite(r)
        n = ok.sum(1)
        mean = np.where(n >= MIN_MEMBERS, np.where(ok, r, 0.0).sum(1) / np.maximum(n, 1), np.nan)
        s = pd.Series(mean)
        c20 = np.exp(np.log1p(s).rolling(RET_WINDOW, min_periods=RET_WINDOW).sum()) - 1
        sd = s.rolling(STD_WINDOW, min_periods=STD_MIN).std()
        with np.errstate(invalid='ignore', divide='ignore'):
            z[:, g] = (c20 / (sd * np.sqrt(RET_WINDOW))).to_numpy()
        r20[:, g] = c20.to_numpy()
        cnt[:, g] = n
    return IndustryState(z=z, ret20=r20, n=cnt)


def build_inputs(panel: Panel, cfg: DipConfig, cls: Classification, *, progress=None, stop=None):
    """返回 (Market, Candidates, IndustryState)，可直接喂给 engine.simulate / latest_signal。
    Market.z 换成“当天最弱行业的 z”，所以引擎里的 z <= 阈值 就等于“有行业触发”；Candidates.e6 换成触发行业里的可交易股票。"""
    key = ('industry-inputs', cls.as_of, float(cfg.z_threshold), float(cfg.min_amount), float(cfg.min_price))
    if key in panel.cache:
        return panel.cache[key]
    market, cand = compute_features(panel, cfg.min_amount, cfg.min_price, progress=progress, stop=stop)
    state = compute_state(panel, cand, cls, stop=stop)
    trig = np.isfinite(state.z) & (state.z <= cfg.z_threshold)
    nd, nc = panel.shape
    in_trig = np.zeros((nd, nc), bool)
    mapped = np.nonzero(cls.labels >= 0)[0]
    in_trig[:, mapped] = trig[:, cls.labels[mapped]]
    pool = cand.uni & in_trig & np.isfinite(cand.ret20)
    zmin = np.where(np.isfinite(state.z), state.z, np.inf).min(axis=1)
    zmin = np.where(np.isfinite(zmin), zmin, np.nan)
    fake_market = Market(mret=market.mret, mk20=market.mk20, z=zmin, count=market.count)
    fake_cand = Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=cand.ret20)
    out = (fake_market, fake_cand, state)
    panel.cache[key] = out
    return out


def run_backtest(panel: Panel, cfg: DipConfig, cls: Classification, *, progress=None, stop=None) -> dict:
    from quantlab.dipbuy.backtest import CAVEATS as MARKET_CAVEATS, RUN_FORMAT, content_hash
    market, cand, _ = build_inputs(panel, cfg, cls, progress=progress, stop=stop)
    raw = simulate(panel, market, cand, cfg, progress=progress, stop=stop)
    summary = summarize(panel, market, raw, cfg)
    cv = curve(panel, market, raw)
    meta = panel.meta or {}
    result = dict(
        format=RUN_FORMAT, kind='industry', engine_version=ENGINE_VERSION, config=cfg.to_dict(), config_hash=cfg.hash(),
        classification=dict(as_of=cls.as_of, n_mapped=cls.n_mapped, n_industries=len(cls.codes)),
        panel={k: meta.get(k) for k in ('signature', 'first_date', 'last_date', 'n_stocks', 'n_days')} | {
            'last_date': panel.last_date, 'n_stocks': int(panel.shape[1]), 'n_days': int(panel.shape[0])},
        summary=summary, curve=cv, drawdown=drawdown_series(cv['equity']), trades=raw['trades'],
        caveats=list(CAVEATS) + [c for c in MARKET_CAVEATS if '幸存者' not in c])
    result['content_hash'] = content_hash(result)
    return result


# ---------------------------------------------------------------- 当日信号
def latest_industry_signal(panel: Panel, cfg: DipConfig, cls: Classification, *, equity: float | None = None,
                           day: str | None = None, names: dict | None = None, top: int | None = None) -> dict:
    """某个交易日收盘后的行业恐慌信号：31 个行业的分、触发的行业，以及全局按 20 日跌幅混排的候选。"""
    market, cand, state = build_inputs(panel, cfg, cls)
    real_market, _ = compute_features(panel, cfg.min_amount, cfg.min_price)
    sig = latest_signal(panel, market, cand, cfg, equity=equity, day=day, names=names, top=top)
    t = sig['index']
    rows = []
    for g in range(len(cls.codes)):
        zg = state.z[t, g]
        rows.append(dict(code=cls.codes[g], name=cls.names[g], stocks=cls.sizes[g], members=int(state.n[t, g]),
                         ret20=None if not np.isfinite(state.ret20[t, g]) else float(state.ret20[t, g]),
                         z=None if not np.isfinite(zg) else float(zg),
                         triggered=bool(np.isfinite(zg) and zg <= cfg.z_threshold)))
    rows.sort(key=lambda r: (r['z'] is None, r['z'] if r['z'] is not None else 0.0))
    index = {str(c): i for i, c in enumerate(panel.codes)}
    for pick in sig['picks']:
        j = index.get(pick['code'])
        pick['industry'] = cls.name_of(j) if j is not None else ''
    sig['industries'] = rows
    sig['triggered'] = [r['name'] for r in rows if r['triggered']]
    sig['market_z'] = None if not np.isfinite(real_market.z[t]) else float(real_market.z[t])
    sig['classification'] = dict(as_of=cls.as_of, n_mapped=cls.n_mapped)
    return sig

