"""Read-only AI access to host-managed Trading Knowledge / Playbook Lab evidence."""
import json

from quantlab.agent.catalog import schema, TEXT, LIMIT, OFFSET, compact
from quantlab.agent.theme_tools import ThemeResearchAPI
from quantlab.storage.codec import encode
from quantlab.trading.playbook_store import PlaybookError, PlaybookStore
from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore
from quantlab.agent.scorecard import AgentScorecardError,AgentScorecardService
from quantlab.trading.selection_outcomes import LIMITATIONS as SELECTION_OUTCOME_LIMITATIONS,SelectionOutcomeError,SelectionOutcomeService

TOOLS = [
    schema('get_playbook_overview','只读查看Playbook Lab对象数量和正式审计完成度。',{}),
    schema('list_expert_sources','只读检索高手原始来源；VERIFIED表示来源元数据和哈希完整，不代表玩法有效。',{'query':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_expert_source','读取一个ExpertSource的时间、哈希、归档引用和完整性。',{'source_id':TEXT}),
    schema('list_strategy_sources','统一只读检索交易知识来源；旧ExpertSource会投影为TRADER。',{'query':TEXT,'source_kind':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_strategy_source','读取一个StrategySource；兼容旧ExpertSource UUID。',{'strategy_source_id':TEXT}),
    schema('list_playbook_source_links','读取Playbook与StrategySource的多对多证据关系。',{'definition_id':TEXT,'strategy_source_id':TEXT,'relation':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_playbook_definition_sources','读取玩法定义及旧正式来源/新StrategySource关系。',{'definition_id':TEXT}),
    schema('list_playbook_definitions','只读检索玩法定义与冻结状态。',{'query':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_playbook_definition','读取一个版本化PlaybookDefinition。',{'definition_id':TEXT}),
    schema('list_playbook_cases','列出指定定义的历史案例；空definition_id表示全部。',{'definition_id':TEXT,'trading_day':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_playbook_case_bundle','读取案例、完整候选集、专家/系统选择和来源。',{'case_id':TEXT}),
    schema('list_playbook_validations','列出玩法验证记录；不会把描述性重建称为Alpha。',{'definition_id':TEXT,'method':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_playbook_validation','读取选择匹配、PIT和执行审计状态。',{'validation_id':TEXT}),
    schema('get_symbol_playbook_history','查询股票历史进入哪些候选集、何时被选或未选。',{'symbol':TEXT}),
    schema('list_market_snapshots','只读查询已冻结MarketSnapshot；不会联网刷新行情。',{'trading_day':TEXT,'frame':TEXT,'symbol':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_market_snapshot','读取一个不可变MarketSnapshot及其捕获/PIT状态。',{'snapshot_id':TEXT}),
    schema('get_agent_scorecard','只读查看按任务类型分离的Agent Scorecard；不产生模型总分，也不自动调权。',{}),
    schema('get_selection_outcome_summary','只读查看Playbook选择结果对照：同一冻结候选集内“选中−未选中”信号收益差，按玩法版本/kind/Frame/窗口分开；描述性观察，不是Alpha或可成交收益，不自动调权。空字符串表示不筛选。',{'definition_id':TEXT,'kind':TEXT,'frame':TEXT}),
    schema('list_selection_outcome_reviews','列出已冻结的逐次选择结果复盘（不含逐证券明细）；可用于找出“未选中却跑赢”的样本再人工/研究核对。',{'definition_id':TEXT,'kind':TEXT,'frame':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_selection_outcome_review','读取一次选择全部已冻结窗口的分组统计、差值与两侧极端样本；宿主CLI可导出逐证券明细。',{'selection_id':TEXT}),
]

SELECTION_OUTCOME_TOOLS=('get_selection_outcome_summary','list_selection_outcome_reviews','get_selection_outcome_review')


def _selection_outcome_view(row):
    view={k:v for k,v in SelectionOutcomeService.compact(row).items() if k not in ('limitations','policy','daily_market_snapshots')}
    view['daily_market_snapshot_ids']=[item['snapshot_id'] for item in row.get('daily_market_snapshots',[])]
    for key in ('unselected_above_selected_mean','selected_below_unselected_mean'):
        view[key]=view.get(key,[])[:10]
    return view


class PlaybookResearchAPI(ThemeResearchAPI):
    def schemas(self):
        return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))

    @staticmethod
    def _validate(definition, arguments):
        props=definition['parameters']['properties']
        if not isinstance(arguments,dict) or set(arguments)!=set(props):
            raise ValueError('Playbook 工具字段必须与 Schema 一致。')
        for key,spec in props.items():
            value=arguments[key]
            if spec['type']=='string':valid=isinstance(value,str) and len(value)<=spec['maxLength']
            else:valid=type(value) is int and spec['minimum']<=value<=spec['maximum']
            if not valid:raise ValueError('Playbook 工具参数无效：'+key)

    def call(self,name,arguments):
        definition=next((tool for tool in TOOLS if tool['name']==name),None)
        if definition is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(playbook_lab_available=True,playbook_write_model=False,
                    strategy_source_available=True,strategy_source_write_model=False,
                    market_snapshot_available=True,market_snapshot_write_model=False,
                    agent_scorecard_available=True,agent_scorecard_write_model=False,
                    agent_scorecard_composite_score=False,
                    selection_outcome_available=True,selection_outcome_write_model=False,
                    selection_outcome_auto_reweighting=False,
                    tools=[tool['name'] for tool in self.schemas()])
            return result
        try:
            self._validate(definition,arguments);store=PlaybookStore(self.output);refs=[]
            if name=='get_playbook_overview':data=store.overview()
            elif name=='list_expert_sources':
                data=store.list_sources(query=arguments['query'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'expert_source','source_id':row['source_id']} for row in data['records']]
            elif name=='get_expert_source':
                data=store.get_source(arguments['source_id']);refs=[{'kind':'expert_source','source_id':data['source_id']}]
            elif name=='list_strategy_sources':
                data=store.list_strategy_sources(query=arguments['query'],source_kind=arguments['source_kind'],
                    offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'strategy_source','strategy_source_id':row['strategy_source_id']} for row in data['records']]
            elif name=='get_strategy_source':
                data=store.get_strategy_source(arguments['strategy_source_id'])
                refs=[{'kind':'strategy_source','strategy_source_id':data['strategy_source_id']}]
            elif name=='list_playbook_source_links':
                data=store.list_source_links(definition_id=arguments['definition_id'],strategy_source_id=arguments['strategy_source_id'],
                    relation=arguments['relation'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'playbook_source_link','link_id':row['link_id']} for row in data['records']]
            elif name=='get_playbook_definition_sources':
                data=store.definition_source_bundle(arguments['definition_id'])
                refs=[{'kind':'playbook_definition','definition_id':arguments['definition_id']}]
                refs.extend({'kind':'strategy_source','strategy_source_id':item['source']['strategy_source_id']}
                    for item in data['strategy_source_links'])
            elif name=='list_playbook_definitions':
                data=store.list_definitions(query=arguments['query'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'playbook_definition','definition_id':row['definition_id']} for row in data['records']]
            elif name=='get_playbook_definition':
                data=store.get_definition(arguments['definition_id']);refs=[{'kind':'playbook_definition','definition_id':data['definition_id']}]
            elif name=='list_playbook_cases':
                data=store.list_cases(definition_id=arguments['definition_id'],trading_day=arguments['trading_day'],
                    offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'playbook_case','case_id':row['case_id']} for row in data['records']]
            elif name=='get_playbook_case_bundle':
                data=store.case_bundle(arguments['case_id']);refs=[{'kind':'playbook_case','case_id':arguments['case_id']}]
            elif name=='list_playbook_validations':
                data=store.list_validations(definition_id=arguments['definition_id'],method=arguments['method'],
                    offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'playbook_validation','validation_id':row['validation_id']} for row in data['records']]
            elif name=='get_playbook_validation':
                data=store.get_validation(arguments['validation_id'])
                refs=[{'kind':'playbook_validation','validation_id':data['validation_id']}]
            elif name=='list_market_snapshots':
                snapshots=MarketSnapshotStore(self.output)
                data=snapshots.list(trading_day=arguments['trading_day'],frame=arguments['frame'],
                    symbol=arguments['symbol'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'market_snapshot','snapshot_id':row['snapshot_id']} for row in data['records']]
            elif name=='get_market_snapshot':
                data=MarketSnapshotStore(self.output).get(arguments['snapshot_id'])
                refs=[{'kind':'market_snapshot','snapshot_id':data['snapshot_id']}]
            elif name=='get_agent_scorecard':
                data=AgentScorecardService(self.output).build()
            elif name in SELECTION_OUTCOME_TOOLS:
                outcomes=SelectionOutcomeService(self.output)
                if name=='get_selection_outcome_summary':
                    data=outcomes.summary(arguments['definition_id'],arguments['kind'],arguments['frame'])
                    data.pop('limitations',None)
                elif name=='list_selection_outcome_reviews':
                    listed=outcomes.list(arguments['definition_id'],arguments['kind'],arguments['frame'],
                        offset=arguments['offset'],limit=arguments['limit'])
                    data={'total':listed['total'],'records':[_selection_outcome_view(row) for row in listed['records']],
                        'errors':listed['errors'],'incomplete':listed['incomplete']}
                    refs=[{'kind':'playbook_selection','selection_id':row['selection_id']} for row in listed['records']]
                else:
                    got=outcomes.get(arguments['selection_id'])
                    data={'selection_id':got['selection_id'],'records':[_selection_outcome_view(row) for row in got['records']],
                        'errors':got['errors'],'incomplete':got['incomplete']}
                    refs=[{'kind':'playbook_selection','selection_id':got['selection_id']}]
                archive_warnings=(['选择结果复盘归档不完整：data.errors 中的坏记录未进入当前列表/汇总，不能把剩余统计当作完整样本。']
                    if data.get('incomplete') else [])
                reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                    'warnings':['选中/未选中信号收益对照只是选择诊断：不是可成交收益或Alpha；未选中跑赢不等于当时应当选中；不自动调权，不写Decision/Intent/Paper。',
                        *archive_warnings,*SELECTION_OUTCOME_LIMITATIONS[:3]],'error':None}
                if len(encode(reply))>24000:
                    reply['data']={'omitted':True,'reason':'result_size_limit'}
                return json.loads(encode(reply))
            else:
                data={'symbol':arguments['symbol'],'records':store.symbol_history(arguments['symbol'])}
                refs=[{'kind':'playbook_case','case_id':row['case_id']} for row in data['records']]
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['Playbook命中/选择匹配不是盈利证明；必须同时检查候选全集、PIT、来源和执行审计。'],'error':None}
            if len(encode(reply))>24000:
                reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (PlaybookError,MarketSnapshotError,AgentScorecardError,SelectionOutcomeError,OSError,ValueError,TypeError,KeyError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'PLAYBOOK_READ_FAILED','message':str(error)[:300]}}


__all__=['PlaybookResearchAPI']
