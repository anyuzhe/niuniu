"""Role-to-model mapping; roles are stable while model overrides are replaceable."""
from __future__ import annotations

from dataclasses import asdict,replace
from pathlib import Path
from uuid import uuid4
import json

from quantlab.agent.agent_memory import ROLES
from quantlab.agent.model_config import ModelConfig,ModelError,assistant_root,strict_json
from quantlab.storage.codec import digest

REVIEWERS=('market_scanner','skeptic','quant_researcher')
EFFORTS=('', 'none','minimal','low','medium','high','xhigh')


def default_team_config():
    return {'version':'ai-team-v1','roles':{
        role:{'enabled':role!='developer','model':'','effort':''} for role in ROLES}}


def validate_team_config(value):
    if not isinstance(value,dict) or set(value)!= {'version','roles'}:raise ValueError('AI Team 配置字段无效。')
    if not isinstance(value['version'],str) or not value['version'].strip() or len(value['version'])>120:raise ValueError('AI Team version 无效。')
    if not isinstance(value['roles'],dict) or set(value['roles'])!=set(ROLES):raise ValueError('AI Team 必须覆盖全部固定角色。')
    result={'version':value['version'],'roles':{}}
    for role,profile in value['roles'].items():
        if not isinstance(profile,dict) or set(profile)!= {'enabled','model','effort'}:raise ValueError('AI Team role 配置无效：'+role)
        if type(profile['enabled']) is not bool:raise ValueError('enabled 必须是布尔值。')
        model=profile['model'];effort=profile['effort']
        if not isinstance(model,str) or len(model)>200 or any(ord(c)<32 for c in model):raise ValueError('角色 model 无效。')
        if effort not in EFFORTS:raise ValueError('角色 effort 无效。')
        result['roles'][role]={'enabled':profile['enabled'],'model':model.strip(),'effort':effort}
    if not result['roles']['chief_researcher']['enabled']:raise ValueError('Chief Researcher 必须启用。')
    if result['roles']['developer']['enabled']:raise ValueError('Developer 在 P10 Dev Studio 前不可启用。')
    return result

class TeamConfigStore:
    def __init__(self,output):
        self.root=assistant_root(output);self.path=self.root/'team.json'

    def load(self):
        if not self.path.exists():return default_team_config()
        if self.path.is_symlink() or self.path.stat().st_size>32_000:raise ModelError('AI Team 配置文件无效。')
        value=strict_json(self.path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or set(value)!= {'config','checksum'}:raise ModelError('AI Team 配置包装无效。')
        if digest(value['config'])!=value['checksum']:raise ModelError('AI Team 配置校验失败。')
        return validate_team_config(value['config'])

    def save(self,config):
        config=validate_team_config(config)
        if self.path.is_symlink():raise ModelError('AI Team 配置不能为符号链接。')
        temp=self.path.with_name('team-'+str(uuid4())+'.tmp')
        payload={'config':config,'checksum':digest(config)}
        try:
            temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
            temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)
        return config


def role_model_config(base,team,role_id):
    team=validate_team_config(team)
    if role_id not in ROLES:raise ValueError('未知 Agent role。')
    profile=team['roles'][role_id]
    if not profile['enabled']:raise ModelError('角色未启用：'+role_id)
    updates={}
    if profile['model']:updates['model']=profile['model']
    if profile['effort']:updates['effort']=profile['effort']
    return replace(base,**updates) if updates else base


def enabled_reviewers(team):
    team=validate_team_config(team)
    return [role for role in REVIEWERS if team['roles'][role]['enabled']]
