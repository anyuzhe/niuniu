"""Read-only imported-data tools; downloading remains an explicit host action."""
import json
from pathlib import Path
import polars as pl
from quantlab.agent.theme_tools import ThemeResearchAPI
from quantlab.agent.catalog import schema,TEXT,LIMIT,OFFSET,compact
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest,read_table,responses,read_dataset_bytes
from quantlab.agent.refresh_readiness import watch_readiness
from quantlab.storage.codec import encode
from quantlab.trading.market_snapshot import MarketSnapshotError,MarketSnapshotStore

TOOLS=[
    schema('list_baostock_series','只读查询人工建立的数据更新通道；不接入批次或授权研究。',{'offset':OFFSET,'limit':LIMIT}),
    schema('get_baostock_series','读取通道发布链和当前批次身份；只核对发布记录，不认证全部数据文件或PIT。',{'series_id':TEXT}),
    schema('compare_factor_candidates','只读对照两个真实单因子归档：相同数据/股票池/处理条件，在共同成熟样本比较Rank IC并单独计算因子相关性；没有显著性或Alpha认证，不创建任务。',{'candidate_run_id':TEXT,'baseline_run_id':TEXT,'horizon':{'type':'integer','minimum':1,'maximum':1000}}),
    schema('get_tracking_control','只读查询宿主预授权的自动跟踪状态、预算和应用内提醒；不启用、修改、撤销或执行任务。',{'watch_id':TEXT}),
    schema('list_baostock_imports','查询实际Baostock导入批次；失败和空响应不隐藏。不联网下载。',{'offset':OFFSET,'limit':LIMIT}),
    schema('get_baostock_import','核对一个批次的响应校验值和数据覆盖。抓取成功不等于PIT或真实交易规则认证。',{'import_id':TEXT}),
    schema('read_baostock_table','分页读取已归档数据表。table名称来自get_baostock_import，symbol留空不筛选。财报原始比例单位保持供应商口径；空值不填零。',{'import_id':TEXT,'table':TEXT,'symbol':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_watch_refresh_readiness','使用已归档完整日历和带时区as_of检查日线跟踪到期候选，不下载、不批准、不运行。',{'watch_id':TEXT,'import_id':TEXT,'as_of':TEXT}),
    schema('list_market_snapshots','只读查询Trading Desk已冻结的MarketSnapshot；不会联网刷新行情。',{'trading_day':TEXT,'frame':TEXT,'symbol':TEXT,'offset':OFFSET,'limit':LIMIT}),
    schema('get_market_snapshot','读取一个MarketSnapshot及其捕获状态、SHA256来源和证券快照。',{'snapshot_id':TEXT}),
]


class MarketDataResearchAPI(ThemeResearchAPI):
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        definition=next((t for t in TOOLS if t['name']==name),None)
        if definition is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(imported_market_data_available=True,data_download_tool=False,candidate_review_available=True,
                    calendar_readiness_available=True,controlled_tracking_available=True,managed_series_available=True,
                    market_snapshot_available=True,market_snapshot_write_model=False,
                    tracking_authorization_host_only=True,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=definition['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('字段必须与工具合同一致')
            for key,prop in props.items():
                value=arguments[key]
                valid=isinstance(value,str) and len(value)<=prop['maxLength'] if prop['type']=='string' else (
                    type(value) is int and prop['minimum']<=value<=prop['maximum'])
                if not valid:raise ValueError('参数类型或范围错误：'+key)
            refs=[]
            if name in ('list_baostock_series','get_baostock_series'):
                from quantlab.data.baostock_series import SeriesService
                service=SeriesService(self.output)
                if name=='list_baostock_series':
                    value=service.list();rows=value['series']
                    data={'series':rows[arguments['offset']:arguments['offset']+arguments['limit']],'total':len(rows),'errors':value['errors']}
                else:
                    state=service.get(arguments['series_id'])
                    data={**state,'history':state['history'][-20:],'history_omitted':max(0,len(state['history'])-20),'publication_record_verified':True,'source_files_verified':False}
                    refs=[{'kind':'market_data','import_id':state['history'][-1]['delivery']['import_id']}]
            elif name=='compare_factor_candidates':
                from quantlab.agent.candidate_review import compare_candidate
                data=compare_candidate(self.output,**arguments)
                refs=[{'kind':'experiment','run_id':arguments[key]} for key in ('candidate_run_id','baseline_run_id')]
            elif name=='get_tracking_control':
                from quantlab.agent.tracking_control_store import ControlStore,control_summary
                data=control_summary(ControlStore(self.output).get(arguments['watch_id']))
                refs=[{'kind':'watch','watch_id':arguments['watch_id']}]
            elif name=='list_baostock_imports':
                rows=[];unreadable=0;root=self.output/'_market_data'/'baostock'
                for path in root.glob('*/manifest.json'):
                    try:
                        _,m=load_import(self.output,path.parent.name)
                        row={k:m.get(k) for k in ('import_id','status','created_at','dataset_ready')}
                        row['dataset']={k:v for k,v in (m.get('dataset') or {}).items() if k in ('ready','calendar_ready','tables')}
                        rows.append(row)
                    except (ValueError,OSError,TypeError):unreadable+=1
                rows.sort(key=lambda r:r.get('created_at') or '',reverse=True)
                selected=rows[arguments['offset']:arguments['offset']+arguments['limit']]
                data={'imports':selected,'total':len(rows),'unreadable':unreadable}
                refs=[{'kind':'market_data','import_id':r['import_id']} for r in selected]
            elif name=='get_watch_refresh_readiness':
                data=watch_readiness(self.output,**arguments)
                refs=[{'kind':'watch','watch_id':arguments['watch_id']}]
            elif name=='list_market_snapshots':
                data=MarketSnapshotStore(self.output).list(trading_day=arguments['trading_day'],frame=arguments['frame'],
                    symbol=arguments['symbol'],offset=arguments['offset'],limit=arguments['limit'])
                refs=[{'kind':'market_snapshot','snapshot_id':r['snapshot_id']} for r in data['records']]
            elif name=='get_market_snapshot':
                data=MarketSnapshotStore(self.output).get(arguments['snapshot_id'])
                refs=[{'kind':'market_snapshot','snapshot_id':data['snapshot_id']}]
            else:
                directory,m=load_import(self.output,arguments['import_id'])
                refs=[{'kind':'market_data','import_id':arguments['import_id']}]
                if name=='get_baostock_import':
                    counts={};verified=0
                    for entry,record in responses(directory,m):
                        verified+=1;item=counts.setdefault(entry['kind'],{'queries':0,'received':0,'no_data':0,'failed':0,'rows':0})
                        item['queries']+=1;item[entry['status']]+=1;item['rows']+=entry['rows']
                    data={k:v for k,v in m.items() if k!='responses'}
                    data.update(verified_responses=verified,response_summary=counts)
                    if m.get('dataset_ready'):
                        ds,_=dataset_manifest(directory/'dataset')
                        for relative in ds['files']:read_dataset_bytes(directory/'dataset',relative,ds)
                        data['verified_dataset_files']=len(ds['files'])
                        data['dataset_fingerprint']=ds['checksum']
                else:
                    frame=read_table(directory/'dataset',arguments['table'])
                    if arguments['symbol']:
                        if 'code' not in frame.columns:raise ValueError('本表没有证券列，不能指定symbol')
                        frame=frame.filter(pl.col('code')==arguments['symbol'])
                    page=frame.slice(arguments['offset'],arguments['limit'])
                    data={'table':arguments['table'],'columns':page.columns,'rows':page.to_dicts(),
                        'total':frame.height,'offset':arguments['offset'],'historical_available_at_verified':False}
            result={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['数据采集日期不是历史首次可用日期；不提供严格PIT、真实每日市值或官方价格限制认证。'],'error':None}
            if len(encode(result))>24000:result['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(result))
        except (ValueError,TypeError,KeyError,OSError,MarketSnapshotError,pl.exceptions.PolarsError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'MARKET_DATA_READ_FAILED','message':str(error)[:240]}}


if __name__=='__main__':
    import argparse
    from quantlab.agent.model_config import strict_json
    parser=argparse.ArgumentParser(description='已导入的Baostock资料与跟踪日历查询，不联网下载')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root')
    parser.add_argument('--call',default='get_capabilities');parser.add_argument('--arguments',default='{}')
    args=parser.parse_args()
    result=MarketDataResearchAPI(args.output,args.data_root).call(args.call,strict_json(args.arguments))
    print(encode(result));raise SystemExit(0 if result['ok'] else 2)
