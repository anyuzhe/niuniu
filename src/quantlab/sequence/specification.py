"""Bounded sequence grammar: nested groups expand to ordered event steps.

Groups may add a total timeout and scoped invalidators to enclosing constraints. Optional steps
are greedy: a matching optional step is consumed before considering a skip.
First and last steps remain required, giving every match a definite boundary.
"""

def normalize_steps(steps, sources):
    flat=[];optional=[]
    def visit(items, inherited=False, depth=0):
        if depth>4 or not isinstance(items,list):raise ValueError('Sequence groups require lists, at most four levels')
        for item in items:
            if isinstance(item,str):source=item;skip=inherited
            elif isinstance(item,dict):
                if set(item)-{'event','steps','optional','timeout_seconds','invalidators'} or ('event' in item)==('steps' in item):raise ValueError('Step requires event or steps')
                if 'event' in item and ('timeout_seconds' in item or 'invalidators' in item):raise ValueError('Independent timeout/invalidators belong to nested groups')
                if 'timeout_seconds' in item and (type(item['timeout_seconds']) is not int or not 0<item['timeout_seconds']<=31536000):raise ValueError('Group timeout must be 1–31536000 seconds')
                if 'invalidators' in item and (not isinstance(item['invalidators'],list) or any(v not in sources for v in item['invalidators'])):raise ValueError('Invalid group invalidators')
                if item.get('invalidators') and 'timeout_seconds' not in item:raise ValueError('Group invalidators require an explicit group timeout')
                if type(item.get('optional',False)) is not bool:raise ValueError('optional must be boolean')
                skip=inherited or item.get('optional',False)
                if 'steps' in item:
                    if not item['steps']:raise ValueError('Empty sequence group')
                    visit(item['steps'],skip,depth+1);continue
                source=item['event']
            else:raise ValueError('Invalid sequence step')
            if not isinstance(source,str) or source not in sources:raise ValueError('Unsupported event selector')
            if skip:optional.append(len(flat))
            flat.append(source)
            if len(flat)>12:raise ValueError('Sequence requires 2–12 expanded steps')
    visit(steps)
    if len(flat)<2 or 0 in optional or len(flat)-1 in optional:raise ValueError('Sequence requires two mandatory boundary steps')
    return flat,tuple(optional)


def sequence_scopes(steps):
    from datetime import timedelta
    from quantlab.sequence.engine import SequenceScope, EventSelector
    scopes=[];position=0
    def visit(items):
        nonlocal position
        for item in items:
            if isinstance(item,dict) and 'steps' in item:
                start=position;visit(item['steps'])
                if 'timeout_seconds' in item:
                    scopes.append(SequenceScope(start,position-1,timedelta(seconds=item['timeout_seconds']),tuple(EventSelector(v) for v in item.get('invalidators',[]))))
            else:position+=1
    visit(steps)
    return tuple(scopes)
