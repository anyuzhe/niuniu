"""System prompt modules, split from the monolithic SYSTEM string in chat_runtime.py."""
from .core import CORE_SYSTEM
from .research import RESEARCH_SYSTEM
from .market import MARKET_SYSTEM
from .governance import GOVERNANCE_SYSTEM

ALL_MODULES = {
    'core': CORE_SYSTEM,
    'research': RESEARCH_SYSTEM,
    'market': MARKET_SYSTEM,
    'governance': GOVERNANCE_SYSTEM,
}

def compose(names=('core', 'research', 'market', 'governance')):
    """按给定顺序拼接 SYSTEM 模块，中间用空行分隔。"""
    parts = []
    for name in names:
        if name not in ALL_MODULES:
            raise ValueError('未认识的 SYSTEM 模块：'+name)
        parts.append(ALL_MODULES[name])
    return '\n\n'.join(parts)
