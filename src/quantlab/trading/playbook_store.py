"""Immutable, checksum-verified storage and audit logic for Expert Playbook Lab."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json
import math
import sqlite3

from quantlab.storage.codec import digest, encode
from .playbook import (
    VALIDATION_METHODS, normalize_candidate_set, normalize_expert_source,
    normalize_playbook_case, normalize_playbook_definition, normalize_selection,
    normalize_validation,
)


class PlaybookError(ValueError):
    def __init__(self, code, message):
        super().__init__(message); self.code = code

def identifier(value, name='id'):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise PlaybookError('INVALID_ARGUMENT', name+' 必须是规范 UUID。') from None
    return value


def now_iso(now_fn):
    value = now_fn()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PlaybookError('INVALID_CLOCK','PlaybookStore 时钟必须返回带时区时间。')
    return value.astimezone(timezone.utc).isoformat()


def _utc(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


SPECS = {
    'sources': ('source_id', {'source_id':'id','request_id':'request_id','input_hash':'input_hash','expert_key':'expert_key','completeness':'completeness','available_at':'available_at'}),
    'definitions': ('definition_id', {'definition_id':'id','request_id':'request_id','input_hash':'input_hash','playbook_key':'playbook_key','version':'version','state':'state','definition_hash':'definition_hash'}),
    'cases': ('case_id', {'case_id':'id','request_id':'request_id','input_hash':'input_hash','definition_id':'definition_id','trading_day':'trading_day','frame':'frame','as_of':'as_of'}),
    'candidate_sets': ('candidate_set_id', {'candidate_set_id':'id','request_id':'request_id','input_hash':'input_hash','case_id':'case_id','definition_id':'definition_id','completeness':'completeness','pit_status':'pit_status','candidate_hash':'candidate_hash'}),
    'selections': ('selection_id', {'selection_id':'id','request_id':'request_id','input_hash':'input_hash','candidate_set_id':'candidate_set_id','kind':'kind'}),
    'validations': ('validation_id', {'validation_id':'id','request_id':'request_id','input_hash':'input_hash','definition_id':'definition_id','method':'method','status':'status'}),
}


class PlaybookStore:
    def __init__(self, output, now_fn=None):
        self.output = Path(output).resolve()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.directory = self.output/'_playbooks'
        self.path = self.directory/'playbook_lab.sqlite3'

    @contextmanager
    def connection(self, write=False):
        paths = [self.directory,self.path,*[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if not self.output.is_dir() or any(path.is_symlink() for path in paths):
            raise PlaybookError('INVALID_WORKSPACE','Playbook Lab 目录无效或包含符号链接。')
        if write:
            self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():
            raise PlaybookError('NOT_FOUND','当前工作空间尚无 Playbook Lab 数据。')
        db = sqlite3.connect(self.path.as_uri()+('?mode=rwc' if write else '?mode=ro'), uri=True,
            timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):
                raise PlaybookError('SCHEMA_VERSION','Playbook Lab 版本不受支持。')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                self._ensure_schema(db)
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    @staticmethod
    def _ensure_schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, expert_key TEXT NOT NULL, completeness TEXT NOT NULL, available_at TEXT, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS source_lookup ON sources(expert_key,completeness,available_at)')
        db.execute('CREATE TABLE IF NOT EXISTS definitions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, playbook_key TEXT NOT NULL, version TEXT NOT NULL, state TEXT NOT NULL, definition_hash TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, UNIQUE(playbook_key,version))')
        db.execute('CREATE INDEX IF NOT EXISTS definition_lookup ON definitions(playbook_key,state,version)')
        db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, definition_id TEXT NOT NULL, trading_day TEXT NOT NULL, frame TEXT NOT NULL, as_of TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS case_lookup ON cases(definition_id,trading_day,frame,as_of)')
        db.execute('CREATE TABLE IF NOT EXISTS candidate_sets (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, case_id TEXT UNIQUE NOT NULL, definition_id TEXT NOT NULL, completeness TEXT NOT NULL, pit_status TEXT NOT NULL, candidate_hash TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS candidate_lookup ON candidate_sets(definition_id,completeness,pit_status)')
        db.execute('CREATE TABLE IF NOT EXISTS selections (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, candidate_set_id TEXT NOT NULL, kind TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS selection_lookup ON selections(candidate_set_id,kind)')
        db.execute('CREATE TABLE IF NOT EXISTS validations (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, definition_id TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS validation_lookup ON validations(definition_id,method,status)')
        db.execute('PRAGMA user_version=1')

    @staticmethod
    def _decode(row, table):
        if row is None:
            raise PlaybookError('NOT_FOUND','Playbook Lab 记录不存在。')
        value = json.loads(row['payload'])
        _, indexed = SPECS[table]
        if digest(value) != row['checksum'] or any(value.get(key) != row[column] for key,column in indexed.items()):
            raise PlaybookError('CORRUPT_RECORD','Playbook Lab 内容或索引校验失败。')
        return value

    def _existing_request(self, db, table, request_id, input_hash):
        row = db.execute(f'SELECT * FROM {table} WHERE request_id=?',(request_id,)).fetchone()
        if row is None:
            return None
        value = self._decode(row,table)
        if value['input_hash'] != input_hash:
            raise PlaybookError('CONFLICT','同一 request_id 不能保存不同内容。')
        return value

    def _get_in_db(self, db, table, record_id):
        id_key,_ = SPECS[table]
        identifier(record_id,id_key)
        return self._decode(db.execute(f'SELECT * FROM {table} WHERE id=?',(record_id,)).fetchone(),table)

    def _get(self, table, record_id):
        if self.path.is_symlink():
            raise PlaybookError('INVALID_WORKSPACE','Playbook Lab 数据库不能为符号链接。')
        with self.connection() as db:
            return self._get_in_db(db,table,record_id)

    def get_source(self, source_id): return self._get('sources',source_id)
    def get_definition(self, definition_id): return self._get('definitions',definition_id)
    def get_case(self, case_id): return self._get('cases',case_id)
    def get_candidate_set(self, candidate_set_id): return self._get('candidate_sets',candidate_set_id)
    def get_selection(self, selection_id): return self._get('selections',selection_id)
    def get_validation(self, validation_id): return self._get('validations',validation_id)

    def create_source(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_expert_source(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'sources',request_id,input_hash)
            if old is not None: return old
            if db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] >= 100000:
                raise PlaybookError('BUDGET_EXCEEDED','ExpertSource 已达十万条。')
            value = {**normalized,'source_id':str(uuid4()),'request_id':request_id,
                'input_hash':input_hash,'captured_at':created}
            search = ' '.join(str(value.get(k,'') or '') for k in
                ('expert_key','title','source_type','locator','completeness','notes')).casefold()
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)',(
                value['source_id'],request_id,input_hash,value['expert_key'],value['completeness'],
                value['available_at'],search,encode(value),digest(value)))
            return value

    @staticmethod
    def _verified_sources(db, source_ids):
        result = []
        for source_id in source_ids:
            row = db.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
            result.append(PlaybookStore._decode(row,'sources'))
        return result

    def create_definition(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_playbook_definition(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'definitions',request_id,input_hash)
            if old is not None: return old
            sources = self._verified_sources(db,normalized['source_ids'])
            if normalized['state']=='FROZEN' and any(s['completeness']!='VERIFIED' for s in sources):
                raise PlaybookError('SOURCE_NOT_VERIFIED','FROZEN Playbook 只能绑定 VERIFIED ExpertSource。')
            definition_hash = digest(normalized)
            value = {**normalized,'definition_id':str(uuid4()),'request_id':request_id,
                'input_hash':input_hash,'definition_hash':definition_hash,'created_at':created}
            search = ' '.join((value['playbook_key'],value['name'],value['version'],value['state'],value['notes'])).casefold()
            try:
                db.execute('INSERT INTO definitions VALUES (?,?,?,?,?,?,?,?,?,?)',(
                    value['definition_id'],request_id,input_hash,value['playbook_key'],value['version'],
                    value['state'],definition_hash,search,encode(value),digest(value)))
            except sqlite3.IntegrityError as exc:
                raise PlaybookError('VERSION_EXISTS','同一 playbook_key/version 已存在；规则变化必须新建版本。') from exc
            return value

    def create_case(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_playbook_case(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'cases',request_id,input_hash)
            if old is not None: return old
            definition = self._get_in_db(db,'definitions',normalized['definition_id'])
            self._verified_sources(db,normalized['source_ids'])
            value = {**normalized,'case_id':str(uuid4()),'request_id':request_id,'input_hash':input_hash,
                'playbook_key':definition['playbook_key'],'playbook_version':definition['version'],
                'definition_hash':definition['definition_hash'],'created_at':created}
            search = ' '.join((value['playbook_key'],value['trading_day'],value['frame'],value['summary'],value['notes'])).casefold()
            db.execute('INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?)',(
                value['case_id'],request_id,input_hash,value['definition_id'],value['trading_day'],value['frame'],
                value['as_of'],search,encode(value),digest(value)))
            return value

    @staticmethod
    def _same_instant(left, right):
        return _utc(left) == _utc(right)

    def create_candidate_set(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_candidate_set(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'candidate_sets',request_id,input_hash)
            if old is not None: return old
            case = self._get_in_db(db,'cases',normalized['case_id'])
            if case['definition_id'] != normalized['definition_id']:
                raise PlaybookError('CASE_MISMATCH','CandidateSet definition_id 与 PlaybookCase 不一致。')
            if (case['trading_day'],case['frame']) != (normalized['trading_day'],normalized['frame']):
                raise PlaybookError('CASE_MISMATCH','CandidateSet 交易日/Frame 与 PlaybookCase 不一致。')
            if not self._same_instant(case['as_of'],normalized['as_of']):
                raise PlaybookError('CASE_MISMATCH','CandidateSet as_of 必须与 PlaybookCase 冻结时点一致。')
            candidate_hash = digest(normalized['candidates'])
            symbols = [item['symbol'] for item in normalized['candidates']]
            value = {**normalized,'candidate_set_id':str(uuid4()),'request_id':request_id,
                'input_hash':input_hash,'candidate_hash':candidate_hash,'candidate_symbols':symbols,
                'candidate_count':len(symbols),'frozen_at':created}
            search = ' '.join([case['playbook_key'],normalized['trading_day'],normalized['frame'],*symbols]).casefold()
            try:
                db.execute('INSERT INTO candidate_sets VALUES (?,?,?,?,?,?,?,?,?,?,?)',(
                    value['candidate_set_id'],request_id,input_hash,value['case_id'],value['definition_id'],
                    value['completeness'],value['pit_status'],candidate_hash,search,encode(value),digest(value)))
            except sqlite3.IntegrityError as exc:
                raise PlaybookError('CASE_ALREADY_FROZEN','该 PlaybookCase 已冻结 CandidateSet；改变候选全集必须新建 Case。') from exc
            return value

    def create_selection(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_selection(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'selections',request_id,input_hash)
            if old is not None: return old
            candidates = self._get_in_db(db,'candidate_sets',normalized['candidate_set_id'])
            universe = set(candidates['candidate_symbols'])
            referenced = set(normalized['selected_symbols']) | set(normalized['ranked_symbols']) | set(normalized['reasons'])
            if not referenced <= universe:
                raise PlaybookError('OUTSIDE_CANDIDATE_SET','SelectionDecision 只能引用冻结 CandidateSet 内的证券。')
            if normalized['kind']=='SYSTEM_PREDICTION' and not self._same_instant(normalized['as_of'],candidates['as_of']):
                raise PlaybookError('LOOKAHEAD_BLOCKED','SYSTEM_PREDICTION 必须在 CandidateSet 冻结时点作出，不能事后回填。')
            selected = normalized['selected_symbols']
            unselected = [symbol for symbol in candidates['candidate_symbols'] if symbol not in set(selected)]
            value = {**normalized,'selection_id':str(uuid4()),'request_id':request_id,'input_hash':input_hash,
                'case_id':candidates['case_id'],'definition_id':candidates['definition_id'],
                'candidate_hash':candidates['candidate_hash'],'candidate_count':candidates['candidate_count'],
                'selected_count':len(selected),'unselected_symbols':unselected,'created_at':created}
            search = ' '.join([value['kind'],*selected,*unselected,value['notes']]).casefold()
            db.execute('INSERT INTO selections VALUES (?,?,?,?,?,?,?,?)',(
                value['selection_id'],request_id,input_hash,value['candidate_set_id'],value['kind'],
                search,encode(value),digest(value)))
            return value

    @staticmethod
    def _selection_metrics(target, model):
        truth = set(target['selected_symbols']); predicted = set(model['selected_symbols'])
        hits = truth & predicted; union = truth | predicted
        precision = len(hits)/len(predicted) if predicted else (1.0 if not truth else 0.0)
        recall = len(hits)/len(truth) if truth else (1.0 if not predicted else 0.0)
        jaccard = len(hits)/len(union) if union else 1.0
        return {'target_count':len(truth),'predicted_count':len(predicted),'hits':len(hits),
            'precision':precision,'recall':recall,'jaccard':jaccard,'exact_match':truth==predicted}

    @staticmethod
    def _execution_audit(summary, evidence_ids):
        if not summary:
            return {'ready':False,'reason':'missing_execution_summary'}
        required = ('gross_return','net_return','costs','slippage','t_plus_one_checked',
            'price_limit_checked','suspension_checked')
        if any(key not in summary for key in required):
            return {'ready':False,'reason':'missing_execution_fields'}
        numbers = [summary[k] for k in ('gross_return','net_return','costs','slippage')]
        if any(type(value) not in (int,float) or not math.isfinite(value) for value in numbers):
            return {'ready':False,'reason':'invalid_execution_numbers'}
        checks = [summary[k] for k in ('t_plus_one_checked','price_limit_checked','suspension_checked')]
        if any(value is not True for value in checks):
            return {'ready':False,'reason':'a_share_constraints_not_all_checked'}
        if not evidence_ids:
            return {'ready':False,'reason':'missing_execution_evidence'}
        return {'ready':True,'reason':'audited_execution_summary'}

    def _formal_source_ready(self, db, case):
        sources = self._verified_sources(db,case['source_ids'])
        return bool(sources) and all(source['completeness']=='VERIFIED' for source in sources)

    def create_validation(self, request_id, content):
        identifier(request_id,'request_id')
        try:
            normalized = normalize_validation(content)
        except ValueError as exc:
            raise PlaybookError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized); created = now_iso(self.now_fn)
        with self.connection(write=True) as db:
            old = self._existing_request(db,'validations',request_id,input_hash)
            if old is not None: return old
            definition = self._get_in_db(db,'definitions',normalized['definition_id'])
            formal_method = normalized['method'] in ('HOLDOUT','WALK_FORWARD')
            pair_rows = []; candidate_total = target_total = predicted_total = hits_total = 0
            all_full = True; all_strict = True; all_sources = True; exact = 0
            seen_cases = set()
            for pair in normalized['pairs']:
                case = self._get_in_db(db,'cases',pair['case_id'])
                target = self._get_in_db(db,'selections',pair['target_selection_id'])
                model = self._get_in_db(db,'selections',pair['model_selection_id'])
                if case['definition_id'] != definition['definition_id']:
                    raise PlaybookError('DEFINITION_MISMATCH','Validation case 不属于指定 PlaybookDefinition。')
                if target['case_id'] != case['case_id'] or model['case_id'] != case['case_id']:
                    raise PlaybookError('CASE_MISMATCH','Validation selection 与 case 不一致。')
                if target['candidate_set_id'] != model['candidate_set_id']:
                    raise PlaybookError('CANDIDATE_MISMATCH','目标与模型选择必须基于同一个冻结 CandidateSet。')
                if target['kind']=='SYSTEM_PREDICTION' or model['kind']!='SYSTEM_PREDICTION':
                    raise PlaybookError('INVALID_SELECTION_ROLE','target 必须是专家/人工标签，model 必须是 SYSTEM_PREDICTION。')
                if formal_method and (target['kind']!='OBSERVED_EXPERT' or not target['evidence_ids']):
                    raise PlaybookError('TARGET_EVIDENCE_REQUIRED',
                        'HOLDOUT/WALK_FORWARD 的目标选择必须是有证据引用的 OBSERVED_EXPERT，不能用人工推测标签代替。')
                candidates = self._get_in_db(db,'candidate_sets',target['candidate_set_id'])
                metrics = self._selection_metrics(target,model)
                pair_rows.append({**pair,'candidate_set_id':candidates['candidate_set_id'],
                    'candidate_count':candidates['candidate_count'],**metrics})
                candidate_total += candidates['candidate_count']; target_total += metrics['target_count']
                predicted_total += metrics['predicted_count']; hits_total += metrics['hits']
                exact += int(metrics['exact_match']); seen_cases.add(case['case_id'])
                all_full = all_full and candidates['completeness']=='FULL'
                all_strict = all_strict and candidates['pit_status']=='STRICT_PIT'
                all_sources = all_sources and self._formal_source_ready(db,case)
            definition_frozen = definition['state']=='FROZEN'
            strict_selection_ready = definition_frozen and all_full and all_strict and all_sources
            if formal_method and not strict_selection_ready:
                raise PlaybookError('FORMAL_VALIDATION_BLOCKED',
                    'HOLDOUT/WALK_FORWARD 要求 FROZEN 规则、FULL CandidateSet、STRICT_PIT 与 VERIFIED 案例来源。')
            micro_precision = hits_total/predicted_total if predicted_total else (1.0 if not target_total else 0.0)
            micro_recall = hits_total/target_total if target_total else (1.0 if not predicted_total else 0.0)
            execution_audit = self._execution_audit(normalized['execution_summary'],normalized['execution_evidence_ids'])
            complete = strict_selection_ready and execution_audit['ready'] and formal_method
            status = 'AUDIT_COMPLETE' if complete else ('STRICT_SELECTION_ONLY' if strict_selection_ready else 'DESCRIPTIVE')
            metrics = {'cases':len(seen_cases),'pairs':len(pair_rows),'candidate_total':candidate_total,
                'target_total':target_total,'predicted_total':predicted_total,'hits':hits_total,
                'micro_precision':micro_precision,'micro_recall':micro_recall,
                'exact_match_rate':exact/len(pair_rows),'pair_results':pair_rows}
            audit = {'definition_frozen':definition_frozen,'candidate_sets_full':all_full,
                'strict_pit':all_strict,'expert_sources_verified':all_sources,
                'execution':execution_audit,'formal_method':formal_method,'audit_complete':complete}
            value = {**normalized,'validation_id':str(uuid4()),'request_id':request_id,'input_hash':input_hash,
                'playbook_key':definition['playbook_key'],'playbook_version':definition['version'],
                'definition_hash':definition['definition_hash'],'status':status,'metrics':metrics,'audit':audit,
                'alpha_verified':False,'profitability_claim':'not_established','created_at':created}
            search = ' '.join((value['playbook_key'],value['playbook_version'],value['method'],status,value['notes'])).casefold()
            db.execute('INSERT INTO validations VALUES (?,?,?,?,?,?,?,?,?)',(
                value['validation_id'],request_id,input_hash,value['definition_id'],value['method'],status,
                search,encode(value),digest(value)))
            return value

    def _list(self, table, clauses=None, values=None, query='', offset=0, limit=200):
        if not isinstance(query,str) or len(query)>200 or type(offset) is not int or not 0<=offset<=100000:
            raise PlaybookError('INVALID_ARGUMENT','检索参数无效。')
        if type(limit) is not int or not 1<=limit<=2000:
            raise PlaybookError('INVALID_ARGUMENT','limit 必须为 1–2000。')
        empty = {'records':[],'total':0,'offset':offset,'next_offset':None}
        if self.path.is_symlink():
            raise PlaybookError('INVALID_WORKSPACE','Playbook Lab 数据库不能为符号链接。')
        if not self.path.exists(): return empty
        clauses = list(clauses or []); values = list(values or [])
        clauses.insert(0,'instr(search_text,?)>0'); values.insert(0,query.casefold())
        where = ' WHERE '+' AND '.join(clauses)
        with self.connection() as db:
            total = db.execute(f'SELECT COUNT(*) FROM {table}'+where,values).fetchone()[0]
            rows = db.execute(f'SELECT * FROM {table}'+where+' ORDER BY rowid DESC LIMIT ? OFFSET ?',
                [*values,limit,offset])
            records = [self._decode(row,table) for row in rows]
        return {'records':records,'total':total,'offset':offset,
            'next_offset':offset+limit if offset+limit<total else None}

    def list_sources(self, query='', expert_key='', completeness='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('expert_key',expert_key),('completeness',completeness)):
            if value: clauses.append(column+'=?');values.append(value)
        return self._list('sources',clauses,values,query,offset,limit)

    def list_definitions(self, query='', playbook_key='', state='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('playbook_key',playbook_key),('state',state)):
            if value: clauses.append(column+'=?');values.append(value)
        return self._list('definitions',clauses,values,query,offset,limit)

    def list_cases(self, definition_id='', trading_day='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('definition_id',definition_id),('trading_day',trading_day)):
            if value: clauses.append(column+'=?');values.append(value)
        return self._list('cases',clauses,values,'',offset,limit)

    def list_candidate_sets(self, definition_id='', case_id='', symbol='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('definition_id',definition_id),('case_id',case_id)):
            if value: clauses.append(column+'=?');values.append(value)
        result = self._list('candidate_sets',clauses,values,symbol,offset,limit)
        if symbol:
            symbol = symbol.lower()
            filtered = [row for row in result['records'] if symbol in row['candidate_symbols']]
            result.update(records=filtered,total=len(filtered),next_offset=None)
        return result

    def list_selections(self, candidate_set_id='', kind='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('candidate_set_id',candidate_set_id),('kind',kind)):
            if value: clauses.append(column+'=?');values.append(value)
        return self._list('selections',clauses,values,'',offset,limit)

    def list_validations(self, definition_id='', method='', offset=0, limit=200):
        clauses=[];values=[]
        for column,value in (('definition_id',definition_id),('method',method)):
            if value: clauses.append(column+'=?');values.append(value)
        return self._list('validations',clauses,values,'',offset,limit)

    def case_bundle(self, case_id):
        case = self.get_case(case_id)
        candidates = self.list_candidate_sets(case_id=case_id,limit=10)['records']
        candidate = candidates[0] if candidates else None
        selections = self.list_selections(candidate_set_id=candidate['candidate_set_id'],limit=200)['records'] if candidate else []
        definition = self.get_definition(case['definition_id'])
        sources = [self.get_source(source_id) for source_id in case['source_ids']]
        return {'case':case,'definition':definition,'sources':sources,'candidate_set':candidate,
            'selections':selections}

    def symbol_history(self, symbol, limit=500):
        from .decision import SYMBOL
        if not isinstance(symbol,str) or not SYMBOL.fullmatch(symbol.lower()):
            raise PlaybookError('INVALID_ARGUMENT','symbol 必须是 sh/sz/bj.XXXXXX。')
        symbol = symbol.lower()
        candidates = self.list_candidate_sets(symbol=symbol,limit=limit)['records']
        rows = []
        for candidate in candidates:
            case = self.get_case(candidate['case_id']); definition = self.get_definition(candidate['definition_id'])
            selections = self.list_selections(candidate_set_id=candidate['candidate_set_id'],limit=200)['records']
            rows.append({'playbook_key':definition['playbook_key'],'playbook_name':definition['name'],
                'version':definition['version'],'case_id':case['case_id'],'trading_day':case['trading_day'],
                'frame':case['frame'],'candidate_set_id':candidate['candidate_set_id'],
                'completeness':candidate['completeness'],'pit_status':candidate['pit_status'],
                'selected_by':[row['kind'] for row in selections if symbol in row['selected_symbols']],
                'unselected_by':[row['kind'] for row in selections if symbol in row['unselected_symbols']]})
        return rows

    def overview(self):
        if self.path.is_symlink():
            raise PlaybookError('INVALID_WORKSPACE','Playbook Lab 数据库不能为符号链接。')
        if not self.path.exists():
            return {'sources':0,'definitions':0,'frozen_definitions':0,'cases':0,'candidate_sets':0,
                'full_candidate_sets':0,'selections':0,'validations':0,'audit_complete_validations':0}
        with self.connection() as db:
            count=lambda table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            return {'sources':count('sources'),'definitions':count('definitions'),
                'frozen_definitions':db.execute("SELECT COUNT(*) FROM definitions WHERE state='FROZEN'").fetchone()[0],
                'cases':count('cases'),'candidate_sets':count('candidate_sets'),
                'full_candidate_sets':db.execute("SELECT COUNT(*) FROM candidate_sets WHERE completeness='FULL'").fetchone()[0],
                'selections':count('selections'),'validations':count('validations'),
                'audit_complete_validations':db.execute("SELECT COUNT(*) FROM validations WHERE status='AUDIT_COMPLETE'").fetchone()[0]}


__all__ = ['PlaybookError','PlaybookStore','identifier']
