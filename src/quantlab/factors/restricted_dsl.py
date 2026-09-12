"""Restricted factor DSL: whitelisted AST only, never eval user text."""
import math
import polars as pl
from quantlab.domain import FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack

FIELDS={'open','high','low','close','volume','turnover','adj_factor'}
BINARY={'add','sub','mul','div','min','max'}
UNARY={'neg','abs','sign'}
ROLLING={'rolling_mean','rolling_std','rolling_sum','rolling_min','rolling_max'}
MAX_NODES=64;MAX_DEPTH=12;MAX_WINDOW=252


def finite_number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('DSL常数必须是有限数值')
    return float(value)


def validate_ast(node,depth=0,counter=None):
    if counter is None:counter=[0]
    counter[0]+=1
    if counter[0]>MAX_NODES or depth>MAX_DEPTH or not isinstance(node,dict):
        raise ValueError('DSL节点数或嵌套深度超出限制')
    op=node.get('op')
    if not isinstance(op,str):raise ValueError('DSL节点缺少op')
    if op=='field':
        if set(node)!={'op','name'} or node['name'] not in FIELDS:
            raise ValueError('DSL字段不在白名单')
        return {'op':'field','name':node['name']}
    if op=='const':
        if set(node)!={'op','value'}:raise ValueError('const字段无效')
        return {'op':'const','value':finite_number(node['value'])}
    if op in BINARY:
        if set(node)!={'op','left','right'}:raise ValueError('二元节点字段无效')
        return {'op':op,'left':validate_ast(node['left'],depth+1,counter),
            'right':validate_ast(node['right'],depth+1,counter)}
    if op in UNARY:
        if set(node)!={'op','arg'}:raise ValueError('一元节点字段无效')
        return {'op':op,'arg':validate_ast(node['arg'],depth+1,counter)}
    if op in ('lag','delta','pct_change'):
        if set(node)!={'op','arg','bars'} or type(node['bars']) is not int or not 1<=node['bars']<=MAX_WINDOW:
            raise ValueError('lag/delta/pct_change须使用1–252根过去K线')
        child=validate_ast(node['arg'],depth+1,counter)
        if contains_temporal(child):raise ValueError('第一版DSL不允许时序窗口嵌套')
        return {'op':op,'arg':child,'bars':node['bars']}
    if op in ROLLING:
        if set(node)!={'op','arg','window'} or type(node['window']) is not int or not 2<=node['window']<=MAX_WINDOW:
            raise ValueError('滚动窗口须为2–252')
        child=validate_ast(node['arg'],depth+1,counter)
        if contains_temporal(child):raise ValueError('第一版DSL不允许时序窗口嵌套')
        return {'op':op,'arg':child,'window':node['window']}
    raise ValueError('DSL操作符不在白名单：'+str(op))


def contains_temporal(node):
    if node['op'] in ('lag','delta','pct_change',*ROLLING):return True
    if node['op'] in BINARY:return contains_temporal(node['left']) or contains_temporal(node['right'])
    if node['op'] in UNARY:return contains_temporal(node['arg'])
    return False


def used_fields(node):
    op=node['op']
    if op=='field':return {node['name']}
    if op=='const':return set()
    if op in BINARY:return used_fields(node['left'])|used_fields(node['right'])
    return used_fields(node['arg'])


def compile_ast(node):
    op=node['op']
    if op=='field':return pl.col(node['name']).cast(pl.Float64)
    if op=='const':return pl.lit(node['value'],dtype=pl.Float64)
    if op in BINARY:
        left,right=compile_ast(node['left']),compile_ast(node['right'])
        if op=='add':return left+right
        if op=='sub':return left-right
        if op=='mul':return left*right
        if op=='div':return pl.when(right.abs()>1e-12).then(left/right).otherwise(None)
        if op=='min':return pl.min_horizontal(left,right)
        return pl.max_horizontal(left,right)
    arg=compile_ast(node['arg'])
    if op=='neg':return -arg
    if op=='abs':return arg.abs()
    if op=='sign':return arg.sign()
    if op=='lag':return arg.shift(node['bars']).over('symbol')
    if op=='delta':return (arg-arg.shift(node['bars'])).over('symbol')
    if op=='pct_change':
        previous=arg.shift(node['bars']).over('symbol')
        return pl.when(previous.abs()>1e-12).then(arg/previous-1).otherwise(None)
    window=node['window']
    if op=='rolling_mean':return arg.rolling_mean(window_size=window,min_samples=window).over('symbol')
    if op=='rolling_std':return arg.rolling_std(window_size=window,min_samples=window,ddof=0).over('symbol')
    if op=='rolling_sum':return arg.rolling_sum(window_size=window,min_samples=window).over('symbol')
    if op=='rolling_min':return arg.rolling_min(window_size=window,min_samples=window).over('symbol')
    if op=='rolling_max':return arg.rolling_max(window_size=window,min_samples=window).over('symbol')
    raise ValueError('未知DSL操作符')


class RestrictedDslFactor(ComputedFactor):
    definition=FactorDefinition('DSL.RESTRICTED','1.0.0','受限DSL候选因子','generated_candidate',
        FactorType.SCALAR,(),tuple(Timeframe),'白名单AST候选；不执行任意代码，仅允许过去滞后与滚动统计。',
        'validated restricted AST',causal=True,lookahead_risk='low',
        tags=('dsl','candidate','restricted'),available_at_rule='current bar close after causal history only')
    def parameters(self,supplied):
        if supplied=={}:
            supplied={'ast':{'op':'pct_change','arg':{'op':'field','name':'close'},'bars':1}}
        if not isinstance(supplied,dict) or set(supplied)!={'ast'}:
            raise ValueError('DSL.RESTRICTED参数必须且只能包含ast')
        return {'ast':validate_ast(supplied['ast'])}
    def compute(self,bars,parameters):
        ast=self.parameters(parameters)['ast'];fields=used_fields(ast)
        missing=fields-set(bars.columns)
        if missing:raise ValueError('DSL缺少行情字段：'+','.join(sorted(missing)))
        expression=compile_ast(ast)
        return bars.select('symbol','datetime','available_at',expression.alias('value'))


def restricted_dsl_pack():
    return FactorPack('RestrictedDslPack','1.0.0',(RestrictedDslFactor(),),('BaseQuantPack',))
