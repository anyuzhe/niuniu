"""Chief-facing peer-review proposal tools; model cannot launch external reviewers."""
import json
from uuid import UUID,uuid5

from quantlab.agent.catalog import schema,TEXT,LIMIT,OFFSET,compact
from quantlab.agent.peer_review import PeerReviewService,normalize_spec
from quantlab.agent.model_config import ModelError
from quantlab.agent.theme_tools import ThemeResearchAPI
from quantlab.storage.codec import digest,encode

JSON_TEXT={'type':'string','maxLength':24000}
TOOLS=[
    schema('preview_peer_review','预检有限同行复核：冻结问题、Reviewer、两轮上限和Git-first记忆版本；不调用任何模型。',{'request_json':JSON_TEXT}),
    schema('propose_peer_review','保存一个pending同行复核请求；不会调用Reviewer，须在宿主AI Team面板启动。',{'request_id':TEXT,'request_json':JSON_TEXT}),
    schema('get_peer_review','读取一个同行复核任务状态和已保存输出；只读。',{'task_id':TEXT}),
    schema('list_peer_reviews','列出同行复核任务；只读。',{'offset':OFFSET,'limit':LIMIT}),
]


def parse_request(text):
    value=json.loads(text)
    return normalize_spec(value)


class PeerReviewResearchAPI(ThemeResearchAPI):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root);self.peer_reviews=PeerReviewService(output,data_root)
    def schemas(self):return super().schemas()+json.loads(json.dumps(TOOLS,ensure_ascii=False))
    def call(self,name,arguments):
        definition=next((t for t in TOOLS if t['name']==name),None)
        if definition is None:
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(peer_review_available=True,peer_review_launch_model=False,
                    peer_review_max_rounds=2,tools=[t['name'] for t in self.schemas()])
            return result
        try:
            props=definition['parameters']['properties']
            if not isinstance(arguments,dict) or set(arguments)!=set(props):raise ValueError('Peer Review 工具字段必须与Schema一致。')
            for key,spec in props.items():
                value=arguments[key]
                valid=(isinstance(value,str) and len(value)<=spec['maxLength']) if spec['type']=='string' else (type(value) is int and spec['minimum']<=value<=spec['maximum'])
                if not valid:raise ValueError('Peer Review 工具参数无效：'+key)
            refs=[]
            if name=='preview_peer_review':data=self.peer_reviews.preview(parse_request(arguments['request_json']))
            elif name=='propose_peer_review':
                data=self.peer_reviews.propose(arguments['request_id'],parse_request(arguments['request_json']))
                refs=[{'kind':'peer_review','task_id':data['task_id']}]
            elif name=='get_peer_review':
                data=self.peer_reviews.get(arguments['task_id']);refs=[{'kind':'peer_review','task_id':data['task_id']}]
            else:
                rows=self.peer_reviews.list();selected=rows['tasks'][arguments['offset']:arguments['offset']+arguments['limit']]
                data={'tasks':selected,'total':len(rows['tasks']),'errors':rows['errors']}
                refs=[{'kind':'peer_review','task_id':r['task_id']} for r in selected]
            result={'ok':True,'tool':name,'data':compact(data),'evidence':refs,
                'warnings':['pending Peer Review 只是一项复核请求；模型不能启动 Reviewer，也不能把共识当作独立市场证据。'],'error':None}
            if len(encode(result))>24000:result['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(result))
        except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError,ModelError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'PEER_REVIEW_TOOL_FAILED','message':str(error)[:300]}}
