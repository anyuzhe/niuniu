from dataclasses import dataclass, field
from typing import Any

from quantlab.statistics.permutation import PermutationConfig
from quantlab.data.base import DataRequest
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.processing.pipeline import PipelineConfig
from quantlab.multitimeframe.config import DailyContextConfig


@dataclass(frozen=True)
class ExperimentConfig:
    research_question: str
    data: DataRequest
    factor_id: str
    factor_version: str = "1.0.0"
    parameters: dict[str, Any] = field(default_factory=dict)
    horizons: tuple[int, ...] = (1, 5, 20)
    quantiles: int = 5
    random_seed: int = 0
    regime: RegimeConfig | None = None
    regime_filter: RegimeFilter | None = None
    bootstrap: BootstrapConfig | None = None
    processor: CrossSectionConfig | PipelineConfig | None = None
    context: DailyContextConfig | None = None
    theory_origin: dict | None = None
    sequence_audit: bool = False
    replay: bool = False
    permutation: PermutationConfig | None = None
    incremental_test: bool = False

    def __post_init__(self) -> None:
        if type(self.replay) is not bool:
            raise ValueError('replay must be boolean')
        if type(self.incremental_test) is not bool or (self.incremental_test and self.permutation is None):
            raise ValueError('incremental_test must be boolean and requires permutation config')
        if type(self.sequence_audit) is not bool:
            raise ValueError('sequence_audit must be a boolean')
        if self.context is not None:
            self.context.request(self.data)
        if type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer")
        if self.regime_filter is not None and self.regime is None:
            raise ValueError("regime_filter requires regime configuration")
        if not self.research_question.strip():
            raise ValueError("research_question is required")
        if not self.horizons or any(type(h) is not int or h < 1 for h in self.horizons) or len(set(self.horizons)) != len(self.horizons):
            raise ValueError("horizons must be unique positive integers")
        if type(self.quantiles) is not int or self.quantiles < 2:
            raise ValueError("quantiles must be >= 2")
