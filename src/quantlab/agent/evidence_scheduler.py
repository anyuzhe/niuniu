"""After-close scheduler for public market evidence and the daily Baostock market snapshot.

The scheduler only runs when the host has enabled it. Each tick checks the trading calendar,
captures due sources for the most recent trading day that is still inside its after-close
window, and records attempts in a checksummed state file. It never captures intraday,
never backfills past the next session and never trades.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import fcntl
import json
import os
import socket
import sys

from quantlab.data.public_evidence import TZ, PublicEvidenceArchive, PublicEvidenceError, capture_timing
from quantlab.storage.codec import digest, encode

SCHEDULE_VERSION = 'evidence-schedule-v1'
LABEL = 'com.niuniu.evidence-archive'
RETRY_COOLDOWN = timedelta(minutes=15)
MAX_ATTEMPTS_PER_DAY = 8
WEEKLY_MAX_AGE_DAYS = 7
SCHEDULE = (
    {'task': 'em_limit_up_pool', 'after': time(15, 40)},
    {'task': 'em_prev_limit_up_pool', 'after': time(15, 40)},
    {'task': 'em_broken_board_pool', 'after': time(15, 40)},
    {'task': 'em_limit_down_pool', 'after': time(15, 40)},
    {'task': 'em_strong_pool', 'after': time(15, 40)},
    {'task': 'em_popularity_rank', 'after': time(15, 40)},
    {'task': 'em_concept_boards', 'after': time(15, 45)},
    {'task': 'em_industry_boards', 'after': time(15, 45)},
    {'task': 'em_billboard_daily', 'after': time(17, 30)},
    {'task': 'em_billboard_buy_seats', 'after': time(17, 30)},
    {'task': 'em_billboard_sell_seats', 'after': time(17, 30)},
    {'task': 'daily_market', 'after': time(18, 0)},
    {'task': 'em_concept_board_members', 'after': time(16, 0), 'weekly': True},
    {'task': 'em_industry_board_members', 'after': time(16, 30), 'weekly': True},
)


class SchedulerError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _read_checked(path, default):
    if not path.exists():
        return default
    if path.is_symlink():
        raise SchedulerError('INVALID_WORKSPACE', path.name + ' 不能是符号链接。')
    value = json.loads(path.read_bytes())
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value.get('checksum') != digest(core):
        raise SchedulerError('CORRUPT_STATE', path.name + ' checksum 校验失败。')
    return core


def _write_checked(path, value):
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(encode(_checked(value)), encoding='utf-8')
    temporary.replace(path)


def previous_weekday(day):
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def baostock_is_trading_day(day, sdk=None):
    if sdk is None:
        import baostock as sdk
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(20)
    try:
        login = sdk.login()
        if getattr(login, 'error_code', None) != '0':
            raise SchedulerError('CALENDAR_UNAVAILABLE', 'Baostock 登录失败。')
        try:
            query = sdk.query_trade_dates(start_date=day.isoformat(), end_date=day.isoformat())
            rows = []
            while query.next():
                rows.append(query.get_row_data())
            if getattr(query, 'error_code', None) != '0' or len(rows) != 1 or rows[0][0] != day.isoformat() or rows[0][1] not in ('0', '1'):
                raise SchedulerError('CALENDAR_UNAVAILABLE', '交易日历查询结果无效。')
            return rows[0][1] == '1'
        finally:
            sdk.logout()
    finally:
        socket.setdefaulttimeout(old)


class EvidenceScheduler:
    def __init__(self, output, *, now_fn=None, archive=None, calendar_fn=None, daily_market_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise SchedulerError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.archive = archive
        self.calendar_fn = calendar_fn or baostock_is_trading_day
        self.daily_market_fn = daily_market_fn
        self.root = self.output / '_market_data' / 'public_evidence' / '_scheduler'

    def _paths(self):
        for path in (self.output / '_market_data', self.output / '_market_data' / 'public_evidence', self.root):
            if path.is_symlink():
                raise SchedulerError('INVALID_WORKSPACE', '调度目录不能是符号链接。')
        return self.root / 'control.json', self.root / 'state.json'

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / 'scheduler.lock'
        with path.open('a+b') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SchedulerError('ALREADY_RUNNING', '另一个调度 tick 正在运行。') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def enable(self, *, confirmed=False, authorization=''):
        if confirmed is not True:
            raise SchedulerError('CONFIRMATION_REQUIRED', '启用收盘后公开证据归档需要宿主显式确认。')
        if not isinstance(authorization, str) or not authorization.strip():
            raise SchedulerError('INVALID_ARGUMENT', '需要记录授权依据。')
        control_path, _ = self._paths()
        self.root.mkdir(parents=True, exist_ok=True)
        control = {'format': 'evidence-scheduler-control-v1', 'enabled': True, 'schedule_version': SCHEDULE_VERSION,
                   'authorization': authorization.strip()[:500], 'enabled_at': self.now_fn().astimezone(timezone.utc).isoformat(),
                   'scope': '仅收盘后低频抓取公开网页证据与 Baostock 当日全市场日线；不盘中抓取、不补历史、不交易。'}
        _write_checked(control_path, control)
        return control

    def pause(self):
        control_path, _ = self._paths()
        control = _read_checked(control_path, None)
        if control is None:
            raise SchedulerError('NOT_CONFIGURED', '调度尚未启用。')
        control = {**control, 'enabled': False, 'paused_at': self.now_fn().astimezone(timezone.utc).isoformat()}
        _write_checked(control_path, control)
        return control

    def _archive(self):
        if self.archive is None:
            self.archive = PublicEvidenceArchive(self.output)
        return self.archive

    def _accepted(self, task, day):
        if task == 'daily_market':
            from quantlab.data.daily_market_archive import DailyMarketArchive
            return DailyMarketArchive(self.output).accepted(day) is not None
        try:
            self._archive().get(task, day)
            return True
        except PublicEvidenceError as error:
            if error.code == 'NOT_FOUND':
                return False
            raise

    def _weekly_due(self, task, day):
        if day.weekday() == 4:
            return True
        latest = None
        for row in self._archive().list_days(task, limit=10):
            if 'error' not in row:
                latest = date.fromisoformat(row['trading_day'])
                break
        return latest is None or (day - latest).days >= WEEKLY_MAX_AGE_DAYS

    def _run(self, task, day, calendar_days):
        if task == 'daily_market':
            if self.daily_market_fn is not None:
                return self.daily_market_fn(day)
            from quantlab.data.daily_market_archive import DailyMarketArchive
            manifest = DailyMarketArchive(self.output).capture(day)
            return {'rows': manifest['rows'], 'created': manifest.get('created')}
        archive = self._archive()
        archive.calendar_days = calendar_days
        manifest = archive.capture(task, day)
        return {'rows': manifest['rows'], 'created': manifest['created'], 'capture_timing': manifest['capture_timing'],
                'warnings': manifest['warnings']}

    def tick(self):
        control_path, state_path = self._paths()
        control = _read_checked(control_path, None)
        if not control or control.get('enabled') is not True:
            return {'status': 'DISABLED', 'actions': []}
        with self._lock():
            now = self.now_fn()
            local = now.astimezone(TZ)
            state = _read_checked(state_path, {'format': 'evidence-scheduler-state-v1', 'days': {}, 'calendar': {}})
            actions = []
            candidates = [d for d in (local.date(), previous_weekday(local.date()))
                          if d.weekday() < 5 and capture_timing(d, now) in ('SAME_DAY_AFTER_CLOSE', 'BEFORE_NEXT_SESSION')]
            for day in sorted(set(candidates)):
                key = day.isoformat()
                if key not in state['calendar']:
                    try:
                        state['calendar'][key] = bool(self.calendar_fn(day))
                    except Exception as error:
                        actions.append({'day': key, 'task': 'calendar', 'ok': False, 'error': f'{type(error).__name__}: {str(error)[:160]}'})
                        continue
                if state['calendar'][key] is not True:
                    continue
                day_state = state['days'].setdefault(key, {})
                for item in SCHEDULE:
                    task = item['task']
                    entry = day_state.setdefault(task, {'attempts': 0, 'status': 'PENDING', 'last_attempt_at': None, 'last_error': None})
                    if entry['status'] in ('ACCEPTED', 'SKIPPED_NOT_DUE'):
                        continue
                    if local.date() == day and local.time() < item['after']:
                        continue
                    if item.get('weekly') and not self._weekly_due(task, day):
                        entry['status'] = 'SKIPPED_NOT_DUE'
                        continue
                    if self._accepted(task, day):
                        entry['status'] = 'ACCEPTED'
                        continue
                    if entry['attempts'] >= MAX_ATTEMPTS_PER_DAY:
                        entry['status'] = 'GAVE_UP'
                        continue
                    last = datetime.fromisoformat(entry['last_attempt_at']) if entry['last_attempt_at'] else None
                    if last is not None and now - last < RETRY_COOLDOWN:
                        continue
                    entry['attempts'] += 1
                    entry['last_attempt_at'] = now.astimezone(timezone.utc).isoformat()
                    try:
                        result = self._run(task, day, {key})
                        entry.update(status='ACCEPTED', last_error=None, result=result)
                        actions.append({'day': key, 'task': task, 'ok': True, **result})
                    except Exception as error:
                        code = getattr(error, 'code', type(error).__name__)
                        entry.update(status='RETRY' if entry['attempts'] < MAX_ATTEMPTS_PER_DAY else 'GAVE_UP',
                                     last_error=f'{code}: {str(error)[:200]}')
                        actions.append({'day': key, 'task': task, 'ok': False, 'error': entry['last_error']})
                    state['last_action_at'] = now.astimezone(timezone.utc).isoformat()
            state['last_tick_at'] = now.astimezone(timezone.utc).isoformat()
            for old in sorted(state['days'])[:-30]:
                state['days'].pop(old)
            for old in sorted(state['calendar'])[:-60]:
                state['calendar'].pop(old)
            _write_checked(state_path, state)
            return {'status': 'OK', 'candidates': [d.isoformat() for d in sorted(set(candidates))], 'actions': actions}

    def status(self):
        control_path, state_path = self._paths()
        control = _read_checked(control_path, None)
        state = _read_checked(state_path, {'days': {}, 'calendar': {}})
        days = sorted(state.get('days', {}))[-5:]
        return {'schedule_version': SCHEDULE_VERSION, 'enabled': bool(control and control.get('enabled')), 'control': control,
                'last_tick_at': state.get('last_tick_at'), 'last_action_at': state.get('last_action_at'),
                'recent_days': {d: state['days'][d] for d in days}, 'schedule': [
                    {'task': item['task'], 'after': item['after'].strftime('%H:%M'), 'weekly': bool(item.get('weekly'))} for item in SCHEDULE]}


def install_agent(output):
    if sys.platform != 'darwin':
        raise SchedulerError('UNSUPPORTED_PLATFORM', '自动安装仅支持 macOS；其他平台可定时运行 --tick。')
    import plistlib
    import subprocess
    output = Path(output).resolve()
    scheduler = EvidenceScheduler(output)
    control, _ = scheduler._paths()
    if not control.exists():
        raise SchedulerError('NOT_CONFIGURED', '请先 --enable --confirm。')
    folder = Path.home() / 'Library/LaunchAgents'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (LABEL + '.plist')
    logs = scheduler.root
    config = {'Label': LABEL, 'ProgramArguments': [sys.executable, '-m', 'quantlab.agent.evidence_scheduler_cli', '--output', str(output), '--tick'],
              'WorkingDirectory': str(Path(__file__).resolve().parents[3]), 'StartInterval': 600, 'RunAtLoad': True,
              'ProcessType': 'Background', 'StandardOutPath': str(logs / 'scheduler.log'), 'StandardErrorPath': str(logs / 'scheduler.error.log')}
    if path.exists() and plistlib.loads(path.read_bytes()) != config:
        raise SchedulerError('CONFLICT', '同名后台任务已有不同配置，请先检查 ' + str(path))
    path.write_bytes(plistlib.dumps(config))
    domain = 'gui/' + str(os.getuid())
    loaded = subprocess.run(['launchctl', 'print', domain + '/' + LABEL], capture_output=True, text=True)
    if loaded.returncode != 0:
        result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
        if result.returncode:
            raise SchedulerError('LAUNCHCTL_FAILED', 'launchctl bootstrap: ' + result.stderr.strip())
    return {'installed': True, 'label': LABEL, 'plist': str(path), 'interval_seconds': 600,
            'requires': 'Mac 登录、联网、外置盘挂载；休眠期间不运行，醒来后在收盘后窗口内补做。'}


__all__ = ['SCHEDULE', 'SCHEDULE_VERSION', 'LABEL', 'EvidenceScheduler', 'SchedulerError', 'install_agent', 'previous_weekday']
