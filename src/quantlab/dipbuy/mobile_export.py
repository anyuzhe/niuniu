"""手机版快照：把策略工作台里“今日信号 / 前向跟踪 / 我的持仓”算成一份加密的 JSON，推到自己的服务器，
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
import os
import secrets
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from quantlab.dipbuy import autorecord, engine, fusion, industry, portfolio, tracker

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
                                  for p in (res.get('rows') or r.get('picks') or []) if p.get('in_plan', True)][:12]))
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
    for variant in FUSION_VARIANTS:
        try:
            cfg = fusion.config_for(variant)
            inp = fusion.build_inputs(panel, cfg, cls)
            plan = portfolio.plan_operations(panel, inp, cfg, data['holdings'], equity=equity, names=names, today=today)
        except Exception as exc:
            plans[variant] = dict(error=f'{type(exc).__name__}: {exc}')
            continue
        if rows is None:
            rows = plan['holdings']
        plans[variant] = {k: plan[k] for k in ('data_date', 'plan_day', 'stale', 'sells', 'buys', 'spares', 'sleeves', 'notes',
                                               'invested_after', 'proceeds', 'new_money', 'gate_open', 'fired', 'hold_days')}
    return _clean(dict(equity_wan=data['equity_wan'], n_holdings=len(data['holdings']), holdings=rows or [], plans=plans))


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
    return snap


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
