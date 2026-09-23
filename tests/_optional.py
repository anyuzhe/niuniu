"""Skip helpers for tests that need optional extras declared in pyproject.toml."""
import importlib.metadata
import unittest


def installed(distribution):
    try:
        importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


# Native vn.py comparison paths are pinned to vnpy==4.4.0 (pip install -e ".[vnpy]").
requires_vnpy = unittest.skipUnless(installed('vnpy'), '需要可选依赖 vnpy：pip install -e ".[vnpy]"')
