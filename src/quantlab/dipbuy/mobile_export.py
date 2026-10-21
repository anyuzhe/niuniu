"""手机版快照：把策略工作台里“今日信号 / 前向跟踪 / 我的持仓”（另带研究线 E6 的前向记录，见 _e6_view）算成一份加密的 JSON，推到自己的服务器，
手机上的网页（PWA，源码在 web/mobile_bench/）下载后在本地解密显示。

  * 只读：手机页只显示，没有任何写入；持仓仍然只在本机录入、修改；
  * 数据在本机加密后才离开电脑（AES-256-GCM，口令经 PBKDF2-SHA256 派生密钥）；服务器上只有静态页面和密文，看不到持仓和信号；
  * 口令存在 <output>/_home/mobile_passphrase（权限 600），推送配置存在 <output>/_home/mobile_publish.json；都在 artifacts/ 里，不进 git；
  * 每次数据变新、台账记完（autorecord.run_if_new）后自动推一次；持仓改了想立刻看到，手动：
        python -m quantlab.dipbuy.mobile_export push --output artifacts
  * 除了结算前向记录（沿用工作台的 settle_ledger，和打开页面时做的事一样）之外，不改任何状态。
"""
from __future__ import annotations

import base64
import json
import math
import re
import os
import secrets
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from quantlab.dipbuy import autorecord, engine, fusion, industry, mobile_overview, portfolio, tracker

SNAPSHOT_FORMAT = 'niuniu-mobile-snapshot-v1'
ENVELOPE_FORMAT = 'niuniu-mobile-envelope-v1'
CONFIG_FORMAT = 'niuniu-mobile-publish-v1'
KDF_ITERATIONS = 300_000
MIN_PASSPHRASE = 12
MAX_LIST = 40            # 信号里的长列表（行业、候选…）手机上只看前面这些
MAX_CURVE = 400          # 净值曲线最多这么多个点
MAX_RECORDS = 12         # 每本台账给手机最近这么多条记录
MAX_TRADES = 30
FUSION_VARIANTS = ('D', 'D1', 'D2', 'D3', 'D4')
KIND_OF = {'D': 'fusion', 'D1': 'fusion1', 'D2': 'fusion2', 'D3': 'fusion3', 'D4': 'fusion4'}
# 策略 F（组合层，用户 2026-10-21 定名）：E6 一份 + D4 一份，每月第一个开市日调回比例。值 = E6 那份占总资产的比例
F_SPLIT = {'F1': 0.30, 'F2': 0.50}
F_FILTER = ('F3', 'F4')   # F3（10-21）、F4（10-22 用户定名，候选）：不是两份钱的组合，是 E6 全仓一只票再加条件；没有 D4 那份、不调仓


# ---------------------------------------------------------------- 文件与配置
def _home(output) -> Path:
    return Path(output).resolve() / '_home'


def _config_path(output) -> Path:
    return _home(output) / 'mobile_publish.json'


def _passphrase_path(output) -> Path:
    return _home(output) / 'mobile_passphrase'


def _write_private(path: Path, text: str) -> None:
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('目录或文件不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def load_config(output) -> dict | None:
    """没配置（或配置不完整）返回 None。配置：{host, remote_dir, url}；host 是 ssh 能直接连的地址，如 root@1.2.3.4。"""
    path = _config_path(output)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('format') != CONFIG_FORMAT:
        return None
    if not all(isinstance(value.get(k), str) and value[k] for k in ('host', 'remote_dir')):
        return None
    return dict(host=value['host'], remote_dir=value['remote_dir'], url=value.get('url') or '', enabled=bool(value.get('enabled', True)))


def save_config(output, *, host: str, remote_dir: str, url: str = '', enabled: bool = True) -> dict:
    if not host or any(c in host for c in ' ;&|$`\'"\n'):
        raise ValueError('host 不合法')
    if not remote_dir.startswith('/') or any(c in remote_dir for c in ' ;&|$`\'"\n') or '..' in remote_dir:
        raise ValueError('remote_dir 必须是不含空格和特殊字符的绝对路径')
    value = dict(format=CONFIG_FORMAT, host=host, remote_dir=remote_dir.rstrip('/'), url=url, enabled=bool(enabled))
    _write_private(_config_path(output), json.dumps(value, ensure_ascii=False, indent=1))
    return value


def load_passphrase(output) -> str | None:
    env = os.environ.get('NIUNIU_MOBILE_PASSPHRASE')
    if env:
        return env
    path = _passphrase_path(output)
    if not path.is_file() or path.is_symlink():
        return None
    text = path.read_text(encoding='utf-8').strip()
    return text or None


def set_passphrase(output, passphrase: str | None = None) -> str:
    """不给口令就随机生成一个（4 组 4 位小写字母数字，约 82 位熵，手机上好输入）。已有口令会被换掉，手机要重新输入。"""
    if passphrase is None:
        alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
        passphrase = '-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f'口令至少 {MIN_PASSPHRASE} 位')
    _write_private(_passphrase_path(output), passphrase + '\n')
    return passphrase


# ---------------------------------------------------------------- 加密
def _derive(passphrase: str, salt: bytes, iterations: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(passphrase.encode('utf-8'))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def encrypt_snapshot(snapshot: dict, passphrase: str, *, iterations: int = KDF_ITERATIONS) -> dict:
    """AES-256-GCM。每次随机盐和随机 12 字节 iv；格式串当作附加认证数据，页面解密时用同一个。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f'口令至少 {MIN_PASSPHRASE} 位')
    salt, iv = os.urandom(16), os.urandom(12)
    key = _derive(passphrase, salt, iterations)
    plain = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    ct = AESGCM(key).encrypt(iv, plain, ENVELOPE_FORMAT.encode('ascii'))
    return dict(format=ENVELOPE_FORMAT, kdf='PBKDF2-SHA256', iterations=int(iterations), salt=_b64(salt), iv=_b64(iv), ct=_b64(ct),
                generated_at=snapshot.get('generated_at'), data_date=snapshot.get('data_date'))


def decrypt_envelope(envelope: dict, passphrase: str) -> dict:
    """和手机页做的事一样；主要给测试用。口令错或内容被改都会抛 ValueError。"""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if envelope.get('format') != ENVELOPE_FORMAT:
        raise ValueError('不是手机快照')
    key = _derive(passphrase, base64.b64decode(envelope['salt']), int(envelope['iterations']))
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(envelope['iv']), base64.b64decode(envelope['ct']), ENVELOPE_FORMAT.encode('ascii'))
    except InvalidTag as exc:
        raise ValueError('口令不对，或内容被改过') from exc
    return json.loads(plain.decode('utf-8'))


# ---------------------------------------------------------------- 组装快照
def _clean(x):
    """变成纯 JSON：numpy 标量转 Python、NaN/inf 变 None。"""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        f = float(x)
        return f if math.isfinite(f) else None
    if x is None or isinstance(x, str):
        return x
    return str(x)


def _trim(sig: dict) -> dict:
    """顶层的长列表只留前 MAX_LIST 个，并记下总数。"""
    out = {}
    for k, v in sig.items():
        if isinstance(v, list) and len(v) > MAX_LIST:
            out[k] = v[:MAX_LIST]
            out[k + '_total'] = len(v)
        else:
            out[k] = v
    return out


def _curve(dates, equity) -> dict:
    n = len(dates)
    step = max(1, math.ceil(n / MAX_CURVE))
    idx = list(range(0, n, step))
    if idx and idx[-1] != n - 1:
        idx.append(n - 1)
    return dict(dates=[str(dates[i]) for i in idx], equity=[None if equity[i] is None else round(float(equity[i]), 4) for i in idx])


def _forward_view(output, panel, cls, kind: str) -> dict:
    try:
        settled = tracker.settle_ledger(output, panel, kind=kind)
        if kind == 'market':
            pf = tracker.forward_portfolio(output, panel)
        elif kind == 'industry':
            pf = tracker.forward_portfolio(output, panel, kind='industry', features=lambda cfg: industry.build_inputs(panel, cfg, cls)[:2])
        else:
            pf = fusion.forward_portfolio(output, panel, cls, kind=kind)
    except Exception as exc:       # 一本算不出来不影响其它几本
        return dict(error=f'{type(exc).__name__}: {exc}')
    ledger = settled['ledger']
    records = []
    for r in reversed(settled['records'][-MAX_RECORDS:]):
        res = r.get('result') or {}
        records.append(dict(signal_date=r.get('signal_date'), status=r.get('status'), z=r.get('z'), fired=r.get('fired'),
                            n_picks=len(r.get('picks') or []), mean_ret=res.get('mean_ret'), mean_mtm=res.get('mean_mtm'),
                            n_filled=res.get('n_filled'), n_closed=res.get('n_closed'),
                            rows=[{k: p.get(k) for k in ('sleeve', 'code', 'name', 'ret', 'mtm', 'status', 'in_plan', 'entry_date', 'exit_date')}
                                  for p in (res.get('rows') or r.get('picks') or []) if p.get('in_plan', True)][:MAX_FORWARD_ROWS]))
    view = dict(start_date=ledger.get('start_date'), config_hash=ledger.get('config_hash'), summary=settled['summary'], records=records)
    if pf:
        view['portfolio'] = dict(start_date=pf['start_date'], curve=_curve(pf['dates'], pf['equity']), summary=pf['summary'],
                                 mismatched=pf.get('mismatched') or [], open_positions=(pf.get('open_positions') or [])[:MAX_LIST],
                                 trades=(pf.get('trades') or [])[-MAX_TRADES:], n_trades=len(pf.get('trades') or []))
    return _clean(view)


def _signal_view(kind: str, panel, cls, names, equity) -> dict:
    try:
        if kind in KIND_OF.values():
            cfg = {'fusion': fusion.default_config, 'fusion1': fusion.d1_config, 'fusion2': fusion.d2_config,
                   'fusion3': fusion.d3_config, 'fusion4': fusion.d4_config}[kind]()
            inp = fusion.build_inputs(panel, cfg, cls)
            sig = fusion.latest_fusion_signal(panel, inp, cfg, equity=equity, names=names)
            return _clean(_trim(sig))
        sig, _ = autorecord.build_signal(kind, panel, cls, names)
        return _clean(_trim(sig))
    except Exception as exc:
        return dict(error=f'{type(exc).__name__}: {exc}')


def _holdings_view(output, panel, cls, names, today: date) -> dict:
    data = portfolio.load(output)
    equity = data['equity_wan'] * 1e4
    plans = {}
    rows = None
    keys = ('data_date', 'plan_day', 'stale', 'sells', 'buys', 'spares', 'sleeves', 'notes',
            'invested_after', 'proceeds', 'new_money', 'gate_open', 'fired', 'hold_days')
    d4 = None
    for variant in FUSION_VARIANTS:
        try:
            cfg = fusion.config_for(variant)
            inp = fusion.build_inputs(panel, cfg, cls)
            plan = portfolio.plan_operations(panel, inp, cfg, data['holdings'], equity=equity, names=names, today=today)
        except Exception as exc:
            plans[variant] = dict(error=f'{type(exc).__name__}: {exc}')
            continue
        if variant == 'D4':
            d4 = (cfg, inp)
        if rows is None:
            rows = plan['holdings']
        plans[variant] = {k: plan[k] for k in keys}
    # 策略 F：D4 那份钱 = 总资产 ×（1 − E6 的比例），按这份钱照 D4 的规则算明天的买卖；E6 那份不在这里（9:25 提醒里算）
    for fid, w in F_SPLIT.items():
        if d4 is None:
            plans[fid] = dict(error='D4 没算出来，F 的 D4 那份也算不出来')
            continue
        try:
            plan = portfolio.plan_operations(panel, d4[1], d4[0], data['holdings'], equity=equity * (1 - w), names=names, today=today)
        except Exception as exc:
            plans[fid] = dict(error=f'{type(exc).__name__}: {exc}')
            continue
        p = {k: plan[k] for k in keys}
        p['notes'] = [f'{fid}：D4 那份 = 总资产 × {1 - w:.0%} = {equity * (1 - w) / 1e4:,.1f} 万，按这份钱照 D4 的规则算；'
                      f'E6 那份 = 总资产 × {w:.0%} = {equity * w / 1e4:,.1f} 万，买卖看 9:25 的提醒。'
                      '如果 E6 那只票也录进了持仓又没标层，它会被当成占用 D4 那份的钱。'] + list(p.get('notes') or [])
        p['f'] = dict(w_e6=w, w_d4=round(1 - w, 4), e6_amount=equity * w, d4_amount=equity * (1 - w))
        plans[fid] = p
    return _clean(dict(equity_wan=data['equity_wan'], n_holdings=len(data['holdings']), holdings=rows or [], plans=plans))


E6_FORMAT = 'niuniu-e6-forward-v1'
E6_SOURCE = Path('/Volumes/Lexar/niuniu-research-ext/e6_fwd_2026Q4/e6_fwd_mobile.json')
MAX_E6_SIGNALS = 40


def _e6_view(path=None):
    """策略 E6（龙头扫板，研究中）的前向记录。研究目录里的记录器每个交易日 19:00 写 e6_fwd_mobile.json，这里只挑展示要用的部分带上。
    文件不在返回 None（手机页那一栏显示"还没有"）；读坏了、格式不对给 error，不影响别的页。路径可用环境变量 NIUNIU_E6_FORWARD 改。"""
    p = Path(path or os.environ.get('NIUNIU_E6_FORWARD') or E6_SOURCE)
    if not p.is_file():
        return None
    try:
        value = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return dict(error=f'{type(exc).__name__}: {exc}')
    if not isinstance(value, dict) or value.get('format') != E6_FORMAT:
        return dict(error='E6 前向记录的格式不认识')
    out = {k: value.get(k) for k in ('generated_at', 'data_date', 'fwd_start', 'summary', 'next', 'n_signals')}
    signals = [r for r in (value.get('signals') or []) if isinstance(r, dict)]
    out['signals'] = signals[:MAX_E6_SIGNALS]
    out['holding'] = [r for r in signals if str(r.get('status') or '').startswith('持有中')]
    out['curve'] = _e6_curve(p.parent / E6_CURVE_NAME)
    out['live'] = _e6_live(p.parent / E6_LIVE_NAME)
    return _clean(out)


E6_LIVE_FORMAT = 'niuniu-e6-live-v1'
E6_LIVE_NAME = 'e6_live.json'


def _e6_live(path):
    """当天的 E6 实盘提醒（研究目录 e6_live.py 9:25 和 14:50 写）：第 1 只、云条件单怎么设、持仓封没封住。只是提醒，不下单。"""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('format') != E6_LIVE_FORMAT:
        return None
    out = {k: value.get(k) for k in ('day', 'generated_at', 'open', 'close', 'error')}
    if isinstance(out.get('open'), dict) and isinstance(out['open'].get('top'), list):
        out['open'] = dict(out['open'], top=out['open']['top'][:6], missing=(out['open'].get('missing') or [])[:20])
    out['prep'] = _e6_prep(Path(path).parent / E6_CANDS_NAME)
    return out


E6_CANDS_NAME = 'e6_live_cands.json'


def _e6_prep(path):
    """08:40 准备的候选表（e6_live.py prep）：只带日期、几只、有没有出错，手机「今天」页用。"""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('format') != 'niuniu-e6-live-cands-v1':
        return None
    f3 = value.get('f3') if isinstance(value.get('f3'), dict) else None      # F3 的两个条件里按天的那部分：昨收大盘 z 在不在平稳段
    return dict(day=value.get('day'), prev=value.get('prev'), generated_at=value.get('generated_at'),
                n=len(value.get('cands') or []), error=value.get('error'),
                f3=None if f3 is None else {k: f3.get(k) for k in ('z', 'calm', 'error')})


F_FORMAT = 'niuniu-f-combo-v1'
F_SOURCE = Path('/Volumes/Lexar/niuniu-research-ext/e6_fwd_2026Q4/f_combo.json')


def _month_last_day(d: date) -> date:
    return (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1))


def _f_view(snap: dict, path=None):
    """策略 F（组合层）：研究目录 f_combo.py 每个交易日 19:30 写 f_combo.json（回测、前向记录）。这里再按账户总资产算两份各多少钱，
    以及下一个开市日（plan_day）是不是调仓日（每月第一个开市日）。文件不在返回 None；读坏了给 error，不影响别的页。"""
    p = Path(path or os.environ.get('NIUNIU_F_COMBO') or F_SOURCE)
    if not p.is_file():
        return None
    try:
        value = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return dict(error=f'{type(exc).__name__}: {exc}')
    if not isinstance(value, dict) or value.get('format') != F_FORMAT:
        return dict(error='策略 F 数据的格式不认识')
    h = snap.get('holdings') or {}
    equity = float(h.get('equity_wan') or 0) * 1e4 if not h.get('error') else None
    plan_day = date.fromisoformat(str(snap['plan_day'])[:10])
    data_day = date.fromisoformat(str(snap['data_date'])[:10])
    on_plan_day = plan_day.month != data_day.month
    nxt = plan_day if on_plan_day else autorecord.next_open_day(_month_last_day(plan_day).isoformat())
    bt = value.get('backtest') or {}
    defs = []
    for d in value.get('defs') or []:
        fid, w = d.get('id'), float(d.get('w_e6') or 0)
        if fid in F_FILTER:          # F3 / F4：全部钱按 E6 加条件做，回测和 E6 全仓对照
            b = bt.get(fid) or {}
            defs.append(dict(id=fid, kind='e6_filter', name=d.get('name'), rule=d.get('rule'), note=d.get('note'), cond=d.get('cond'),
                             w_e6=1.0, w_d4=0.0, e6_amount=equity, d4_amount=None if equity is None else 0.0,
                             backtest={k: b.get(k) for k in ('first', 'last', 'n_signals', 'n_e6_signals', 'n_trades', 'per_trade', 'win',
                                                              'total', 'e6_total', 'segs', 'years', 'dates', 'equity')}))
            continue
        if fid not in F_SPLIT:
            continue
        b = bt.get(fid) or {}
        defs.append(dict(id=fid, name=d.get('name'), w_e6=w, w_d4=round(1 - w, 4),
                         e6_amount=None if equity is None else equity * w, d4_amount=None if equity is None else equity * (1 - w),
                         backtest={k: b.get(k) for k in ('total', 'segs', 'years', 'dates', 'equity')}))
    fw = value.get('forward') or {}
    return _clean(dict(generated_at=value.get('generated_at'), rule=value.get('rule'), note=value.get('note'), equity=equity,
                       defs=defs, backtest={k: bt.get(k) for k in ('first', 'last', 'n_days', 'corr_daily', 'E6', 'D4')},
                       forward={k: fw.get(k) for k in ('start', 'e6_data_date', 'd4_start', 'e6_holding', 'f3_holding', 'f3_signals',
                                                       'f4_holding', 'f4_signals', 'n', 'note', 'dates', 'series')},
                       rebalance=dict(on_plan_day=on_plan_day, next=nxt.isoformat(), rule='每月第一个开市日')))


E6_CURVE_FORMAT = 'niuniu-e6-curve-v1'
E6_CURVE_NAME = 'e6_curve_hist.json'
MAX_E6_CURVE_POINTS = 400


def _e6_curve(path):
    """E6 的历史账户曲线（研究目录 e6_curve_hist.py 生成，月末点）。没有或读不出就是 None，E6 页只是不画图。"""
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('format') != E6_CURVE_FORMAT:
        return None

    def one(v):
        dates, equity = v.get('dates') or [], v.get('equity') or []
        if not isinstance(dates, list) or not isinstance(equity, list) or len(dates) != len(equity) or len(dates) < 2:
            return None
        keep = {k: v.get(k) for k in ('first', 'last', 'slots', 'total', 'years', 'segs', 'note')}
        return dict(keep, dates=dates[-MAX_E6_CURVE_POINTS:], equity=equity[-MAX_E6_CURVE_POINTS:])
    six = one(value)                     # 顶层：每个信号 1/6 资金
    if six is None:
        return None
    full = value.get('full')             # 全仓一只票（可选）
    six['full'] = one(dict(full, first=value.get('first'), last=value.get('last'))) if isinstance(full, dict) else None
    return six


def _results_table():
    """策略说明页的回测对照表；抓不到（比如没装 Qt）就不放，手机页自带一份同样的说明。"""
    try:
        from quantlab.desktop.strategy_guide import RESULT_HEAD, RESULTS
        return dict(head=list(RESULT_HEAD), rows=[list(r) for r in RESULTS])
    except Exception:
        return None


def build_snapshot(output, panel, cls, names, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(autorecord.SHANGHAI)
    today = now.astimezone(autorecord.SHANGHAI).date()
    equity = portfolio.load(output)['equity_wan'] * 1e4
    kinds = autorecord.KINDS
    labels = autorecord.LABELS
    snap = dict(format=SNAPSHOT_FORMAT, generated_at=now.isoformat(timespec='seconds'), data_date=str(panel.last_date),
                plan_day=autorecord.next_open_day(str(panel.last_date)).isoformat(),
                fresh=autorecord.is_fresh(str(panel.last_date), now), kinds=list(kinds), labels=dict(labels),
                signals={}, forward={}, holdings=None, results=_results_table(),
                note='纸面记录，不下单、不连券商；手机页只读。')
    for kind in kinds:
        snap['signals'][kind] = _signal_view(kind, panel, cls, names, equity)
        snap['forward'][kind] = _forward_view(output, panel, cls, kind)
    try:
        snap['holdings'] = _holdings_view(output, panel, cls, names, today)
    except Exception as exc:
        snap['holdings'] = dict(error=f'{type(exc).__name__}: {exc}')
    try:
        snap['e6'] = _e6_view()
    except Exception as exc:       # E6 是研究线，读不出来不影响抄底这几本
        snap['e6'] = dict(error=f'{type(exc).__name__}: {exc}')
    try:
        snap['f'] = _f_view(snap)
    except Exception as exc:       # 策略 F 读不出来也不影响别的
        snap['f'] = dict(error=f'{type(exc).__name__}: {exc}')
    snap['overview'] = _overview_view(panel, cls, snap, output)
    _fill_names(snap, names or {})
    snap['stocks'] = _stock_series(panel, snap, names)
    return snap


MAX_FORWARD_ROWS = 40     # 一条前向记录最多列多少只（策略 D 每层最多 20 只）


def _fill_names(x, names: dict) -> None:
    """快照里凡是有代码没名称的行（例如前向组合的模拟持仓），按名称表补上，手机上才不只显示代码。"""
    if isinstance(x, dict):
        c = x.get('code')
        if isinstance(c, str) and _CODE.match(c) and not x.get('name') and names.get(c):
            x['name'] = names[c]
        for v in x.values():
            _fill_names(v, names)
    elif isinstance(x, list):
        for v in x:
            _fill_names(v, names)


STOCK_DAYS = 60          # 手机上点一只股票看的最近走势（交易日）
MAX_STOCKS = 400
_CODE = re.compile(r'^(sh|sz|bj)\.\d{6}$')


def _codes_in(x, out):
    if isinstance(x, dict):
        c = x.get('code')
        if isinstance(c, str) and _CODE.match(c) and c not in out:
            out.append(c)
        for v in x.values():
            _codes_in(v, out)
    elif isinstance(x, list):
        for v in x:
            _codes_in(v, out)
    return out


def _r(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if math.isfinite(v) else None


def _stock_series(panel, snap: dict, names, qfq_dir=None) -> dict:
    """快照里出现过的每只股票，附最近 STOCK_DAYS 个交易日的日 K（前复权开高低收 + 成交量），手机上点一行就能看 K 线（不再联网）。
    日 K 读数据清单里 READY 的前复权日线；某只读不到时退回面板里的前复权收盘价（只有收盘，没有开高低）。"""
    try:
        codes = _codes_in({k: v for k, v in snap.items() if k != 'stocks'}, [])[:MAX_STOCKS]
        index = {str(c): i for i, c in enumerate(panel.codes)}
        n = min(STOCK_DAYS, len(panel.dates))
        rows = slice(len(panel.dates) - n, len(panel.dates))
        dates = [str(d) for d in panel.dates[rows]]
        pos = {d: i for i, d in enumerate(dates)}
        if qfq_dir is None:
            try:
                from quantlab.dipbuy import panel as dpanel
                qfq_dir = dpanel.ready_dirs()[0]
            except Exception:
                qfq_dir = None
        series = {}
        for code in codes:
            item = dict(name=(names or {}).get(code))
            bars = None
            if qfq_dir is not None:
                f = Path(qfq_dir) / (code.replace('.', '_', 1) + '.parquet')
                if f.is_file():
                    try:
                        import pandas as pd
                        df = pd.read_parquet(f, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df['date'] = df['date'].astype(str).str[:10]
                        df = df[df['date'].isin(pos)]
                        bars = {k: [None] * n for k in ('o', 'h', 'l', 'c', 'v')}
                        for d, o, h, lo, c, v in df[['date', 'open', 'high', 'low', 'close', 'volume']].itertuples(index=False):
                            i = pos[d]
                            bars['o'][i], bars['h'][i], bars['l'][i], bars['c'][i] = _r(o), _r(h), _r(lo), _r(c)
                            bars['v'][i] = int(v) if v is not None and math.isfinite(float(v)) else None
                    except Exception:
                        bars = None
            if bars is None or not any(x is not None for x in bars['c']):
                j = index.get(code)
                if j is None:
                    continue
                bars = dict(c=[_r(v) for v in panel.c[rows, j]])
            item.update(bars)
            series[code] = item
        return _clean(dict(dates=dates, adjust='qfq', series=series))
    except Exception as exc:       # 走势算不出来不影响别的
        return dict(error=f'{type(exc).__name__}: {exc}')


def _overview_view(panel, cls, snap: dict, output=None) -> dict:
    """首页「市场概览」。算不出来就给 error，不拖累别的页。"""
    try:
        cfg = fusion.d4_config()
        inp = fusion.build_inputs(panel, cfg, cls)
        sig = snap['signals'].get('fusion4') or {}
        if sig.get('error'):
            raise ValueError(sig['error'])
        ov = mobile_overview.build_overview(panel, inp, sig, snap['signals'], snap.get('holdings'), as_of=snap['data_date'],
                                            plan_day=snap['plan_day'], fresh=snap['fresh'], labels=snap['labels'],
                                            threshold=cfg.z_threshold)
        ov['limit_board'] = mobile_overview.limit_board_view(output, snap['data_date']) if output is not None else None
        return _clean(ov)
    except Exception as exc:
        return dict(error=f'{type(exc).__name__}: {exc}')


# ---------------------------------------------------------------- 推送
def push_bytes(host: str, remote_path: str, data: bytes, *, timeout: float = 60) -> None:
    """走 ssh 把内容写到服务器上的临时文件再 mv 过去（原子替换，读的人不会看到半截文件）。host 用 BatchMode，不会卡在输密码。"""
    if any(c in remote_path for c in ' ;&|$`\'"\n') or not remote_path.startswith('/'):
        raise ValueError('remote_path 不合法')
    cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host,
           f'cat > {remote_path}.tmp && chmod 644 {remote_path}.tmp && mv {remote_path}.tmp {remote_path}']
    proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError('推送失败：' + proc.stderr.decode('utf-8', 'replace').strip()[:300])


def publish(output, panel, cls, names, *, now: datetime | None = None, config: dict | None = None, passphrase: str | None = None) -> dict:
    """算快照 → 加密 → 推到服务器的 data.json。没配置或没口令返回 skipped，不抛错（它挂在自动记录后面，不能拖累记录）。"""
    config = config or load_config(output)
    if not config or not config.get('enabled', True):
        return dict(status='skipped', message='没有配置手机版推送')
    passphrase = passphrase or load_passphrase(output)
    if not passphrase:
        return dict(status='skipped', message='没有设置手机版口令')
    try:
        snap = build_snapshot(output, panel, cls, names, now=now)
        env = encrypt_snapshot(snap, passphrase)
        data = json.dumps(env, separators=(',', ':')).encode('ascii')
        push_bytes(config['host'], config['remote_dir'] + '/data.json', data)
    except Exception as exc:
        return dict(status='error', message=f'{type(exc).__name__}: {exc}')
    return dict(status='pushed', message=f"已推送 {len(data) / 1024:.0f} KB，数据截至 {snap['data_date']}", bytes=len(data), data_date=snap['data_date'])


# ---------------------------------------------------------------- 命令行
def _load_inputs(output, catalog_path):
    from quantlab.dipbuy import panel as dpanel
    panel = dpanel.load_panel(output, catalog_path)
    names = dpanel.load_names(catalog_path)
    cls = industry.load_classification_for(panel, catalog_path)
    return panel, cls, names


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='手机版快照：配置、推送')
    ap.add_argument('action', choices=['setup', 'push', 'build', 'status'])
    ap.add_argument('--output', required=True)
    ap.add_argument('--catalog', default=None, help='数据清单文件；不给就用默认位置（和桌面版一样）')
    ap.add_argument('--host', help='setup：ssh 地址，如 root@1.2.3.4')
    ap.add_argument('--remote-dir', help='setup：服务器上站点目录（绝对路径）')
    ap.add_argument('--url', default='', help='setup：手机上打开的网址（只用于显示）')
    ap.add_argument('--new-passphrase', action='store_true', help='setup：生成新口令（换掉旧的）')
    ap.add_argument('--out', help='build：把加密文件写到这里而不是推送')
    args = ap.parse_args(argv)
    if args.action == 'setup':
        if not (args.host and args.remote_dir):
            ap.error('setup 需要 --host 和 --remote-dir')
        save_config(args.output, host=args.host, remote_dir=args.remote_dir, url=args.url)
        if args.new_passphrase or not load_passphrase(args.output):
            set_passphrase(args.output)
            print('已生成新口令，保存在 ' + str(_passphrase_path(args.output)) + '（在手机页第一次打开时输入；查看：cat 这个文件）')
        print('配置已保存：', _config_path(args.output))
        return 0
    if args.action == 'status':
        cfg = load_config(args.output)
        print('配置：', cfg or '没有')
        print('口令：', '已设置' if load_passphrase(args.output) else '没有')
        return 0
    catalog = Path(args.catalog) if args.catalog else None
    panel, cls, names = _load_inputs(args.output, catalog)
    if args.action == 'build':
        passphrase = load_passphrase(args.output)
        if not passphrase:
            ap.error('没有口令：先运行 setup')
        env = encrypt_snapshot(build_snapshot(args.output, panel, cls, names), passphrase)
        Path(args.out or 'mobile_data.json').write_text(json.dumps(env, separators=(',', ':')), encoding='ascii')
        print('已写出', args.out or 'mobile_data.json')
        return 0
    result = publish(args.output, panel, cls, names)
    print(result['status'], result['message'])
    return 0 if result['status'] in ('pushed', 'skipped') else 1


if __name__ == '__main__':
    raise SystemExit(main())
