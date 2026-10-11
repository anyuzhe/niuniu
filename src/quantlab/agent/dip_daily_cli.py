"""不开牛牛也自动跑的每日流水线：后台入口与 macOS LaunchAgent（用户 2026-10-11 要求）。

每个交易日的顺序（上游不完成，下游不开始）：

  ① 值班程序 scripts/collect/scheduler.py：09:10 盘中记录器 → 15:45 通达信部分（daily_close_early）→
     16:30 起等 Baostock 发布后做收盘后日常更新并封存（daily_close_update）。逻辑、授权范围和自带的单实例锁都不改，
     这里只是让它不依赖客户端：后台任务每 5 分钟拉一次，已有值班程序（客户端开着时它在跑）就立刻退出，客户端关了就由后台这一份接手；
  ② 证据归档 com.niuniu.evidence-archive（evidence_scheduler）：18:00 起的涨停池、公告、前向参考、涨停板情绪库等，已经是独立后台任务；
  ③ 本模块 --tick：数据任务（early / update）都不在跑时，调 autorecord.run_if_new——面板指纹变了才记 7 本台账并推手机；
     面板没变但涨停板情绪库更新了（②比①晚），再推一次手机，让概览里的涨停板情绪是新的。

      python -m quantlab.agent.dip_daily_cli --output artifacts --tick
      python -m quantlab.agent.dip_daily_cli --output artifacts --run-duty
      python -m quantlab.agent.dip_daily_cli --output artifacts --install     # 装两个 LaunchAgent
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DUTY_LABEL = 'com.niuniu.duty-scheduler'
DAILY_LABEL = 'com.niuniu.dip-daily'
INTERVAL = 300
LIVE_JOBS = {'daily_close_early', 'daily_close_update'}
STATE_FORMAT = 'niuniu-dip-daily-v1'
REPO = Path(__file__).resolve().parents[3]


def _mine(output) -> Path:
    return Path(output).resolve() / '_home' / 'dip_daily.json'


def load_mine(output) -> dict:
    try:
        value = json.loads(_mine(output).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) and value.get('format') == STATE_FORMAT else {}
    except (OSError, ValueError):
        return {}


def save_mine(output, **fields) -> None:
    path = _mine(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = dict(load_mine(output), **fields, format=STATE_FORMAT)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)


def data_busy(jobs=None):
    """正在跑的收盘后数据任务（没有就是 None）。数据盘没接上时 DataUpdateJobs 读不到任务，也返回 None。"""
    if jobs is None:
        from quantlab.data.data_services import DataUpdateJobs
        jobs = DataUpdateJobs()
    return jobs._running(LIVE_JOBS)


def sentiment_token(output):
    """涨停板情绪库最新一份覆盖到哪天；没有库返回 None。"""
    try:
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        rows = [r for r in MarketSentimentLibrary(output).list() if 'error' not in r]
        return max(r['last_date'] for r in rows) if rows else None
    except Exception:
        return None


def _clean(last) -> bool:
    if not last:
        return False
    bad = any(r.get('status') == 'error' for r in (last.get('results') or {}).values())
    return not bad and (last.get('mobile') or {}).get('status') != 'error'


def tick(output, catalog_path=None, *, jobs=None, record=None, token=None):
    """一次检查，返回 {status, ...}：disabled / waiting / done / republished / idle / error。"""
    from quantlab.dipbuy import autorecord
    record = record or autorecord.run_if_new
    if not autorecord.load_state(output)['enabled']:
        return dict(status='disabled')
    busy = data_busy(jobs)
    if busy:
        return dict(status='waiting', reason=f"数据任务还在跑：{busy['job_id']} {busy['run_id']}")
    token = token if token is not None else sentiment_token(output)
    last = record(output, catalog_path)
    if last is not None:
        if _clean(last):
            save_mine(output, token=token)
        return dict(status='done', summary=autorecord.describe_last(last))
    mine = load_mine(output)
    if token and mine.get('token') != token and autorecord.load_state(output).get('last_signature'):
        forced = record(output, catalog_path, force=True)
        if forced is None:                     # 别的进程正在做 / 数据没开放：下次再说
            return dict(status='idle')
        if _clean(forced):
            save_mine(output, token=token)
        return dict(status='republished', summary=autorecord.describe_last(forced))
    return dict(status='idle')


def load_env_file(path, environ=None) -> int:
    """读 .env（KEY=VALUE，# 注释，已有的环境变量不覆盖）；返回新设置了几个。不打印任何值。"""
    environ = os.environ if environ is None else environ
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key and key not in environ:
            environ[key] = value
            n += 1
    return n


def run_duty() -> int:
    """后台跑值班程序（等价于启动脚本里的那一行，只是没有 --parent-pid，所以不会因客户端关闭而退出）。"""
    import runpy
    load_env_file(REPO / '.env')
    script = REPO / 'scripts' / 'collect' / 'scheduler.py'
    sys.argv = [str(script)]
    try:
        runpy.run_path(str(script), run_name='__main__')
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 0
    return 0


def agent_configs(output) -> dict:
    output = Path(output).resolve()
    base = {'WorkingDirectory': str(REPO), 'ProcessType': 'Background', 'StartInterval': INTERVAL, 'RunAtLoad': True,
            'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'}}
    return {
        DUTY_LABEL: dict(base, Label=DUTY_LABEL,
                         ProgramArguments=[sys.executable, '-m', 'quantlab.agent.dip_daily_cli', '--output', str(output), '--run-duty'],
                         StandardOutPath=str(output / 'scheduler.log'), StandardErrorPath=str(output / 'scheduler.error.log')),
        DAILY_LABEL: dict(base, Label=DAILY_LABEL,
                          ProgramArguments=[sys.executable, '-m', 'quantlab.agent.dip_daily_cli', '--output', str(output), '--tick'],
                          StandardOutPath=str(output / 'dip_daily.log'), StandardErrorPath=str(output / 'dip_daily.error.log')),
    }


def install_agents(output) -> list:
    if sys.platform != 'darwin':
        raise OSError('自动安装仅支持 macOS；其他平台可定时运行 --tick，并常驻 --run-duty。')
    import plistlib
    import subprocess
    folder = Path.home() / 'Library/LaunchAgents'
    folder.mkdir(parents=True, exist_ok=True)
    domain = 'gui/' + str(os.getuid())
    out = []
    for label, config in agent_configs(output).items():
        path = folder / (label + '.plist')
        if path.exists() and plistlib.loads(path.read_bytes()) != config:
            raise OSError('同名后台任务已有不同配置，请先检查 ' + str(path))
        path.write_bytes(plistlib.dumps(config))
        if subprocess.run(['launchctl', 'print', domain + '/' + label], capture_output=True, text=True).returncode != 0:
            result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
            if result.returncode:
                raise OSError('launchctl bootstrap ' + label + ': ' + result.stderr.strip())
        out.append(dict(label=label, plist=str(path), interval_seconds=INTERVAL))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='不开牛牛也自动跑的每日流水线：数据任务做完后记信号并推手机；值班程序常驻')
    parser.add_argument('--output', required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ('tick', 'run-duty', 'install'):
        modes.add_argument('--' + mode, action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.run_duty:
            return run_duty()
        if args.install:
            print(json.dumps(install_agents(args.output), ensure_ascii=False))
            return 0
        result = tick(args.output)
        if result['status'] not in ('idle', 'disabled'):
            print(json.dumps(dict(at=datetime.now().astimezone().isoformat(timespec='seconds'), **result), ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(json.dumps(dict(status='error', error=f'{type(error).__name__}: {error}'[:400]), ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
