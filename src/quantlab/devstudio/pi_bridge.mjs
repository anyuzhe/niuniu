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
const budgetText = reason => `\n\n[Pi budget stop: ${reason}]\n\n预算已到，以下为宿主确定性停止说明（不是研究结论）：请将当前状态标记为未完成/需跟进；只保留已实际取得的证据，并明确列出未完成项。不得推断或编造研究数值，不得批准、提交或写入 finding。可从本次已有证据恢复后续工作。`;
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
    let calls = 0, finished = false, stopReason = null;
    const seen = new Set(), allowed = new Set(cfg.tools.map(t => t.name));
    const usage = {input:0, output:0, totalTokens:0};
    const complete = (text, termination, reason=null) => send({type:'result',result:{text,provider:'pi_sdk',model:id,pi_provider:provider,
      tool_calls:calls,usage,termination,needs_followup:termination==='budget_stopped',reason}});
    const finalizationInstruction = '\n\n预算收尾规则：本轮仅可总结上下文中已经存在的证据及未完成项。不得批准、提交、写入 finding 或声称未验证工作已完成。';
    send({type:'identity', model:id, pi_provider:provider, builtin_tools:false, extensions:false});
    for (let round=0; round<cfg.max_rounds; round++) {
      const finalRound = round === cfg.max_rounds - 1 || calls >= cfg.max_tool_calls || stopReason !== null;
      const requestContext = {...context,
        systemPrompt:context.systemPrompt + (finalRound ? finalizationInstruction : ''),
        tools:finalRound ? [] : cfg.tools};
      if (JSON.stringify(requestContext).length > cfg.max_context_chars) {
        stopReason = 'context_budget_exhausted';
        complete(budgetText(stopReason),'budget_stopped',stopReason); finished=true; break;
      }
      const options = {maxTokens:cfg.max_output_tokens};
      if (cfg.effort && cfg.effort !== 'none') options.reasoning = cfg.effort;
      const response = await runtime.completeSimple(model, requestContext, options);
      if (['error','aborted','length'].includes(response.stopReason)) throw new Error(response.errorMessage || ('Pi incomplete response: '+response.stopReason));
      if (response.provider !== provider || response.model !== id) throw new Error('Pi returned a different model identity');
      for (const k of Object.keys(usage)) usage[k] += response.usage?.[k] || 0;
      context.messages.push(response);
      const actions = response.content.filter(c => c.type === 'toolCall');
      if (!actions.length) {
        const text = response.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
        if (!text.trim()) {
          complete(budgetText('no_final_answer'),'budget_stopped','no_final_answer'); finished=true; break;
        }
        if (finalRound && !stopReason) stopReason='round_budget_finalization';
        complete(text,stopReason ? 'budget_stopped' : 'completed',stopReason); finished = true; break;
      }
      // Validate the complete action batch before dispatching any member.
      const batchIds = new Set();
      for (const action of actions) {
        if (!allowed.has(action.name) || !action.id || seen.has(action.id) || batchIds.has(action.id) ||
            !action.arguments || typeof action.arguments !== 'object' || Array.isArray(action.arguments)) throw new Error('Unknown or duplicate Pi tool call');
        batchIds.add(action.id);
      }
      for (const action of actions) seen.add(action.id);
      const remaining = Math.max(0,cfg.max_tool_calls-calls);
      const dispatchable = finalRound ? 0 : Math.min(actions.length,remaining);
      for (let i=0; i<actions.length; i++) {
        const action=actions[i];
        if (i >= dispatchable || stopReason !== null) {
          context.messages.push({role:'toolResult',toolCallId:action.id,toolName:action.name,
            content:[{type:'text',text:JSON.stringify({ok:false,error:{code:'PI_TOOL_BUDGET_BLOCKED',message:'Not executed: tool dispatch is closed by the round/tool/host budget; use only existing evidence.'}})}],
            isError:true,timestamp:Date.now()});
          stopReason = stopReason || (finalRound ? 'model_requested_tools_during_finalization' : 'tool_budget_exhausted');
          continue;
        }
        calls++;
        send({type:'tool_call',id:action.id,name:action.name,arguments:action.arguments});
        const reply = await receive();
        if (reply.type !== 'tool_result' || reply.id !== action.id) throw new Error('Mismatched host tool result');
        context.messages.push({role:'toolResult',toolCallId:action.id,toolName:action.name,
          content:[{type:'text',text:JSON.stringify(reply.result)}],isError:reply.result?.ok===false,timestamp:Date.now()});
        const code=reply.result?.error?.code;
        if (['TOOL_CONTEXT_BUDGET_EXHAUSTED','TOOL_FAILURE_LIMIT','TOOL_BUDGET_EXHAUSTED'].includes(code)) stopReason=code.toLowerCase();
      }
      if (finalRound && !stopReason) stopReason='model_requested_tools_during_finalization';
      if (calls >= cfg.max_tool_calls) stopReason=stopReason || 'tool_budget_exhausted';
    }
    if (!finished) {
      stopReason=stopReason || 'round_budget_exhausted';
      complete(budgetText(stopReason),'budget_stopped',stopReason);
    }
  }
  input.close();
  process.stdout.write('', () => process.exit(0));
} catch (error) {
  send({type:'error',message:String(error.message || error).slice(0,1000)});
  input.close();
  process.stdout.write('', () => process.exit(1));
}
