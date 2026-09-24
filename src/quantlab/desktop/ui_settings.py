"""Per-workspace desktop preferences (only UI layout; never research, data or permissions)."""
import json
from pathlib import Path

DEFAULTS = {'pro_mode': False}


def _path(output):
    return Path(output) / '_desktop' / 'ui.json'


def load_ui_settings(output):
    path = _path(output)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            return dict(DEFAULTS)
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if not isinstance(value, dict):
        return dict(DEFAULTS)
    return {key: value[key] if type(value.get(key)) is type(default) else default for key, default in DEFAULTS.items()}


def save_ui_settings(output, **changes):
    settings = {**load_ui_settings(output), **{k: v for k, v in changes.items() if k in DEFAULTS}}
    path = _path(output)
    if path.parent.is_symlink():
        raise ValueError('界面设置目录不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return settings
