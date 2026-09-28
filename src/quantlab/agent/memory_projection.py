"""Explicitly partial, text-preserving views of large verified research notes.

No store writes and no authority upgrade. Repeated evidence context is omitted,
not represented as a complete source. Exact fields stay available via pointers.
"""
from copy import deepcopy
from quantlab.storage.codec import digest, encode


def large_memory_view(data):
    view=deepcopy(data)
    record=view.get('record')
    if not isinstance(record,dict):return None
    omitted=[]
    for index,ref in enumerate(record.get('evidence',[])):
        if 'context' in ref:
            context=ref.pop('context')
            omitted.append({'pointer':f'/record/evidence/{index}/context','sha256':digest(context)})
        if 'value' in ref and len(encode(ref['value']))>512:
            value=ref.pop('value');ref['value_omitted']=True
            omitted.append({'pointer':f'/record/evidence/{index}/value','sha256':digest(value)})
    if 'parameters' in record and len(encode(record['parameters']))>2048:
        parameters=record.pop('parameters')
        omitted.append({'pointer':'/record/parameters','sha256':digest(parameters)})
    view['projection']={'format':'research-memory-text-view-v1','complete_record':False,
        'text_fields_complete':True,'record_digest':digest(data['record']),'omitted_fields':omitted,
        'policy':'Only a bounded presentation: text is unchanged; evidence contexts/large values or parameters are omitted explicitly. '
                 'Re-read hypothesis parameters or inspect_research_evidence for exact fields. '
                 'Source integrity is not claim verification or Alpha.'}
    return view
