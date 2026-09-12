"""Configurable A-share Decision Frame windows and submission classification."""
from __future__ import annotations

from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from quantlab.storage.codec import digest,encode

POLICY_VERSION='a-share-default-v1'
TIMEZONE='Asia/Shanghai'
DEFAULT_WINDOWS={
    'PREP':{'start_day_offset':-1,'start':'15:00','end_day_offset':0,'end':'09:15'},
    'AUCTION':{'start_day_offset':0,'start':'09:15','end_day_offset':0,'end':'09:30'},
    'R1':{'start_day_offset':0,'start':'09:30','end_day_offset':0,'end':'10:30'},
    'R2':{'start_day_offset':0,'start':'10:30','end_day_offset':0,'end':'13:30'},
    'R3':{'start_day_offset':0,'start':'13:30','end_day_offset':0,'end':'15:30'},
    'D1':None,'D2':None,'D3_PLUS':None,
}


def default_policy():
    return {'version':POLICY_VERSION,'timezone':TIMEZONE,'windows':json.loads(json.dumps(DEFAULT_WINDOWS))}


def _clock(value):
    try:return time.fromisoformat(value)
    except (TypeError,ValueError):raise ValueError('Frame 时间必须为 HH:MM。') from None


def validate_policy(value):
    from .decision import FRAMES
    if not isinstance(value,dict) or set(value)!= {'version','timezone','windows'}:raise ValueError('Frame Policy 字段无效。')
    if not isinstance(value['version'],str) or not value['version'].strip() or len(value['version'])>120:raise ValueError('Frame Policy version 无效。')
    try:ZoneInfo(value['timezone'])
    except Exception:raise ValueError('Frame Policy timezone 无效。') from None
    if not isinstance(value['windows'],dict) or set(value['windows'])!=set(FRAMES):raise ValueError('Frame Policy 必须覆盖全部 Frame。')
    for frame,spec in value['windows'].items():
        if spec is None:continue
        if not isinstance(spec,dict) or set(spec)!= {'start_day_offset','start','end_day_offset','end'}:raise ValueError('Frame Window 字段无效：'+frame)
        if type(spec['start_day_offset']) is not int or type(spec['end_day_offset']) is not int:raise ValueError('Frame 日偏移必须是整数。')
        if not -2<=spec['start_day_offset']<=2 or not -2<=spec['end_day_offset']<=2:raise ValueError('Frame 日偏移超出允许范围。')
        start=_clock(spec['start']);end=_clock(spec['end'])
        anchor=date(2026,1,2)
        start_dt=datetime.combine(anchor+timedelta(days=spec['start_day_offset']),start)
        end_dt=datetime.combine(anchor+timedelta(days=spec['end_day_offset']),end)
        if end_dt<=start_dt:raise ValueError('Frame 结束时间必须晚于开始时间：'+frame)
    return json.loads(json.dumps(value))


class FramePolicyStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.directory=self.output/'_trading';self.path=self.directory/'frame_policy.json'

    def load(self):
        if self.path.is_symlink() or self.directory.is_symlink():raise ValueError('Frame Policy 路径不能是符号链接。')
        if not self.path.exists():return default_policy()
        value=json.loads(self.path.read_text());policy=value.get('policy')
        if not isinstance(value,dict) or set(value)!= {'policy','checksum'} or digest(policy)!=value['checksum']:raise ValueError('Frame Policy 校验失败。')
        return validate_policy(policy)

    def save(self,policy):
        policy=validate_policy(policy);self.directory.mkdir(exist_ok=True)
        if self.path.is_symlink() or self.directory.is_symlink():raise ValueError('Frame Policy 路径不能是符号链接。')
        current=self.load() if self.path.exists() else default_policy()
        if digest(current)!=digest(policy) and current['version']==policy['version']:
            raise ValueError('修改 Frame 时间窗口时必须同时更新 policy version。')
        payload={'policy':policy,'checksum':digest(policy)};tmp=self.path.with_suffix('.tmp')
        tmp.write_text(encode(payload));tmp.replace(self.path);return policy


def assess_submission(trading_day,frame,submitted_at,policy):
    policy=validate_policy(policy);tz=ZoneInfo(policy['timezone'])
    if isinstance(submitted_at,str):submitted_at=datetime.fromisoformat(submitted_at.replace('Z','+00:00'))
    if not isinstance(submitted_at,datetime) or submitted_at.tzinfo is None:raise ValueError('submitted_at 必须是带时区时间。')
    local=submitted_at.astimezone(tz);day=date.fromisoformat(trading_day);window=policy['windows'][frame]
    base={'frame_policy_version':policy['version'],'frame_timezone':policy['timezone'],'submitted_local':local.isoformat()}
    if window is None:
        status='BACKFILL' if local.date()>day else 'UNBOUNDED'
        return {**base,'submission_status':status,'frame_open_at':None,'frame_close_at':None,'submission_lag_seconds':None}
    start=datetime.combine(day+timedelta(days=window['start_day_offset']),_clock(window['start']),tzinfo=tz)
    end=datetime.combine(day+timedelta(days=window['end_day_offset']),_clock(window['end']),tzinfo=tz)
    if local.date()>day:status='BACKFILL'
    elif local<start:status='EARLY'
    elif local<=end:status='ON_TIME'
    else:status='LATE'
    lag=(local-end).total_seconds() if status in ('LATE','BACKFILL') else 0.0
    return {**base,'submission_status':status,'frame_open_at':start.isoformat(),'frame_close_at':end.isoformat(),'submission_lag_seconds':lag}
