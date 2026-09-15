/* Research forms call typed local APIs; no command strings are accepted. */
let jobTimer;
let researchDraft;
const modeNames={theory_study:'理论研究全流程',execution:'独立成交回测',single:'单因子 / 条件 / 组合',holdout:'固定 train / valid / test',walkforward:'滚动验证',ablation:'逐输入消融',sweep:'参数扫描'};
const jobNames={queued:'排队中',running:'运行中',completed:'已完成',failed:'失败',interrupted:'服务中断'};
async function post(path,payload){
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||`请求失败 (${response.status})`);
    return result;
}
function field(form,label,name,value,type='text'){
    const input=el(type==='textarea'?'textarea':'input');
    if(type!=='textarea')input.type=type;
    input.name=name;input.value=value??'';
    const container=add(el('label',undefined,'form-field'),el('span',label),input);
    form.append(container);
    return input;
}
function choice(form,label,name,options,value){
    const control=el('select');control.name=name;
    for(const [key,title] of options){const option=el('option',title);option.value=key;control.append(option);}
    control.value=value;
    form.append(add(el('label',undefined,'form-field'),el('span',label),control));
    return control;
}
async function launch(token){
    const [settings,catalog,recent]=await Promise.all([api('/api/settings'),api('/api/catalog'),api('/api/runs?limit=1')]);
    if(token!==generation)return;
    app.replaceChildren(el('h1','新建研究实验'),el('p','配置研究假设与数据范围，提交后由本地队列串行执行。结果沿用现有实验归档和报告。','muted'));
    if(!settings.execution_enabled){
        app.append(el('p','当前为只读模式。启动服务时加入 --data-root /Volumes/Lexar/niuniu-data 才能运行实验。','note'));return;
    }
    app.append(el('p',`只读行情来源：${settings.data_root}`,'muted mono'));
    const latest=recent.runs[0]||{};
    researchDraft??={question:'工作台因子研究',symbols:(latest.symbols||[]).join(' '),start:latest.start||'',end:latest.end||'',timeframe:latest.timeframe||'1d',target:'factor:BASE.MOMENTUM@1.0.0',parameters:'{"lookback":20}',horizons:'1 5 20',quantiles:5,mode:'single',adjustment:'qfq',grid:'{"lookback":[5,10,20]}',advanced:'{}',train_days:30,valid_days:10,test_days:10};
    const form=el('form',undefined,'card research-form'),fields=el('div',undefined,'form-grid');form.append(fields);app.append(form);
    const question=field(fields,'研究问题','question',researchDraft.question);question.required=true;
    const symbols=field(fields,'股票代码（空格或逗号分隔）','symbols',researchDraft.symbols);symbols.required=true;
    const start=field(fields,'开始日期','start',researchDraft.start,'date');start.required=true;
    const end=field(fields,'结束日期','end',researchDraft.end,'date');end.required=true;
    const timeframe=choice(fields,'K 线周期','timeframe',[['1d','日线'],['5m','5 分钟']],researchDraft.timeframe);
    const adjustment=choice(fields,'复权口径','adjustment',[['raw','不复权 raw'],['qfq','前复权 qfq']],researchDraft.adjustment);
    const target=choice(fields,'因子 / 固定研究模板','target',[
        ...catalog.factors.map(f=>[`factor:${f.definition.factor_id}@${f.definition.version}`,`${f.definition.name_cn} · ${f.definition.factor_id}@${f.definition.version}`]),
        ...catalog.theories.map(t=>[`theory:${t.template_id}@${t.version}`,`模板 · ${t.name}`])],researchDraft.target);
    const universe=choice(fields,'历史股票池','universe_mode',[['explicit','显式股票列表'],['listing','历史上市区间（非严格 PIT）'],['pit','PIT 资格记录（未知排除）']],researchDraft.universe_mode||'explicit');
    const listingDays=field(fields,'上市区间模式：最少上市自然日','min_listed_days',researchDraft.min_listed_days||0,'number');listingDays.min='0';
    const mode=choice(fields,'研究方式','mode',Object.entries(modeNames),researchDraft.mode);
    const horizons=field(fields,'未来持有期（K 线根数）','horizons',researchDraft.horizons);horizons.required=true;
    const quantiles=field(fields,'分位组数','quantiles',researchDraft.quantiles,'number');quantiles.min='2';quantiles.required=true;
    const params=field(form,'因子参数 JSON（选择因子时填入注册默认值）','parameters',researchDraft.parameters,'textarea');
    const splitBox=el('div',undefined,'form-grid');form.append(splitBox);
    const trainEnd=field(splitBox,'训练段结束日期','train_end',researchDraft.train_end,'date');
    const validEnd=field(splitBox,'验证段结束日期','valid_end',researchDraft.valid_end,'date');
    const scheduleBox=el('div',undefined,'form-grid');form.append(scheduleBox);
    const lengths=['train_days','valid_days','test_days'].map((name,i)=>field(scheduleBox,['训练窗口自然日数','验证窗口自然日数','测试窗口自然日数'][i],name,researchDraft[name],'number'));
    lengths.forEach(f=>f.min='1');
    const grid=field(form,'扫描网格 JSON','grid',researchDraft.grid,'textarea');
    const auditCheck=field(form,'保存序列审计','sequence_audit','','checkbox');auditCheck.checked=!!researchDraft.sequence_audit;
    const replayCheck=field(form,'保存 K 线审计回放','replay','','checkbox');replayCheck.checked=researchDraft.replay??true;
    const advanced=field(form,'可选配置 JSON：regime / regime_filter / context / bootstrap / permutation / incremental_test / processor / seed / execution / theory_study / portfolio / execution_backend / market_rules；扫描可加 split 或 schedule','advanced',researchDraft.advanced,'textarea');
    const scopeNote=el('p',undefined,'note');form.append(scopeNote);
    const status=el('div');status.setAttribute('role','status');
    const actions=el('div',undefined,'toolbar');
    const validate=button('校验并预览配置',async()=>{status.replaceChildren();try{const resolved=await post('/api/validate',collect());status.append(el('p','配置校验通过。尚未读取行情或执行实验。','success'),raw('查看解析后的完整配置',resolved));}catch(e){error(status,e);}});
    const submit=el('button','提交实验','primary');submit.type='submit';add(actions,validate,submit,link('查看运行任务','#jobs','button'));form.append(actions,status);
    let lastPayload='',submissionId;
    function remember(){for(const input of form.elements)if(input.name)researchDraft[input.name]=input.type==='checkbox'?input.checked:input.value;}
    form.addEventListener('input',remember);
    form.addEventListener('change',remember);
    function update(){
        scopeNote.textContent=mode.value==='execution'?'独立回测按因子值超过阈值的前 N 名生成目标，支持等权或正分数权重及目标风控，在下一根开盘模拟成交；持有期仅用于来源研究标签。费用与 T+1 为可配置模型，未处理公司行动及真实流动性。':'未来收益是未扣成本的研究标签；参数扫描不自动择优。历史上市区间不包含 ST、停牌等完整历史可交易状态。';
        if(mode.value==='theory_study')scopeNote.textContent='理论全流程会运行组件、完整组合、消融、固定样本外、滚动和参数敏感性。请在可选 JSON 中提供 theory_study：split、schedule、input、grid；示例见 README。参数敏感性是描述性比较，不自动择优。';
        const theory=target.value.startsWith('theory:');params.disabled=theory;
        params.parentElement.hidden=theory;
        splitBox.hidden=mode.value!=='holdout';scheduleBox.hidden=mode.value!=='walkforward';grid.parentElement.hidden=mode.value!=='sweep';
        trainEnd.required=validEnd.required=mode.value==='holdout';lengths.forEach(f=>f.required=mode.value==='walkforward');
    }
    target.onchange=()=>{
        const chosen=catalog.factors.find(f=>`factor:${f.definition.factor_id}@${f.definition.version}`===target.value);
        if(chosen)params.value=pretty(chosen.defaults);
        remember();update();
    };
    mode.onchange=update;update();
    function collect(){
        remember();
        const [source,reference]=target.value.split(':');const [id,version]=reference.split('@');
        const spec={question:question.value,symbols:symbols.value.trim().split(/[\s,，]+/).filter(Boolean),start:start.value,end:end.value,
            timeframe:timeframe.value,adjustment:adjustment.value,mode:mode.value,
            horizons:horizons.value.trim().split(/[\s,，]+/).map(Number),quantiles:Number(quantiles.value),sequence_audit:auditCheck.checked,replay:replayCheck.checked,universe:{mode:universe.value,min_listed_days:universe.value==='listing'?Number(listingDays.value):0}};
        if(source==='theory'){spec.theory=id;spec.theory_version=version;}else{spec.factor=id;spec.version=version;spec.parameters=JSON.parse(params.value);}
        if(mode.value==='holdout')spec.split={train_end:trainEnd.value,valid_end:validEnd.value};
        if(mode.value==='walkforward')spec.schedule=Object.fromEntries(lengths.map(f=>[f.name,Number(f.value)]));
        if(mode.value==='sweep')spec.grid=JSON.parse(grid.value);
        const extra=JSON.parse(advanced.value);
        const allowed=['regime','regime_filter','context','bootstrap','permutation','incremental_test','processor','seed','execution','theory_study','portfolio','execution_backend','market_rules',...(mode.value==='sweep'?['split','schedule']:[])];
        if(!extra||Array.isArray(extra)||typeof extra!=='object'||Object.keys(extra).some(k=>!allowed.includes(k)))throw Error('可选配置包含不支持或重复覆盖的字段');
        return {...spec,...extra};
    }
    form.onsubmit=async event=>{
        event.preventDefault();submit.disabled=true;validate.disabled=true;status.replaceChildren(el('p','正在提交…','muted'));
        try{
            const spec=collect(),payload=JSON.stringify(spec);
            if(payload!==lastPayload){submissionId=crypto.randomUUID();lastPayload=payload;}
            const job=await post('/api/jobs',{job_id:submissionId,spec});
            if(token===generation)location.hash='job='+job.job_id;
        }catch(e){error(status,e);}finally{submit.disabled=false;validate.disabled=false;}
    };
}
async function jobsPage(token){
    app.replaceChildren(el('h1','运行任务'),el('p','本工作台每次只执行一个研究任务。刷新或关闭页面不会停止后台研究。','muted'),link('新建研究实验','#new','button primary'));
    const body=el('div');app.append(body);let offset=0;
    async function load(){
        try{
            const data=await api(`/api/jobs?offset=${offset}&limit=20`);if(token!==generation)return;
            body.replaceChildren(table(['任务','方式','状态','提交时间（UTC）','结果'],data.jobs.map(j=>[
                link(j.spec.question||j.job_id,'#job='+j.job_id),modeNames[j.spec.mode||'single'],
                el('span',jobNames[j.status]||j.status,`tag ${j.status}`),j.created_at.slice(0,19).replace('T',' '),
                j.run_id?link('查看实验结果','#run='+j.run_id):j.error||'—'])));
            if(!data.jobs.length)body.append(el('p','尚未提交任务。','empty'));
            pager(body,offset,data.total,20,v=>{offset=v;clearTimeout(jobTimer);load();});
            jobTimer=setTimeout(load,2500);
        }catch(e){if(token===generation)error(body,e);}
    }
    await load();
}
async function jobPage(id,token){
    const job=await api('/api/jobs/'+encodeURIComponent(id));if(token!==generation)return;
    app.replaceChildren(link('← 运行任务','#jobs'),el('h1',job.spec.question||'研究任务'),el('p',id,'mono muted'));
    const status=el('div',undefined,'card');app.append(status,raw('提交配置',job.spec),raw('执行配置（已解析版本和参数）',job.resolved));
    async function refresh(value){
        if(token!==generation)return;
        status.replaceChildren(el('h2',jobNames[value.status]||value.status),el('p',`提交：${value.created_at} · 开始：${value.started_at||'—'} · 结束：${value.finished_at||'—'}`,'muted'));
        if(value.error)status.append(el('p',value.error,'error'));
        if(value.run_id)status.append(link('查看实验结果','#run='+value.run_id,'button primary'));
        if(['queued','running'].includes(value.status))jobTimer=setTimeout(async()=>{
            try{await refresh(await api('/api/jobs/'+encodeURIComponent(id)));}catch(e){if(token===generation)error(status,e);}
        },1500);
    }
    await refresh(job);
}
