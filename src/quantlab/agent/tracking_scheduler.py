"""Bounded local-data refreshes under an explicit host grant; no LLM or network."""
from copy import deepcopy
from dataclasses import asdict
from zoneinfo import ZoneInfo
import polars as pl
from datetime import date,datetime,timedelta
from uuid import UUID,uuid5
from quantlab.agent.tracking_authorization import utc
from quantlab.agent.tracking_control_store import ControlStore,notify
from quantlab.agent.watchlist import WatchService
from quantlab.agent.refresh_readiness import watch_readiness,watch_readiness_calendar
from quantlab.agent.series_auto_update import maybe_update_series
from quantlab.data.baostock_series import read_series
from quantlab.agent.proposals import workspace_identity
from quantlab.agent.planning import ResearchBudget,preview_experiment
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest, read_table
from quantlab.data.session_coverage import audit_daily_coverage, calendar_sessions
from quantlab.data.provider import local_data_provider
from quantlab.workbench.jobs import prepare
from quantlab.experiments.campaign_state import input_signature
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.codec import digest

PENDING=('reserved','queued','running')


class TrackingScheduler:
    def __init__(self,output,data_root,get_queue):
        self.store=ControlStore(output);self.output=self.store.output
        self.data_root=data_root;self.get_queue=get_queue
        self.watch=WatchService(output,data_root)
    def validate(self,state,stamp):
        grant=state['grant'];definition,watch_state=self.watch.store.read(state['watch_id'])
        if not watch_state['active']:raise ValueError('跟踪已暂停，授权停止接收新任务')
        if not state['enabled']:raise ValueError('授权已撤销')
        if not datetime.fromisoformat(grant['prepared_at'])<=stamp<datetime.fromisoformat(grant['expires_at']):
            raise ValueError('授权过期或系统时钟回退')
        actual={'output':workspace_identity(self.output),'data_root':workspace_identity(self.data_root),
            'runtime':runtime_fingerprint()}
        if actual!=grant['binding'] or digest(definition)!=grant['watch_hash']:
            raise ValueError('代码、目录或跟踪定义变化，需要重新授权')
        if grant.get('calendar_mode')=='series_current':
            series=read_series(self.data_root)
            if series['series_id']!=grant.get('series_id'):
                raise ValueError('固定更新通道身份变化，需要重新授权')
            if grant['import_id'] not in [p['delivery']['import_id'] for p in series['history']]:
                raise ValueError('授权起始数据批次不在当前发布链中')
            expected=state.get('accepted_publication_id') or grant.get('series_publication_id')
            current=series['history'][-1];latest_update=(state.get('data_updates') or [None])[-1]
            recovering=bool(latest_update and latest_update.get('status')=='downloading' and
                latest_update.get('import_id')==current['delivery']['import_id'])
            if expected and current['publication_id']!=expected and not recovering:
                raise ValueError('固定通道发布版本由其他操作改变，需要重新授权')
            if grant.get('auto_download',{}).get('enabled') and not (self.data_root/'baostock-series.json').is_file():
                raise ValueError('自动下载只允许固定更新通道')
        else:
            directory,receipt=load_import(self.output,grant['import_id'])
            manifest,_=dataset_manifest(directory/'dataset')
            if manifest['checksum']!=grant['calendar_hash']:
                raise ValueError('授权日历变化，需要重新授权')
    def queue(self):
        queue=self.get_queue()
        if workspace_identity(queue.root)!=workspace_identity(self.output) or workspace_identity(queue.data_root)!=workspace_identity(self.data_root):
            raise ValueError('调度队列与授权工作空间不一致')
        return queue
    def calendar_source(self,state):
        grant=state['grant']
        if grant.get('calendar_mode')=='series_current':
            series=read_series(self.data_root);current=series['history'][-1]
            directory,receipt=load_import(self.output,current['delivery']['import_id'])
            manifest,_=dataset_manifest(directory/'dataset')
            if receipt.get('status') not in ('completed','completed_with_errors') or not manifest['calendar_ready']:
                raise ValueError('固定通道当前发布没有可用完整日历')
            return read_table(directory/'dataset','calendar'),{'mode':'series','series_id':series['series_id'],
                'generation':series['generation'],'publication_id':current['publication_id'],
                'import_id':current['delivery']['import_id'],'checksum':manifest['checksum']}
        directory,receipt=load_import(self.output,grant['import_id']);manifest,_=dataset_manifest(directory/'dataset')
        if receipt.get('status') not in ('completed','completed_with_errors') or manifest['checksum']!=grant['calendar_hash']:
            raise ValueError('授权日历批次状态或校验值变化')
        return read_table(directory/'dataset','calendar'),{'mode':'import','import_id':grant['import_id'],'checksum':manifest['checksum']}
    def calendar(self,state):return self.calendar_source(state)[0]
    def data_signature(self,spec,target,stamp,control):
        config=prepare(spec).config
        if config.data.end!=date.fromisoformat(target):raise ValueError('任务与目标日期不一致')
        batch=local_data_provider(self.data_root,spec['adjustment']).load(config.data)
        report=audit_daily_coverage(batch.bars,self.calendar(control),config.data.symbols,
            config.data.start,config.data.end,stamp)
        control['delivery_audit']=report
        if report['status']!='complete':
            gaps=[r['symbol']+':'+','.join(r['missing_examples'][:3]) for r in report['symbols'] if r['missing_sessions']]
            raise ValueError('日线覆盖不完整，未创建研究任务；'+(';'.join(gaps[:5]) or '存在重复、非交易日或未可用数据'))
        signature=input_signature(spec,self.data_root)
        if signature['status']!='available':raise ValueError('本地输入尚未通过校验')
        first=signature['inputs'][0]
        if first['bars_hash']!=digest(batch.bars.write_json()) or first['snapshot']!=asdict(batch.snapshot):
            raise ValueError('逐日审计后输入已变化，请重新核对')
        return digest(signature)
    def dispatch(self,state,cycle,stamp):
        self.validate(state,stamp)
        if self.data_signature(cycle['spec'],cycle['end'],stamp,state)!=cycle['guard']['input_signature']:
            raise ValueError('保留任务的输入数据变化，拒绝静默重放')
        result=self.queue().submit(cycle['job_id'],cycle['spec'],execution_guard=cycle['guard'])
        cycle.update(status='queued',submitted_at=stamp.isoformat())
        self.store.save(state)
    def settle(self,state,stamp):
        pending=[c for c in state['cycles'] if c['status'] in PENDING]
        if not pending:return
        jobs={j['job_id']:j for j in self.queue().list()}
        for cycle in pending:
            job=jobs.get(cycle['job_id'])
            if job is None:
                if cycle['status']=='reserved' and state['enabled']:
                    if stamp>=datetime.fromisoformat(state['next_check']):
                        self.dispatch(state,cycle,stamp)
                    continue
                cycle['status']='abandoned';state.update(enabled=False,status='lost_job')
                notify(state,'lost_job','lost_job',{'job_id':cycle['job_id']},stamp);continue
            if job['spec']!=cycle['spec'] or job.get('execution_guard')!=cycle['guard']:
                raise ValueError('任务日志和预授权配置不一致')
            if job['status']=='completed':
                result=self.watch.observe(state['watch_id'],job['run_id'])
                cycle.update(status='synced',run_id=job['run_id'],snapshot_id=result['snapshot']['snapshot_id'])
                state['status']='synchronized'
                notify(state,'synced:'+cycle['end'],'snapshot_updated',
                    {'end':cycle['end'],'run_id':job['run_id'],'snapshot_id':cycle['snapshot_id']},stamp)
                for alert in result['snapshot'].get('alerts',[]):
                    key='alert:'+alert['kind']+':'+str(alert.get('window',''))+':'+str(alert.get('horizon',''))
                    notify(state,key,alert['kind'],alert,stamp)
            elif job['status'] in ('failed','cancelled','interrupted'):
                cycle.update(status=job['status'],error=job.get('error'))
                state.update(enabled=False,status='execution_needs_review')
                notify(state,'job:'+cycle['job_id'],job['status'],
                    {'job_id':cycle['job_id'],'error':job.get('error')},stamp)
            else:cycle['status']=job['status']
        self.store.save(state)
    def advance(self,state,stamp):
        if not state['enabled'] or any(c['status'] in PENDING for c in state['cycles']):return
        if stamp<datetime.fromisoformat(state['next_check']):return
        grant=state['grant'];state['last_check']=stamp.isoformat()
        state['next_check']=(stamp+timedelta(minutes=grant['interval_minutes'])).isoformat()
        if len(state['cycles'])>=grant['max_jobs']:
            state.update(enabled=False,status='budget_exhausted');return
        if grant.get('calendar_mode')=='series_current' and grant.get('auto_download',{}).get('enabled'):
            update=maybe_update_series(self.output,self.data_root,grant,state,stamp,lambda:self.store.save(state))
            state['last_data_update']=update;state['last_data_update_at']=stamp.isoformat()
            if update['status']=='published':
                state['accepted_publication_id']=update['publication_id']
                self.store.save(state)
                notify(state,'data_publication:'+str(update.get('publication_id')),'data_series_updated',update,stamp)
            if update['status'] in ('failed','revision_review','cooldown','downloading','budget_exhausted'):
                names={'failed':'data_update_failed','revision_review':'data_revision_review',
                    'cooldown':'data_update_cooldown','downloading':'data_update_in_progress',
                    'budget_exhausted':'data_download_budget_exhausted'}
                state['status']=names[update['status']]
                if update['status']=='budget_exhausted':state['enabled']=False
                notify(state,'data_update',state['status'],update,stamp)
                return update.get('network_requests',0)
        calendar,calendar_ref=self.calendar_source(state)
        readiness=(watch_readiness_calendar(self.output,state['watch_id'],calendar,stamp.isoformat(),calendar_ref)
            if grant.get('calendar_mode')=='series_current' else watch_readiness(self.output,state['watch_id'],grant['import_id'],stamp.isoformat()))
        state['readiness']=readiness['status'];state['calendar_ref']=calendar_ref
        if readiness['status'] not in ('candidate_for_refresh','up_to_date'):
            state['status']=readiness['status'];return
        if readiness['proposed_end'] is None:return
        start=date.fromisoformat(grant['spec']['start'])
        cap_sessions=calendar_sessions(calendar,start,date.fromisoformat(grant['end']))
        candidates=[d for d in cap_sessions if str(d)<=readiness['proposed_end']]
        if not candidates:
            state['status']='no_trading_session_within_cap';return
        target=str(candidates[-1]);state['target_session']=target
        if all(v and datetime.fromisoformat(v).astimezone(ZoneInfo('Asia/Shanghai')).date()>=candidates[-1]
               for v in readiness['data_watermarks'].values()):
            state['status']='up_to_date'
            if candidates[-1]==cap_sessions[-1]:state.update(enabled=False,status='end_cap_reached')
            return
        if any(c['end']==target for c in state['cycles']):return
        spec=deepcopy(grant['spec']);spec['end']=target
        preview_experiment(spec,ResearchBudget(**grant['budget']))
        signature=self.data_signature(spec,target,stamp,state)
        guard={k:grant['budget'][k] for k in ('cooperative_seconds','max_active_jobs')}
        guard.update(runtime=grant['binding']['runtime'],input_signature=signature)
        cycle={'end':target,'job_id':str(uuid5(UUID(state['grant_id']),target)),
            'status':'reserved','spec':spec,'guard':guard,'reserved_at':stamp.isoformat(),
            'authorization':'tracking_grant','grant_id':state['grant_id']}
        state['cycles'].append(cycle);state['status']='reserved'
        self.store.save(state)  # Durable before queue submission, including on lost acknowledgement.
        self.dispatch(state,cycle,stamp);state['status']='submitted'
    def tick(self,*,now=None):
        stamp=utc(now);listing=self.store.list();results=[];network_requests=0
        for item in listing['controls']:
            watch_id=item['watch_id']
            if not item['enabled'] and not any(c['status'] in PENDING for c in item['cycles']):
                results.append({'watch_id':watch_id,'status':item['status'],'enabled':False})
                continue
            try:
                with self.store.locked(watch_id):
                    state=self.store.get(watch_id)
                    if state['enabled']:
                        try:self.validate(state,stamp)
                        except (ValueError,OSError,KeyError,TypeError) as error:
                            state.update(enabled=False,status='reauthorization_required')
                            notify(state,'authorization','reauthorization_required',str(error)[:240],stamp)
                    before_updates=len(state.get('data_updates',[]))
                    try:
                        self.settle(state,stamp)
                        self.advance(state,stamp)
                    except (ValueError,OSError,KeyError,TypeError) as error:
                        state['status']='blocked'
                        state['next_check']=(stamp+timedelta(minutes=state['grant']['interval_minutes'])).isoformat()
                        notify(state,'blocked','blocked',str(error)[:240],stamp)
                    network_requests+=max(0,len(state.get('data_updates',[]))-before_updates)
                    self.store.save(state)
                    results.append({'watch_id':watch_id,'status':state['status'],
                        'enabled':state['enabled'],'tasks_reserved':len(state['cycles'])})
            except BlockingIOError:results.append({'watch_id':watch_id,'status':'busy'})
        return {'controls':results,'errors':listing['errors'],'network_requests':network_requests}

    def reconcile_completed(self,watch_id,*,now=None):
        """Host action: adopt a manually recovered original job, never submit/resume."""
        stamp=utc(now)
        with self.store.locked(watch_id):
            state=self.store.get(watch_id)
            if state is None:raise ValueError('没有可核对的跟踪授权记录')
            candidates=[c for c in state['cycles'] if c['status'] in ('failed','cancelled','interrupted')]
            results=[];synchronized=0
            jobs={j['job_id']:j for j in self.queue().list()} if candidates else {}
            for cycle in candidates:
                job=jobs.get(cycle['job_id'])
                row={'job_id':cycle['job_id'],'previous_status':cycle['status']}
                try:
                    if job is None:raise ValueError('原任务记录缺失，不创建替代任务')
                    if job['spec']!=cycle['spec'] or job.get('execution_guard')!=cycle['guard']:
                        raise ValueError('原任务配置或执行约束变化，拒绝纳入跟踪')
                    if job['status']!='completed':
                        row.update(status='not_completed',job_status=job['status'])
                        results.append(row);continue
                    result=self.watch.observe(watch_id,job['run_id'])
                    cycle['manual_recovery']={'from_status':cycle['status'],'prior_error':cycle.get('error'),
                        'attempt':job.get('attempt',1),'checked_at':stamp.isoformat()}
                    cycle.update(status='synced',run_id=job['run_id'],
                        snapshot_id=result['snapshot']['snapshot_id'])
                    synchronized+=1
                    row.update(status='synced',run_id=job['run_id'],snapshot_id=cycle['snapshot_id'])
                    notify(state,'synced:'+cycle['end'],'snapshot_updated',row,stamp)
                    for alert in result['snapshot'].get('alerts',[]):
                        key='alert:'+alert['kind']+':'+str(alert.get('window',''))+':'+str(alert.get('horizon',''))
                        notify(state,key,alert['kind'],alert,stamp)
                    self.store.save(state)
                except (ValueError,OSError,KeyError,TypeError,pl.exceptions.PolarsError) as error:
                    row.update(status='requires_review',error=type(error).__name__+': '+str(error)[:240])
                results.append(row)
            if synchronized and not state['enabled']:
                state['recovery_previous_status']=state['status']
                state['status']='recovered_results_synced'
            report={'checked_at':stamp.isoformat(),'results':results,'synchronized':synchronized,
                'authorization_enabled':state['enabled'],'new_research_jobs':0,'resumed_jobs':0}
            state['last_reconciliation']=report
            self.store.save(state)
            return report
