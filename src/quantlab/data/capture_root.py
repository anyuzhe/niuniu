"""Where a workspace keeps its market-data captures (remediation stage 2, D1).

Historically every capture writer (retro daily, DailyMarket, public evidence,
forward reference, Baostock imports/series) wrote under ``<output>/_market_data``,
i.e. inside the code repository's ``artifacts/``.  Stage 2 copies those captures
into the data root and points the workspace at them with an explicit redirect file:

    <output>/_market_data.redirect.json
    {"format": "niuniu-capture-root-redirect-v1",
     "capture_root": "/Volumes/Lexar/niuniu-data/lake/_market_data",
     "capture_root_id": "<64 hex>"}

The target directory must contain ``CAPTURE_ROOT.json`` with the same id, so a
redirect can never silently land on an unrelated or empty folder.  The directory
keeps the name ``_market_data`` because several validators check that name.

Without a redirect file the historical ``<output>/_market_data`` is returned
unchanged.  A present but invalid redirect raises; there is no fallback.  The old
``<output>/_market_data`` tree is left in place as the historical source of paths
recorded in earlier manifests.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REDIRECT_NAME = "_market_data.redirect.json"
REDIRECT_FORMAT = "niuniu-capture-root-redirect-v1"
MARKER_NAME = "CAPTURE_ROOT.json"
MARKER_FORMAT = "niuniu-capture-root-v1"
DIRECTORY_NAME = "_market_data"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX = 16_000


class CaptureRootError(ValueError):
    pass


def _no_symlink_ancestors(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            # macOS fixed aliases /tmp -> /private/tmp and /var -> /private/var only.
            if candidate in (Path("/tmp"), Path("/var")) and \
                    candidate.resolve() == Path("/private") / candidate.name:
                continue
            raise CaptureRootError(f"capture root path contains a symlink: {candidate}")


def _read_json(path: Path, what: str) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX:
        raise CaptureRootError(f"{what} is not a bounded regular file: {path}")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureRootError(f"{what} is not valid JSON") from exc
    if not isinstance(body, dict):
        raise CaptureRootError(f"{what} must be a JSON object")
    return body


def read_redirect(output) -> dict | None:
    redirect = Path(os.path.abspath(os.fspath(output))) / REDIRECT_NAME
    if redirect.is_symlink():
        raise CaptureRootError("capture redirect must not be a symlink")
    if not redirect.exists():
        return None
    body = _read_json(redirect, "capture redirect")
    if set(body) != {"format", "capture_root", "capture_root_id"} or body["format"] != REDIRECT_FORMAT:
        raise CaptureRootError("capture redirect has an unexpected shape")
    root = Path(str(body["capture_root"]))
    if not root.is_absolute() or ".." in root.parts:
        raise CaptureRootError("capture_root must be an absolute normalized path")
    if root.name != DIRECTORY_NAME:
        raise CaptureRootError(f"capture_root directory must be named {DIRECTORY_NAME}")
    if not _HEX64.match(str(body["capture_root_id"])):
        raise CaptureRootError("capture_root_id must be 64 lowercase hex")
    return body


def capture_root(output) -> Path:
    """Capture directory for ``output`` (redirected or historical)."""
    output = Path(os.path.abspath(os.fspath(output)))
    body = read_redirect(output)
    if body is None:
        return output / DIRECTORY_NAME
    root = Path(body["capture_root"])
    _no_symlink_ancestors(root)
    if not root.is_dir():
        raise CaptureRootError(f"redirected capture root is missing: {root}")
    marker = _read_json(root / MARKER_NAME, "capture root marker")
    if marker.get("format") != MARKER_FORMAT or marker.get("capture_root_id") != body["capture_root_id"]:
        raise CaptureRootError("capture root marker does not match the redirect")
    return root


def legacy_root(output) -> Path:
    """The historical in-workspace capture directory, whether or not redirected."""
    return Path(os.path.abspath(os.fspath(output))) / DIRECTORY_NAME
