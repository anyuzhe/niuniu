import hashlib
from copy import deepcopy
from pathlib import Path

from quantlab.factors.combinations import ConditionCombination


def templates() -> list[dict]:
    """Fresh definitions on each call so callers cannot mutate the catalog."""
    return [
        {'template_id':'RESEARCH.WYCKOFF_CLASSIC_POSITION','version':'1.0.0','name':'威克夫 A–E 完整规则链持仓与评分',
         'scope':'OHLCV 明确规则：双向 A–E、三定律量价代理、冻结区间及逐事件序列，评分 >=80 且进入向上 E 持仓；不同于主观判图。',
         'concepts':{'position':'完整阶段链后的持仓状态','score':'市场/量价与阶段评分'},
         'parameters':{'inputs':{'position':{'factor_id':'WYCKOFF.CLASSIC_POSITION','version':'1.0.0','parameters':{}},
             'score':{'factor_id':'WYCKOFF.CLASSIC_SCORE','version':'1.0.0','parameters':{}}},
             'rule':{'all':[{'input':'position','op':'eq','value':1},{'input':'score','op':'ge','value':80}]}}},
        {'template_id':'RESEARCH.BROOKS_WEDGE_REVERSAL','version':'1.0.0','name':'Brooks 三极值收缩反转与正动量',
         'scope':'五个交替确认极值构成三次新低且末次增量缩小，后续收盘突破最近高点；明确规则代理，不是完整主观楔形判图。',
         'concepts':{'entry':'三极值收缩后的向上反转确认','momentum':'同根 20 根正动量'},
         'parameters':{'inputs':{'entry':{'factor_id':'BROOKS.WEDGE_CONFIRMED_UP','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'entry','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.BROOKS_DIRECTION_MOMENTUM','version':'1.0.0','name':'Brooks 持续方向代理与正动量',
         'scope':'强实体收盘突破此前区间后锁存方向，直到反向强实体突破；不是持仓建议或完整 AlwaysIn 判图。',
         'concepts':{'direction':'突破锁存方向等于 +1','momentum':'同根 20 根正动量'},
         'parameters':{'inputs':{'direction':{'factor_id':'BROOKS.CTX_ALWAYS_IN','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'direction','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.BROOKS_BREAKOUT_PULLBACK','version':'1.0.0','name':'Brooks 突破回踩再启动与正动量',
         'scope':'冻结前区间突破、不同 K 线回踩边界并再突破回踩高点；收盘规则代理，后续测量目标仅作事件跟踪。',
         'concepts':{'entry':'向上突破回踩后的再启动确认','momentum':'同根 20 根正动量'},
         'parameters':{'inputs':{'entry':{'factor_id':'BROOKS.BP_RESUMED_UP','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'entry','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.WYCKOFF_PHASE_E_MOMENTUM','version':'1.0.0','name':'Wyckoff 阶段延续确认与正动量',
         'scope':'Spring/Test/SOS 后，缩量回踩边界并再次收盘突破 SOS 极值确认 E；不同 K 线确认，是价格阶段代理，不识别机构行为。',
         'concepts':{'continuation':'向上阶段链 E 确认','momentum':'同根 20 根正动量'},
         'parameters':{'inputs':{'continuation':{'factor_id':'WYCKOFF.PHASE_E_UP','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'continuation','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.CHAN_RULE_BUY2_MOMENTUM','version':'1.0.0','name':'Chan 确认二类买点与正动量',
         'scope':'归一化速度背驰的一类确认后，首次回踩不破极值，再由确认笔突破回踩起点；明确规则代理，不含完整特征序列或缺口分类。',
         'concepts':{'buy':'确认推进规则的二类买点','momentum':'同根 20 根正动量'},
         'parameters':{'inputs':{'buy':{'factor_id':'CHAN.RULE_BUY2','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'buy','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.CHAN_INCLUSION_CENTER_MOMENTUM','version':'1.0.0','name':'Chan 包含确认中枢与正动量',
         'scope':'后继非包含 K 线确认合并条，再确认交替笔和三笔中枢；不含线段、背驰或买卖点。',
         'concepts':{'center':'包含处理后确认的三笔中枢创建','momentum':'同根 20 根动量为正'},
         'parameters':{'inputs':{'center':{'factor_id':'CHAN.INCLUSION_CENTER','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'center','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.ICT_OB_TOUCH_MOMENTUM','version':'1.0.0','name':'ICT OB 首次回测与正动量',
         'scope':'BOS 与位移创建的反向实体 K 线全区间，后续首次接触时动量为正；只按收盘确认，不推断机构订单或盘中成交路径。',
         'concepts':{'touch':'向上 OB 后续首次接触，收盘未越远端失效','momentum':'同根 20 根动量为正'},
         'parameters':{'inputs':{'touch':{'factor_id':'ICT.OB_TOUCHED_UP','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'touch','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.WYCKOFF_SOS_MOMENTUM','version':'1.0.0','name':'Wyckoff 强势突破与正动量',
         'scope':'冻结前区间 Spring→缩量 Test→SOS 的 OHLC 规则变体；不声称识别完整吸筹阶段。',
         'concepts':{'sos':'冻结区间收回、缩量测试、收盘突破','momentum':'完成时动量为正'},
         'parameters':{'inputs':{'sos':{'factor_id':'WYCKOFF.SOS','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'sos','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.ICT_MSS_FVG','version':'1.0.0','name':'ICT 结构转变与活跃 FVG',
         'scope':'三个不同可用时点的扫出、实体位移、已确认摆动突破；完成时至少一个活跃 FVG。仅 OHLC 变体，不推断真实挂单流动性。',
         'concepts':{'mss':'扫出→位移→确认摆动突破','zone':'完成时活跃 FVG 数量大于零（双向）'},
         'parameters':{'inputs':{'mss':{'factor_id':'ICT.MSS_UP','version':'1.0.0','parameters':{}},
             'zone':{'factor_id':'ZONE.FVG_ACTIVE_COUNT','version':'1.0.0','parameters':{}}},
             'rule':{'all':[{'input':'mss','op':'eq','value':1},{'input':'zone','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.BROOKS_SECOND_ENTRY','version':'1.0.0','name':'Brooks 二次入场与趋势背景',
         'scope':'收盘确认 H2 变体；回调、首次尝试、失败、二次突破在不同时刻发生。趋势是滞后收盘方向，不等同主观 Brooks 判图。',
         'concepts':{'entry':'10 根背景、20 根内完成二次入场','trend':'完成时滞后 10 根方向仍向上'},
         'parameters':{'inputs':{'entry':{'factor_id':'BROOKS.SECOND_UP','version':'1.0.0','parameters':{}},
             'trend':{'factor_id':'BROOKS.TREND_UP','version':'1.0.0','parameters':{}}},
             'rule':{'all':[{'input':'entry','op':'eq','value':1},{'input':'trend','op':'eq','value':1}]}}},
        {'template_id':'RESEARCH.CONFIRMED_BOS_MOMENTUM','version':'1.0.0','name':'确认结构突破与正动量',
         'scope':'已确认严格摆动高点的首次收盘突破，同根要求动量为正；明确规则的 SMC 基础变体，不含 CHoCH 或完整订单流理论。',
         'concepts':{'bos':'左右各 2 根确认后，高点首次被收盘跨越','momentum':'20 根动量大于零'},
         'parameters':{'inputs':{'bos':{'factor_id':'SMC.BOS_UP','version':'1.0.0','parameters':{'left':2,'right':2}},
            'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
            'rule':{'all':[{'input':'bos','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.RECLAIM_CONFIRMATION', 'version':'1.0.0', 'name':'前低收回后的向上确认与正动量',
         'scope':'限时两步序列完成当根同时要求正动量；前高突破失败取消等待。不代表完整反转理论或成交策略。',
         'concepts':{'confirmation':'前低突破失败后 172800 秒内收盘突破实时前 20 根最高价', 'momentum':'完成当根近 20 根收盘变化率大于零'},
         'parameters':{'inputs':{
             'confirmation':{'factor_id':'SEQ.FAILED_LOW_THEN_BREAKOUT','version':'1.0.0','parameters':{'lookback':20,'max_gap_seconds':172800}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'confirmation','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.FAILED_LOW_POSITIVE_MOMENTUM', 'version':'1.0.0', 'name':'正动量背景下的前低突破失败',
         'scope':'本根跌破此前区间下沿后收回，且 20 根动量为正；仅为 OHLC 条件，不推断盘中路径或后续反转。',
         'concepts':{'failure':'最低价跌破此前 20 根最低价，收盘回到此前区间（含边界）', 'momentum':'近 20 根收盘变化率大于零'},
         'parameters':{'inputs':{
             'failure':{'factor_id':'EVT.FAILED_BREAKOUT_LOW','version':'1.0.0','parameters':{'lookback':20}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'failure','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
        {'template_id':'RESEARCH.TREND_BREAKOUT', 'version':'1.0.0', 'name':'趋势背景下的收盘突破',
         'scope':'固定阈值研究假设；趋势仅指有符号方向效率，不代表完整价格行为理论。',
         'concepts':{'trend':'近 20 根有符号方向效率大于 0.6', 'breakout':'收盘严格突破此前 20 根最高价'},
         'parameters':{'inputs':{
             'trend':{'factor_id':'BASE.DIRECTIONAL_EFFICIENCY','version':'1.0.0','parameters':{'lookback':20}},
             'breakout':{'factor_id':'EVT.BREAKOUT_HIGH','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'trend','op':'gt','value':0.6},{'input':'breakout','op':'eq','value':1}]}}},
        {'template_id':'RESEARCH.BULL_FVG_MOMENTUM', 'version':'1.0.0', 'name':'看涨 FVG 与正动量',
         'scope':'三根 K 线看涨缺口创建与正动量同根确认；不含位移、时段、回踩或成交规则。',
         'concepts':{'gap':'三根 K 线看涨 FVG 创建标记', 'momentum':'近 20 根收盘变化率大于零'},
         'parameters':{'inputs':{
             'gap':{'factor_id':'ZONE.FVG_BULL_CREATED','version':'1.0.0','parameters':{}},
             'momentum':{'factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20}}},
             'rule':{'all':[{'input':'gap','op':'eq','value':1},{'input':'momentum','op':'gt','value':0}]}}},
    ]


def resolve_template(template_id, registry, version='1.0.0'):
    template = next((t for t in templates() if t['template_id']==template_id and t['version']==version), None)
    if template is None:
        raise ValueError(f'Unknown theory template: {template_id}@{version}')
    factor = ConditionCombination(registry)
    parameters = factor.parameters(template['parameters'])
    origin = {**template, 'parameters':parameters, 'factor_id':'COMB.CONDITION', 'factor_version':'1.0.0',
        'code_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'inputs':factor.lineage(parameters)}
    return deepcopy(parameters), origin
