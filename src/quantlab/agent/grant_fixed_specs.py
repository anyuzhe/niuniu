"""Host-frozen specifications narrow an existing research grant; no new authority.

A reference resolves only against the active grant's hash-bound inline catalog,
not paths, global files, model text, or a mutable secondary database.
"""
import re
from dataclasses import asdict
from quantlab.agent.planning import ProposalError, parse_spec
from quantlab.storage.codec import digest, encode


def prepared_digest(spec):
    from quantlab.workbench.jobs import prepare
    return digest(asdict(prepare(spec)))


def normalize_fixed_specs(specs, scope):
    from quantlab.agent.research_session_grant import _validate_spec
    if not isinstance(specs, dict) or not 1 <= len(specs) <= 20:
        raise ValueError('Fixed grant requires 1–20 named specifications')
    if len(encode(specs).encode('utf-8')) > 262144:
        raise ValueError('Fixed specification catalog exceeds 256 KiB')
    result = {}; seen = set()
    for name, value in specs.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
            raise ValueError('Fixed specification name must be a bounded identifier, not a path')
        spec = parse_spec(encode(value))
        _validate_spec({'scope':scope}, spec)
        identity = prepared_digest(spec)
        if identity in seen:
            raise ValueError('Duplicate normalized fixed specifications')
        seen.add(identity); result[name] = spec
    return dict(sorted(result.items()))


def resolve_fixed_spec(plan, supplied):
    """Return the original host-frozen bytes' JSON value and normalized identity.

    Direct JSON is still supported, but in a fixed grant it must match a frozen
    specification including the question, symbols, parameters and every option.
    """
    supplied = parse_spec(encode(supplied))
    fixed = plan.get('fixed_specs')
    if fixed is None:
        if 'grant_spec' in supplied:
            raise ProposalError('GRANT_FIXED_SPEC', '当前授权没有固定配置目录，不能使用grant_spec引用')
        return supplied, None
    if not isinstance(fixed, dict) or not fixed:
        raise ProposalError('GRANT_FIXED_SPEC', '固定配置目录为空或无效')
    if 'grant_spec' in supplied:
        name = supplied['grant_spec']
        if set(supplied) != {'grant_spec'} or not isinstance(name, str) or name not in fixed:
            raise ProposalError('GRANT_FIXED_SPEC', '只能引用当前授权的精确grant_spec编号，不接受覆盖字段或路径')
        value = parse_spec(encode(fixed[name]))
        return value, prepared_digest(value)
    identity = prepared_digest(supplied)
    for spec in fixed.values():
        if prepared_digest(spec) == identity:
            return parse_spec(encode(spec)), identity
    raise ProposalError('GRANT_FIXED_SPEC', '配置与宿主冻结方案不一致（包括证券、参数、日期和问题），未创建任务；请使用grant_spec引用')


def fixed_spec_summary(plan, jobs):
    """Bounded discovery for the model; never return a second editable spec."""
    result = []
    for name, spec in plan.get('fixed_specs', {}).items():
        result.append({'grant_spec':name, 'question':spec.get('question','')[:200],
            'factor':spec.get('factor'), 'version':spec.get('version','1.0.0'),
            'symbols_count':len(spec.get('symbols',[])), 'prepared_digest':prepared_digest(spec),
            'existing_job_ids':[j['job_id'] for j in jobs if j.get('spec_digest') == digest(spec)]})
    return result
