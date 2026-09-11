"""Calendar-based refresh suggestions; no scheduled execution or implied approval."""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
import polars as pl
from quantlab.data.baostock_dataset import read_table,dataset_manifest
from quantlab.data.baostock_ingest import load_import
from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import encode,digest


def latest_nominal_session(calendar,as_of,adjustment,buffer_minutes=30):
    if not isinstance(as_of,datetime) or as_of.tzinfo is None:raise ValueError('截止时间必须带时区')
    if adjustment not in ('raw','qfq'):raise ValueError('仅支持原始或前复权日线')
    if type(buffer_minutes) is not int or not 0<=buffer_minutes<=180:raise ValueError('缓冲分钟无效')
    stamp=as_of.astimezone(ZoneInfo('Asia/Shanghai'));today=stamp.date()
    rows=calendar.select('calendar_date','is_trading_day').sort('calendar_date').to_dicts()
    by_day={date.fromisoformat(r['calendar_date']):r['is_trading_day'] for r in rows}
    if not rows or len(by_day)!=len(rows) or any(v not in ('0','1') for v in by_day.values()):
        raise ValueError('交易日历重复、为空或含未知状态')
    dates=sorted(by_day)
    if not dates[0]<=today<=dates[-1]:raise ValueError('截止日不在已抓取日历内，不能推断为休市')
    expected=(dates[-1]-dates[0]).days+1
    if len(dates)!=expected:raise ValueError('日历存在缺日，不能回退到工作日猜测')
    release=time(17,30) if adjustment=='raw' else time(18,0)
    candidates=[d for d,v in by_day.items() if v=='1' and
        datetime.combine(d,release,stamp.tzinfo)+timedelta(minutes=buffer_minutes)<=stamp]
    return max(candidates) if candidates else None


def watch_readiness_calendar(output,watch_id,calendar,as_of,calendar_ref):
    watch=WatchService(output).get(watch_id);definition=watch['definition']
    cfg=definition['rule']['config']
    if cfg['data']['timeframe']!='1d':raise ValueError('此到期检查目前只处理日线跟踪')
    stamp=datetime.fromisoformat(as_of)
    if calendar_ref.get('mode')=='series':
        local=stamp.astimezone(ZoneInfo('Asia/Shanghai'))
        last=date.fromisoformat(calendar['calendar_date'].max())
        if local.date()>last:
            stamp=datetime.combine(last,time(23,59),local.tzinfo)
    target=latest_nominal_session(calendar,stamp,definition['rule']['adjustment'])
    known={};latest=watch['latest']
    if latest:known={s:row['data_at'] for s,row in latest['preview']['watermarks'].items()}
    behind=[s for s in cfg['data']['symbols'] if target is not None and
        (not known.get(s) or datetime.fromisoformat(known[s]).astimezone(ZoneInfo('Asia/Shanghai')).date()<target)]
    from quantlab.experiments.runner import runtime_fingerprint
    from quantlab.agent.tracking_preview import tracking_fingerprint
    compatible=(definition['rule']['source_runtime']==runtime_fingerprint() and
        definition['tracking_algorithm']==tracking_fingerprint())
    status='paused' if not watch['active'] else 'source_unverified' if watch['source_integrity']!='verified' else 'baseline_rebuild_required' if not compatible else (
        'no_nominally_released_session' if target is None else 'candidate_for_refresh' if behind else 'up_to_date')
    return {'watch_id':watch_id,'calendar_ref':calendar_ref,'as_of':as_of,'status':status,
        'proposed_end':target.isoformat() if target else None,'symbols_behind':behind,
        'data_watermarks':known,'new_research_jobs':0,'automatic_execution':False,
        'policy':'Current vendor schedule raw17:30/qfq18:00 Asia/Shanghai plus30min; actual delivery is unverified.',
        'limitations':['这是到期候选判断，不表示上游已更新或本地行情已下载。',
            '自动下载仅在宿主明确授权的固定通道中允许；历史修订会停止自动发布。',
            '未启用实盘或连续显著性判断。']}


def watch_readiness(output,watch_id,import_id,as_of):
    directory,source=load_import(output,import_id)
    manifest,_=dataset_manifest(directory/'dataset')
    if source.get('status') not in ('completed','completed_with_errors'):
        raise ValueError('只接受已完成的数据批次日历；取消或失败批次需重新导入')
    if not manifest['calendar_ready']:raise ValueError('本批未取得完整交易日历')
    calendar=read_table(directory/'dataset','calendar')
    value=watch_readiness_calendar(output,watch_id,calendar,as_of,
        {'mode':'import','import_id':import_id,'checksum':manifest['checksum']})
    value.update(calendar_import_id=import_id,calendar_fingerprint=manifest['checksum'])
    return value
