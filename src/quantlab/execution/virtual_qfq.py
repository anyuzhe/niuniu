"""Explicit virtual-unit simulation, never a raw security/account contract.

The old published research input remains execution-forbidden by default. Only
ExecutionConfig.price_mode='virtual_qfq' opts into this hypothetical consumer.
No original data, provider mark, broker account, or live authority is created.
"""
from datetime import date
import re

DISCLOSURE = {
    'format':'niuniu-virtual-qfq-ledger-v1',
    'real_account':False,
    'raw_share_units':False,
    'cost_included':True,
    'limitations':[
        '前复权虚拟单位资金模拟：初始金额为名义人民币尺度，持仓数量不是原始股数，不能作为真实券商账户复算。',
        '源前复权价格已经含发布方公司行动处理，不重复派息/送股；没有认证现金红利到账、持股税、真实整手与公司行动时点。',
        '停牌不成交，按最近已观察前复权收盘值估值；每证券首日无可用价格则拒绝，不伪造vendor_previous_close。',
        '日线收盘信号下一开盘撮合，T+1、现金/仓位/佣金滑点/税费按配置模拟，不读取当根收盘后量来决定开盘成交。',
        '价格阻断为固定模拟规则：沪深主板10%、主板ST5%、创业/科创20%，以前一已观察qfq收盘为基准；不是官方历史限价/价格舍入/除权日/新股豁免校验。ST不新增买入。',
        '容量上限以此前已完成bar的原始volume除以其factor换算虚拟单位，只是滞后代理，不证明开盘盘口成交或真实容量。',
        '100单位整手是虚拟单位网格，不对应原始股数或科创板200股门槛；没有严格PIT、独立盲测或盈利认证。',
        '信号消失驱动减仓，现有T+1或停牌/价格阻断可能推迟退出；不含独立止损止盈或最大回撤保证，末日不强平。',
    ],
}

def validate_virtual_range(bars):
    if bars['datetime'].min().date()<date(2020,8,24):
        raise ValueError('Virtual board-limit model only covers dates from 2020-08-24')
    for s in bars['symbol'].unique():
        if not re.fullmatch(r'(?:sh\.(?:60|68)\d{4}|sz\.(?:00|30)\d{4})',s):
            raise ValueError('Unsupported code family for virtual board-limit model')

def blocked_reason(symbol,price,previous_close,buying,is_st):
    if is_st not in (0,1):raise ValueError('Unknown virtual ST state')
    if buying and is_st:return 'virtual_st_buy_blocked'
    if previous_close is None:return 'virtual_previous_price_unavailable'
    growth=symbol.startswith(('sh.68','sz.30'))
    rate=.2 if growth else .05 if is_st else .1
    bound=previous_close*(1+rate if buying else 1-rate)
    if (buying and price>=bound-1e-10) or (not buying and price<=bound+1e-10):
        return 'virtual_modeled_price_limit'
    return None
