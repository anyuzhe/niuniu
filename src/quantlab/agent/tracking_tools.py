"""Expose only a read-only maturation preview to the research assistant."""
import json
import polars as pl
from quantlab.agent.campaign_tools import ResearchCampaignAPI
from quantlab.agent.catalog import schema,TEXT,compact
from quantlab.agent.model_config import strict_json,ModelError
from quantlab.agent.tracking_preview import tracking_preview
from quantlab.storage.codec import encode

TOOL=schema('get_tracking_preview',
    '只读计算已完成单因子归档的成熟标签和近期窗口指标。as_of为带时区截止时间；windows_json如[20,60,120]，按已观察交易日期。min_dates为最少有效IC日期。不会创建跟踪池、运行新研究或启动定时任务。',
    {'run_id':TEXT,'as_of':{'type':'string','maxLength':100},
     'windows_json':{'type':'string','maxLength':120},'min_dates':{'type':'integer','minimum':1,'maximum':1000}})


class TrackingResearchAPI(ResearchCampaignAPI):
    def schemas(self):return super().schemas()+[json.loads(json.dumps(TOOL,ensure_ascii=False))]
    def call(self,name,arguments):
        if name!='get_tracking_preview':
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(version='1.4',tracking_preview_available=True,
                    watchlist_available=False,automatic_tracking=False,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=TOOL['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('字段必须与工具合同一致')
            for key,spec in props.items():
                value=arguments[key]
                valid=(isinstance(value,str) and len(value)<=spec['maxLength']) if spec['type']=='string' else (
                    type(value) is int and spec['minimum']<=value<=spec['maximum'])
                if not valid:raise ValueError('参数类型或范围无效：'+key)
            data=tracking_preview(self.output,arguments['run_id'],arguments['as_of'],
                strict_json(arguments['windows_json']),arguments['min_dates'])
            result={'ok':True,'tool':name,'data':compact(data),
                'evidence':[{'kind':'experiment','run_id':arguments['run_id']}],
                'warnings':['只读标签成熟预览；不是自动追踪、因子重新计算或新回测。'],'error':None}
            if len(encode(result))>24000:
                result['data']={'source_run_id':arguments['run_id'],'omitted':True,'reason':'result_size_limit'}
                result['warnings'].append('摘要过大，请减少窗口数量。')
            return json.loads(encode(result))
        except (ValueError,TypeError,KeyError,OSError,ModelError,pl.exceptions.PolarsError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'TRACKING_PREVIEW_FAILED','message':str(error)[:240]}}
