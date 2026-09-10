import math
from dataclasses import dataclass, field
from datetime import date

from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe


@dataclass(frozen=True)
class DailyContextConfig:
    start: date
    factor_id: str = "BASE.MOMENTUM"
    version: str = "1.0.0"
    parameters: dict = field(default_factory=dict)
    op: str = "gt"
    value: float = 0.0
    timeframe: str = '1d'

    def __post_init__(self):
        if type(self.start) is not date:
            raise ValueError("Daily context start must be a date")
        if self.op not in ("gt", "ge", "lt", "le", "eq", "ne"):
            raise ValueError("Invalid daily context comparison")
        if type(self.value) not in (int, float) or not math.isfinite(self.value):
            raise ValueError("Daily context threshold must be finite")
        if not isinstance(self.parameters, dict):
            raise ValueError("Daily context parameters must be an object")

    def request(self, low: DataRequest) -> DataRequest:
        high=Timeframe(self.timeframe)
        if high.minutes<=low.timeframe.minutes or self.start > low.start:
            raise ValueError('Context requires a higher timeframe and context.start <= data.start')
        return DataRequest(low.symbols, high, self.start, low.end)
