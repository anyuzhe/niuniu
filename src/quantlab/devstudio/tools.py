"""Role-scoped model tools for Dev Studio. No shell, git commit or push tools."""
from __future__ import annotations

import json

from .service import DevStudioError,DevStudioService

TEXT={'type':'string','maxLength':12000}
SHORT={'type':'string','maxLength':500}
PATH={'type':'string','maxLength':500}
STRINGS={'type':'array','items':{'type':'string','maxLength':1000},'maxItems':100}
PATHS={'type':'array','items':{'type':'string','maxLength':500},'maxItems':50}
UUIDS={'type':'array','items':{'type':'string','maxLength':64},'maxItems':20}


def tool(name,description,properties):
    return {'name':name,'description':description,'parameters':{'type':'object','properties':properties,
        'required':list(properties),'additionalProperties':False}}

def _validate_value(value,spec,name):
    kind=spec.get('type')
    if kind=='string':
        if not isinstance(value,str) or len(value)>spec.get('maxLength',10**9):raise ValueError('invalid tool field: '+name)
        if 'enum' in spec and value not in spec['enum']:raise ValueError('invalid tool enum: '+name)
    elif kind=='integer':
        if type(value) is not int or value<spec.get('minimum',-10**18) or value>spec.get('maximum',10**18):raise ValueError('invalid tool integer: '+name)
    elif kind=='array':
        if not isinstance(value,list) or len(value)>spec.get('maxItems',1000):raise ValueError('invalid tool array: '+name)
        for item in value:_validate_value(item,spec.get('items',{}),name)
    elif kind=='object':
        if not isinstance(value,dict):raise ValueError('invalid tool object: '+name)
    else:raise ValueError('unsupported tool schema: '+name)


def _validate_call(definitions,name,args):
    definition=next((x for x in definitions if x['name']==name),None)
    if definition is None:raise ValueError('unknown tool')
    props=definition['parameters']['properties']
    if not isinstance(args,dict) or set(args)!=set(props):raise ValueError('tool fields must exactly match schema')
    for key,spec in props.items():_validate_value(args[key],spec,key)


def model_state(service,task_id):
    state=service.get(task_id)
    tests=[]
    for item in state.get('test_runs',[])[-20:]:
        row=dict(item)
        if isinstance(row.get('stdout_tail'),str):row['stdout_tail']=row['stdout_tail'][-2000:]
        if isinstance(row.get('stderr_tail'),str):row['stderr_tail']=row['stderr_tail'][-2000:]
        tests.append(row)
    return {'task_id':state['task_id'],'state':state['state'],'spec':state['spec'],'base_branch':state.get('base_branch',''),
        'base_sha':state.get('base_sha',''),'subtasks':state['subtasks'],'test_runs':tests,
        'main_acceptance':state.get('main_acceptance'),'merge':state.get('merge'),'events':state.get('events',[])[-30:]}


def model_diff(value):
    patch=value.get('patch','');limit=120000
    return {**value,'patch':patch[:limit]+('\n[diff truncated; inspect files individually]' if len(patch)>limit else ''),
        'patch_truncated':len(patch)>limit}

COMMON=[
    tool('dev_task_status','Read the frozen DevTask, subtasks, tests and acceptance state.',{}),
    tool('dev_read_file','Read UTF-8 text from the isolated DevTask worktree.',{'path':PATH}),
    tool('dev_search','Search literal text in the isolated worktree.',{'query':SHORT}),
    tool('dev_diff','Read the current isolated worktree diff and changed-file list.',{}),
]
MAIN=COMMON+[
    tool('dev_create_subtask','Create one depth-1 dynamic subtask. Only IMPLEMENTER may request lease_paths.',{
        'role':{'type':'string','enum':['EXPLORER','IMPLEMENTER','TESTER','REVIEWER']},'title':SHORT,'instruction':TEXT,
        'depends_on':UUIDS,'lease_paths':PATHS,'acceptance_criteria':STRINGS,
        'effort':{'type':'string','enum':['','none','minimal','low','medium','high','xhigh']}}),
    tool('dev_reopen_subtask','Reopen one DONE/BLOCKED subtask using the same role and same immutable path lease.',{
        'subtask_id':{'type':'string','maxLength':64},'instruction':TEXT}),
    tool('dev_accept_task','Main Agent final decision. ACCEPT is blocked unless Reviewer PASS and all frozen tests pass.',{
        'verdict':{'type':'string','enum':['ACCEPT','REPLAN','BLOCK']},'summary':TEXT,'evidence':STRINGS}),
]
SUBMIT=tool('dev_submit_result','Finish this subtask with a bounded evidence summary. Actual changed files are recomputed by the host.',{
    'summary':TEXT,'verdict':{'type':'string','enum':['PASS','FAIL','NEEDS_CHANGES','UNKNOWN']},
    'evidence':STRINGS,'stop_reason':SHORT})
WRITE=tool('dev_write_file','Write one UTF-8 file inside this IMPLEMENTER path lease only. Use expected_sha256 from dev_read_file; empty means create/overwrite without CAS.',{
    'path':PATH,'text':{'type':'string','maxLength':500000},'expected_sha256':{'type':'string','maxLength':64}})
TEST=tool('dev_run_frozen_test','Run one DevTask test command by frozen index; the model cannot invent a new command.',{
    'command_index':{'type':'integer','minimum':0,'maximum':19}})


class _BaseAPI:
    def __init__(self,service,task_id):self.service=service;self.task_id=task_id
    def _raw_state(self):return self.service.get(self.task_id)
    def _state(self):return model_state(self.service,self.task_id)
    def _common(self,name,args,subtask_id=None):
        if name=='dev_task_status':return self._state()
        if name=='dev_read_file':
            if subtask_id:return self.service.read_file(self.task_id,subtask_id,args['path'])
            state=self._raw_state();return self.service.workspace.read_file(state['worktree_path'],args['path'])
        if name=='dev_search':
            if subtask_id:return self.service.search(self.task_id,subtask_id,args['query'])
            state=self._raw_state();return self.service.workspace.search(state['worktree_path'],args['query'])
        if name=='dev_diff':return model_diff(self.service.diff(self.task_id,subtask_id))
        raise KeyError(name)
    @staticmethod
    def _reply(name,fn):
        try:return {'ok':True,'tool':name,'data':fn(),'error':None}
        except (DevStudioError,OSError,ValueError,KeyError,TypeError) as exc:
            return {'ok':False,'tool':name,'data':None,'error':{'code':getattr(exc,'code','DEV_TOOL_FAILED'),'message':str(exc)[:500]}}


class MainDevAPI(_BaseAPI):
    def schemas(self):return json.loads(json.dumps(MAIN))
    def call(self,name,args):
        if name not in {x['name'] for x in MAIN}:return {'ok':False,'tool':name,'data':None,'error':{'code':'UNKNOWN_TOOL','message':'tool unavailable'}}
        args=args or {}
        def work():
            _validate_call(MAIN,name,args)
            if name in {x['name'] for x in COMMON}:return self._common(name,args)
            if name=='dev_create_subtask':return self.service.add_subtask(self.task_id,{**args,'model':''})
            if name=='dev_reopen_subtask':return self.service.reopen_subtask(self.task_id,args['subtask_id'],args['instruction'])
            return self.service.accept(self.task_id,args['verdict'],args['summary'],args['evidence'])
        return self._reply(name,work)


class SubtaskDevAPI(_BaseAPI):
    def __init__(self,service,task_id,subtask_id):
        super().__init__(service,task_id);self.subtask_id=subtask_id
    def _sub(self):
        state=self._raw_state();return next(s for s in state['subtasks'] if s['subtask_id']==self.subtask_id)
    def schemas(self):
        role=self._sub()['spec']['role'];items=list(COMMON)
        if role=='IMPLEMENTER':items.append(WRITE)
        if role=='TESTER':items.append(TEST)
        items.append(SUBMIT);return json.loads(json.dumps(items))
    def call(self,name,args):
        definitions=self.schemas();available={x['name'] for x in definitions}
        if name not in available:return {'ok':False,'tool':name,'data':None,'error':{'code':'UNKNOWN_TOOL','message':'tool unavailable for role'}}
        args=args or {}
        def work():
            _validate_call(definitions,name,args)
            if name in {x['name'] for x in COMMON}:return self._common(name,args,self.subtask_id)
            if name=='dev_write_file':return self.service.write_file(self.task_id,self.subtask_id,args['path'],args['text'],args['expected_sha256'] or None)
            if name=='dev_run_frozen_test':
                state=self._raw_state();index=args['command_index'];commands=state['spec']['test_commands']
                if not 0<=index<len(commands):raise DevStudioError('INVALID_ARGUMENT','frozen test index out of range')
                return self.service.run_test(self.task_id,self.subtask_id,commands[index])
            if name=='dev_submit_result':
                state=self._raw_state();sub=next(s for s in state['subtasks'] if s['subtask_id']==self.subtask_id)
                changed=[]
                if sub['spec']['role']=='IMPLEMENTER':
                    actual=self.service.workspace.changed_files(state['worktree_path'])
                    changed=[p for p in actual if any(p==lease or p.startswith(lease+'/') for lease in sub['spec']['lease_paths'])]
                tests=[]
                if sub['spec']['role']=='TESTER':
                    commands=state['spec']['test_commands'];tests=state['test_runs'][-len(commands):] if commands else []
                result={'summary':args['summary'],'changed_files':changed,'tests':tests,'evidence':args['evidence'],
                    'verdict':args['verdict'],'stop_reason':args['stop_reason']}
                return self.service.finish_subtask(self.task_id,self.subtask_id,result)
            raise KeyError(name)
        return self._reply(name,work)


__all__=['MainDevAPI','SubtaskDevAPI']
