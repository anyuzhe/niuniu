"""GTJA 191 factor implementations vendored from aurumq-rl (MIT). See PROVENANCE.md and LICENSE_AURUMQ."""
from ._registry import GTJA191_REGISTRY as REGISTRY

from . import (  # noqa: F401
    batch_001_020, batch_021_040, batch_041_060, batch_061_080, batch_081_100,
    batch_101_120, batch_121_140, batch_141_160, batch_161_180, batch_181_191,
)

__all__ = ["REGISTRY"]
