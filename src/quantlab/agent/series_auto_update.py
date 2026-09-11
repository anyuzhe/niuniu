"""Finite, host-authorized Baostock downloads for a fixed series; no model control."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from quantlab.data.baostock_ingest import load_import, run_import
from quantlab.data.baostock_series import SeriesService, read_series
from quantlab.storage.codec import digest
from uuid import uuid4

ZONE=ZoneInfo('Asia/Shanghai')
TERMINAL=('published','failed','revision_review','no_data','cancelled','timed_out')


def candidate_day(stamp,end_cap):
    local=stamp.astimezone(ZONE)
    # Query today's complete daily data only after the same conservative buffer
    # used by tracking. The provider calendar in the returned batch remains authoritative.
    day=local.date() if (local.hour,local.minute)>=(18,30) else local.date()-timedelta(days=1)
    return min(day,datetime.fromisoformat(end_cap+'T00:00:00+08:00').date())


def update_spec(output,series_root,target):
    state=read_series(series_root);token=state['history'][-1]['delivery']
    _,receipt=load_import(output,token['import_id']);plan=receipt['plan']
    datasets=['calendar','daily_raw']+(['daily_qfq'] if 'qfq' in token['modes'] else [])
    return {'symbols':list(token['symbols']),'start':token['start'],'end':str(target),
        'datasets':datasets,'snapshot_dates':[],'quarters':[]}


def maybe_update_series(output,series_root,grant,state,stamp,persist=None):
    policy=grant.get('auto_download') or {'enabled':False}
    if not policy.get('enabled'):return {'status':'disabled','network_requests':0}
    if type(policy.get('max_downloads')) is not int or not 1<=policy['max_downloads']<=10:
        raise ValueError('自动下载预算无效')
    history=state.setdefault('data_updates',[])
    series=read_series(series_root);current_entry=series['history'][-1];current=current_entry['delivery']
    expected=state.get('accepted_publication_id') or grant.get('series_publication_id')
    target=candidate_day(stamp,grant['end']);latest=history[-1] if history else None
    recovering_own_publication=bool(latest and latest.get('target')==str(target) and
        latest.get('status')=='downloading' and latest.get('import_id')==current.get('import_id'))
    if expected and current_entry['publication_id']!=expected and not recovering_own_publication:
        raise ValueError('固定通道发布版本由其他操作改变，需要重新授权')
    if recovering_own_publication:
        latest.update(status='published',generation=series['generation'],publication_id=current_entry['publication_id'],recovered_publication=True)
        if persist is not None:persist()
        return {'status':'published','network_requests':0,'import_id':latest['import_id'],
            'generation':latest['generation'],'publication_id':latest['publication_id'],'recovered':True}
    if target<=datetime.fromisoformat(current['end']+'T00:00:00+08:00').date():
        return {'status':'current','network_requests':0,'current_end':current['end']}
    recovered=None
    if latest and latest['target']==str(target):
        if latest['status']=='downloading' and latest.get('import_id'):
            try:
                _, recovered=load_import(output,latest['import_id'])
            except (OSError,ValueError,KeyError,TypeError):
                recovered=None
            if recovered is None:
                started=datetime.fromisoformat(latest['checked_at'])
                if stamp-started<timedelta(minutes=15):
                    return {'status':'downloading','network_requests':0,'import_id':latest['import_id']}
                latest.update(status='failed',error='预留下载长时间没有生成可核验回执')
                if persist is not None:persist()
            if recovered and recovered.get('status') in ('completed','completed_with_errors','failed','cancelled','timed_out'):
                latest['import_status']=recovered.get('status');latest['dataset_ready']=bool(recovered.get('dataset_ready'))
            elif recovered and recovered.get('status')=='running':
                started=datetime.fromisoformat(latest['checked_at'])
                if stamp-started<timedelta(minutes=15):
                    return {'status':'downloading','network_requests':0,'import_id':latest['import_id']}
                latest.update(status='failed',error='下载回执长时间停留在running，需要冷却后重新下载')
                if persist is not None:persist()
        if latest['status']=='failed':
            retry_at=datetime.fromisoformat(latest['checked_at'])+timedelta(hours=6)
            if stamp<retry_at:return {'status':'cooldown','network_requests':0,'retry_at':retry_at.isoformat()}
        elif latest['status'] not in ('cancelled','downloading'):
            return {'status':latest['status'],'network_requests':0,'import_id':latest.get('import_id')}
        if latest['status']=='downloading' and recovered:
            entry=latest;result=recovered;network_requests=0
        else:
            entry=None
    else:entry=None
    if entry is None:
        if len(history)>=policy['max_downloads']:
            return {'status':'budget_exhausted','network_requests':0}
        spec=update_spec(output,series_root,target);entry={'target':str(target),
            'spec_digest':digest(spec),'checked_at':stamp.isoformat(),'status':'downloading',
            'import_id':str(uuid4())}
        history.append(entry)
        if persist is not None:persist()
        result=run_import(output,spec,timeout=300,identifier=entry['import_id'])
        network_requests=1
    entry.update(import_id=result.get('import_id',entry.get('import_id')),import_status=result.get('status'),
        dataset_ready=bool(result.get('dataset_ready')))
    if result.get('status') not in ('completed','completed_with_errors') or not result.get('dataset_ready'):
        entry['status']='failed';entry['error']=str(result.get('error') or result.get('normalization_error') or result.get('status'))[:300]
        return {'status':'failed','network_requests':network_requests,'import_id':entry.get('import_id')}
    service=SeriesService(output)
    latest_series=read_series(series_root);latest_publication=latest_series['history'][-1]
    if latest_publication['delivery']['import_id']==entry['import_id']:
        entry.update(status='published',generation=latest_series['generation'],
            publication_id=latest_publication['publication_id'],recovered_publication=True)
        if persist is not None:persist()
        return {'status':'published','network_requests':network_requests,'import_id':entry['import_id'],
            'generation':entry['generation'],'publication_id':entry['publication_id'],'recovered':True}
    if expected and latest_publication['publication_id']!=expected:
        raise ValueError('下载期间固定通道被其他操作更新，需要重新授权')
    try:
        plan=service.preview(series['series_id'],entry['import_id'])
    except (OSError,ValueError,KeyError,TypeError) as error:
        entry.update(status='failed',error='下载批次未通过发布审计：'+str(error)[:240])
        if persist is not None:persist()
        return {'status':'failed','network_requests':network_requests,'import_id':entry['import_id'],
            'error':entry['error']}
    entry['plan_digest']=digest(plan);entry['revisions']=plan['revisions_require_confirmation']
    if plan['revisions_require_confirmation']:
        entry['status']='revision_review'
        return {'status':'revision_review','network_requests':network_requests,'import_id':entry['import_id'],
            'comparisons':plan['comparisons']}
    published=service.accept(plan,entry['plan_digest'],confirmed=True,accept_revisions=False)
    entry.update(status='published',generation=published['generation'],
        publication_id=published['publication']['publication_id'])
    return {'status':'published','network_requests':network_requests,'import_id':entry['import_id'],
        'generation':entry['generation'],'publication_id':entry['publication_id']}
