"""Read-only proactive research agenda for the assistant."""
import json
from quantlab.agent.catalog import schema,compact
from quantlab.agent.alpha_factory_tools import AlphaFactoryAPI
from quantlab.agent.research_agenda import ResearchAgendaService
from quantlab.storage.codec import encode

TOOL=schema('get_research_agenda','汇总当前工作空间最值得处理的研究待办：来源异常、失败任务、待审批Factory、未研究DSL、缺少增量证据和开放假设。不执行任何动作。',
    {'limit':{'type':'integer','minimum':1,'maximum':100}})


class ResearchAgendaAPI(AlphaFactoryAPI):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root);self.agenda=ResearchAgendaService(output,data_root)
    def schemas(self):return super().schemas()+[json.loads(json.dumps(TOOL,ensure_ascii=False))]
    def call(self,name,arguments):
        if name!='get_research_agenda':
            result=super().call(name,arguments)
            if name=='get_capabilities' and result.get('ok'):
                result['data'].update(research_agenda_available=True,research_agenda_read_only=True,
                    tools=[t['name'] for t in self.schemas()])
            return result
        try:
            if not isinstance(arguments,dict) or set(arguments)!={'limit'} or type(arguments['limit']) is not int or not 1<=arguments['limit']<=100:
                raise ValueError('Agenda参数无效')
            data=self.agenda.build(arguments['limit'])
            reply={'ok':True,'tool':name,'data':compact(data),'evidence':[],
                'warnings':['Agenda只是确定性待办排序；不会自动执行研究或证明Alpha。'],'error':None}
            if len(encode(reply))>32000:reply['data']={'omitted':True,'reason':'result_size_limit'}
            return json.loads(encode(reply))
        except (ValueError,TypeError,KeyError,OSError) as error:
            return {'ok':False,'tool':name,'data':None,'evidence':[],'warnings':[],
                'error':{'code':'RESEARCH_AGENDA_FAILED','message':str(error)[:300]}}
