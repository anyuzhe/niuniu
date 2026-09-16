from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.research_skill_tools import ResearchSkillResearchAPI
from quantlab.knowledge.research_skill import FORMAT, REQUIRED_POLICY
from quantlab.knowledge.research_skill_git import (
    CURATION_FORMAT, archive_git_research_skill, materialize_git_research_skill,
)
from quantlab.knowledge.research_skill_library import (
    AUTHORIZATION, LIBRARY_FORMAT, ResearchSkillLibrary, ResearchSkillLibraryError,
)


class ResearchSkillLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name);self.data_root = self.base / 'data';self.data_root.mkdir()
        self.upstream = self.base / 'upstream';self.upstream.mkdir()
        self.origin = 'https://github.com/example/read-only-skill.git'
        self.executed = self.base / 'script-executed'
        files = {
            'references/interview.txt': '我的投资以景气为主。',
            'references/holding.json': '{"quarter":"2025Q1","symbol":"000001"}',
            'references/outcome.json': '{"date":"2025-05-01","return":0.1}',
            'scripts/evil.py': f"from pathlib import Path\nPath({str(self.executed)!r}).write_text('bad')\n",
        }
        for relative,content in files.items():
            path=self.upstream/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
        self.git('init','-q');self.git('config','user.email','test@example.com');self.git('config','user.name','Test')
        self.git('add','.');self.git('commit','-qm','fixture');self.git('remote','add','origin',self.origin)
        self.commit=self.git_output('rev-parse','HEAD');self.tree=self.git_output('rev-parse','HEAD^{tree}')
        self.control=self.base/'control';self.write_control()
        self.plan=self.base/'plan.json';self.write_plan('0'*64)
        archived=archive_git_research_skill(self.data_root,self.upstream,'manager-skill',self.origin,
            self.commit,self.tree,confirm_untrusted_no_exec=True,
            now_fn=lambda:datetime(2026,9,16,tzinfo=timezone.utc))
        self.write_plan(archived['archive_snapshot'])
        package=materialize_git_research_skill(self.data_root,self.control,self.plan,
            confirm_retrospective_only=True)
        self.archive_snapshot=archived['archive_snapshot'];self.package_snapshot=package['package_snapshot']
        self.host=self.base/'host';skills=self.host/'research_skills';skills.mkdir(parents=True)
        shutil.copytree(self.control,skills/'manager-skill')
        (skills/'curation').mkdir();shutil.copy2(self.plan,skills/'curation'/'manager.json')
        registry={'format':LIBRARY_FORMAT,'skills':[{'skill_key':'manager-skill',
            'control_snapshot':self.control_snapshot,'archive_snapshot':self.archive_snapshot,
            'package_snapshot':self.package_snapshot,'curation_plan':'curation/manager.json',
            'authorization':AUTHORIZATION}]}
        (skills/'library.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
        self.git('init','-q',cwd=self.host);self.git('config','user.email','test@example.com',cwd=self.host)
        self.git('config','user.name','Test',cwd=self.host);self.git('add','.',cwd=self.host)
        self.git('commit','-qm','host authorization',cwd=self.host)
        self.output=self.base/'output';self.output.mkdir()

    def git(self,*args,cwd=None):
        subprocess.run(['git','-C',str(cwd or self.upstream),*args],check=True,capture_output=True)

    def git_output(self,*args):
        return subprocess.run(['git','-C',str(self.upstream),*args],check=True,capture_output=True,text=True).stdout.strip()

    @staticmethod
    def resource(root,resource_id,relative,role,content):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
        payload=path.read_bytes()
        return {'resource_id':resource_id,'path':relative,'role':role,
            'sha256':sha256(payload).hexdigest(),'bytes':len(payload),'locator':'',
            'published_at':None,'available_at':None,'timing_class':'NOT_APPLICABLE'}

    def write_control(self):
        self.control.mkdir()
        resources=[
            self.resource(self.control,'behavior','SKILL.md','BEHAVIOR_CONTRACT','deny execution'),
            self.resource(self.control,'method','method.md','METHOD','quote then hypothesis'),
            self.resource(self.control,'scorecard','scorecard.md','SCORECARD','similarity only'),
            self.resource(self.control,'script-policy','scripts/README.md','SCRIPT_POLICY','never execute'),
        ]
        manifest={'format':FORMAT,'skill_key':'manager-skill','title':'control','version':'control-1',
            'status':'SOURCE_REQUIRED','strategy_source_kind':'TRADER','summary':'source-free control package',
            'keywords':['景气'],'resources':resources,'claims':[],'alignments':[],
            'hypotheses':[{'hypothesis_key':'cycle','title':'景气候选','status':'DRAFT','claim_ids':[],
                'feature_candidates':['景气'],'required_data':['PIT data'],'target_horizon':'MEDIUM_TERM',
                'playbook_key':'','score_semantics':'RESEARCH_HYPOTHESIS_NOT_ALPHA'}],
            'policy':deepcopy(REQUIRED_POLICY)}
        (self.control/'skill.yml').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        from quantlab.knowledge.research_skill import audit_research_skill
        self.control_snapshot=audit_research_skill(self.control)['package_snapshot']

    def plan_resource(self,resource_id,upstream,target,role):
        payload=(self.upstream/upstream).read_bytes()
        return {'resource_id':resource_id,'upstream_path':upstream,'target_path':target,'role':role,
            'sha256':sha256(payload).hexdigest(),'bytes':len(payload),
            'locator':f'https://github.com/example/read-only-skill/blob/{self.commit}/{upstream}'}

    def write_plan(self,archive_snapshot):
        plan={'format':CURATION_FORMAT,'skill_key':'manager-skill','control_snapshot':self.control_snapshot,
            'archive_snapshot':archive_snapshot,'version':'upstream-1','status':'DRAFT',
            'strategy_source_kind':'TRADER','title':'curated manager skill','summary':'retrospective fixture only',
            'keywords':['景气','季度持仓'],'resources':[
                self.plan_resource('statement','references/interview.txt','references/upstream/interview.txt','PRIMARY_STATEMENT'),
                self.plan_resource('holding','references/holding.json','references/upstream/holding.json','DISCLOSED_ACTION'),
                self.plan_resource('outcome','references/outcome.json','references/upstream/outcome.json','REALIZED_OUTCOME'),
            ],'claims':[{'claim_id':'view','kind':'DIRECT_QUOTE','text':'我的投资以景气为主。','resource_ids':['statement']},
                {'claim_id':'holding-fact','kind':'FACT_TO_VERIFY','text':'holding to verify','resource_ids':['holding']}],
            'alignments':[{'alignment_id':'say-do-result','statement_claim_id':'view','action_resource_ids':['holding'],
                'outcome_resource_ids':['outcome'],'assessment':'MIXED','notes':'no causal claim'}],
            'hypotheses':[{'hypothesis_key':'cycle','title':'景气候选','status':'DRAFT','claim_ids':['view'],
                'feature_candidates':['景气'],'required_data':['PIT data'],'target_horizon':'MEDIUM_TERM',
                'playbook_key':'','score_semantics':'RESEARCH_HYPOTHESIS_NOT_ALPHA'}]}
        self.plan.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')

    def library(self):return ResearchSkillLibrary(self.data_root,self.host)

    def test_registered_package_search_and_excerpt_are_read_only(self):
        unavailable=ResearchSkillLibrary(None,self.host).list('',0,20)['records'][0]
        self.assertFalse(unavailable['package_available']);self.assertEqual(unavailable['integrity'],'DATA_ROOT_NOT_CONFIGURED')
        library=self.library();listing=library.list('景气',0,20)
        self.assertEqual(listing['total'],1);record=listing['records'][0]
        self.assertEqual(record['integrity'],'VERIFIED');self.assertTrue(record['archive_verified'])
        self.assertEqual(record['counts']['claims'],2);self.assertFalse(record['boundaries']['strict_pit_eligible'])
        detail=library.get('manager-skill',self.package_snapshot)
        self.assertEqual(detail['strategy_source_preview']['completeness'],'PARTIAL')
        self.assertNotIn('archive_ref',detail['strategy_source_preview'])
        claims=library.search('manager-skill',self.package_snapshot,'CLAIM','景气','DIRECT_QUOTE',0,20)
        self.assertEqual(claims['total'],1);self.assertEqual(claims['records'][0]['resources'][0]['resource_id'],'statement')
        hypotheses=library.search('manager-skill',self.package_snapshot,'HYPOTHESIS','','MEDIUM_TERM',0,20)
        self.assertEqual(hypotheses['records'][0]['claims'][0]['kind'],'DIRECT_QUOTE')
        alignments=library.search('manager-skill',self.package_snapshot,'ALIGNMENT','','MIXED',0,20)
        self.assertEqual(alignments['records'][0]['statement_claim']['claim_id'],'view')
        first=library.excerpt('manager-skill',self.package_snapshot,'statement',0,4)
        self.assertEqual(first['text'],'我');self.assertEqual(first['returned_bytes'],3);self.assertEqual(first['next_offset_bytes'],3)
        second=library.excerpt('manager-skill',self.package_snapshot,'statement',3,6)
        self.assertEqual(second['text'],'的投');self.assertEqual(second['content_treatment'],'UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS')
        self.assertFalse(self.executed.exists())

    def test_exact_authorization_lineage_and_bytes_fail_closed(self):
        library=self.library()
        with self.assertRaises(ResearchSkillLibraryError) as unauthorized:
            library.get('manager-skill','f'*64)
        self.assertEqual(unauthorized.exception.code,'RESEARCH_SKILL_NOT_AUTHORIZED')
        with self.assertRaises(ResearchSkillLibraryError) as boundary:
            library.excerpt('manager-skill',self.package_snapshot,'statement',1,10)
        self.assertEqual(boundary.exception.code,'RESEARCH_SKILL_BYTE_OFFSET_INVALID')
        with self.assertRaises(ResearchSkillLibraryError) as classification:
            library.search('manager-skill',self.package_snapshot,'CLAIM','','BUY',0,20)
        self.assertEqual(classification.exception.code,'INVALID_ARGUMENT')
        plan=json.loads((self.host/'research_skills/curation/manager.json').read_text())
        plan['summary']='changed lineage'
        (self.host/'research_skills/curation/manager.json').write_text(json.dumps(plan),encoding='utf-8')
        self.git('add','.',cwd=self.host);self.git('commit','-qm','invalid lineage fixture',cwd=self.host)
        with self.assertRaises(ResearchSkillLibraryError) as lineage:
            library.get('manager-skill',self.package_snapshot)
        self.assertEqual(lineage.exception.code,'RESEARCH_SKILL_LINEAGE_INVALID')

    def test_source_controlled_authorization_must_be_git_clean(self):
        self.assertEqual(self.library().get('manager-skill',self.package_snapshot)['skill']['integrity'],'VERIFIED')
        with (self.host/'research_skills/library.json').open('a',encoding='utf-8') as stream:stream.write('\n')
        with self.assertRaises(ResearchSkillLibraryError) as dirty:
            self.library().list('',0,20)
        self.assertEqual(dirty.exception.code,'LIBRARY_SOURCE_DIRTY')

    def test_agent_tools_are_bounded_and_have_no_write_or_script_surface(self):
        api=ResearchSkillResearchAPI(ReadOnlyResearchAPI(self.output),self.data_root,self.host)
        names={tool['name'] for tool in api.schemas()}
        expected={'list_research_skills','get_research_skill','search_research_skill_items',
            'read_research_skill_resource_excerpt'}
        self.assertTrue(expected.issubset(names))
        self.assertFalse(any(name.startswith(('create_research_skill','write_research_skill','execute_research_skill')) for name in names))
        capabilities=api.call('get_capabilities',{})
        self.assertTrue(capabilities['data']['research_skill_library_read_only'])
        listed=api.call('list_research_skills',{'query':'景气','offset':0,'limit':20})
        self.assertTrue(listed['ok']);self.assertEqual(listed['evidence'][0]['kind'],'research_skill')
        found=api.call('search_research_skill_items',{'skill_key':'manager-skill',
            'package_snapshot':self.package_snapshot,'item_type':'CLAIM','query':'景气',
            'classification':'DIRECT_QUOTE','offset':0,'limit':20})
        self.assertTrue(found['ok']);self.assertEqual(found['evidence'][-1]['item_id'],'view')
        excerpt=api.call('read_research_skill_resource_excerpt',{'skill_key':'manager-skill',
            'package_snapshot':self.package_snapshot,'resource_id':'statement','offset_bytes':0,'limit_bytes':100})
        self.assertTrue(excerpt['ok']);self.assertIn('UNTRUSTED_EXTERNAL_DATA',excerpt['data']['content_treatment'])
        self.assertNotIn(str(self.base),json.dumps([listed,found,excerpt],ensure_ascii=False))
        invalid=api.call('list_research_skills',{'query':'','offset':0,'limit':20,'extra':True})
        self.assertFalse(invalid['ok']);self.assertEqual(invalid['error']['code'],'INVALID_ARGUMENT')
        self.assertFalse(self.executed.exists())

    def test_daily_assistant_and_peer_review_expose_only_read_tools(self):
        chat_names={tool['name'] for tool in ChatRuntime(self.output,self.data_root).api.schemas()}
        review_names={tool['name'] for tool in ReviewReadOnlyAPI(self.output,self.data_root).schemas()}
        for name in ('list_research_skills','get_research_skill','search_research_skill_items',
                'read_research_skill_resource_excerpt'):
            self.assertIn(name,chat_names);self.assertIn(name,review_names)
        for forbidden in ('write_research_skill','execute_research_skill_script','create_strategy_source',
                'create_playbook_definition'):
            self.assertNotIn(forbidden,chat_names);self.assertNotIn(forbidden,review_names)


if __name__=='__main__':unittest.main()
