"""Freeze the post-hoc study design on the already validated new 500-stock sample."""
import json
from pathlib import Path
from dataclasses import asdict
from quantlab.workbench.jobs import prepare
from quantlab.storage.codec import encode,digest
from quantlab.experiments.runner import runtime_fingerprint

root=Path('artifacts/core-completion');root.mkdir(exist_ok=True)
source=Path('artifacts/chan-500-full-ten-year-qfq/client-spec.json')
old=json.loads(source.read_text())
inputs={
    'classic':{'factor_id':'CHAN.CLASSIC_POSITION','parameters':{}},
    'sequence':{'factor_id':'CHAN.CLASSIC_SEQUENCE_BUY2','parameters':{}},
    'momentum':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':20}},
}
study={
    'question':'经典缠论 · 新500股十年 · 组件/消融/分段/扩展滚动 · 事后研究',
    'symbols':old['symbols'],'start':old['start'],'end':old['end'],'timeframe':'1d','adjustment':'qfq',
    'mode':'theory_study','factor':'COMB.SCORE','parameters':{'inputs':inputs,'weights':{'classic':.6,'sequence':.2,'momentum':.2}},
    'horizons':[1,5,20],'quantiles':5,'seed':20260910,'regime':{},
    'bootstrap':{'resamples':499,'block_days':20,'confidence':.95},
    'permutation':{'resamples':9999,'block_days':20,'alpha':.05},
    'replay':True,'sequence_audit':True,
    'theory_study':{'split':{'train_end':'2021-09-04','valid_end':'2023-09-04'},
        'schedule':{'train_days':1826,'valid_days':365,'test_days':365,'expanding':True},
        'input':'momentum','grid':{'lookback':[10,20,60]},'audit_components':False},
}
resolved=prepare(study)
(root/'classic-500-study-spec.json').write_text(json.dumps(study,ensure_ascii=False,indent=2))
(root/'classic-500-study-frozen.json').write_text(encode({'spec_digest':digest(study),'submission':resolved.preview(),
    'runtime':runtime_fingerprint(),'original_sample_spec':str(source.resolve()),
    'research_timing':'Retrospective: this sample and previous strategy results were already inspected. No claim of unseen OOS.',
    'interpretation':'Weights are fixed raw-value weights without implicit standardization. Classical parameters remain frozen. Complete component audit saved once via full score; other children retain numerical observations.',
    'limitations':['Full-history surviving-stock selection, not historical PIT market universe','OHLCV Amihud liquidity and sample breadth are proxies','Block sign inference assumes joint block symmetry; Holm is confined to this study','No automatic choice of best parameter or best test fold']}))
# A small real-data integration job before the full client submission.
smoke={**study,'question':'研究全流程集成核验 · 3股真实日线','symbols':old['symbols'][:3],
    'bootstrap':{'resamples':20,'block_days':20},'permutation':{'resamples':20,'block_days':20},
    'end':'2018-09-04','theory_study':{'split':{'train_end':'2017-09-04','valid_end':'2018-03-04'},
        'schedule':{'train_days':365,'valid_days':90,'test_days':180,'expanding':True},'input':'momentum','grid':{'lookback':[10,20]},'audit_components':False}}
prepare(smoke);(root/'classic-smoke-spec.json').write_text(json.dumps(smoke,ensure_ascii=False,indent=2))
print('Frozen',len(study['symbols']),'symbols; windows',len(resolved.theory_study.schedule.windows(resolved.config.data)))
