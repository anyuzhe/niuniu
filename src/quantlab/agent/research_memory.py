"""Structured hypotheses and evidence-backed draft findings; no research execution."""
from dataclasses import asdict
import math
from quantlab.agent.memory_store import MemoryStore, MemoryError, identifier
from quantlab.agent.memory_evidence import EvidenceResolver
from quantlab.agent.model_config import strict_json
from quantlab.app import default_registry
from quantlab.storage.codec import digest, encode

HYPOTHESIS_FIELDS = {'title','statement','factor_id','factor_version','parameters','mechanism','falsification','supersedes'}
FINDING_FIELDS = {'hypothesis_id','title','statement','assessment','limitations','next_action','evidence','supersedes'}
ASSESSMENTS = {'supported','contradicted','inconclusive','unavailable','implementation_failure'}


def payload(text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>65536:
        raise MemoryError('INVALID_ARGUMENT', '记录须为不超过64 KiB的 JSON 对象。')
    try:
        value = strict_json(text)
    except (ValueError,RuntimeError,RecursionError):
        raise MemoryError('INVALID_ARGUMENT', '记录 JSON 无效、字段重复或含非有限数。') from None
    if not isinstance(value,dict):
        raise MemoryError('INVALID_ARGUMENT', '记录须为 JSON 对象。')
    return value


def text_field(value, name, maximum=4000):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:
        raise MemoryError('INVALID_ARGUMENT', name+'须为非空且不超长的文本。')


class ResearchMemory:
    def __init__(self, output, *, origin='model_draft'):
        if origin not in ('model_draft','human_note'):
            raise ValueError('Invalid memory origin')
        self.store = MemoryStore(output)
        self.resolver = EvidenceResolver(output)
        self.registry = default_registry()
        self.origin = origin

    def save(self, kind, request_id, value):
        identifier(request_id)
        fields = HYPOTHESIS_FIELDS if kind=='hypothesis' else FINDING_FIELDS if kind=='finding' else None
        if fields is None or not isinstance(value,dict) or set(value)!=fields:
            raise MemoryError('INVALID_ARGUMENT', '研究记录字段必须与类型合同完全一致。')
        text_field(value['title'],'标题',200); text_field(value['statement'],'研究陈述')
        if value['supersedes'] is not None: identifier(value['supersedes'])
        input_hash = digest({'kind':kind,'value':value,'origin':self.origin})
        old = self.store.request(request_id,input_hash)
        if old is not None: return self.get(old['memory_id'])
        if kind=='hypothesis':
            text_field(value['mechanism'],'机制假设'); text_field(value['falsification'],'可证伪条件')
            text_field(value['factor_id'],'因子编号',200); text_field(value['factor_version'],'因子版本',200)
            if not isinstance(value['parameters'],dict):
                raise MemoryError('INVALID_ARGUMENT','因子参数须为对象。')
            try:
                factor = self.registry.get(value['factor_id'],value['factor_version'])
                parameters = factor.parameters(value['parameters'])
            except (ValueError,KeyError,TypeError) as error:
                raise MemoryError('INVALID_FACTOR','因子或参数未通过原注册表校验：'+str(error)[:200]) from None
            candidate = {'factor_id':value['factor_id'], 'factor_version':value['factor_version'], 'parameters':parameters}
            content = {**value, **candidate, 'candidate_id':digest(candidate), 'hypothesis_id':None,
                       'definition_hash':digest(asdict(factor.definition)),
                       'factor_code_hash':self.registry.code_hash(factor), 'status':'hypothesis', 'evidence':[]}
        else:
            hypothesis = self.store.get(identifier(value['hypothesis_id']))
            if hypothesis['kind']!='hypothesis':
                raise MemoryError('INVALID_PARENT','hypothesis_id 必须指向研究假设。')
            if value['assessment'] not in ASSESSMENTS:
                raise MemoryError('INVALID_ARGUMENT','未知结论分类。')
            text_field(value['limitations'],'适用范围与局限'); text_field(value['next_action'],'下一步')
            refs = value['evidence']
            if not isinstance(refs,list) or not 1<=len(refs)<=8:
                raise MemoryError('INVALID_ARGUMENT','结论需要1–8条真实归档字段引用。')
            evidence = []; seen = set()
            for ref in refs:
                if not isinstance(ref,dict) or set(ref)!={'run_id','pointer','relation'}:
                    raise MemoryError('INVALID_ARGUMENT','引用只接受 run_id、pointer、relation；不得自行填数值。')
                if ref['relation'] not in ('supports','contradicts','context'):
                    raise MemoryError('INVALID_ARGUMENT','证据关系须为支持、反对或背景。')
                key = (identifier(ref['run_id']),ref['pointer'])
                if not isinstance(key[1],str) or key in seen:
                    raise MemoryError('INVALID_ARGUMENT','证据字段无效或重复。')
                seen.add(key)
                evidence.append({**self.resolver.capture(*key),'relation':ref['relation']})
            if value['assessment'] in ('supported','contradicted'):
                usable = [e for e in evidence if e['context']['status']=='completed' and type(e['value']) in (int,float) and math.isfinite(e['value'])]
                if not usable:
                    raise MemoryError('INSUFFICIENT_EVIDENCE','支持/反对草稿至少需一个成功研究的有效数值；空值或失败状态不能代替统计。')
            if value['assessment']=='implementation_failure' and not any(e['context']['status']=='failed' for e in evidence):
                raise MemoryError('INSUFFICIENT_EVIDENCE','实现失败分类需要失败研究归档。')
            inherited = {k:hypothesis[k] for k in ('factor_id','factor_version','parameters','candidate_id','definition_hash','factor_code_hash')}
            content = {**value, **inherited, 'status':value['assessment'], 'evidence':evidence}
        content.update(kind=kind, origin=self.origin, review_state='draft', claim_verified=False)
        if len(encode(content).encode('utf-8'))>131072:
            raise MemoryError('RESULT_TOO_LARGE','研究记录与证据超过128 KiB。')
        record = self.store.create(request_id,input_hash,content)
        return self.get(record['memory_id'])

    def get(self, memory_id):
        record = self.store.get(memory_id)
        checks = [self.resolver.verify(e) for e in record['evidence']]
        state = ('no_evidence' if not checks else 'verified' if all(c['status']=='verified' for c in checks)
                 else 'source_changed' if any(c['status']=='source_changed' for c in checks) else 'unavailable')
        try:
            factor = self.registry.get(record['factor_id'],record['factor_version'])
            definition_current = (digest(asdict(factor.definition))==record['definition_hash'] and
                                  self.registry.code_hash(factor)==record['factor_code_hash'])
        except (ValueError,KeyError,TypeError): definition_current = False
        return {'record':record, 'source_integrity':state, 'evidence_checks':checks,
                'factor_definition_current':definition_current, 'claim_verified':False,
                'warning':'校验只证明引用与归档一致，不证明文字解释、统计假设或未来盈利；分类均为待复核草稿。'}
