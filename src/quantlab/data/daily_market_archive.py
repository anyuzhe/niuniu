"""Immutable daily full-A-share Baostock snapshots for PREP automation."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import io
import json
import re
import socket

import polars as pl

from quantlab.data.capture_root import capture_root
from quantlab.data.baostock_catalog import DAILY_FIELDS
from quantlab.storage.codec import digest, encode

FORMAT='baostock-daily-market-v1'
RAW_FORMAT='baostock-daily-market-raw-v1'
EXPECTED_FIELDS=tuple(DAILY_FIELDS.split(','))
SYMBOL=re.compile(r'^(?:sh|sz)\.\d{6}$')


class DailyMarketArchiveError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _day(value):
    if isinstance(value,date):return value
    try:return date.fromisoformat(value)
    except (TypeError,ValueError):
        raise DailyMarketArchiveError('INVALID_ARGUMENT','date 必须为 YYYY-MM-DD。') from None


def _float(value,name,*,positive=False,nonnegative=False,optional=False):
    if value in ('',None):
        if optional:return None
        raise DailyMarketArchiveError('DATA_SCHEMA',name+' 不能为空。')
    try:number=float(value)
    except (TypeError,ValueError):
        raise DailyMarketArchiveError('DATA_SCHEMA',name+' 必须为数值。') from None
    if not (number==number and abs(number)!=float('inf')):
        raise DailyMarketArchiveError('DATA_SCHEMA',name+' 必须为有限数。')
    if positive and number<=0:raise DailyMarketArchiveError('DATA_SCHEMA',name+' 必须大于0。')
    if nonnegative and number<0:raise DailyMarketArchiveError('DATA_SCHEMA',name+' 不能小于0。')
    return number


def _normalize_row(row,day):
    if not isinstance(row,dict) or set(row)!=set(EXPECTED_FIELDS):
        raise DailyMarketArchiveError('DATA_SCHEMA','全市场日线字段与 Baostock 0.9.3 合同不一致。')
    if row['date']!=day.isoformat():raise DailyMarketArchiveError('DATA_SCHEMA','供应商返回了非请求日期。')
    code=row['code']
    if not isinstance(code,str) or not SYMBOL.fullmatch(code):raise DailyMarketArchiveError('DATA_SCHEMA','证券代码无效。')
    if row['adjustflag']!='3':raise DailyMarketArchiveError('DATA_SCHEMA','全市场日线必须是不复权 adjustflag=3。')
    if row['tradestatus'] not in ('0','1') or row['isST'] not in ('0','1'):
        raise DailyMarketArchiveError('DATA_SCHEMA','tradestatus/isST 必须为 0/1。')
    tradable=row['tradestatus']=='1'
    result={'date':day,'code':code,'adjustflag':'3','tradestatus':row['tradestatus'],'isST':row['isST']}
    for key in ('open','high','low','close','preclose'):
        result[key]=_float(row[key],key,positive=tradable,optional=not tradable)
    result['volume']=_float(row['volume'],'volume',nonnegative=True,optional=not tradable)
    result['amount']=_float(row['amount'],'amount',nonnegative=True,optional=True)
    for key in ('turn','pctChg','peTTM','pbMRQ','psTTM','pcfNcfTTM'):
        result[key]=_float(row[key],key,optional=True)
    if tradable:
        o,h,l,c=(result[k] for k in ('open','high','low','close'))
        if h<max(o,l,c) or l>min(o,h,c):
            raise DailyMarketArchiveError('DATA_SCHEMA','OHLC 关系无效。')
    return result


def _frame(rows,day):
    normalized=[_normalize_row(row,day) for row in rows]
    codes=[row['code'] for row in normalized]
    if len(codes)!=len(set(codes)):raise DailyMarketArchiveError('DATA_SCHEMA','同日证券不能重复。')
    if len(normalized)>20000:raise DailyMarketArchiveError('BUDGET_EXCEEDED','全市场日线超过20000行。')
    if not normalized:raise DailyMarketArchiveError('NO_DATA','供应商没有返回任何A股日线。')
    frame=pl.DataFrame(normalized).sort('code')
    return frame


def _parquet_bytes(frame):
    stream=io.BytesIO();frame.write_parquet(stream,compression='zstd');return stream.getvalue()


def _sha(payload):return hashlib.sha256(payload).hexdigest()


def _pointer_value(day,snapshot_id,manifest_sha):
    core={'format':'baostock-daily-market-pointer-v1','date':day.isoformat(),
        'snapshot_id':snapshot_id,'manifest_sha256':manifest_sha}
    return {**core,'checksum':digest(core)}


class DailyMarketArchive:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        if not self.output.is_dir():raise DailyMarketArchiveError('INVALID_WORKSPACE','工作空间不存在。')
        self.market_root=capture_root(self.output);self.root=self.market_root/'daily_market'

    def _guard(self):
        for path in (self.market_root,self.root):
            if path.is_symlink():raise DailyMarketArchiveError('INVALID_WORKSPACE','DailyMarket 路径不能是符号链接。')

    def day_root(self,day):
        day=_day(day);return self.root/day.isoformat()

    def _snapshot_root(self,day,snapshot_id):
        return self.day_root(day)/snapshot_id

    def _accepted_path(self,day):return self.day_root(day)/'accepted.json'

    def _read_pointer(self,day):
        path=self._accepted_path(day)
        if not path.exists():return None
        if path.is_symlink() or path.stat().st_size>10000:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','accepted pointer 无效。')
        value=json.loads(path.read_text())
        if not isinstance(value,dict) or set(value)!={'format','date','snapshot_id','manifest_sha256','checksum'}:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','accepted pointer 字段无效。')
        core={k:value[k] for k in ('format','date','snapshot_id','manifest_sha256')}
        if value['checksum']!=digest(core) or value['date']!=_day(day).isoformat():
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','accepted pointer 校验失败。')
        return value

    def _read_manifest(self,day,snapshot_id):
        folder=self._snapshot_root(day,snapshot_id);path=folder/'manifest.json'
        if any(p.is_symlink() for p in (folder,path)) or not path.is_file() or path.stat().st_size>100000:
            raise DailyMarketArchiveError('NOT_FOUND','DailyMarket snapshot 不存在或路径异常。')
        raw=path.read_bytes();value=json.loads(raw)
        required={'format','snapshot_id','date','fetched_at','sdk_version','fields','rows','raw_sha256',
            'parquet_sha256','content_hash','revision_of','capture_state','limitations'}
        if not isinstance(value,dict) or set(value)!=required or value.get('format')!=FORMAT:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket manifest 字段无效。')
        if value['snapshot_id']!=snapshot_id or value['date']!=_day(day).isoformat():
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket manifest 身份不一致。')
        raw_path=folder/'raw.json';parquet_path=folder/'daily.parquet'
        if any(p.is_symlink() for p in (raw_path,parquet_path)) or not raw_path.is_file() or not parquet_path.is_file():
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket snapshot 文件缺失。')
        raw_bytes=raw_path.read_bytes();pq_bytes=parquet_path.read_bytes()
        if _sha(raw_bytes)!=value['raw_sha256'] or _sha(pq_bytes)!=value['parquet_sha256']:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket snapshot 哈希校验失败。')
        raw_value=json.loads(raw_bytes)
        raw_required={'format','date','fields','rows','fetched_at','sdk_version'}
        if not isinstance(raw_value,dict) or set(raw_value)!=raw_required or raw_value.get('format')!=RAW_FORMAT:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket raw 字段无效。')
        core={'date':raw_value['date'],'fields':raw_value['fields'],'rows':raw_value['rows']}
        if digest(core)!=value['content_hash'] or len(raw_value['rows'])!=value['rows'] or raw_value['fields']!=value['fields']:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket content_hash 校验失败。')
        return value,_sha(raw)

    def accepted(self,day):
        pointer=self._read_pointer(day)
        if pointer is None:return None
        manifest,manifest_sha=self._read_manifest(day,pointer['snapshot_id'])
        if manifest_sha!=pointer['manifest_sha256']:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','accepted manifest 哈希变化。')
        return manifest

    def get(self,day,snapshot_id=''):
        day=_day(day);pointer=self._read_pointer(day)
        if snapshot_id:
            manifest,_=self._read_manifest(day,snapshot_id)
        else:
            manifest=self.accepted(day)
            if manifest is None:raise DailyMarketArchiveError('NOT_FOUND','该日期没有 accepted DailyMarket snapshot。')
        return {**manifest,'accepted':bool(pointer and pointer['snapshot_id']==manifest['snapshot_id'])}

    def _fetch(self,day,sdk=None):
        day=_day(day);logged=False;old_timeout=socket.getdefaulttimeout();socket.setdefaulttimeout(20)
        try:
            if sdk is None:
                import baostock as sdk
            with redirect_stdout(io.StringIO()):login=sdk.login()
            if getattr(login,'error_code',None)!='0':
                raise DailyMarketArchiveError('PROVIDER_ERROR','Baostock 登录失败：'+str(getattr(login,'error_msg',''))[:200])
            logged=True;query=sdk.query_daily_history_k_AStock(date=day.isoformat())
            if getattr(query,'error_code',None)!='0':
                raise DailyMarketArchiveError('PROVIDER_ERROR','Baostock 全市场日线失败：'+str(getattr(query,'error_msg',''))[:200])
            fields=tuple(query.fields)
            if fields!=EXPECTED_FIELDS:
                raise DailyMarketArchiveError('DATA_SCHEMA','Baostock 全市场日线字段版本发生变化。')
            rows=[]
            while query.next():
                values=query.get_row_data()
                if len(values)!=len(fields) or any(not isinstance(v,str) for v in values):
                    raise DailyMarketArchiveError('DATA_SCHEMA','Baostock 返回行与字段不一致。')
                rows.append(dict(zip(fields,values)))
                if len(rows)>20000:raise DailyMarketArchiveError('BUDGET_EXCEEDED','Baostock 全市场日线超过20000行。')
            if getattr(query,'error_code',None)!='0':
                raise DailyMarketArchiveError('PROVIDER_ERROR','Baostock 全市场日线分页失败。')
            return fields,rows,getattr(sdk,'__version__','unknown')
        finally:
            try:
                if logged:
                    with redirect_stdout(io.StringIO()):sdk.logout()
            finally:socket.setdefaulttimeout(old_timeout)

    def _write_pointer(self,day,snapshot_id,manifest_sha):
        folder=self.day_root(day);folder.mkdir(parents=True,exist_ok=True)
        if folder.is_symlink():raise DailyMarketArchiveError('INVALID_WORKSPACE','DailyMarket 日期目录不能是符号链接。')
        path=self._accepted_path(day);value=_pointer_value(_day(day),snapshot_id,manifest_sha)
        temporary=path.with_name('.accepted-'+str(uuid4())+'.tmp')
        try:
            temporary.write_text(encode(value));temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)

    def capture(self,day,*,sdk=None):
        self._guard();day=_day(day);fields,rows,sdk_version=self._fetch(day,sdk)
        frame=_frame(rows,day);fetched=self.now_fn()
        if not isinstance(fetched,datetime) or fetched.tzinfo is None:
            raise DailyMarketArchiveError('INVALID_CLOCK','DailyMarketArchive 时钟必须带时区。')
        core={'date':day.isoformat(),'fields':list(fields),'rows':rows};content_hash=digest(core)
        snapshot_id=str(uuid5(NAMESPACE_URL,f'niuniu-daily-market:{day.isoformat()}:{content_hash}'))
        raw_value={'format':RAW_FORMAT,**core,'fetched_at':fetched.astimezone(timezone.utc).isoformat(),
            'sdk_version':str(sdk_version)}
        raw_bytes=encode(raw_value).encode('utf-8');parquet_bytes=_parquet_bytes(frame)
        accepted=self.accepted(day);revision_of=accepted['snapshot_id'] if accepted else None
        capture_state='accepted' if accepted is None else ('accepted' if accepted['content_hash']==content_hash else 'revision_review')
        if accepted and accepted['content_hash']==content_hash:return {**accepted,'created':False,'revision_detected':False}
        manifest={'format':FORMAT,'snapshot_id':snapshot_id,'date':day.isoformat(),
            'fetched_at':raw_value['fetched_at'],'sdk_version':str(sdk_version),'fields':list(fields),
            'rows':frame.height,'raw_sha256':_sha(raw_bytes),'parquet_sha256':_sha(parquet_bytes),
            'content_hash':content_hash,'revision_of':revision_of,'capture_state':capture_state,
            'limitations':['Baostock当次观察值，不认证历史首次发布时间。',
                'daily_market接口实际返回证券集合不等于已认证PIT Universe。',
                '涨跌停官方逐日价格边界仍需独立MarketRules证据。']}
        day_root=self.day_root(day);day_root.mkdir(parents=True,exist_ok=True)
        destination=self._snapshot_root(day,snapshot_id)
        if destination.exists():
            existing,manifest_sha=self._read_manifest(day,snapshot_id)
            if existing['content_hash']!=content_hash:raise DailyMarketArchiveError('CONFLICT','DailyMarket snapshot_id 内容冲突。')
        else:
            temporary=day_root/('.tmp-'+str(uuid4()));temporary.mkdir()
            try:
                (temporary/'raw.json').write_bytes(raw_bytes)
                (temporary/'daily.parquet').write_bytes(parquet_bytes)
                manifest_bytes=encode(manifest).encode('utf-8');(temporary/'manifest.json').write_bytes(manifest_bytes)
                temporary.replace(destination);manifest_sha=_sha(manifest_bytes)
            finally:
                if temporary.exists():
                    for child in temporary.iterdir():child.unlink(missing_ok=True)
                    temporary.rmdir()
        if accepted is None:self._write_pointer(day,snapshot_id,manifest_sha)
        return {**manifest,'created':True,'revision_detected':capture_state=='revision_review'}

    def accept_revision(self,day,snapshot_id,*,confirmed=False):
        if confirmed is not True:raise DailyMarketArchiveError('CONFIRMATION_REQUIRED','接受市场数据修订需要宿主显式确认。')
        day=_day(day);current=self.accepted(day)
        if current is None:raise DailyMarketArchiveError('NOT_FOUND','该日期没有当前 accepted snapshot。')
        candidate,manifest_sha=self._read_manifest(day,snapshot_id)
        if candidate['snapshot_id']==current['snapshot_id']:return {**candidate,'changed':False}
        if candidate['revision_of']!=current['snapshot_id']:
            raise DailyMarketArchiveError('STALE_REVISION','修订不是基于当前 accepted snapshot。')
        if candidate['capture_state']!='revision_review':
            raise DailyMarketArchiveError('INVALID_REVISION','只有 revision_review snapshot 可切换。')
        self._write_pointer(day,snapshot_id,manifest_sha)
        return {**candidate,'changed':True}

    def read_frame(self,day,snapshot_id=None):
        day=_day(day)
        if snapshot_id is None:
            manifest=self.accepted(day)
            if manifest is None:raise DailyMarketArchiveError('NOT_FOUND','该日期没有 accepted DailyMarket snapshot。')
            snapshot_id=manifest['snapshot_id']
        else:manifest,_=self._read_manifest(day,snapshot_id)
        path=self._snapshot_root(day,snapshot_id)/'daily.parquet';payload=path.read_bytes()
        if _sha(payload)!=manifest['parquet_sha256']:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket parquet 哈希变化。')
        frame=pl.read_parquet(io.BytesIO(payload))
        if frame.height!=manifest['rows'] or frame['code'].n_unique()!=frame.height:
            raise DailyMarketArchiveError('CORRUPT_ARCHIVE','DailyMarket parquet 行数/证券唯一性异常。')
        return frame,manifest

    def list_days(self,limit=5000):
        if type(limit) is not int or not 1<=limit<=5000:raise DailyMarketArchiveError('INVALID_ARGUMENT','limit 必须为1–5000。')
        self._guard();rows=[]
        if not self.root.exists():return []
        for folder in sorted((p for p in self.root.iterdir() if p.is_dir()),reverse=True):
            try:day=_day(folder.name)
            except DailyMarketArchiveError:continue
            accepted=self.accepted(day)
            if accepted is None:continue
            revisions=0
            for child in folder.iterdir():
                if not child.is_dir():continue
                try:manifest,_=self._read_manifest(day,child.name)
                except DailyMarketArchiveError:continue
                revisions+=int(manifest['snapshot_id']!=accepted['snapshot_id'] and
                    manifest.get('capture_state')=='revision_review' and
                    manifest.get('revision_of')==accepted['snapshot_id'])
            rows.append({'date':day.isoformat(),'snapshot_id':accepted['snapshot_id'],'rows':accepted['rows'],
                'fetched_at':accepted['fetched_at'],'content_hash':accepted['content_hash'],'revision_candidates':revisions})
            if len(rows)>=limit:break
        return rows

    def latest_day(self):
        rows=self.list_days(limit=1);return rows[0]['date'] if rows else None

    def overview(self):
        rows=self.list_days(limit=5000)
        return {'accepted_days':len(rows),'latest_day':rows[0]['date'] if rows else None,
            'accepted_rows':sum(row['rows'] for row in rows),
            'revision_candidates':sum(row['revision_candidates'] for row in rows),
            'network_download_by_default':False,'provider':'baostock.query_daily_history_k_AStock'}


__all__=['FORMAT','EXPECTED_FIELDS','DailyMarketArchiveError','DailyMarketArchive']
