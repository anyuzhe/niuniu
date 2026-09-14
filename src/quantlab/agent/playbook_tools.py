"""Read-only AI access to host-managed Trading Knowledge / Playbook Lab evidence."""
import json

from quantlab.agent.catalog import schema, TEXT, LIMIT, OFFSET, compact
from quantlab.agent.theme_tools import ThemeResearchAPI
from quantlab.storage.codec import encode
from quantlab.trading.playbook_store import PlaybookError, PlaybookStore
from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore

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
]


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
            else:
                data={'symbol':arguments['symbol'],'records':store.symbol_history(arguments['symbol'])}
                refs=[{'kind':'playbook_case','case_id':row['case_id']} for row in data['records']]
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['Playbook命中/选择匹配不是盈利证明；必须同时检查候选全集、PIT、来源和执行审计。'],'error':None}
            if len(encode(reply))>24000:
                reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (PlaybookError,MarketSnapshotError,OSError,ValueError,TypeError,KeyError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'PLAYBOOK_READ_FAILED','message':str(error)[:300]}}


__all__=['PlaybookResearchAPI']
