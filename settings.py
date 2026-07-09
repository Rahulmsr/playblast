from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from maya import cmds

ADMIN_ENV_VAR = "PLAYBLAST_ADMIN"

DEFAULT_SETTINGS = {
    "playblast": {
        "directory": "{scene_dir}",
        "filename": "{scene}",
        "force_overwrite": True,
        "camera": "",
        "hide_default_cameras": True,
        "resolution_preset": "HD 540",
        "width": 960,
        "height": 540,
        "frame_range": "Playback",
        "start_frame": 1,
        "end_frame": 100,
        "step": 1,
        "encoding": "h264 mp4",
        "show_ornaments": False,
        "overscan": False,
        "shot_mask": True,
        "show_in_viewer": True,
        "log_to_script_editor": False,
    },
    "shot_mask": {
        "camera_scope": "<All Cameras>",
        "labels": {
            "top_left": "",
            "top_center": "{scene}",
            "top_right": "",
            "bottom_left": "{user}",
            "bottom_center": "",
            "bottom_right": "{counter}",
        },
        "font_path": "",
        "font_size": 24,
        "text_color": "#FFFFFF",
        "text_alpha": 1.0,
        "text_scale": 1.0,
        "margin": 24,
        "top_bar": True,
        "bottom_bar": True,
        "bar_color": "#000000",
        "bar_alpha": 0.75,
        "bar_height": 48,
        "counter_padding": 4,
        "use_logo": True,
        "logo_path": "",
        "logo_position": "top_left",
        "logo_vertical_align": "middle",
        "logo_width": 120,
        "logo_alpha": 1.0,
    },
    "settings": {
        "ffmpeg_path": "",
        "player_path": "",
        "temp_dir": "{project}/playblasts/.temp",
    },
}


def settings_path() -> str:
    """Return the studio YAML path kept beside the tool."""
    return studio_settings_path()


def studio_settings_path() -> str:
    return (Path(__file__).parent / "settings.yaml").as_posix()


def legacy_settings_path() -> str:
    return (Path(__file__).parent / "settings.json").as_posix()


def user_settings_path() -> str:
    override = os.environ.get("PLAYBLAST_USER_SETTINGS")
    if override:
        return Path(override).expanduser().as_posix()

    user_dir = os.environ.get("PLAYBLAST_USER_CONFIG_DIR")
    if user_dir:
        root = Path(user_dir).expanduser()
    else:
        try:
            root = Path(cmds.internalVar(userAppDir=True))
        except Exception:
            root = Path.home() / "maya"
        root = root / "playblast"
    return (root / "user_settings.yaml").as_posix()


def is_admin_mode() -> bool:
    value = os.environ.get(ADMIN_ENV_VAR, "")
    return value.strip().lower() in {"1", "true", "yes", "on", "supervisor"}


def load_settings() -> dict:
    data = _load_studio_settings()
    _merge_dict(data, _read_mapping(user_settings_path()))
    return data


def clear_user_settings() -> str:
    """Remove per-user overrides so the next load uses studio defaults."""
    path = user_settings_path()
    if os.path.exists(path):
        os.remove(path)
    return path


def save_settings(data: dict) -> str:
    """Save GUI changes as per-user overrides only."""
    studio_data = _load_studio_settings()
    user_data = _diff_dict(studio_data, data)
    path = user_settings_path()
    _write_mapping(path, user_data)
    return path


def save_studio_settings(data: dict) -> str:
    """Write the show-wide YAML. Intended for supervisor/admin mode only."""
    if not is_admin_mode():
        raise RuntimeError(
            "Studio settings can only be saved when {0}=1.".format(ADMIN_ENV_VAR)
        )
    path = studio_settings_path()
    _write_mapping(path, data)
    return path


def reset_playblast(data: dict) -> dict:
    studio_data = _load_studio_settings()
    data["playblast"] = copy.deepcopy(studio_data["playblast"])
    data["settings"]["ffmpeg_path"] = studio_data["settings"].get("ffmpeg_path", "")
    data["settings"]["temp_dir"] = studio_data["settings"].get(
        "temp_dir", DEFAULT_SETTINGS["settings"]["temp_dir"]
    )
    return data


def reset_shot_mask(data: dict) -> dict:
    studio_data = _load_studio_settings()
    data["shot_mask"] = copy.deepcopy(studio_data["shot_mask"])
    return data


def _load_studio_settings() -> dict:
    data = copy.deepcopy(DEFAULT_SETTINGS)
    studio_yaml = _read_mapping(studio_settings_path())
    if studio_yaml:
        _merge_dict(data, studio_yaml)
        return data

    legacy_json = _read_json_mapping(legacy_settings_path())
    if legacy_json:
        _merge_dict(data, legacy_json)
    return data


def _read_json_mapping(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as stream:
            data = json.load(stream)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_mapping(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as stream:
            return _parse_yaml(stream.read())
    except Exception:
        return {}


def _write_mapping(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(path, "w") as stream:
        stream.write(_dump_yaml(data))


def _merge_dict(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = value


def _diff_dict(base: dict, current: dict) -> dict:
    diff = {}
    for key, value in current.items():
        base_value = base.get(key)
        if isinstance(value, dict) and isinstance(base_value, dict):
            nested = _diff_dict(base_value, value)
            if nested:
                diff[key] = nested
        elif value != base_value:
            diff[key] = value
    return diff


def _parse_yaml(text: str) -> dict:
    root = {}
    stack = [(-1, root)]

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        item = line.strip()
        if ":" not in item:
            continue

        key, raw_value = item.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if raw_value == "":
            value = {}
            parent[key] = value
            stack.append((indent, value))
        else:
            parent[key] = _parse_scalar(raw_value)

    return root


def _parse_scalar(value: str):
    value = value.strip()
    if value in {"''", '""'}:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1].replace("\\'", "'").replace('\\"', '"')
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _dump_yaml(data: dict, indent: int = 0) -> str:
    lines = []
    for key, value in data.items():
        prefix = " " * indent + str(key) + ":"
        if isinstance(value, dict):
            lines.append(prefix)
            lines.append(_dump_yaml(value, indent + 2).rstrip())
        else:
            lines.append(prefix + " " + _format_scalar(value))
    return "\n".join(line for line in lines if line != "") + "\n"


def _format_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if text == "":
        return "''"
    needs_quotes = (
        text.strip() != text
        or any(char in text for char in [":", "#", "{", "}", "\\"])
        or text.lower() in {"true", "false", "null", "none"}
    )
    if needs_quotes:
        return "'" + text.replace("'", "\\'") + "'"
    return text
