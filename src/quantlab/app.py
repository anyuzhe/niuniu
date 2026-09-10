"""Composition root. Concrete adapters are wired only here and in clients."""

from pathlib import Path

from quantlab.data.universe import build_universe
from quantlab.factors.smc import smc_pack
from quantlab.factors.brooks import brooks_pack
from quantlab.factors.brooks_breakout import brooks_breakout_pack
from quantlab.factors.brooks_context import brooks_context_pack
from quantlab.factors.brooks_wedge import brooks_wedge_pack
from quantlab.factors.ict import ict_pack
from quantlab.factors.wyckoff import wyckoff_pack
from quantlab.factors.wyckoff_classic import classic_wyckoff_pack
from quantlab.factors.wyckoff_phases import wyckoff_phase_pack
from quantlab.factors.chan import chan_pack
from quantlab.factors.chan_inclusion import chan_inclusion_pack
from quantlab.factors.order_block import order_block_pack
from quantlab.factors.chan_progression import chan_progression_pack
from quantlab.data.mqc import MQCParquetProvider
from quantlab.experiments.runner import ExperimentRunner
from quantlab.factors.builtin import base_quant_pack
from quantlab.factors.alpha import alpha_packs
from quantlab.factors.ict_context import ict_context_pack
from quantlab.factors.registry import FactorRegistry
from quantlab.factors.technical import technical_pack
from quantlab.factors.zones import zone_pack
from quantlab.factors.sequences import sequence_pack
from quantlab.factors.chan_sequence import chan_sequence_pack
from quantlab.factors.chan_classic import classic_chan_pack
from quantlab.factors.chan_multiscale import classic_multiscale_pack
from quantlab.factors.combinations import combination_pack
from quantlab.storage.experiments import LocalExperimentStore


def default_registry() -> FactorRegistry:
    registry = FactorRegistry()
    registry.register_pack(base_quant_pack())
    registry.register_pack(technical_pack())
    registry.register_pack(smc_pack())
    registry.register_pack(brooks_pack())
    registry.register_pack(brooks_breakout_pack())
    registry.register_pack(brooks_context_pack())
    registry.register_pack(brooks_wedge_pack())
    registry.register_pack(zone_pack())
    registry.register_pack(ict_pack())
    registry.register_pack(wyckoff_pack())
    registry.register_pack(classic_wyckoff_pack())
    registry.register_pack(wyckoff_phase_pack())
    registry.register_pack(chan_pack())
    registry.register_pack(chan_inclusion_pack())
    registry.register_pack(order_block_pack())
    registry.register_pack(chan_progression_pack())
    registry.register_pack(ict_context_pack())
    registry.register_pack(sequence_pack())
    registry.register_pack(chan_sequence_pack())
    registry.register_pack(classic_chan_pack())
    registry.register_pack(classic_multiscale_pack())
    for pack in alpha_packs():registry.register_pack(pack)
    registry.register_pack(combination_pack(registry))
    return registry


def build_runner(data_root: Path, artifact_root: Path, symbols: tuple[str, ...], adjustment: str = "raw", universe_config=None, snapshot_manifest=None) -> ExperimentRunner:
    from quantlab.data.archive import ArchivedBarProvider
    if snapshot_manifest and adjustment!='raw':raise ValueError('Archived data requires raw adjustment')
    data=ArchivedBarProvider(snapshot_manifest) if snapshot_manifest else MQCParquetProvider(data_root, adjustment)
    return ExperimentRunner(data, default_registry(), build_universe(data_root, symbols, universe_config), LocalExperimentStore(artifact_root))
