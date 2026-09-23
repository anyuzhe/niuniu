"""After-close scheduler for public market evidence and the daily Baostock market snapshot.

The scheduler only runs when the host has enabled it. Each tick checks the trading calendar,
captures due sources for the most recent trading day that is still inside its after-close
window, and records attempts in a checksummed state file. It never captures intraday,
never backfills past the next session and never trades.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import fcntl
import io
import json
import os
import socket
import sys

from quantlab.data.capture_root import capture_root
from quantlab.data.public_evidence import TZ, PublicEvidenceArchive, PublicEvidenceError, capture_timing, next_weekday
from quantlab.storage.codec import digest, encode

SCHEDULE_VERSION = 'evidence-schedule-v1'
LABEL = 'com.niuniu.evidence-archive'
INTRADAY_LABEL = 'com.niuniu.evidence-intraday'
INTRADAY_MAX_ATTEMPTS = 3
# launchd start times (Mon–Fri): two tries inside every auction/intraday window; tick_intraday skips what is already accepted.
INTRADAY_TRIGGERS = ((9, 26), (9, 28), (10, 1), (10, 6), (11, 1), (11, 6), (13, 31), (13, 36), (14, 31), (14, 36))
RETRY_COOLDOWN = timedelta(minutes=15)
STAGED_TASK_SECONDS = 300
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
    {'task': 'forward_reference', 'after': time(18, 0)},
    {'task': 'em_concept_board_members', 'after': time(16, 0), 'weekly': True},
    {'task': 'em_industry_board_members', 'after': time(16, 30), 'weekly': True},
    # Derived locally from the archives above; rebuilt whenever its accepted inputs change.
    {'task': 'theme_facts', 'after': time(16, 10), 'refresh': True},
    {'task': 'limit_research', 'after': time(18, 10), 'refresh': True},
    {'task': 'event_details', 'after': time(18, 15), 'refresh': True},
    {'task': 'daily_review', 'after': time(18, 20), 'refresh': True},
    {'task': 'forecast_resolution', 'after': time(18, 25), 'refresh': True},
    {'task': 'forecast_baselines', 'after': time(18, 25)},
    # Host-authorized autonomous research: at most the plan's nightly budget of in-sample screenings; skipped without an active plan.
    {'task': 'auto_research', 'after': time(19, 0)},
    # Pending host promotions are confirmed and confirmed rules are measured on data after their confirmation window.
    {'task': 'conclusion_monitor', 'after': time(19, 30), 'refresh': True},
    # Pre-market brief for the next weekday; rebuilt whenever its review, conclusions or recorded forecasts change.
    {'task': 'premarket_brief', 'after': time(19, 40), 'refresh': True},
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
        with redirect_stdout(io.StringIO()):  # the SDK prints to stdout, which would corrupt tick JSON
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
            with redirect_stdout(io.StringIO()):
                sdk.logout()
    finally:
        socket.setdefaulttimeout(old)


class EvidenceScheduler:
    def __init__(self, output, *, now_fn=None, archive=None, calendar_fn=None, daily_market_fn=None, reference_fn=None, theme_library=None,
                 research_fn=None, detail_library=None, review_library=None, forecast_journal=None, auto_research=None,
                 conclusion_library=None, premarket_library=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise SchedulerError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.archive = archive
        self.calendar_fn = calendar_fn or baostock_is_trading_day
        self.daily_market_fn = daily_market_fn
        self.reference_fn = reference_fn
        self.theme_library = theme_library
        self.research_fn = research_fn
        self.detail_library = detail_library
        self.review_library = review_library
        self.forecast_journal = forecast_journal
        self.auto_research = auto_research
        self.conclusion_library = conclusion_library
        self.premarket_library = premarket_library
        self.market_root = capture_root(self.output)
        self.root = self.market_root / 'public_evidence' / '_scheduler'

    def _paths(self):
        for path in (self.market_root, self.market_root / 'public_evidence', self.root):
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

    # ---- authorized auction/intraday snapshots (D-1, 2026-09-17) -------------------------------------------
    def _intraday_paths(self):
        self._paths()
        return self.root / 'intraday_control.json', self.root / 'intraday_state.json'

    @contextmanager
    def _intraday_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'intraday.lock').open('a+b') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SchedulerError('ALREADY_RUNNING', '另一个盘中抓取 tick 正在运行。') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def enable_intraday(self, *, confirmed=False, authorization=''):
        from quantlab.data.eastmoney_sources import intraday_sources
        if confirmed is not True:
            raise SchedulerError('CONFIRMATION_REQUIRED', '启用竞价/盘中快照需要宿主显式确认。')
        if not isinstance(authorization, str) or not authorization.strip():
            raise SchedulerError('INVALID_ARGUMENT', '需要记录授权依据。')
        control_path, _ = self._intraday_paths()
        self.root.mkdir(parents=True, exist_ok=True)
        control = {'format': 'evidence-scheduler-intraday-control-v1', 'enabled': True, 'authorization': authorization.strip()[:500],
                   'enabled_at': self.now_fn().astimezone(timezone.utc).isoformat(),
                   'tasks': [{'task': s.source_id, 'window': [s.capture_window[0].strftime('%H:%M:%S'), s.capture_window[1].strftime('%H:%M:%S')]}
                             for s in intraday_sources()],
                   'scope': '仅在授权时段内低频抓取：09:25:30–09:29:30 集合竞价全市场快照；10:00、11:00、13:30、14:30 起 10 分钟内涨停/炸板/跌停池快照；'
                            '与收盘后归档分开存放，不补抓、不交易。'}
        _write_checked(control_path, control)
        return control

    def pause_intraday(self):
        control_path, _ = self._intraday_paths()
        control = _read_checked(control_path, None)
        if control is None:
            raise SchedulerError('NOT_CONFIGURED', '竞价/盘中快照尚未启用。')
        control = {**control, 'enabled': False, 'paused_at': self.now_fn().astimezone(timezone.utc).isoformat()}
        _write_checked(control_path, control)
        return control

    def tick_intraday(self):
        from quantlab.data.eastmoney_sources import intraday_sources
        control_path, state_path = self._intraday_paths()
        control = _read_checked(control_path, None)
        if not control or control.get('enabled') is not True:
            return {'status': 'DISABLED', 'actions': []}
        with self._intraday_lock():
            now = self.now_fn()
            local = now.astimezone(TZ)
            day, key = local.date(), local.date().isoformat()
            state = _read_checked(state_path, {'format': 'evidence-scheduler-intraday-state-v1', 'days': {}, 'calendar': {}})
            due = [s for s in intraday_sources() if s.capture_window[0] <= local.time() < s.capture_window[1]]
            actions, status = [], 'OK'
            if day.weekday() >= 5 or not due:
                status = 'NOTHING_DUE'
            else:
                if key not in state['calendar']:
                    try:
                        state['calendar'][key] = bool(self.calendar_fn(day))
                    except Exception as error:
                        actions.append({'day': key, 'task': 'calendar', 'ok': False, 'error': f'{type(error).__name__}: {str(error)[:160]}'})
                if key not in state['calendar']:
                    status = 'CALENDAR_UNAVAILABLE'
                elif state['calendar'][key] is not True:
                    status = 'NOT_TRADING_DAY'
                else:
                    archive = self._archive()
                    archive.calendar_days = {key}
                    day_state = state['days'].setdefault(key, {})
                    for source in due:
                        entry = day_state.setdefault(source.source_id, {'attempts': 0, 'status': 'PENDING', 'last_error': None})
                        if entry['status'] in ('ACCEPTED', 'GAVE_UP'):
                            continue
                        try:
                            archive.get(source.source_id, day)
                            entry['status'] = 'ACCEPTED'
                            continue
                        except PublicEvidenceError as error:
                            if error.code != 'NOT_FOUND':
                                raise
                        entry['attempts'] += 1
                        entry['last_attempt_at'] = now.astimezone(timezone.utc).isoformat()
                        try:
                            manifest = archive.capture(source.source_id, day)
                            entry.update(status='ACCEPTED', last_error=None, rows=manifest['rows'])
                            actions.append({'day': key, 'task': source.source_id, 'ok': True, 'rows': manifest['rows'],
                                            'capture_timing': manifest['capture_timing']})
                        except Exception as error:
                            code = getattr(error, 'code', type(error).__name__)
                            entry.update(status='RETRY' if entry['attempts'] < INTRADAY_MAX_ATTEMPTS else 'GAVE_UP', last_error=f'{code}: {str(error)[:200]}')
                            actions.append({'day': key, 'task': source.source_id, 'ok': False, 'error': entry['last_error']})
            state['last_tick_at'] = now.astimezone(timezone.utc).isoformat()
            if actions:
                state['last_action_at'] = state['last_tick_at']
            for old in sorted(state['days'])[:-10]:
                state['days'].pop(old)
            for old in sorted(state['calendar'])[:-20]:
                state['calendar'].pop(old)
            _write_checked(state_path, state)
            return {'status': status, 'day': key, 'due': [s.source_id for s in due], 'actions': actions}

    def _archive(self):
        if self.archive is None:
            self.archive = PublicEvidenceArchive(self.output)
        return self.archive

    def _themes(self):
        if self.theme_library is None:
            from quantlab.trading.theme_engine import ThemeFactsLibrary
            self.theme_library = ThemeFactsLibrary(self.output, evidence=self._archive())
        return self.theme_library

    def _details(self):
        if self.detail_library is None:
            from quantlab.trading.event_details import EventDetailLibrary
            self.detail_library = EventDetailLibrary(self.output, evidence=self._archive())
        return self.detail_library

    def _research(self, action, day):
        """Daily limit-research builds: ``current`` checks, ``build`` rebuilds event library and sentiment through ``day``."""
        if self.research_fn is not None:
            return self.research_fn(action, day)
        from quantlab.data.retro_daily import RetroDailyStore
        from quantlab.trading.limit_events import LimitEventLibrary, default_capture_ids
        from quantlab.trading.market_sentiment import MarketSentimentLibrary
        events, sentiment = LimitEventLibrary(self.output), MarketSentimentLibrary(self.output)
        if action == 'current':
            return (events.latest_covering(day, current_code=True) is not None
                    and sentiment.latest_covering(day, current_code=True) is not None)
        captures, retro_end = default_capture_ids(RetroDailyStore(self.output))
        through = day.isoformat() if day > retro_end else None
        built = events.build(captures, forward_through=through)
        daily = sentiment.build(captures, forward_through=through)
        return {'event_build_id': built['build_id'], 'events': built['stats']['events'], 'sentiment_build_id': daily['build_id'],
                'created': bool(built['created'] or daily['created'])}

    def _reviews(self):
        if self.review_library is None:
            from quantlab.trading.daily_review import DailyReviewLibrary
            self.review_library = DailyReviewLibrary(self.output)
        return self.review_library

    def _forecasts(self):
        if self.forecast_journal is None:
            from quantlab.trading.limit_forecasts import LimitForecastJournal
            self.forecast_journal = LimitForecastJournal(self.output)
        return self.forecast_journal

    def _auto(self):
        if self.auto_research is None:
            from quantlab.trading.auto_research import AutoResearch
            self.auto_research = AutoResearch(self.output)
        return self.auto_research

    def _conclusions(self):
        if self.conclusion_library is None:
            from quantlab.trading.research_conclusions import ConclusionLibrary
            self.conclusion_library = ConclusionLibrary(self.output)
        return self.conclusion_library

    def _premarket(self):
        if self.premarket_library is None:
            from quantlab.trading.premarket_brief import PremarketBriefLibrary
            self.premarket_library = PremarketBriefLibrary(self.output)
        return self.premarket_library

    def _accepted(self, task, day):
        if task == 'premarket_brief':
            return self._premarket().is_current(next_weekday(day))
        if task == 'conclusion_monitor':
            return self._conclusions().is_current(day)
        if task == 'auto_research':
            return self._auto().active_plan() is None or self._auto().night_done(day)
        if task == 'forecast_resolution':
            return not self._forecasts().forecasts(day) or self._forecasts().is_resolved(day)
        if task == 'forecast_baselines':
            target = next_weekday(day)
            return any(f['forecaster'].startswith('baseline:') for f in self._forecasts().forecasts(target))
        if task == 'daily_review':
            return self._reviews().is_current(day)
        if task == 'limit_research':
            return bool(self._research('current', day))
        if task == 'event_details':
            return self._details().is_current(day)
        if task == 'theme_facts':
            return self._themes().is_current(day)
        if task == 'forward_reference':
            from quantlab.data.forward_daily import ForwardDailyError, ForwardReferenceArchive
            try:
                ForwardReferenceArchive(self.output).latest_covering(day)
                return True
            except ForwardDailyError:
                return False
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

    def _run(self, task, day, calendar_days, staged=False):
        if task == 'premarket_brief':
            if not self._reviews().is_current(day):
                raise SchedulerError('REVIEW_NOT_READY', f'{day} 的收盘复盘尚未生成，盘前简报不能依据更早的收盘。')
            brief = self._premarket().build(next_weekday(day))
            return {'target_day': brief['target_day'], 'brief_id': brief['brief_id'], 'created': brief['created'],
                    'valid_conclusions': len(brief['conclusions']['monitoring']), 'risks': len(brief['risks'])}
        if task == 'conclusion_monitor':
            result = self._conclusions().evaluate(day)
            return {'evaluated': len(result['evaluated']), 'decaying': sum(e['status'] == 'DECAYING' for e in result['evaluated']),
                    'confirmations_run': len(result['confirmations']['ran']), 'confirmations_changed': len(result['confirmations']['changed'])}
        if task == 'auto_research':
            result = self._auto().run(night=day)
            return {'status': result['status'], 'ran': len(result['ran']), 'passed': sum(r['state'] == 'SCREENED_PASS' for r in result['ran']),
                    'interrupted': result['interrupted']}
        if task == 'forecast_resolution':
            resolution = self._forecasts().resolve(day)
            return {'resolved': sum(i['status'] == 'RESOLVED' for i in resolution['items']), 'items': len(resolution['items']),
                    'trading_day': resolution['trading_day']}
        if task == 'forecast_baselines':
            result = self._forecasts().generate_baselines(next_weekday(day))
            return {'target_day': result['target_day'], 'written': len(result['written']), 'last_day': result['last_day']}
        if task == 'daily_review':
            review = self._reviews().build(day)
            return {'review_id': review['review_id'], 'created': review['created'], 'phase': review['machine_state']['phase']}
        if task == 'limit_research':
            return self._research('build', day)
        if task == 'event_details':
            manifest = self._details().build(day)
            return {'build_id': manifest['build_id'], 'created': manifest['created'], 'rows': manifest['rows'],
                    'reconciliation': manifest['reconciliation']}
        if task == 'theme_facts':
            manifest = self._themes().build(day)
            return {'build_id': manifest['build_id'], 'created': manifest['created'], 'families': manifest['families'],
                    'skipped_families': manifest['skipped_families']}
        if task == 'forward_reference':
            if self.reference_fn is not None:
                return self.reference_fn(day)
            from quantlab.data.forward_daily import ForwardReferenceArchive
            manifest = ForwardReferenceArchive(self.output).capture()
            return {'snapshot_id': manifest['snapshot_id'], 'as_of': manifest['as_of'], 'created': manifest['created']}
        if task == 'daily_market':
            if self.daily_market_fn is not None:
                return self.daily_market_fn(day)
            from quantlab.data.daily_market_archive import DailyMarketArchive
            manifest = DailyMarketArchive(self.output).capture(day)
            return {'rows': manifest['rows'], 'created': manifest.get('created')}
        archive = self._archive()
        archive.calendar_days = calendar_days
        manifest = archive.capture(task, day, max_seconds=STAGED_TASK_SECONDS) if staged else archive.capture(task, day)
        if manifest.get('state') == 'IN_PROGRESS':
            return {'in_progress': True, 'fetched': manifest['fetched'], 'queued': manifest['queued']}
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
                    if entry['status'] == 'SKIPPED_NOT_DUE' or (entry['status'] == 'ACCEPTED' and not item.get('refresh')):
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
                    if entry['status'] == 'RETRY' and last is not None and now - last < RETRY_COOLDOWN:
                        continue
                    entry['attempts'] += 1
                    entry['last_attempt_at'] = now.astimezone(timezone.utc).isoformat()
                    try:
                        result = self._run(task, day, {key}, staged=bool(item.get('weekly')))
                        if result.get('in_progress'):
                            # Progress is kept in staging; continuing next tick is not a failed attempt.
                            entry['attempts'] -= 1
                            entry.update(status='IN_PROGRESS', last_attempt_at=None, last_error=None, result=result)
                        else:
                            entry.update(status='ACCEPTED', last_error=None, result=result)
                            if item.get('refresh'):
                                entry['attempts'] = 0  # successful rebuilds of derived data never count toward giving up
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
        intraday_control_path, intraday_state_path = self._intraday_paths()
        intraday_control = _read_checked(intraday_control_path, None)
        intraday_state = _read_checked(intraday_state_path, {'days': {}})
        intraday = {'enabled': bool(intraday_control and intraday_control.get('enabled')), 'control': intraday_control,
                    'last_tick_at': intraday_state.get('last_tick_at'),
                    'recent_days': {d: intraday_state['days'][d] for d in sorted(intraday_state.get('days', {}))[-3:]}}
        return {'schedule_version': SCHEDULE_VERSION, 'enabled': bool(control and control.get('enabled')), 'control': control, 'intraday': intraday,
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


def intraday_agent_config(output):
    """launchd job for authorized auction/intraday snapshots: calendar triggers inside each window, Monday to Friday."""
    output = Path(output).resolve()
    logs = EvidenceScheduler(output).root
    return {'Label': INTRADAY_LABEL, 'ProgramArguments': [sys.executable, '-m', 'quantlab.agent.evidence_scheduler_cli', '--output', str(output),
                                                          '--tick-intraday'],
            'WorkingDirectory': str(Path(__file__).resolve().parents[3]), 'RunAtLoad': False, 'ProcessType': 'Background',
            'StartCalendarInterval': [{'Weekday': weekday, 'Hour': hour, 'Minute': minute} for weekday in range(1, 6) for hour, minute in INTRADAY_TRIGGERS],
            'StandardOutPath': str(logs / 'intraday.log'), 'StandardErrorPath': str(logs / 'intraday.error.log')}


def install_intraday_agent(output):
    if sys.platform != 'darwin':
        raise SchedulerError('UNSUPPORTED_PLATFORM', '自动安装仅支持 macOS；其他平台可在时段内运行 --tick-intraday。')
    import plistlib
    import subprocess
    scheduler = EvidenceScheduler(output)
    control, _ = scheduler._intraday_paths()
    if not control.exists():
        raise SchedulerError('NOT_CONFIGURED', '请先 --enable-intraday --confirm。')
    folder = Path.home() / 'Library/LaunchAgents'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (INTRADAY_LABEL + '.plist')
    config = intraday_agent_config(output)
    if path.exists() and plistlib.loads(path.read_bytes()) != config:
        raise SchedulerError('CONFLICT', '同名后台任务已有不同配置，请先检查 ' + str(path))
    path.write_bytes(plistlib.dumps(config))
    domain = 'gui/' + str(os.getuid())
    loaded = subprocess.run(['launchctl', 'print', domain + '/' + INTRADAY_LABEL], capture_output=True, text=True)
    if loaded.returncode != 0:
        result = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True, text=True)
        if result.returncode:
            raise SchedulerError('LAUNCHCTL_FAILED', 'launchctl bootstrap: ' + result.stderr.strip())
    return {'installed': True, 'label': INTRADAY_LABEL, 'plist': str(path), 'triggers': [f'{h:02d}:{m:02d}' for h, m in INTRADAY_TRIGGERS],
            'requires': 'Mac 登录、联网、外置盘挂载；休眠或错过时段则当天不补抓。'}


__all__ = ['SCHEDULE', 'SCHEDULE_VERSION', 'LABEL', 'INTRADAY_LABEL', 'EvidenceScheduler', 'SchedulerError', 'install_agent', 'install_intraday_agent',
           'intraday_agent_config', 'previous_weekday']
