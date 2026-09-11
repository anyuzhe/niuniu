"""Fixed host-approved local refresh plans. No network or model approval API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from quantlab.agent.proposals import ProposalService
from quantlab.agent.watchlist import WatchService
from quantlab.agent.refresh_readiness import latest_nominal_session
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest, read_table
from quantlab.agent.tracking_control_store import ControlStore
from quantlab.experiments.campaign_state import write_checked
from quantlab.storage.codec import digest


def utc(value=None):
    value=value or datetime.now(timezone.utc)
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError('控制时点必须包含时区')
    return value.astimezone(timezone.utc)


def preview_control(output,data_root,watch_id,import_id,end,expires_at,
                    max_jobs=3,interval_minutes=60,*,now=None):
    stamp=utc(now);expiry=utc(datetime.fromisoformat(expires_at))
    if not timedelta(minutes=5)<=expiry-stamp<=timedelta(days=30):
        raise ValueError('授权有效期须为5分钟至30天')
    if type(max_jobs) is not int or not 1<=max_jobs<=10:
        raise ValueError('一次授权最多1–10个研究任务')
    if type(interval_minutes) is not int or not 60<=interval_minutes<=1440:
        raise ValueError('检查间隔须为60–1440分钟')
    service=WatchService(output,data_root);definition,state=service.store.read(watch_id)
    if not state['active']:raise ValueError('跟踪已暂停')
    if definition['rule']['config']['data']['timeframe']!='1d':
        raise ValueError('受控调度目前只支持日线')
    spec=service.refresh_spec(watch_id,end)
    spec['question']=definition['name']+' · 受控授权刷新'
    preview=ProposalService(output,data_root).preview(spec)
    directory,receipt=load_import(output,import_id)
    manifest,_=dataset_manifest(directory/'dataset')
    if receipt['status'] not in ('completed','completed_with_errors') or not manifest['calendar_ready']:
        raise ValueError('授权需要已完成且完整的日历批次')
    calendar=read_table(directory/'dataset','calendar')
    latest_nominal_session(calendar,stamp,spec['adjustment'])
    if not manifest['plan']['start']<=end<=manifest['plan']['end']:
        raise ValueError('允许刷新截止须在所选日历覆盖内')
    return {'version':1,'watch_id':watch_id,'import_id':import_id,'end':end,
        'expires_at':expiry.isoformat(),'prepared_at':stamp.isoformat(),
        'max_jobs':max_jobs,'interval_minutes':interval_minutes,
        'watch_hash':digest(definition),'calendar_hash':manifest['checksum'],
        'spec':spec,'binding':preview['binding'],'budget':preview['budget'],
        'max_total_bar_evaluations':max_jobs*preview['estimate']['bar_evaluations_upper_estimate'],
        'scope':'本机已下载行情、固定规则与起点；仅截止日期可延长。无下载、模型调用或交易。'}


def authorize_control(output,data_root,plan,expected_digest,*,confirmed=False,now=None):
    if confirmed is not True:raise ValueError('必须在宿主界面核对完整计划并明确授权')
    if digest(plan)!=expected_digest:raise ValueError('授权摘要已变化，请重新预览')
    stamp=utc(now);prepared=utc(datetime.fromisoformat(plan['prepared_at']))
    if not timedelta(0)<=stamp-prepared<=timedelta(minutes=30):
        raise ValueError('预览已过期或时钟回退，请重新核对')
    current=preview_control(output,data_root,plan['watch_id'],plan['import_id'],plan['end'],
        plan['expires_at'],plan['max_jobs'],plan['interval_minutes'],now=prepared)
    if current!=plan or stamp>=utc(datetime.fromisoformat(plan['expires_at'])):
        raise ValueError('规则、代码、目录、日历或授权期限变化')
    store=ControlStore(output)
    with store.locked(plan['watch_id']) as folder:
        old=store.get(plan['watch_id'])
        if old and (old['enabled'] or any(c['status'] not in ('synced','failed','cancelled','interrupted','abandoned') for c in old['cycles'])):
            raise ValueError('请先撤销旧授权并处理未完成任务，再建立新授权')
        if old:
            history=folder/'history'
            if history.is_symlink():raise ValueError('授权历史路径异常')
            history.mkdir(exist_ok=True)
            archived=history/(old['grant_id']+'.json')
            if archived.exists():raise ValueError('旧授权已经归档，需核对状态')
            write_checked(archived,old)
        state={'watch_id':plan['watch_id'],'grant_id':str(uuid4()),'grant':plan,
            'enabled':True,'status':'authorized','authorized_at':stamp.isoformat(),
            'next_check':stamp.isoformat(),'last_check':None,'cycles':[],
            'notices':{},'authorization_source':'explicit_host_confirmation'}
        store.save(state)
    return state
