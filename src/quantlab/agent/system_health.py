"""Read-only System Health aggregation. Operational liveness is never research correctness."""
from __future__ import annotations

from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import json
import shutil
import os
import importlib.util
from uuid import UUID

from quantlab.experiments.campaign_state import read_checked

STATUSES=('OK','WARN','BLOCKED','UNKNOWN','NOT_CONFIGURED')
TZ=ZoneInfo('Asia/Shanghai')


def _aware(value):
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError('System Health clock must be timezone-aware')
    return value.astimezone(timezone.utc)


def _parse(value):
    if not value:return None
    try:
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return result if result.tzinfo is not None else None
    except (TypeError,ValueError):return None


def _component(status,summary,*,evidence=None,blockers=None,warnings=None,limitations=None):
    if status not in STATUSES:raise ValueError('invalid health status')
    return {'status':status,'summary':str(summary)[:1000],'evidence':evidence or {},
        'blockers':blockers or [],'warnings':warnings or [],'limitations':limitations or []}


def _axis(components,names):
    values=[components[name]['status'] for name in names]
    if 'BLOCKED' in values:return 'BLOCKED'
    if 'WARN' in values:return 'WARN'
    if 'UNKNOWN' in values:return 'UNKNOWN'
    if 'OK' in values:return 'OK'
    return 'NOT_CONFIGURED'


def _lock_active(path):
    path=Path(path)
    if not path.exists():return False
    if path.is_symlink():raise ValueError('lock path cannot be symlink: '+str(path))
    with path.open('rb') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        else:
            fcntl.flock(stream,fcntl.LOCK_UN);return False


class SystemHealthService:
    def __init__(self,output,data_root=None,now_fn=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise ValueError('System Health workspace does not exist')

    def _workspace(self,now):
        blockers=[];warnings=[];evidence={'output':str(self.output),'data_root':str(self.data_root) if self.data_root else None}
        if self.output.is_symlink():blockers.append('workspace_output_symlink')
        if self.data_root is None:warnings.append('data_root_not_configured')
        elif not self.data_root.is_dir():blockers.append('data_root_missing')
        elif self.data_root.is_symlink():blockers.append('data_root_symlink')
        try:
            usage=shutil.disk_usage(self.output);free_gb=usage.free/(1024**3);evidence['workspace_free_gb']=round(free_gb,3)
            if usage.free<100*1024**2:blockers.append('workspace_disk_free_below_100mb')
            elif usage.free<1024**3:warnings.append('workspace_disk_free_below_1gb')
        except OSError:warnings.append('workspace_disk_usage_unavailable')
        status='BLOCKED' if blockers else ('WARN' if warnings else 'OK')
        return _component(status,'工作空间和行情目录只做存在性/容量检查，不代表研究数据正确。',evidence=evidence,
            blockers=blockers,warnings=warnings,limitations=['Disk free space is operational capacity only.'])

    def _artifact_growth(self,now):
        cutoff=now-timedelta(hours=24);entries=0;run_dirs=0;system_dirs=0;files=0;recent=0;symlinks=0;latest=None;unreadable=0
        try:items=list(self.output.iterdir())
        except OSError as exc:
            return _component('WARN','产物增长元数据不可读。',warnings=['artifact_growth_scan_failed'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        for path in items:
            if path.is_symlink():symlinks+=1;continue
            entries+=1
            try:
                stat=path.stat();modified=datetime.fromtimestamp(stat.st_mtime,tz=timezone.utc)
            except OSError:unreadable+=1;continue
            latest=max(latest,modified) if latest else modified;recent+=int(modified>=cutoff)
            if path.is_file():files+=1
            elif path.is_dir():
                try:UUID(path.name);run_dirs+=1
                except ValueError:
                    if path.name.startswith('_') or path.name.startswith('paper'):system_dirs+=1
        warnings=[]
        if symlinks:warnings.append('artifact_symlinks_skipped')
        if unreadable:warnings.append('artifact_top_level_unreadable')
        return _component('WARN' if warnings else 'OK',f'Artifacts top-level={entries}；run_dirs={run_dirs}；24h changed={recent}。',
            evidence={'top_level_entries':entries,'run_directories':run_dirs,'system_directories':system_dirs,'top_level_files':files,
                'modified_24h_top_level_entries':recent,'latest_modified_at':latest.isoformat() if latest else None,
                'symlinks_skipped':symlinks,'unreadable_top_level_entries':unreadable},warnings=warnings,
            limitations=['Growth is a fast top-level proxy; System Health does not recursively scan every artifact file or persist a storage time series.',
                'Disk free capacity is reported separately by workspace health.'])

    def _jobs(self,now):
        root=self.output/'_jobs'
        if not root.exists():return _component('NOT_CONFIGURED','尚无 JobQueue 持久记录。')
        if root.is_symlink():return _component('BLOCKED','JobQueue 目录是符号链接。',blockers=['job_directory_symlink'])
        records=[];unreadable=0
        for path in root.glob('*.json'):
            if path.is_symlink():unreadable+=1;continue
            try:
                if str(UUID(path.stem))!=path.stem:raise ValueError()
                value=json.loads(path.read_text())
                if value.get('job_id')!=path.stem:raise ValueError()
                records.append(value)
            except (OSError,ValueError,TypeError,KeyError):unreadable+=1
        counts=Counter(str(row.get('status','unknown')) for row in records)
        try:worker_active=_lock_active(root/'worker.lock')
        except ValueError:return _component('BLOCKED','JobQueue worker.lock 路径异常。',blockers=['job_worker_lock_invalid'])
        running=counts.get('running',0);queued=counts.get('queued',0);blockers=[];warnings=[]
        if running and not worker_active:blockers.append('orphan_running_jobs_without_worker_lock')
        cutoff=now-timedelta(hours=24);recent_failures=0
        for row in records:
            if row.get('status') not in ('failed','interrupted'):continue
            at=_parse(row.get('finished_at') or row.get('started_at') or row.get('created_at'))
            if at and at.astimezone(timezone.utc)>=cutoff:recent_failures+=1
        if recent_failures:warnings.append('recent_failed_or_interrupted_jobs')
        if unreadable:warnings.append('unreadable_job_records')
        status='BLOCKED' if blockers else ('WARN' if warnings else 'OK')
        recent=sorted(records,key=lambda row:(str(row.get('created_at') or ''),str(row.get('job_id') or '')),reverse=True)[:10]
        recent=[{key:row.get(key) for key in ('job_id','status','created_at','started_at','finished_at','run_id')}|{'error_present':bool(row.get('error'))} for row in recent]
        return _component(status,f'JobQueue 共 {len(records)} 条；active={running+queued}，近24h失败/中断={recent_failures}。',
            evidence={'counts':dict(counts),'worker_lock_active':worker_active,'unreadable_records':unreadable,
                'recent_failed_or_interrupted':recent_failures,'recent_jobs':recent},blockers=blockers,warnings=warnings,
            limitations=['Historical failed jobs may remain archived; only the last 24h is treated as a current warning.',
                'Health exposes recent job metadata only; research specs and error text are intentionally omitted.'])

    def _tracking_daemon(self,now):
        from quantlab.agent.tracking_daemon import daemon_status
        try:value=daemon_status(self.output)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Tracking daemon 状态回执不可读。',blockers=['tracking_daemon_status_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        if value.get('status')=='not_started':return _component('NOT_CONFIGURED','Tracking daemon 尚未启动。',evidence=value)
        updated=_parse(value.get('updated_at'));age=None
        if updated:age=max(0.0,(now-updated.astimezone(timezone.utc)).total_seconds())
        poll=float(value.get('poll_seconds') or 60);warnings=[];blockers=[]
        if value.get('status')=='error':blockers.append('tracking_daemon_last_tick_error')
        if value.get('stale'):warnings.append('tracking_daemon_not_active_with_nonterminal_heartbeat')
        if value.get('active') and (age is None or age>max(300,poll*3)):warnings.append('tracking_daemon_heartbeat_stale')
        status='BLOCKED' if blockers else ('WARN' if warnings else 'OK')
        return _component(status,f"Tracking daemon status={value.get('status')} active={bool(value.get('active'))}。",
            evidence={'active':bool(value.get('active')),'status':value.get('status'),'updated_at':value.get('updated_at'),
                'heartbeat_age_seconds':age,'poll_seconds':value.get('poll_seconds'),'error':value.get('error')},
            blockers=blockers,warnings=warnings,limitations=['Daemon liveness does not certify research correctness or data qualification.'])

    def _mcp(self,now):
        if importlib.util.find_spec('mcp') is None:
            return _component('NOT_CONFIGURED','MCP 可选依赖未安装。',limitations=['MCP is optional and its absence does not block local desktop research.'])
        try:
            from quantlab.agent.market_data_tools import MarketDataResearchAPI
            from quantlab.agent.mcp_server import WRITE_PREFIXES
            names=[item['name'] for item in MarketDataResearchAPI(self.output,self.data_root).schemas()]
            writes=[name for name in names if any(name.startswith(prefix) for prefix in WRITE_PREFIXES)]
        except (ImportError,OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','MCP adapter 无法构建工具目录。',blockers=['mcp_adapter_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        return _component('OK',f'MCP adapter ready；tools={len(names)}；transport=stdio/streamable-http(loopback)。',
            evidence={'adapter_ready':True,'server_liveness':None,'tool_count':len(names),'write_capable_tool_count':len(writes),
                'transports':['stdio','streamable-http'],'http_binding':'loopback_only'},
            limitations=['stdio/stateless HTTP has no durable server heartbeat in v1; adapter readiness is not proof that an MCP process is currently running.',
                'Tool availability does not expand host authorization or certify research correctness.'])

    def _market_data_series(self,now):
        from quantlab.data.baostock_series import SeriesService
        try:value=SeriesService(self.output).list()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Baostock Series 状态不可读。',blockers=['market_data_series_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        rows=value.get('series') or [];errors=value.get('errors') or []
        if not rows and not errors:return _component('NOT_CONFIGURED','尚无 host-approved Baostock Series。')
        latest_end=max((str((row.get('current') or {}).get('end') or '') for row in rows),default='')
        generations=sum(int(row.get('generation') or 0) for row in rows);warnings=[]
        if errors:warnings.append('unreadable_market_data_series')
        return _component('WARN' if warnings else 'OK',f'Baostock Series={len(rows)}；最新 accepted cutoff={latest_end or "UNKNOWN"}。',
            evidence={'series_count':len(rows),'latest_accepted_end':latest_end or None,'total_generations':generations,
                'series':[{'series_id':row.get('series_id'),'name':row.get('name'),'generation':row.get('generation'),
                    'end':(row.get('current') or {}).get('end'),'symbols':len((row.get('current') or {}).get('symbols') or []),
                    'modes':(row.get('current') or {}).get('modes')} for row in rows[:50]],'unreadable':len(errors)},
            warnings=warnings,limitations=['Series cutoff/completeness is an accepted retrospective batch contract, not strict-PIT freshness certification.'])

    def _notifications(self,now):
        from quantlab.agent.tracking_control_store import ControlStore
        from quantlab.agent.notification_delivery import DeliveryStore
        try:
            controls=ControlStore(self.output).list();history=DeliveryStore(self.output).history(limit=200)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Notifications 状态不可读。',blockers=['notification_state_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        unread=sum(sum(1 for notice in (state.get('notices') or {}).values() if notice.get('unread') is True) for state in controls.get('controls') or [])
        states=Counter(row.get('state','UNKNOWN') for row in history.get('deliveries') or []);cutoff=now-timedelta(hours=24)
        recent_failed=0;recent_reserved=0
        for row in history.get('deliveries') or []:
            at=_parse(row.get('updated_at') or row.get('created_at'))
            if not at or at.astimezone(timezone.utc)<cutoff:continue
            recent_failed+=int(row.get('state')=='dispatch_failed');recent_reserved+=int(row.get('state')=='reserved')
        warnings=[]
        if controls.get('errors'):warnings.append('unreadable_tracking_controls')
        if unread:warnings.append('unread_in_app_notifications')
        if recent_failed:warnings.append('recent_notification_dispatch_failures')
        if recent_reserved:warnings.append('recent_unresolved_notification_reservations')
        configured=bool((controls.get('controls') or []) or history.get('total') or controls.get('errors'))
        if not configured:return _component('NOT_CONFIGURED','尚无 Tracking notifications / delivery receipts。')
        return _component('WARN' if warnings else 'OK',f'Notifications unread={unread}；delivery receipts={history.get("total",0)}。',
            evidence={'tracking_controls':len(controls.get('controls') or []),'control_errors':len(controls.get('errors') or []),
                'unread_in_app':unread,'delivery_total':history.get('total',0),'delivery_state_counts':dict(states),
                'recent_dispatch_failed_24h':recent_failed,'recent_reserved_24h':recent_reserved,'display_confirmed':False},warnings=warnings,
            limitations=['Qt hand-off is not certified user-visible delivery; the in-app notice remains authoritative.'])

    def _daily_market(self,now):
        from quantlab.data.daily_market_archive import DailyMarketArchive,DailyMarketArchiveError
        try:value=DailyMarketArchive(self.output).overview()
        except (DailyMarketArchiveError,OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','DailyMarket 归档读取失败。',blockers=['daily_market_archive_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        if not value['accepted_days']:return _component('NOT_CONFIGURED','尚无 accepted DailyMarket 日快照。',evidence=value)
        latest=value.get('latest_day');today=now.astimezone(TZ).date();warnings=[];blockers=[];age_days=None
        try:
            from datetime import date
            day=date.fromisoformat(latest);age_days=(today-day).days
            if age_days<0:blockers.append('daily_market_latest_day_in_future')
            elif age_days>3:warnings.append('daily_market_calendar_day_lag_gt_3')
            elif age_days>1:warnings.append('daily_market_calendar_day_lag_gt_1')
        except (TypeError,ValueError):blockers.append('daily_market_latest_day_invalid')
        if value.get('revision_candidates',0):blockers.append('daily_market_revision_review_pending')
        status='BLOCKED' if blockers else ('WARN' if warnings else 'OK')
        return _component(status,f"DailyMarket latest={latest} accepted_days={value['accepted_days']} revisions={value['revision_candidates']}。",
            evidence={**value,'calendar_age_days':age_days},blockers=blockers,warnings=warnings,
            limitations=['Freshness uses calendar-day lag only; exchange holidays are not inferred as missing sessions.'])

    def _market_snapshots(self,now):
        from quantlab.trading.market_snapshot import MarketSnapshotStore,MarketSnapshotError
        store=MarketSnapshotStore(self.output)
        try:overview=store.overview();records=store.list(limit=2000)['records'] if overview['snapshots'] else []
        except (MarketSnapshotError,OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','MarketSnapshot 存储不可读。',blockers=['market_snapshot_store_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        if not records:return _component('NOT_CONFIGURED','尚无 MarketSnapshot。',evidence=overview)
        latest_by_frame={}
        for row in records:latest_by_frame.setdefault(row['frame'],row)
        today=now.astimezone(TZ).date().isoformat()
        live_today=[row for row in records if row['trading_day']==today and row.get('capture_status')=='LIVE_NEAR_REALTIME']
        local=now.astimezone(TZ);in_market_window=local.weekday()<5 and local.time().replace(tzinfo=None)>=datetime.strptime('09:15','%H:%M').time() and local.time().replace(tzinfo=None)<=datetime.strptime('15:30','%H:%M').time()
        status='OK' if live_today or not in_market_window else 'UNKNOWN'
        return _component(status,f"MarketSnapshot 共 {overview['snapshots']} 条；今日近实时={len(live_today)}。",
            evidence={'overview':overview,'live_today':len(live_today),'latest_by_frame':{k:{'trading_day':v['trading_day'],'as_of':v['as_of'],'provider':v['provider'],'capture_status':v['capture_status'],'completeness':v['completeness']} for k,v in latest_by_frame.items()}},
            limitations=['No current LIVE snapshot during a weekday market window is UNKNOWN, not automatically a provider outage; exchange holidays are not inferred.'])

    def _orchestrator(self,now):
        root=self.output/'_daily_orchestrator'
        if not root.exists():return _component('NOT_CONFIGURED','尚无 Daily Orchestrator 计划。')
        if root.is_symlink():return _component('BLOCKED','Daily Orchestrator 目录是符号链接。',blockers=['daily_orchestrator_symlink'])
        rows=[];unreadable=0
        for path in root.glob('*.json'):
            if path.is_symlink():unreadable+=1;continue
            try:
                value=read_checked(path)
                if value.get('format')!='daily-playbook-orchestrator-v1':raise ValueError()
                rows.append(value)
            except (OSError,ValueError,TypeError,KeyError):unreadable+=1
        if not rows:
            return _component('BLOCKED' if unreadable else 'NOT_CONFIGURED','没有可读 Daily Orchestrator 计划。',evidence={'unreadable':unreadable},blockers=['orchestrator_state_unreadable'] if unreadable else [])
        rows.sort(key=lambda r:(r.get('trading_day',''),r.get('updated_at','')),reverse=True);latest=rows[0];state=str(latest.get('status','UNKNOWN'))
        blockers=[];warnings=[];today=now.astimezone(TZ).date().isoformat();plan_day=str(latest.get('trading_day') or '')
        current_plan=(plan_day==today)
        if state.startswith('BLOCKED'):
            code='orchestrator_'+state.lower()
            if current_plan:blockers.append(code)
            else:warnings.append('historical_'+code)
        elif state in ('COMPLETE_WITH_MISSED','DAILY_MARKET_CAPTURE_FAILED') or 'MISSED' in state:
            warnings.append(('orchestrator_' if current_plan else 'historical_orchestrator_')+state.lower())
        if unreadable:warnings.append('unreadable_orchestrator_states')
        status='BLOCKED' if blockers else ('WARN' if warnings else ('UNKNOWN' if state=='UNKNOWN' else 'OK'))
        return _component(status,f"最新计划 {latest.get('trading_day')} status={state}；current_day={current_plan}。",
            evidence={'plans':len(rows),'current_plan_present':current_plan,'today':today,'latest':{'trading_day':latest.get('trading_day'),'as_of_session':latest.get('as_of_session'),
                'status':state,'updated_at':latest.get('updated_at'),'daily_market':latest.get('daily_market'),
                'prep_status':(latest.get('prep') or {}).get('status'),'auction_status':(latest.get('auction') or {}).get('status'),
                'r1_status':(latest.get('r1') or {}).get('status')},'unreadable':unreadable},blockers=blockers,warnings=warnings,
            limitations=['A historical blocked/missed plan remains visible as WARN but does not block today by itself.'])

    def _pit_playbook(self,now):
        from quantlab.trading.playbook_store import PlaybookStore,PlaybookError
        store=PlaybookStore(self.output)
        try:overview=store.overview();sets=store.list_candidate_sets(limit=2000)['records'] if overview['candidate_sets'] else []
        except (PlaybookError,OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Playbook/PIT 结构化证据不可读。',blockers=['playbook_store_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        if not sets:return _component('NOT_CONFIGURED','尚无 CandidateSet/PIT 证据。',evidence=overview)
        counts=Counter((row.get('completeness','UNKNOWN'),row.get('pit_status','UNKNOWN')) for row in sets)
        latest=max(sets,key=lambda r:(r.get('as_of',''),r.get('candidate_set_id','')))
        strict=latest.get('completeness')=='FULL' and latest.get('pit_status')=='STRICT_PIT';warnings=[]
        if not strict:warnings.append('latest_candidate_set_not_full_strict_pit')
        if overview.get('frozen_definitions',0)==0:warnings.append('no_frozen_playbook_definition')
        status='WARN' if warnings else 'OK'
        return _component(status,f"最新 CandidateSet={latest.get('completeness')}/{latest.get('pit_status')}；FROZEN definitions={overview.get('frozen_definitions',0)}。",
            evidence={'overview':overview,'latest_candidate_set':{'id':latest.get('candidate_set_id'),'trading_day':latest.get('trading_day'),
                'frame':latest.get('frame'),'as_of':latest.get('as_of'),'completeness':latest.get('completeness'),'pit_status':latest.get('pit_status')},
                'candidate_quality_counts':{f'{a}/{b}':n for (a,b),n in counts.items()},
                'official_rule_receipt_present':bool(self.data_root and (self.data_root/'research'/'official_market_rules.json').is_file())},
            warnings=warnings,limitations=['CandidateSet PIT is case-specific and never certifies the whole provider or data lake.'])

    def _paper(self,now):
        from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics
        try:value=PaperLifecycleAnalytics(self.output).build()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Paper lifecycle 证据不可读。',blockers=['paper_lifecycle_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        configured=bool(value.get('paper_plans') or value.get('dynamic_account_count') or value.get('system_predictions'))
        if not configured:return _component('NOT_CONFIGURED','尚无 Paper lifecycle 证据。',evidence=value)
        failures=sum(v for k,v in (value.get('paper_plan_status') or {}).items() if 'FAILED' in k)
        failures+=sum(v for k,v in (value.get('paper_rebalance_status') or {}).items() if 'FAILED' in k)
        status='WARN' if failures else 'OK'
        return _component(status,f"Paper plans={value.get('paper_plans')} executions={value.get('paper_executions')} dynamic_accounts={value.get('dynamic_account_count')}。",
            evidence=value,warnings=['paper_execution_failures_present'] if failures else [],
            limitations=['Paper health is simulated execution evidence and never certifies real broker readiness.'])

    def _broker_shadow(self,now):
        from quantlab.broker import BrokerSnapshotStore
        try:value=BrokerSnapshotStore(self.output).list(limit=2000)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Broker shadow 快照不可读。',blockers=['broker_shadow_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        rows=value['records'];warnings=[]
        if not rows:return _component('NOT_CONFIGURED','尚无只读 Broker 账户快照。',evidence={'real_broker_connected':False,'order_submission':False})
        latest=rows[0];captured=_parse(latest.get('captured_at'));age=None
        if captured:age=max(0.0,(now-captured.astimezone(timezone.utc)).total_seconds())
        if age is None or age>86400:warnings.append('broker_snapshot_stale_gt_24h')
        if value.get('errors'):warnings.append('unreadable_broker_snapshots')
        return _component('WARN' if warnings else 'OK',f"Broker read-only snapshots={value['total']} latest={latest['account_alias']}。",
            evidence={'snapshot_count':value['total'],'latest_snapshot_id':latest['snapshot_id'],'provider':latest['provider'],
                'account_alias':latest['account_alias'],'captured_at':latest['captured_at'],'age_seconds':age,
                'position_count':len(latest['positions']),'real_broker_connected':False,'order_submission':False},warnings=warnings,
            limitations=['Imported account exports are read-only evidence; they do not prove a live broker connection or authorize orders.'])

    def _devstudio(self,now):
        from quantlab.devstudio.store import DevTaskStore,DevTaskError
        try:tasks=DevTaskStore(self.output).list(limit=2000)
        except (DevTaskError,OSError,ValueError,KeyError,TypeError) as exc:
            return _component('BLOCKED','Dev Studio 状态不可读。',blockers=['devstudio_state_invalid'],evidence={'error':type(exc).__name__+': '+str(exc)[:300]})
        if not tasks:return _component('NOT_CONFIGURED','尚无 DevTask。')
        counts=Counter(row.get('state','UNKNOWN') for row in tasks);warnings=[];blockers=[];missing=[];stale=[]
        for task in tasks:
            state=task.get('state');worktree=Path(task.get('worktree_path','')) if task.get('worktree_path') else None
            if state not in ('MERGED','CANCELLED') and (worktree is None or not worktree.is_dir()):missing.append(task.get('task_id'))
            updated=_parse(task.get('updated_at'))
            if state=='RUNNING' and updated and now-updated.astimezone(timezone.utc)>timedelta(hours=2):stale.append(task.get('task_id'))
        if missing:blockers.append('active_devtask_worktree_missing')
        if counts.get('BLOCKED'):warnings.append('blocked_devtasks_present')
        if counts.get('READY_FOR_HUMAN'):warnings.append('devtasks_waiting_human_merge')
        if stale:warnings.append('running_devtasks_stale_gt_2h')
        status='BLOCKED' if blockers else ('WARN' if warnings else 'OK')
        return _component(status,f"DevTask={len(tasks)} active={sum(v for k,v in counts.items() if k not in ('MERGED','CANCELLED'))}。",
            evidence={'counts':dict(counts),'missing_active_worktrees':missing,'stale_running_tasks':stale},blockers=blockers,warnings=warnings,
            limitations=['READY_FOR_HUMAN is an attention state, not a software failure.'])

    def _logs(self,now):
        candidates=[self.output/'_tracking_daemon'/'launchd.out.log',self.output/'_tracking_daemon'/'launchd.err.log']
        rows=[];warnings=[]
        for path in candidates:
            if not path.exists():continue
            if path.is_symlink():return _component('BLOCKED','日志路径是符号链接。',blockers=['system_log_symlink'])
            try:
                stat=path.stat();modified=datetime.fromtimestamp(stat.st_mtime,tz=timezone.utc);row={'path':str(path.relative_to(self.output)),
                    'bytes':stat.st_size,'modified_at':modified.isoformat()};rows.append(row)
                if path.name.endswith('.err.log') and stat.st_size and now-modified<timedelta(hours=24):warnings.append('recent_nonempty_tracking_error_log')
            except OSError:warnings.append('system_log_metadata_unreadable')
        if not rows:return _component('NOT_CONFIGURED','尚无已知后台日志文件。')
        return _component('WARN' if warnings else 'OK',f'已知后台日志 {len(rows)} 个；只读元数据，不自动读取敏感内容。',evidence={'logs':rows},warnings=warnings,
            limitations=['Log health uses size/mtime metadata only and does not infer correctness from text content.'])

    def build(self):
        now=_aware(self.now_fn());components={
            'workspace':self._workspace(now),'artifact_growth':self._artifact_growth(now),'jobs':self._jobs(now),
            'tracking_daemon':self._tracking_daemon(now),'mcp':self._mcp(now),'notifications':self._notifications(now),
            'market_data_series':self._market_data_series(now),'daily_market':self._daily_market(now),'market_snapshots':self._market_snapshots(now),
            'daily_orchestrator':self._orchestrator(now),'pit_playbook':self._pit_playbook(now),
            'paper_lifecycle':self._paper(now),'broker_shadow':self._broker_shadow(now),
            'dev_studio':self._devstudio(now),'logs':self._logs(now)}
        runtime=('workspace','artifact_growth','jobs','tracking_daemon','mcp','notifications','dev_studio','logs')
        readiness=('market_data_series','daily_market','market_snapshots','daily_orchestrator','pit_playbook','paper_lifecycle')
        blockers=[];warnings=[]
        for name,value in components.items():
            blockers.extend({'component':name,'code':code} for code in value['blockers'])
            warnings.extend({'component':name,'code':code} for code in value['warnings'])
        counts=Counter(value['status'] for value in components.values())
        return {'format':'niuniu-system-health-v1','checked_at':now.isoformat(),
            'summary':{'runtime_status':_axis(components,runtime),'research_readiness_status':_axis(components,readiness),
                'component_status_counts':dict(counts),'blocker_count':len(blockers),'warning_count':len(warnings),
                'health_score':None,'automatic_actions':False,'real_broker_connected':False},
            'components':components,'blockers':blockers,'warnings':warnings,
            'interpretation':'Operational OK means observable files/services are readable and consistent. It does not mean a strategy is correct, profitable, strict-PIT, or ready for real trading.'}


__all__=['STATUSES','SystemHealthService']
