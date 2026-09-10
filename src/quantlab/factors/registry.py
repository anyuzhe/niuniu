import hashlib
import inspect
from dataclasses import dataclass

from quantlab.factors.base import Factor


@dataclass(frozen=True)
class FactorPack:
    pack_id: str
    version: str
    factors: tuple[Factor, ...]
    dependencies: tuple[str, ...] = ()


class FactorRegistry:
    def __init__(self):
        self._factors: dict[tuple[str, str], Factor] = {}
        self._packs: dict[str, FactorPack] = {}

    def register_pack(self, pack: FactorPack) -> None:
        if pack.pack_id in self._packs:
            raise ValueError(f"Duplicate pack: {pack.pack_id}")
        if any(dep not in self._packs for dep in pack.dependencies):
            raise ValueError("Register pack dependencies first")
        keys = [(f.definition.factor_id, f.definition.version) for f in pack.factors]
        if len(keys) != len(set(keys)) or any(key in self._factors for key in keys):
            raise ValueError("Duplicate factor id/version")
        self._factors.update(zip(keys, pack.factors))
        self._packs[pack.pack_id] = pack

    def get(self, factor_id: str, version: str) -> Factor:
        try:
            return self._factors[(factor_id, version)]
        except KeyError as error:
            raise ValueError(f"Unknown factor: {factor_id}@{version}") from error

    def describe(self) -> list[dict]:
        return [{"definition": f.definition, "defaults": f.parameters({}), "code_hash": self.code_hash(f)} for f in self._factors.values()]

    @staticmethod
    def code_hash(factor: Factor) -> str:
        # Include the defining module (helpers too), not just a class name.
        source = inspect.getsource(inspect.getmodule(type(factor)))
        return hashlib.sha256(source.encode()).hexdigest()
