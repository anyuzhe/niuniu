export class ModelRuntime {
  static async create(){return new ModelRuntime();}
  getModel(provider,id){return id==='absent'?undefined:{provider,id,api:'fake'};}
  async getAvailable(){return [{id:'unit'}];}
  async completeSimple(model,context,options){
    const mode=context.systemPrompt.match(/SCENARIO:([a-z_]+)/)?.[1] || 'normal';
    const trace=process.env.PI_FAKE_TRACE;
    if(trace) await import('node:fs/promises').then(fs=>fs.appendFile(trace,JSON.stringify({mode,tools:context.tools.length,messages:context.messages})+'\n'));
    this.n=(this.n||0)+1;
    const call=(id,name='echo')=>({type:'toolCall',id,name,arguments:{value:id}});
    const result=(content,stopReason='stop')=>({role:'assistant',provider:model.provider,model:model.id,api:'fake',usage:{input:2,output:3,totalTokens:5},timestamp:Date.now(),stopReason,content});
    const hasToolResult=context.messages.some(m=>m.role==='toolResult');
    if(mode==='unknown' && this.n===1)return result([call('bad','bash')]);
    if(mode==='duplicate_batch' && this.n===1)return result([call('same'),call('same')]);
    if(mode==='multi' && this.n===1)return result([call('one'),call('two')]);
    if(mode==='once' && this.n===1)return result([call('once')]);
    if(mode==='host_context' && this.n===1)return result([call('host')]);
    if(mode==='host_failure' && this.n===1)return result([call('host')]);
    if(mode==='context_overflow' && this.n===1)return result([call('huge')]);
    if(mode==='ignore' && context.tools.length===0)return result([call('ignored')]);
    if(mode==='empty' && context.tools.length===0)return result([]);
    if(context.tools.length===0)return result([{type:'text',text: mode==='normal'?'completed normally':'summarized existing evidence; incomplete items remain'}]);
    if(hasToolResult)return result([{type:'text',text:'summarized existing evidence; incomplete items remain'}]);
    return result([{type:'text',text:'completed normally'}]);
  }
}
