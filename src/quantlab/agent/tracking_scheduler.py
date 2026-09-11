"""Bounded local-data refreshes under an explicit host grant; no LLM or network."""
from copy import deepcopy
import polars as pl
from datetime import date,datetime,timedelta
from uuid import UUID,uuid5
from quantlab.agent.tracking_authorization import utc
from quantlab.agent.tracking_control_store import ControlStore,notify
from quantlab.agent.watchlist import WatchService
from quantlab.agent.refresh_readiness import watch_readiness
from quantlab.agent.proposals import workspace_identity
from quantlab.agent.planning import ResearchBudget,preview_experiment
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest
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
        directory,receipt=load_import(self.output,grant['import_id'])
        manifest,_=dataset_manifest(directory/'dataset')
        if manifest['checksum']!=grant['calendar_hash']:
            raise ValueError('授权日历变化，需要重新授权')
    def queue(self):
        queue=self.get_queue()
        if workspace_identity(queue.root)!=workspace_identity(self.output) or workspace_identity(queue.data_root)!=workspace_identity(self.data_root):
            raise ValueError('调度队列与授权工作空间不一致')
        return queue
    def data_signature(self,spec,target,stamp):
        config=prepare(spec).config
        batch=local_data_provider(self.data_root,spec['adjustment']).load(config.data)
        for symbol in config.data.symbols:
            rows=batch.bars.filter(pl.col('symbol')==symbol)
            if rows.is_empty() or rows['datetime'].max().date()!=date.fromisoformat(target):
                raise ValueError('所选本地数据尚未覆盖目标日：'+symbol)
            if rows['available_at'].max()>stamp:raise ValueError('本地数据包含尚未完成的K线')
        signature=input_signature(spec,self.data_root)
        if signature['status']!='available':raise ValueError('本地输入尚未通过校验')
        return digest(signature)
    def dispatch(self,state,cycle,stamp):
        self.validate(state,stamp)
        if self.data_signature(cycle['spec'],cycle['end'],stamp)!=cycle['guard']['input_signature']:
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
        readiness=watch_readiness(self.output,state['watch_id'],grant['import_id'],stamp.isoformat())
        state['readiness']=readiness['status']
        if readiness['status'] not in ('candidate_for_refresh','up_to_date'):
            state['status']=readiness['status'];return
        if readiness['proposed_end'] is None:return
        target=min(grant['end'],readiness['proposed_end'])
        if all(v and datetime.fromisoformat(v).date()>=date.fromisoformat(target)
               for v in readiness['data_watermarks'].values()):
            state['status']='up_to_date'
            if target==grant['end']:state.update(enabled=False,status='end_cap_reached')
            return
        if any(c['end']==target for c in state['cycles']):return
        spec=deepcopy(grant['spec']);spec['end']=target
        preview_experiment(spec,ResearchBudget(**grant['budget']))
        signature=self.data_signature(spec,target,stamp)
        guard={k:grant['budget'][k] for k in ('cooperative_seconds','max_active_jobs')}
        guard.update(runtime=grant['binding']['runtime'],input_signature=signature)
        cycle={'end':target,'job_id':str(uuid5(UUID(state['grant_id']),target)),
            'status':'reserved','spec':spec,'guard':guard,'reserved_at':stamp.isoformat(),
            'authorization':'tracking_grant','grant_id':state['grant_id']}
        state['cycles'].append(cycle);state['status']='reserved'
        self.store.save(state)  # Durable before queue submission, including on lost acknowledgement.
        self.dispatch(state,cycle,stamp);state['status']='submitted'
    def tick(self,*,now=None):
        stamp=utc(now);listing=self.store.list();results=[]
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
                    try:
                        self.settle(state,stamp)
                        self.advance(state,stamp)
                    except (ValueError,OSError,KeyError,TypeError) as error:
                        state['status']='blocked'
                        state['next_check']=(stamp+timedelta(minutes=state['grant']['interval_minutes'])).isoformat()
                        notify(state,'blocked','blocked',str(error)[:240],stamp)
                    self.store.save(state)
                    results.append({'watch_id':watch_id,'status':state['status'],
                        'enabled':state['enabled'],'tasks_reserved':len(state['cycles'])})
            except BlockingIOError:results.append({'watch_id':watch_id,'status':'busy'})
        return {'controls':results,'errors':listing['errors'],'network_requests':0}

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
