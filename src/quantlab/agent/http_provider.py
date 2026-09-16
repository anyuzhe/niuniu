"""Configurable HTTP model protocols; no OAuth extraction or automatic redirects."""
import json
import os
import time
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from quantlab.agent.model_config import ModelError,ChatStopped,strict_json


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


from quantlab.agent.provider_compat import CompletionProtocol,tool_budget_result


class HTTPProvider(CompletionProtocol):
    def __init__(self,config,api_key=''):
        self.config=config;self.key=api_key or os.environ.get(config.api_key_env,'')
        if any(ord(c)<32 for c in self.key):raise ModelError('密钥含无效控制字符')
    def request(self,path,payload,timeout):
        headers={'Accept':'application/json','Content-Type':'application/json'}
        if self.key:headers['Authorization']='Bearer '+self.key
        data=None if payload is None else json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if data and len(data)>1_000_000:raise ModelError('模型请求体超过预算')
        req=Request(self.config.base_url.rstrip('/')+path,data=data,headers=headers,
            method='GET' if data is None else 'POST')
        try:
            with build_opener(NoRedirect()).open(req,timeout=timeout) as response:
                raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ModelError('模型响应过大')
            value=strict_json(raw.decode('utf-8'))
            if not isinstance(value,dict):raise ModelError('模型响应必须是 JSON 对象')
            return value
        except HTTPError as exc:raise ModelError('模型接口 HTTP '+str(exc.code)+'；请核对地址、模型权限和密钥') from None
        except (URLError,TimeoutError,OSError):raise ModelError('模型连接超时或网络不可用') from None
        except (ValueError,UnicodeError):raise ModelError('模型接口返回无效 JSON') from None
    def probe(self,stop=None):
        result=self.request('/models',None,self.config.timeout_seconds)
        return {'provider':self.config.provider,'models':[{'id':m['id'],'model':m['id']}
            for m in result.get('data',[])[:100] if isinstance(m,dict) and isinstance(m.get('id'),str)],
            'has_more':len(result.get('data',[]))>100,'warnings':['模型目录可读取不代表所选模型已完成生成验证。']}
    def run(self,system,messages,tools,dispatch,emit,stop):
        cfg=self.config;responses=cfg.provider=='responses';deadline=time.monotonic()+cfg.timeout_seconds
        wire=([{'role':'system','content':system}] if not responses else [])+list(messages)
        calls=0;seen=set();rounds=0;synthesis_only=False
        while rounds<cfg.max_rounds or synthesis_only:
            this_synthesis=synthesis_only;synthesis_only=False;rounds+=1
            if stop.is_set():raise ChatStopped('已停止助手；未取消研究任务')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ModelError('模型请求达到本轮时限')
            if len(json.dumps(wire,ensure_ascii=False))>cfg.max_context_chars:
                raise ModelError('工具结果与会话已超过上下文预算，请新建对话或提高预算')
            payload={'model':cfg.model,'stream':False}
            if responses:
                payload.update(instructions=system,input=wire,store=False,max_output_tokens=cfg.max_output_tokens,
                    tools=[] if this_synthesis else [{'type':'function',**t,'strict':True} for t in tools])
                if cfg.effort:payload['reasoning']={'effort':cfg.effort}
            else:
                payload.update(messages=wire,max_completion_tokens=cfg.max_output_tokens,
                    tools=[] if this_synthesis else [{'type':'function','function':{**t,'strict':True}} for t in tools])
                if cfg.effort:payload['reasoning_effort']=cfg.effort
            result=self.request('/responses' if responses else '/chat/completions',payload,remaining)
            if stop.is_set():raise ChatStopped('请求已返回，助手已停止；不再执行工具')
            if responses:
                if result.get('status') not in (None,'completed'):raise ModelError('模型响应未完整完成')
                items=result.get('output',[]);wire.extend(items)
                pending=[i for i in items if i.get('type')=='function_call']
                text='\n'.join(c.get('text','') for item in items if item.get('type')=='message'
                    for c in item.get('content',[]) if c.get('type')=='output_text')
                actions=[(p.get('call_id'),p.get('name'),p.get('arguments')) for p in pending]
            else:
                choices=result.get('choices',[])
                if not choices:raise ModelError('模型没有返回回答')
                if choices[0].get('finish_reason') not in ('stop','tool_calls',None):raise ModelError('模型回答截断或未正常结束')
                item=choices[0]['message'];wire.append(item);text=item.get('content') or ''
                actions=[(p.get('id'),p.get('function',{}).get('name'),p.get('function',{}).get('arguments'))
                    for p in item.get('tool_calls',[])]
            if this_synthesis and actions:
                raise ModelError('模型在工具预算用尽后的收尾阶段仍请求工具')
            blocked=False
            for call_id,name,arguments in actions:
                if not isinstance(call_id,str) or call_id in seen:raise ModelError('无效或重复工具调用编号')
                seen.add(call_id);parsed=strict_json(arguments) if isinstance(arguments,str) else arguments
                if calls>=cfg.max_tool_calls:
                    blocked=True;value=tool_budget_result(name,cfg.max_tool_calls)
                    emit('tool_call',{'name':name,'arguments':parsed,'call_id':call_id})
                    emit('tool_result',{'name':name,'call_id':call_id,'result':value})
                else:
                    calls+=1;value=dispatch(name,parsed,call_id)
                encoded=json.dumps(value,ensure_ascii=False,allow_nan=False)
                wire.append({'type':'function_call_output','call_id':call_id,'output':encoded} if responses else
                    {'role':'tool','tool_call_id':call_id,'content':encoded})
            if blocked:
                synthesis_only=True;continue
            if not actions:
                if not isinstance(text,str) or not text.strip():raise ModelError('模型没有返回最终文本')
                if len(text)>cfg.max_output_tokens*8:raise ModelError('模型回复超过文本预算')
                emit('text_delta',{'text':text})
                return {'text':text,'provider':cfg.provider,'model':result.get('model',cfg.model),
                    'tool_calls':calls,'usage':result.get('usage',{})}
        raise ModelError('已达到本轮模型往返轮数预算；已完成的工具记录保留')
