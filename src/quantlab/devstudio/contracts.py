"""Strict Dev Studio task/subtask contracts. Models never own authority here."""
from __future__ import annotations

from pathlib import PurePosixPath
from uuid import UUID
import re

ROLES=('EXPLORER','IMPLEMENTER','TESTER','REVIEWER')
TASK_STATES=('DRAFT','PLANNED','RUNNING','REVIEW','READY_FOR_HUMAN','MERGED','BLOCKED','CANCELLED')
SUBTASK_STATES=('PENDING','RUNNING','DONE','BLOCKED','CANCELLED')
VERDICTS=('PASS','FAIL','NEEDS_CHANGES','UNKNOWN')


def uuid_text(value,name='id'):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise ValueError(name+' must be canonical UUID') from None
    return value


def text(value,name,maximum=4000,required=False):
    if value is None:value=''
    if not isinstance(value,str):raise ValueError(name+' must be text')
    value=value.strip()
    if required and not value:raise ValueError(name+' is required')
    if len(value)>maximum:raise ValueError(name+' is too long')
    return value


def string_list(value,name,maximum=100,item_max=500,required=False):
    if value is None:value=[]
    if not isinstance(value,list) or len(value)>maximum:raise ValueError(name+' must be a bounded list')
    result=[]
    for item in value:
        item=text(item,name,item_max,True)
        if item not in result:result.append(item)
    if required and not result:raise ValueError(name+' cannot be empty')
    return result


def repo_path(value,name='path'):
    value=text(value,name,500,True).replace('\\','/')
    path=PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError(name+' must be repository-relative')
    normalized='/'.join(part for part in path.parts if part not in ('','.'))
    if not normalized or normalized.startswith('.git') or '/.git/' in '/'+normalized+'/':
        raise ValueError(name+' cannot target git metadata')
    if any(part in ('.git','..') for part in path.parts):raise ValueError(name+' cannot target git metadata')
    return normalized


def path_list(value,name='paths',maximum=50):
    if value is None:value=[]
    if not isinstance(value,list) or len(value)>maximum:raise ValueError(name+' must be a bounded list')
    result=[]
    for item in value:
        item=repo_path(item,name)
        if item not in result:result.append(item)
    return result


def normalize_task_spec(value):
    if not isinstance(value,dict):raise ValueError('DevTask spec must be an object')
    allowed={'title','request','acceptance_criteria','allowed_paths','test_commands','max_parallel_subagents','notes','team'}
    if set(value)-allowed:raise ValueError('DevTask spec has unknown fields')
    parallel=value.get('max_parallel_subagents',3)
    if type(parallel) is not int or not 1<=parallel<=3:raise ValueError('max_parallel_subagents must be 1..3')
    commands=value.get('test_commands') or []
    if not isinstance(commands,list) or len(commands)>20:raise ValueError('test_commands must be a bounded list')
    normalized_commands=[]
    for command in commands:
        if not isinstance(command,list) or not 3<=len(command)<=20 or any(not isinstance(x,str) or not x or len(x)>300 for x in command):
            raise ValueError('each test command must be an argv list')
        normalized_commands.append(command)
    allowed_paths=path_list(value.get('allowed_paths'),'allowed_paths',100)
    if not allowed_paths:raise ValueError('allowed_paths cannot be empty; DevTask write scope must be explicit')
    result = {'title':text(value.get('title'),'title',160,True),
        'request':text(value.get('request'),'request',20000,True),
        'acceptance_criteria':string_list(value.get('acceptance_criteria'),'acceptance_criteria',50,1000,True),
        'allowed_paths':allowed_paths,
        'test_commands':normalized_commands,'max_parallel_subagents':parallel,
        'notes':text(value.get('notes'),'notes',8000)}
    if 'team' in value:
        from .team import normalize_team, validate_team_tests
        result['team'] = normalize_team(value['team'], allowed_paths)
        validate_team_tests(normalized_commands)
    return result


def normalize_subtask_spec(value):
    if not isinstance(value,dict):raise ValueError('Subtask spec must be an object')
    allowed={'role','title','instruction','depends_on','lease_paths','acceptance_criteria','model','effort','domain'}
    if set(value)-allowed:raise ValueError('Subtask spec has unknown fields')
    role=text(value.get('role'),'role',30,True).upper()
    if role not in ROLES:raise ValueError('unknown Dev Studio role')
    lease_paths=path_list(value.get('lease_paths'),'lease_paths',50)
    if role!='IMPLEMENTER' and lease_paths:raise ValueError('only IMPLEMENTER may hold write leases')
    depends=value.get('depends_on') or []
    if not isinstance(depends,list) or len(depends)>20:raise ValueError('depends_on must be bounded')
    depends=[uuid_text(item,'depends_on') for item in depends]
    effort=text(value.get('effort'),'effort',20).lower()
    if effort not in ('','none','minimal','low','medium','high','xhigh'):raise ValueError('invalid effort')
    result = {'role':role,'title':text(value.get('title'),'title',160,True),
        'instruction':text(value.get('instruction'),'instruction',12000,True),
        'depends_on':depends,'lease_paths':lease_paths,
        'acceptance_criteria':string_list(value.get('acceptance_criteria'),'acceptance_criteria',30,1000),
        'model':text(value.get('model'),'model',160),'effort':effort}
    if 'domain' in value:
        from .team import DOMAINS
        domain = text(value['domain'], 'domain', 20, True).upper()
        if domain not in DOMAINS: raise ValueError('unknown professional domain')
        result['domain'] = domain
    return result


def paths_overlap(left,right):
    left=repo_path(left);right=repo_path(right)
    return left==right or left.startswith(right+'/') or right.startswith(left+'/')


def normalize_result(value):
    if not isinstance(value,dict):raise ValueError('result must be an object')
    allowed={'summary','changed_files','tests','evidence','verdict','stop_reason'}
    if set(value)-allowed:raise ValueError('result has unknown fields')
    verdict=text(value.get('verdict','UNKNOWN'),'verdict',30,True).upper()
    if verdict not in VERDICTS:raise ValueError('invalid verdict')
    tests=value.get('tests') or []
    if not isinstance(tests,list) or len(tests)>100:raise ValueError('tests must be bounded')
    return {'summary':text(value.get('summary'),'summary',12000,True),
        'changed_files':path_list(value.get('changed_files'),'changed_files',200),
        'tests':tests,'evidence':string_list(value.get('evidence'),'evidence',100,1000),
        'verdict':verdict,'stop_reason':text(value.get('stop_reason'),'stop_reason',1000)}


__all__=['ROLES','TASK_STATES','SUBTASK_STATES','VERDICTS','uuid_text','repo_path','path_list',
    'paths_overlap','normalize_task_spec','normalize_subtask_spec','normalize_result']
