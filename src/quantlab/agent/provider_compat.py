"""Adapters for the first P1B interface; all requests use one provider engine."""

def legacy_event(emit,kind,value):
    if kind=='text_delta':emit('delta',value['text'])
    elif kind=='connection':emit('model',value)
    elif kind=='tool_call':emit('tool_start',value)
    else:emit(kind,value)


class CompletionProtocol:
    def complete(self,messages,tools,invoke,emit,stop):
        system='\n'.join(m['content'] for m in messages if m.get('role')=='system')
        conversation=[m for m in messages if m.get('role')!='system']
        return self.run(system,conversation,tools,lambda name,args,call_id:invoke(name,args),
            lambda kind,value:legacy_event(emit,kind,value),stop)


class CompleteAdapter:
    def __init__(self,provider):self.provider=provider
    def run(self,system,messages,tools,dispatch,emit,stop):
        counter=0
        def invoke(name,args):
            nonlocal counter
            counter+=1;return dispatch(name,args,str(counter))
        def forward(kind,value):
            if kind=='delta':emit('text_delta',{'text':value})
            elif kind=='model':emit('connection',value)
            else:emit(kind,value)
        return self.provider.complete([{'role':'system','content':system},*messages],tools,invoke,forward,stop)
