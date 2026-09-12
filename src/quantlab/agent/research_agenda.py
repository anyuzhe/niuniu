"""Deterministic research agenda over durable workspace evidence; read-only."""
from datetime import datetime,timezone
from pathlib import Path
import json

from quantlab.agent.alpha_factory import AlphaFactoryService
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.agent.incremental_evidence import IncrementalEvidenceService
from quantlab.agent.memory_store import MemoryStore,MemoryError
from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record_fields


def now():return datetime.now(timezone.utc).isoformat()


def agenda_item(kind,title,reason,action,priority,evidence):
    core={'kind':kind,'title':title,'reason':reason,'action':action,'priority':priority,'evidence':evidence}
    return {'agenda_id':digest(core),**core}


class ResearchAgendaService:
    def __init__(self,output,data_root=None):
        self.output=Path(output).resolve();self.data_root=data_root
        if not self.output.is_dir():raise ValueError('研究工作空间不存在')
    def _memory_items(self):
        store=MemoryStore(self.output);records=[]
        try:
            offset=0
            while len(records)<200:
                page=store.search('',include_superseded=False,offset=offset,limit=20)
                records.extend(page['records'])
                if page['next_offset'] is None:break
                offset=page['next_offset']
        except MemoryError as error:
            if error.code=='NOT_FOUND':return []
            raise
        findings={r['hypothesis_id'] for r in records if r['kind']=='finding' and r.get('hypothesis_id')}
        return [agenda_item('open_hypothesis',r['title'],'研究假设尚无当前结论记录',
            '为该假设设计固定研究或证据包',60,[{'kind':'memory','memory_id':r['memory_id']}])
            for r in records if r['kind']=='hypothesis' and r['memory_id'] not in findings]

    def _job_items(self):
        rows=[];folder=self.output/'_jobs'
        for path in sorted(folder.glob('*.json'))[-200:] if folder.exists() else []:
            try:
                if path.is_symlink() or path.stat().st_size>2_000_000:continue
                job=json.loads(path.read_text())
                if job.get('status') in ('failed','interrupted'):
                    rows.append(agenda_item('failed_job',(job.get('spec') or {}).get('question','研究任务失败'),
                        job.get('error') or job['status'],'核对失败原因；不要自动重试或换参数',85,
                        [{'kind':'job','job_id':job.get('job_id')}]))
            except (OSError,ValueError,KeyError,TypeError):continue
        return rows
    def _watch_items(self):
        service=WatchService(self.output,self.data_root);items=[]
        listing=service.store.list()
        for row in listing['watches'][:100]:
            try:value=service.get(row['watch_id'])
            except (OSError,ValueError,KeyError,TypeError):continue
            ref=[{'kind':'watch','watch_id':row['watch_id']}]
            integrity=value['source_integrity']
            if integrity!='verified':
                items.append(agenda_item('watch_integrity',row['name'],'观察池来源状态为 '+integrity,
                    '先核对来源或做基准换版，不继续解释最新指标',100,ref));continue
            latest=value.get('latest') or {};alerts=latest.get('alerts') or []
            reviews=[a for a in alerts if a.get('severity')=='review']
            if reviews:
                items.append(agenda_item('watch_review',row['name'],'观察池出现需要人工复核的历史输入修订',
                    '核对修订来源并决定是否重建基准',95,ref))
            elif alerts:
                items.append(agenda_item('watch_notice',row['name'],'观察池存在 '+str(len(alerts))+' 条数据/样本提醒',
                    '查看成熟样本、水位与缺失情况',65,ref))
        if listing['unreadable']:
            items.append(agenda_item('watch_store_error','观察池存在不可读记录',str(listing['unreadable'])+' 条记录无法解析',
                '人工核对观察池存储，不自动删除',100,[]))
        return items
    def _candidate_items(self):
        dsl=DslCandidateService(self.output);items=[];runs={};run_keys={}
        for path in self.output.glob('*/experiment.json'):
            try:
                record=load_record_fields(path,{'run_id','kind','status','created_at','manifest'})
                cfg=(record.get('manifest') or {}).get('config') or {}
                if record.get('status')=='completed' and record.get('kind','factor')=='factor' and cfg.get('factor_id')=='DSL.RESTRICTED':
                    key=digest(cfg.get('parameters',{}));run_keys[record['run_id']]=key;old=runs.get(key)
                    if old is None or record.get('created_at','')>old.get('created_at',''):runs[key]=record
            except (OSError,ValueError,KeyError,TypeError):continue
        evidence_states=IncrementalEvidenceService(self.output).list()['proposals']
        factories=AlphaFactoryService(self.output,self.data_root).list()['factories']
        covered={s['prepared']['plan']['candidate_run_id'] for s in evidence_states
            if s.get('status')=='completed' and s.get('prepared',{}).get('plan',{}).get('candidate_run_id')}
        covered_keys={run_keys[r] for r in covered if r in run_keys};factory_candidates=set()
        for factory in factories:
            if factory.get('status')=='completed':
                for job in factory.get('jobs',[]):
                    if job.get('kind')=='factor':
                        factory_candidates.add(job.get('candidate_id'))
                        try:
                            record=json.loads((self.output/'_jobs'/(job['job_id']+'.json')).read_text())
                            if record.get('status')=='completed' and record.get('run_id'):covered.add(record['run_id'])
                        except (OSError,ValueError,KeyError,TypeError):pass
        for proposal in dsl.pending()['proposals']:
            plan=proposal['plan']
            items.append(agenda_item('dsl_registration',plan['name'],'DSL候选已通过预检但尚未人工注册',
                '在宿主候选面板核对AST和来源后决定是否注册',92,
                [{'kind':'dsl_proposal','request_id':proposal['request_id']}]))
        listing=dsl.list(query='',limit=100)
        for candidate in listing['candidates']:
            full=dsl.get(candidate['candidate_id']);key=digest(full['plan']['parameters']);run=runs.get(key)
            ref=[{'kind':'dsl_candidate','candidate_id':candidate['candidate_id']}]
            if run is None:
                items.append(agenda_item('candidate_unresearched',candidate['name'],'已注册DSL候选尚无完成的单因子归档',
                    '用固定股票池/日期/口径生成研究提案；注册本身不等于Alpha',80,ref))
            elif key not in covered_keys and candidate['candidate_id'] not in factory_candidates:
                items.append(agenda_item('candidate_needs_incremental',candidate['name'],'候选已有单因子研究，但尚无完成的增量证据包/Factory覆盖',
                    '与预先指定基准和控制因子做共同样本与增量验证',72,
                    [*ref,{'kind':'experiment','run_id':run['run_id']}]))
        return items
    def _factory_items(self):
        items=[];service=AlphaFactoryService(self.output,self.data_root);rows=service.list()
        for state in rows['factories'][:100]:
            ref=[{'kind':'alpha_factory','proposal_id':state['proposal_id']}]
            if state['status']=='pending':
                items.append(agenda_item('factory_approval',state['prepared']['plan']['name'],'固定Alpha Factory等待人工批准',
                    '核对冻结候选、样本、测试族和筛选规则后决定是否提交',94,ref))
            elif state['status'] in ('admitting','submitted','running'):
                items.append(agenda_item('factory_running',state['prepared']['plan']['name'],'Alpha Factory已有批准任务尚未完成收口',
                    '等待原任务终态后同步Factory；不要另开重复Factory',55,ref))
            elif state['status']=='completed':
                promoted={r['candidate_id'] for r in state.get('promotions',[])}
                for cid in state.get('recommended_candidate_ids',[]):
                    if cid not in promoted:
                        items.append(agenda_item('factory_watchlist_candidate','Factory候选 '+cid[:8],
                            '候选满足本轮预先冻结的观察池规则，但尚未人工加入Watchlist',
                            '人工复核完整证据后决定是否进入观察池；不会自动授权刷新',88,
                            [*ref,{'kind':'dsl_candidate','candidate_id':cid}]))
        if rows['errors']:
            items.append(agenda_item('factory_store_error','Alpha Factory存在不可读记录',str(len(rows['errors']))+' 条记录无法解析',
                '人工核对Factory存储，不自动删除',100,[]))
        return items
    def _incremental_items(self):
        items=[];rows=IncrementalEvidenceService(self.output).list()
        for state in rows['proposals'][:100]:
            if state['status']=='pending':
                items.append(agenda_item('incremental_approval','候选增量证据包',
                    '固定增量证据计划等待宿主确认','核对候选、控制因子、训练截止和检验族后决定是否执行',90,
                    [{'kind':'proposal','proposal_id':state['proposal_id']}]))
            elif state['status']=='running':
                items.append(agenda_item('incremental_running','候选增量证据包','证据包处于运行/恢复状态',
                    '优先收口原证据包，不按结果另起重复测试',50,[{'kind':'proposal','proposal_id':state['proposal_id']}]))
        if rows['errors']:
            items.append(agenda_item('incremental_store_error','增量证据存在不可读记录',str(len(rows['errors']))+' 条记录无法解析',
                '人工核对证据包存储',100,[]))
        return items

    def build(self,limit=20):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Agenda limit须为1–100')
        items=[]
        for producer in (self._watch_items,self._factory_items,self._incremental_items,
                self._candidate_items,self._job_items,self._memory_items):
            items.extend(producer())
        unique={row['agenda_id']:row for row in items}
        ordered=sorted(unique.values(),key=lambda r:(-r['priority'],r['kind'],r['agenda_id']))
        counts={}
        for row in ordered:counts[row['kind']]=counts.get(row['kind'],0)+1
        return {'generated_at':now(),'items':ordered[:limit],'total':len(ordered),'counts':counts,
            'new_research_jobs':0,'automatic_execution':False,
            'limitations':['Agenda只从当前工作空间持久化证据生成待办，不调用模型、不下载数据、不运行研究。',
                '优先级是确定性工作流排序，不是收益预测或投资建议。',
                '主动研究仍须通过原提案/Factory人工批准边界。']}
