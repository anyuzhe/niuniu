"""Read-only model access to host-managed A-share Theme Matrix snapshots."""
import json
from quantlab.agent.catalog import schema,TEXT,LIMIT,OFFSET,compact
from quantlab.agent.watch_tools import WatchResearchAPI
from quantlab.storage.codec import encode
from quantlab.trading.theme_store import ThemeStore,ThemeError

TOOLS=[
    schema('list_theme_snapshots','只读查询正式Theme Snapshot；没有记录表示未知，不从Decision标签推导主线强弱。',{'query':TEXT,'start':TEXT,'end':TEXT,'frame':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_theme_snapshot','读取一个正式Theme Snapshot的市场事实、Machine Rule、量化证据、AI判断和风险复核。只读。',{'snapshot_id':TEXT}),
]


class ThemeResearchAPI(WatchResearchAPI):
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        definition=next((tool for tool in TOOLS if tool['name']==name),None)
        if definition is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(theme_matrix_available=True,theme_snapshot_write_model=False,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=definition['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('Theme工具字段必须与Schema一致。')
            for key,prop in props.items():
                value=arguments[key]
                valid=isinstance(value,str) and len(value)<=prop['maxLength'] if prop['type']=='string' else type(value) is int and prop['minimum']<=value<=prop['maximum']
                if not valid:raise ValueError('Theme工具参数无效：'+key)
            store=ThemeStore(self.output);refs=[]
            if name=='list_theme_snapshots':
                data=store.list(query=arguments['query'],start=arguments['start'],end=arguments['end'],frame=arguments['frame'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'theme_snapshot','snapshot_id':r['snapshot_id']} for r in data['records']]
            else:
                data=store.get(arguments['snapshot_id']);refs=[{'kind':'theme_snapshot','snapshot_id':data['snapshot_id']}]
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['Theme Snapshot 是宿主保存的研究/交易判断记录；UNKNOWN或缺记录不得被解释为看多/看空。'],'error':None}
            if len(encode(reply))>24000:reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (ThemeError,OSError,ValueError,TypeError,KeyError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'THEME_READ_FAILED','message':str(error)[:240]}}
