"""Read-only agent access to human-managed factor watches."""
import json
import polars as pl
from quantlab.agent.catalog import schema, TEXT, LIMIT, OFFSET, compact
from quantlab.agent.agenda_tools import ResearchAgendaAPI
from quantlab.agent.watchlist import WatchService
from quantlab.storage.codec import encode

TOOLS = [
    schema('list_factor_watches','查询人工建立的因子跟踪池；不创建、刷新、批准或调度研究。',
        {'query':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_factor_watch','读取跟踪快照、水位、历史修订及Sequential Monitor。序贯证据仅相对冻结经验基线，不等于未来Alpha认证。',
        {'watch_id':TEXT}),
]


class WatchResearchAPI(ResearchAgendaAPI):
    def schemas(self): return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self, name, arguments):
        tool = next((t for t in TOOLS if t['name']==name),None)
        if tool is None:
            result = super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(version='1.7',watchlist_available=True,sequential_watch_monitor_available=True,
                    automatic_tracking=False,host_authorized_tracking_available=True,tracking_daemon_available=True,
                    watch_refresh_requires_host_approval=True,model_can_authorize_tracking=False,
                    tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props = tool['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):
                raise ValueError('Watch tool arguments differ from the schema')
            for key, prop in props.items():
                value = arguments[key]
                valid = isinstance(value,str) and len(value)<=prop['maxLength'] if prop['type']=='string' else (
                    type(value) is int and prop['minimum']<=value<=prop['maximum'])
                if not valid: raise ValueError('Invalid watch argument: '+key)
            service = WatchService(self.output,self.data_root)
            if name=='list_factor_watches':
                result = service.store.list(); query = arguments['query'].casefold()
                rows = [r for r in result['watches'] if query in encode(r).casefold()]
                selected = rows[arguments['offset']:arguments['offset']+arguments['limit']]
                data = {'watches':selected,'total':len(rows),'unreadable':result['unreadable']}
                refs = [{'kind':'watch','watch_id':r['watch_id']} for r in selected]
            else:
                data = watch_summary(service.get(arguments['watch_id']))
                refs = [{'kind':'watch','watch_id':arguments['watch_id']}]
                if data['latest'] and data['source_integrity']=='verified':
                    refs.append({'kind':'experiment','run_id':data['latest']['source_run_id']})
            reply = {'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['调度授权状态见返回记录；Sequential Monitor只对冻结经验基线做重复查看控制，不认证未来Alpha、不自动停用因子。'],'error':None}
            if len(encode(reply))>24000:
                reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (OSError,ValueError,TypeError,KeyError,pl.exceptions.PolarsError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'WATCH_READ_FAILED','message':str(error)[:240]}}


def watch_summary(value):
    """Keep all window/horizon diagnostics, page large symbol watermarks."""
    result = {k:v for k,v in value.items() if k not in ('latest','definition')}
    d = value['definition']; cfg = d['rule']['config']
    result['definition'] = {k:d[k] for k in ('watch_id','name','base_run_id','windows','min_dates')}
    result['definition'].update(factor_id=cfg['factor_id'],factor_version=cfg['factor_version'],
        parameters=cfg['parameters'],data=cfg['data'],adjustment=d['rule']['adjustment'])
    if value['latest']:
        s = value['latest']; p = s['preview']
        result['latest'] = {k:s[k] for k in ('snapshot_id','source_run_id','change','baseline_differences','alerts')}
        result['latest']['sequential_monitor']=s.get('sequential_monitor',{'status':'LEGACY_NOT_CONFIGURED'})
        summary = {k:p[k] for k in ('as_of','bars','factor_rows','weighting')}
        summary['watermarks'] = dict(list(p['watermarks'].items())[:20])
        summary['watermarks_omitted'] = max(0,len(p['watermarks'])-20)
        summary['windows'] = {}
        for window, item in p['windows'].items():
            row = {k:v for k,v in item.items() if k!='horizons'}; row['horizons'] = {}
            for h, entry in item['horizons'].items():
                row['horizons'][h] = {k:v for k,v in entry.items() if k!='metrics'}
                row['horizons'][h].update({k:entry['metrics'].get(k) for k in (
                    'rank_ic','ic','rank_icir','mean_forward_return','long_short_spread')})
            summary['windows'][window] = row
        result['latest']['preview'] = summary
    else: result['latest'] = None
    return result
