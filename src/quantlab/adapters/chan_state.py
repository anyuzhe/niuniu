"""Data-only graph checkpoints for the pinned Chan core (no executable pickle)."""
import importlib
from datetime import datetime
from enum import Enum


def _class(name):
    module,attribute=name.rsplit('.',1)
    if not (module.startswith('quantlab._vendor.chanpy.') or name in ('quantlab.adapters.chan_classic.ClassicChanState','quantlab.domain.Event','quantlab.domain.Timeframe')):
        raise ValueError('Unsupported Chan state class')
    value=getattr(importlib.import_module(module),attribute)
    if not isinstance(value,type):raise ValueError('Chan state contains a callable instead of a class')
    return value


def dump_state(root):
    nodes=[];pending=[];seen={}
    def value(v):
        if isinstance(v,Enum):return {'enum':[type(v).__module__+'.'+type(v).__qualname__,v.name]}
        if v is None or type(v) in (str,int,bool):return {'value':v}
        if type(v) is float:return {'float':v.hex()}
        if isinstance(v,datetime):return {'datetime':[v.isoformat(),getattr(v.tzinfo,'key',None),v.fold]}
        if id(v) not in seen:
            seen[id(v)]=len(nodes);nodes.append(None);pending.append(v)
        return {'ref':seen[id(v)]}
    head=value(root);index=0
    while index<len(pending):
        v=pending[index]
        if type(v) in (list,tuple,set):node={'kind':type(v).__name__,'items':[value(x) for x in v]}
        elif type(v) is dict:node={'kind':'dict','items':[[value(k),value(x)] for k,x in v.items()]}
        else:
            name=type(v).__module__+'.'+type(v).__qualname__;_class(name)
            # typing's runtime annotation is unused by the pinned algorithms.
            node={'kind':'object','class':name,'fields':{k:value(x) for k,x in vars(v).items() if k!='__orig_class__'}}
        nodes[index]=node;index+=1
    return {'version':1,'root':head,'nodes':nodes}


def load_state(payload):
    if payload.get('version')!=1:raise ValueError('Unsupported Chan state version')
    nodes=payload['nodes'];objects=[]
    for node in nodes:
        kind=node['kind']
        if kind=='object':objects.append(object.__new__(_class(node['class'])))
        elif kind=='list':objects.append([])
        elif kind=='dict':objects.append({})
        elif kind=='set':objects.append(set())
        elif kind=='tuple':objects.append(None)
        else:raise ValueError('Invalid Chan state node')
    resolving=set()
    def value(v):
        if len(v)!=1:raise ValueError('Invalid Chan state value')
        key=next(iter(v))
        if key=='value':
            if v[key] is not None and type(v[key]) not in (str,int,bool):raise ValueError('Invalid primitive')
            return v[key]
        if key=='float':return float.fromhex(v[key])
        if key=='datetime':
            from zoneinfo import ZoneInfo
            stamp,zone,fold=v[key];result=datetime.fromisoformat(stamp)
            return result.astimezone(ZoneInfo(zone)).replace(fold=fold) if zone else result.replace(fold=fold)
        if key=='enum':
            cls=_class(v[key][0])
            if not issubclass(cls,Enum):raise ValueError('Invalid enum')
            return cls[v[key][1]]
        if key!='ref' or type(v[key]) is not int or not 0<=v[key]<len(nodes):raise ValueError('Invalid Chan state reference')
        index=v[key]
        if nodes[index]['kind']=='tuple' and objects[index] is None:
            if index in resolving:raise ValueError('Cyclic immutable state')
            resolving.add(index);objects[index]=tuple(value(x) for x in nodes[index]['items']);resolving.remove(index)
        return objects[index]
    # Allocate every mutable object before reconnecting cyclic core references.
    for index,node in enumerate(nodes):
        target=objects[index];kind=node['kind']
        if kind=='object':target.__dict__.update({k:value(v) for k,v in node['fields'].items()})
        elif kind=='dict':target.update((value(k),value(v)) for k,v in node['items'])
        elif kind=='list':target.extend(value(v) for v in node['items'])
        elif kind=='set':target.update(value(v) for v in node['items'])
        elif kind=='tuple':value({'ref':index})
    from .chan_classic import ClassicChanState
    root=value(payload['root'])
    if not isinstance(root,ClassicChanState):raise ValueError('Chan checkpoint root differs')
    return root
