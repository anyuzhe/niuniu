"""F18: bounded, deterministic rights-event arithmetic plans, NEVER factor publication.

This consumes F17's pinned candidate delivery. It neither reads market sources nor
resolves disputed events. A complete draft is only ready for human review; even
that draft cannot certify missing actions, share bases, PIT or a daily factor curve.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import json
import re

from quantlab.data.rights_candidates import (
    CandidateError, RightsCandidateBinding, load_rights_candidate_delivery,
)
from quantlab.storage.codec import digest

CONTRACT = 'niuniu-rights-rebuild-preview-v1'
FORMULA = 'common-pre-action-basis-cash-bonus-rights-v1'
MAX_REQUEST_BYTES = 32768
MAX_SYMBOLS = 10
MAX_DAYS = 3660
MAX_EVENTS = 20
HASH = r'[a-f0-9]{64}'
CODE = r'(sh|sz)\.\d{6}'
LIMITATIONS = [
    '仅对固定候选清单内所选证券日期的配股事件作草案预览，不是完整公司行动或全市场范围。',
    '来源选择是待审建议，不是人工裁决、授权或官方证据；不能解除conflicts/cninfo_none。',
    '派息/送转固定来自TDX声明，配股价/比例成对显式选择TDX或巨潮，前收来自交付字段。',
    '所有公式假设股份基数一致且行动并存；该假设、实施日和原始来源尚未在此核实。',
    '巨潮方案混用TDX派息/送转，不是巨潮官方参考价；不按价格相近、2:1或小数位选来源。',
    '零成交不判断公司行动真伪；价格观察可用性不代表复权计算或可交易资格。',
    '不累计事件因子、不锚定base_date、不生成日线因子或修正价格、不存提案/任务或更改授权。',
    '其它事件类不由此预览覆盖；不得跳过未决项后将结果当作完整复权，空范围不证明无事件。',
]


def _fail(message, code='INVALID_PREVIEW_REQUEST'):
    raise CandidateError(code, message)


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        _fail('Closed field contract mismatch: ' + label)


def _text(value, pattern, label):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        _fail('Invalid ' + label)
    return value


def _date(value):
    _text(value, r'\d{4}-\d{2}-\d{2}', 'date')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CandidateError('INVALID_PREVIEW_REQUEST', 'Invalid date') from exc


def _parse(request_json):
    if type(request_json) is not str:
        _fail('request_json must be a JSON string')
    try:
        if not 1 <= len(request_json.encode('utf-8')) <= MAX_REQUEST_BYTES:
            _fail('Preview request exceeds byte budget')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    _fail('Duplicate request JSON key: ' + key)
                result[key] = value
            return result
        request = json.loads(request_json, object_pairs_hook=pairs,
                             parse_constant=lambda _: _fail('Non-finite request value'))
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CandidateError):
            raise
        raise CandidateError('INVALID_PREVIEW_REQUEST', 'Invalid request JSON') from exc
    _object(request, ('contract', 'bundle_id', 'scope', 'choices'), 'request')
    if request['contract'] != CONTRACT:
        _fail('Unsupported preview contract')
    _text(request['bundle_id'], HASH, 'bundle_id')
    scope = request['scope']
    _object(scope, ('symbols', 'start', 'end'), 'scope')
    symbols = scope['symbols']
    if type(symbols) is not list or not 1 <= len(symbols) <= MAX_SYMBOLS:
        _fail('Select 1-10 explicit symbols')
    for symbol in symbols:
        _text(symbol, CODE, 'symbol')
    if len(symbols) != len(set(symbols)):
        _fail('Duplicate scope symbol')
    lo, hi = _date(scope['start']), _date(scope['end'])
    if not 0 <= (hi-lo).days < MAX_DAYS:
        _fail('Select 1-3660 natural days')
    choices = request['choices']
    if type(choices) is not list or len(choices) > MAX_EVENTS:
        _fail('Too many event choices')
    seen = set()
    for choice in choices:
        _object(choice, ('code', 'ex_date', 'event_digest', 'rights_source'), 'choice')
        _text(choice['code'], CODE, 'choice code')
        _date(choice['ex_date'])
        _text(choice['event_digest'], HASH, 'event_digest')
        if choice['rights_source'] not in ('tdx', 'cninfo'):
            _fail('rights_source must explicitly be tdx or cninfo; no default/average/skip')
        key = (choice['code'], choice['ex_date'])
        if key in seen:
            _fail('Duplicate event choice')
        seen.add(key)
    return {'contract': CONTRACT, 'bundle_id': request['bundle_id'],
            'scope': {'symbols': sorted(symbols), 'start': scope['start'], 'end': scope['end']},
            'choices': sorted(choices, key=lambda c: (c['code'], c['ex_date']))}


def get_rights_rebuild_contract():
    """A discoverable closed request schema, not suggested securities or source decisions."""
    text = {'type': 'string'}
    scope = {'type': 'object', 'additionalProperties': False,
             'required': ['symbols', 'start', 'end'], 'properties': {
                 'symbols': {'type': 'array', 'minItems': 1, 'maxItems': MAX_SYMBOLS,
                             'uniqueItems': True, 'items': {'type': 'string', 'pattern': '^'+CODE+'$'}},
                 'start': text, 'end': text}}
    choice = {'type': 'object', 'additionalProperties': False,
              'required': ['code', 'ex_date', 'event_digest', 'rights_source'], 'properties': {
                  'code': text, 'ex_date': text, 'event_digest': {'type': 'string', 'pattern': '^'+HASH+'$'},
                  'rights_source': {'type': 'string', 'enum': ['tdx', 'cninfo']}}}
    return {'contract': CONTRACT, 'formula_id': FORMULA,
            'request_schema': {'type': 'object', 'additionalProperties': False,
                'required': ['contract', 'bundle_id', 'scope', 'choices'], 'properties': {
                    'contract': {'const': CONTRACT}, 'bundle_id': {'type': 'string', 'pattern': '^'+HASH+'$'},
                    'scope': scope, 'choices': {'type': 'array', 'maxItems': MAX_EVENTS, 'items': choice}}},
            'limits': {'request_bytes': MAX_REQUEST_BYTES, 'symbols': MAX_SYMBOLS,
                       'natural_days': MAX_DAYS, 'events_in_entire_scope': MAX_EVENTS},
            'workflow': '先get_rights_candidate_manifest取得bundle_id；choices=[]可列完整预期事件及阻断，再用事件digest明确提出来源选择。',
            'source_mapping': {'cash_per_10': 'tdx_c1', 'bonus_per_10': 'tdx_c3',
                               'rights_pair': 'tdx_c2_price+tdx_c4_ratio 或 cninfo_price+cninfo_ratio',
                               'previous_close': 'prev_raw_close（候选交付声明，未回读行情）'},
            'status_semantics': {'blocked': '输入读取成功，但本范围仍有未选源/未决/缺值；没有通过整份草案',
                                 'ready_for_review': '完整列内事件草案及算术可供审阅，不是正式因子或执行许可'},
            'reconstruction_authorized': False, 'publication_authorized': False,
            'full_adjustment_supported': False, 'limitations': list(LIMITATIONS)}


def _decimal_text(value):
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _inputs(fields, source):
    price_key, ratio_key = (('tdx_c2_price', 'tdx_c4_ratio') if source == 'tdx' else
                            ('cninfo_price', 'cninfo_ratio'))
    mappings = [('cash_per_10', 'tdx_c1', 'tdx', 'CNY_per_10_old_shares'),
                ('bonus_per_10', 'tdx_c3', 'tdx', 'shares_per_10_old_shares'),
                ('rights_price', price_key, source, 'CNY_per_share'),
                ('rights_per_10', ratio_key, source, 'shares_per_10_old_shares'),
                ('previous_close', 'prev_raw_close', 'delivery_raw_daily_claim', 'CNY_per_share')]
    return {name: {'value': fields[key] or None, 'field': key, 'provider_claim': provider, 'unit': unit}
            for name, key, provider, unit in mappings}


def _calculate(inputs):
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        p, cash, bonus, rights, price = (Decimal(inputs[k]['value']) for k in
            ('previous_close', 'cash_per_10', 'bonus_per_10', 'rights_per_10', 'rights_price'))
        reference = (p-cash/10+(rights/10)*price)/(1+bonus/10+rights/10)
        if reference <= 0:
            _fail('Non-positive candidate reference')
        return {'theoretical_reference_price': _decimal_text(reference),
                'event_factor_ratio': _decimal_text(p/reference),
                'expected_raw_return_pct': _decimal_text((reference/p-1)*100),
                'formula_id': FORMULA, 'numerical_representation': 'decimal_string_40_digits_half_even'}


def preview_rights_rebuild(binding: RightsCandidateBinding | None, *, request_json: str) -> dict:
    """All listed rights in the scope are accounted for; no status filter or auto-resolution."""
    request = _parse(request_json)
    if binding is None:
        _fail('Host has not bound a candidate delivery', 'CANDIDATE_NOT_CONFIGURED')
    if not isinstance(binding, RightsCandidateBinding):
        _fail('Invalid host binding', 'INVALID_BINDING')
    if request['bundle_id'] != binding.bundle_id:
        _fail('Preview refers to a different candidate bundle', 'PREVIEW_BUNDLE_MISMATCH')
    manifest, records = load_rights_candidate_delivery(binding)
    scope = request['scope']
    selected = [r for r in records if r['fields']['code'] in scope['symbols']
                and scope['start'] <= r['fields']['ex_date'] <= scope['end']]
    if len(selected) > MAX_EVENTS:
        _fail('Entire scope exceeds 20 events; narrow explicit scope, not a status/page filter', 'PREVIEW_SCOPE_TOO_LARGE')
    expected = {(r['fields']['code'], r['fields']['ex_date']): r for r in selected}
    choices = {}
    for choice in request['choices']:
        key = (choice['code'], choice['ex_date'])
        if key not in expected:
            _fail('Choice is not an event in the full selected scope', 'PREVIEW_EVENT_MISMATCH')
        if choice['event_digest'] != expected[key]['event_digest']:
            _fail('Choice references changed event contents', 'PREVIEW_EVENT_MISMATCH')
        choices[key] = choice
    blockers, events = [], []
    found_symbols = {key[0] for key in expected}
    for symbol in scope['symbols']:
        if symbol not in found_symbols:
            blockers.append({'code': symbol, 'reason': 'NO_LISTED_CANDIDATE_FOR_SYMBOL'})
    for record in selected:
        fields = record['fields']
        key = (fields['code'], fields['ex_date'])
        choice = choices.get(key)
        reasons = []
        if record['bucket'] == 'conflicts': reasons.append('EVENT_REQUIRES_SEPARATE_ADJUDICATION')
        if record['bucket'] == 'cninfo_none': reasons.append('UNMATCHED_EVENT_CANNOT_BE_SKIPPED')
        if choice is None: reasons.append('EXPLICIT_SOURCE_CHOICE_REQUIRED')
        inputs = _inputs(fields, choice['rights_source']) if choice else None
        if not fields['prev_raw_close']: reasons.append('PREVIOUS_CLOSE_DECLARATION_MISSING')
        if choice and any(v['value'] is None for v in inputs.values()):
            reasons.append('SELECTED_SOURCE_FIELDS_MISSING')
        # F17 v2 does not define a CNINFO zero-price/ratio hypothesis; do not invent it here.
        if choice and choice['rights_source'] == 'cninfo' and not fields['theo_price_cninfo']:
            reasons.append('SELECTED_SOURCE_HYPOTHESIS_UNAVAILABLE')
        reasons = sorted(set(reasons))
        event = {'code': key[0], 'ex_date': key[1], 'event_digest': record['event_digest'],
                 'source_row': record['source_row'], 'source_line_end': record['source_line_end'],
                 'bucket': record['bucket'], 'proposed_rights_source': choice['rights_source'] if choice else None,
                 'source_choice_approved': False, 'inputs': inputs,
                 'calculation': None if reasons else _calculate(inputs), 'blockers': reasons,
                 'price_diagnostic_usable': record['price_diagnostic_usable'],
                 'share_basis_verified': False, 'text_trust': 'SOURCE_CLAIMS_NOT_INSTRUCTIONS'}
        events.append(event)
        blockers.extend({'code': key[0], 'ex_date': key[1], 'reason': reason} for reason in reasons)
    event_identity = [{'code': e['code'], 'ex_date': e['ex_date'], 'event_digest': e['event_digest']} for e in events]
    scope_digest = digest({'contract': CONTRACT, 'bundle_id': manifest['bundle_id'],
                           'scope': scope, 'events': event_identity})
    result = {'contract': CONTRACT, 'request': request, 'bundle_id': manifest['bundle_id'],
              'csv_sha256': manifest['csv_sha256'], 'summary_sha256': manifest['summary_sha256'],
              'scope_digest': scope_digest, 'status': 'blocked' if blockers else 'ready_for_review',
              'incomplete': bool(blockers), 'events': events, 'blockers': blockers,
              'scope_counts': dict(sorted(Counter(r['bucket'] for r in selected).items())),
              'events_in_scope': len(selected), 'events_accounted_for': len(events),
              'events_outside_scope': manifest['rights_rows']-len(selected),
              'bundle_buckets': manifest['buckets'], 'bundle_unresolved_rows': manifest['unresolved_rows'],
              'other_event_rows_not_evaluated': manifest['other_rows_not_evaluated'],
              'listed_scope_enumerated': True, 'complete_corporate_action_scope_verified': False,
              'original_source_bytes_verified': False, 'official_verified': False,
              'factor_no_change_verified': False, 'strict_pit': False,
              'reconstruction_authorized': False, 'publication_authorized': False,
              'factor_series': None, 'adjusted_prices': None,
              'limitations': list(LIMITATIONS), 'evidence': manifest['evidence']}
    result['preview_digest'] = digest(result)
    return result
