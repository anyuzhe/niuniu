"""Exact deduplication of completed causal event chains, not endpoint signals."""
import json
from datetime import datetime,timezone
from itertools import combinations
from quantlab.storage.codec import digest,encode


def _time(value):
    result=datetime.fromisoformat(value)
    if result.tzinfo is None:raise ValueError('Sequence overlap requires aware information times')
    return result.astimezone(timezone.utc).isoformat()


def completed_chains(audit):
    """Keep the event order, causal times, versions and metadata in identity.

    Different sequence definitions can realize the same chain. Reporting that
    observed duplication does not establish equivalence of their rules.
    """
    audit=json.loads(encode(audit));result={}
    for sequence in audit.get('sequences',[]):
        alias=sequence['alias']
        if alias in result:raise ValueError('Duplicate sequence alias')
        events={}
        for event in sequence['events']:
            identity={k:v for k,v in event.items() if k!='event_id'}
            for key in ('occurred_at','available_at','confirmed_at'):
                if identity.get(key) is not None:identity[key]=_time(identity[key])
            fingerprint=digest(identity)
            if event['event_id'] in events and events[event['event_id']][0]!=fingerprint:
                raise ValueError('Conflicting event identities')
            events[event['event_id']]=(fingerprint,event)
        groups={};count=0
        for match in sequence['transitions']:
            # A component trace may contain its whole parent state machine.
            if match['sequence_id']!=sequence['factor']['factor_id']:continue
            if match['status']!='completed' or match.get('completion_selected') is not True:continue
            ids=match['event_ids']
            if not ids or len(ids)!=len(set(ids)):raise ValueError('Completed sequence requires distinct ordered events')
            if any(key not in events for key in ids):raise ValueError('Completed sequence references missing events')
            times=[_time(events[key][1]['available_at']) for key in ids]
            if times!=sorted(times) or times[-1]>_time(match['available_at']):raise ValueError('Noncausal completed event chain')
            if any(events[key][1]['symbol']!=match['symbol'] for key in ids):raise ValueError('Sequence events cross symbols')
            signature=digest({'symbol':match['symbol'],'timeframe':match['timeframe'],
                'available_at':_time(match['available_at']),'events':[events[key][0] for key in ids]})
            groups.setdefault(signature,set()).add(match['match_id']);count+=1
        result[alias]={'signatures':set(groups),'completed_records':count,
            'unique_chains':len(groups),'duplicate_records':count-len(groups),
            'groups':[{'chain_hash':key,'representative_match':sorted(ids)[0],'match_ids':sorted(ids)} for key,ids in sorted(groups.items())]}
    return result


def sequence_overlap(audit):
    chains=completed_chains(audit);pairs=[]
    for left,right in combinations(sorted(chains),2):
        a=chains[left]['signatures'];b=chains[right]['signatures'];common=a&b;union=a|b
        pairs.append({'left':left,'right':right,'left_unique_chains':len(a),'right_unique_chains':len(b),
            'intersection':len(common),'union':len(union),'jaccard':len(common)/len(union) if union else None,
            'shared_chain_hashes':sorted(common)})
    return {'method':'exact_ordered_causal_event_chain_v1',
        'scope':'Selected completed chains only. Exact ordered event content, versions, metadata and information times; no automatic removal, no claim of rule equivalence. Unsupported factors are omitted, not counted as zero.',
        'aliases':{key:{k:v for k,v in value.items() if k!='signatures'} for key,value in chains.items()},'pairs':pairs}
