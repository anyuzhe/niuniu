// Local Pi ModelRuntime transport. No AgentSession, extensions, built-in tools,
// skills, project discovery or shell: Niuniu remains the only tool authority.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const lines = input[Symbol.asyncIterator]();
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const receive = async () => {
  const {value, done} = await lines.next();
  if (done) throw new Error('Host disconnected');
  if (value.length > 2000000) throw new Error('Host frame too large');
  return JSON.parse(value);
};
try {
  const cfg = await receive();
  const { ModelRuntime } = await import(pathToFileURL(process.argv[2]).href);
  const runtime = await ModelRuntime.create({ allowModelNetwork: false });
  const split = cfg.model.indexOf('/');
  const provider = cfg.model.slice(0, split), id = cfg.model.slice(split + 1);
  const model = runtime.getModel(provider, id);
  if (!model) throw new Error('Pi model not found: ' + cfg.model);
  const available = await runtime.getAvailable(provider);
  if (!available.some(m => m.id === id)) throw new Error('Pi provider is not authenticated: ' + provider);
  if (cfg.probe) {
    send({type:'result', result:{provider:'pi_sdk', model:id, pi_provider:provider, available:true}});
  } else {
    const zeroUsage = {input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
    const messages = cfg.messages.map(m => m.role === 'user'
      ? {role:'user', content:m.content, timestamp:Date.now()}
      : {role:'assistant', content:[{type:'text',text:m.content}], api:model.api, provider, model:id, usage:zeroUsage, stopReason:'stop', timestamp:Date.now()});
    const context = { systemPrompt:cfg.system, messages, tools:cfg.tools };
    let calls = 0, finished = false;
    const seen = new Set(), allowed = new Set(cfg.tools.map(t => t.name));
    const usage = {input:0, output:0, totalTokens:0};
    send({type:'identity', model:id, pi_provider:provider, builtin_tools:false, extensions:false});
    for (let round=0; round<cfg.max_rounds; round++) {
      if (JSON.stringify(context).length > cfg.max_context_chars) throw new Error('Pi context budget exhausted');
      const options = {maxTokens:cfg.max_output_tokens};
      if (cfg.effort && cfg.effort !== 'none') options.reasoning = cfg.effort;
      const response = await runtime.completeSimple(model, context, options);
      if (['error','aborted','length'].includes(response.stopReason)) throw new Error(response.errorMessage || ('Pi incomplete response: '+response.stopReason));
      if (response.provider !== provider || response.model !== id) throw new Error('Pi returned a different model identity');
      for (const k of Object.keys(usage)) usage[k] += response.usage?.[k] || 0;
      context.messages.push(response);
      const actions = response.content.filter(c => c.type === 'toolCall');
      if (!actions.length) {
        const text = response.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
        if (!text.trim()) throw new Error('Pi returned no final answer');
        send({type:'result',result:{text, provider:'pi_sdk', model:id, pi_provider:provider, tool_calls:calls, usage}});
        finished = true; break;
      }
      for (const action of actions) {
        if (!allowed.has(action.name) || seen.has(action.id)) throw new Error('Unknown or duplicate Pi tool call');
        seen.add(action.id);
        if (++calls > cfg.max_tool_calls) throw new Error('Pi tool budget exhausted');
        send({type:'tool_call',id:action.id,name:action.name,arguments:action.arguments});
        const reply = await receive();
        if (reply.type !== 'tool_result' || reply.id !== action.id) throw new Error('Mismatched host tool result');
        context.messages.push({role:'toolResult',toolCallId:action.id,toolName:action.name,
          content:[{type:'text',text:JSON.stringify(reply.result)}],isError:reply.result?.ok===false,timestamp:Date.now()});
      }
    }
    if (!finished) throw new Error('Pi round budget exhausted');
  }
  input.close();
  process.stdout.write('', () => process.exit(0));
} catch (error) {
  send({type:'error',message:String(error.message || error).slice(0,1000)});
  input.close();
  process.stdout.write('', () => process.exit(1));
}
