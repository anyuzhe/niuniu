/* All prices and overlays come from the server's availability-truncated view. */
function svgNode(tag,attrs={},text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,v]of Object.entries(attrs))n.setAttribute(key,String(v));if(text!==undefined)n.textContent=text;return n;}
function candleChart(data){
    const svg=svgNode('svg',{viewBox:'0 0 1000 440',role:'img','aria-label':`${data.symbol} 截至 ${data.as_of} 的 K 线与已知审计标记`});
    const bars=data.bars;if(!bars.length)return svg;
    const low=Math.min(...bars.map(b=>b.low)),high=Math.max(...bars.map(b=>b.high));const span=Math.max(high-low,high*.002);
    const y=p=>390-(p-low)/span*330,x=i=>65+(i+.5)*900/bars.length;
    for(let i=0;i<=4;i++){const p=low+span*i/4;svg.append(svgNode('line',{x1:65,x2:965,y1:y(p),y2:y(p),class:'chart-grid'}),svgNode('text',{x:5,y:y(p)+4,class:'chart-label'},p.toFixed(2)));}
    for(const z of data.zones){const state=data.zone_states[z.zone_id];if(state&&state.status!=='active')continue;
        if(z.upper_price<low||z.lower_price>high)continue;
        const first=bars.findIndex(b=>b.available_at>=z.available_at);if(first<0)continue;
        svg.append(svgNode('rect',{x:x(first)-3,y:y(Math.min(high,z.upper_price)),width:965-x(first),height:Math.max(2,y(Math.max(low,z.lower_price))-y(Math.min(high,z.upper_price))),class:'chart-zone'}));
    }
    bars.forEach((b,i)=>{const cls=b.close>=b.open?'candle-up':'candle-down';const group=svgNode('g');group.append(svgNode('title',{},`${b.datetime} 开 ${b.open} 高 ${b.high} 低 ${b.low} 收 ${b.close}`),svgNode('line',{x1:x(i),x2:x(i),y1:y(b.high),y2:y(b.low),class:cls}),svgNode('rect',{x:x(i)-Math.max(1,330/bars.length),y:y(Math.max(b.open,b.close)),width:Math.max(2,660/bars.length),height:Math.max(1,Math.abs(y(b.open)-y(b.close))),class:cls}));svg.append(group);});
    for(const e of data.events){const index=bars.findIndex(b=>b.available_at===e.available_at);if(index>=0){const marker=svgNode('circle',{cx:x(index),cy:y(bars[index].high)-9,r:4,class:'chart-event'});marker.append(svgNode('title',{},`${e.factor_id} · 可用时间 ${e.available_at}`));svg.append(marker);}}
    for(const s of data.structures){const index=bars.findIndex(b=>b.datetime===s.occurred_at);if(index>=0){const marker=svgNode('circle',{cx:x(index),cy:y(s.price),r:3,class:'chart-pivot'});marker.append(svgNode('title',{},`${s.kind} · 确认于 ${s.available_at}`));svg.append(marker);}}
    for(const f of data.fills){const index=bars.findIndex(b=>b.datetime===f.bar_end);if(index>=0){svg.append(svgNode('text',{x:x(index),y:y(f.price)-6,class:'chart-label'},f.side==='buy'?'B':'S'));}}
    svg.append(svgNode('text',{x:65,y:425,class:'chart-label'},bars[0].datetime),svgNode('text',{x:965,y:425,'text-anchor':'end',class:'chart-label'},bars.at(-1).datetime));return svg;
}
async function replayView(target,id,isCurrent){
    let at=0,symbol='',serial=0;const controls=el('div',undefined,'toolbar'),view=el('div');
    target.replaceChildren(el('p','游标停在哪根，就只展示截至该根可用的信息。红涨绿跌；金点为已知事件、蓝点为已确认拐点、淡蓝区为当时活跃 FVG。B/S 是已发生的模拟成交。叠加规则为诊断视图，参数见下方。','note'),controls,view);
    async function load(){const ticket=++serial;try{
        const d=await api(`/api/runs/${id}/replay?`+new URLSearchParams({at,symbol,limit:100}));if(ticket!==serial||!isCurrent()||!target.isConnected)return;symbol=d.symbol;
        const slider=el('input');slider.type='range';slider.min=0;slider.max=d.total_bars-1;slider.value=at;slider.setAttribute('aria-label','回放 K 线游标');slider.onchange=()=>{at=Number(slider.value);load();};
        const prev=button('上一根',()=>{at--;load();}),next=button('下一根',()=>{at++;load();});prev.disabled=at===0;next.disabled=at===d.total_bars-1;
        controls.replaceChildren(select('股票',d.symbols.map(s=>[s,s]),symbol,v=>{symbol=v;at=0;load();}),prev,next,button('最后一根',()=>{at=d.total_bars-1;load();}),slider,el('span',`${at+1} / ${d.total_bars}`,'muted'));
        view.replaceChildren(el('p',`当前可用时点：${d.as_of}`,'mono'),add(el('div',undefined,'card candle-chart'),candleChart(d)),raw('当前 K 线 OHLCV',d.bars.at(-1)),raw('诊断叠加规则',d.overlay_rules),raw('截至游标的已知事件',d.events),raw('截至游标的已确认结构',d.structures),raw('截至游标的区域状态',d.zone_states),raw('截至游标的模拟成交',d.fills));
    }catch(e){if(ticket===serial&&isCurrent())error(view,e);}}
    await load();
}
