const $=id=>document.getElementById(id);
const text=(tag,value,cls='')=>{const n=document.createElement(tag);n.textContent=value??'—';if(cls)n.className=cls;return n};
function clear(node){while(node.firstChild)node.removeChild(node.firstChild)}
function card(label,value){const n=text('div','', 'card');n.append(text('span',label,'label'),text('b',value));return n}
function item(title,meta='',cls=''){const n=text('div','',`item ${cls}`);n.append(text('strong',title));if(meta)n.append(text('div',meta,'meta'));return n}
function decisionLine(d){if(!d)return '—';return `${d.symbol||''} · ${d.action||''} · ${d.frame||''}`}
async function getJSON(path){const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}
function render(data){
  const s=$('summary');clear(s);const h=data.system_health?.summary||{};
  s.append(card('交易日',data.trading_day),card('最新 Frame',data.latest_saved_frame||'—'));
  s.append(card('Runtime',h.runtime_status||'—'),card('Research',h.research_readiness_status||'—'));
  s.append(card('候选',data.counts?.candidates??0),card('计划/持仓',data.counts?.plans??0));
  const a=$('actions');clear(a);
  [...(data.candidates||[]),...(data.plans||[])].slice(0,30).forEach(d=>a.append(item(decisionLine(d),`${d.theme||'未标主题'} · ${d.ai_thesis||''}`)));
  if(!a.children.length)a.append(item('暂无候选或持仓计划'));
  const t=$('themes');clear(t);
  (data.themes||[]).forEach(x=>t.append(item(`${x.theme||'未命名'} · ${x.machine_state||'UNKNOWN'}`,`${x.ai_state||'UNKNOWN'} · ${x.risk_review||''}`)));
  (data.risks||[]).slice(0,12).forEach(x=>t.append(item(x.symbol||x.theme||'风险',x.risk_review||x.invalidation||x.exit_condition||'', 'risk')));
  if(!t.children.length)t.append(item('暂无主线/风险记录'));
  renderStock(data.stock);
}function renderStock(stock){
  const section=$('stock-section'),box=$('stock');clear(box);
  if(!stock){section.hidden=true;return}section.hidden=false;
  box.append(item(stock.symbol,decisionLine(stock.current_decision)));
  const c=stock.counts||{};box.append(item('证据数量',`Decision ${c.decision_history||0} · Experiment ${c.experiments||0} · Watch ${c.watches||0} · Playbook ${c.playbooks||0}`));
  (stock.decision_history||[]).slice(0,8).forEach(d=>box.append(item(decisionLine(d),`${d.trading_day||''} · ${d.ai_thesis||''}`)));
}
async function refresh(){
  $('notice').textContent='读取同一工作空间状态…';const day=$('day').value,symbol=$('symbol').value.trim();
  const q=new URLSearchParams({trading_day:day,symbol});
  try{const data=await getJSON(`/api/mobile/brief?${q}`);render(data);$('notice').textContent=`只读 · ${data.day_source} · 不创建手机端状态`}
  catch(e){$('notice').textContent=`读取失败：${e.message}`}
}
$('refresh').addEventListener('click',refresh);
$('symbol').addEventListener('keydown',e=>{if(e.key==='Enter')refresh()});
refresh();