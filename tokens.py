
from __future__ import annotations

import getpass
import os
from datetime import datetime

from maya import cmds


def scene_path() -> str:
    return cmds.file(query=True, sceneName=True) or ""


def scene_dir() -> str:
    path = scene_path()
    if path:
        return os.path.dirname(path)
    return project_root()


def scene_name() -> str:
    path = scene_path()
    if not path:
        return "untitled"
    return os.path.splitext(os.path.basename(path))[0]


def project_root() -> str:
    root = cmds.workspace(query=True, rootDirectory=True) or os.getcwd()
    return os.path.normpath(root)


def focal_length(camera: str) -> str:
    if not camera:
        return ""
    shape = camera
    shapes = cmds.listRelatives(camera, shapes=True, fullPath=True) or []
    if shapes:
        shape = shapes[0]
    try:
        value = cmds.getAttr(shape + ".focalLength")
        return str(round(float(value), 2))
    except Exception:
        return ""


def context(
    camera: str = "", frame: int | None = None, counter: int | None = None
) -> dict:
    now = datetime.now()
    return {
        "project": project_root(),
        "scene": scene_name(),
        "scene_dir": scene_dir(),
        "scene_path": scene_path(),
        "camera": camera or "",
        "frame": "" if frame is None else str(int(frame)),
        "counter": "" if counter is None else str(counter),
        "focal_length": focal_length(camera),
        "user": getpass.getuser(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
    }


def expand(
    value: str, camera: str = "", frame: int | None = None, counter: int | None = None
) -> str:
    result = str(value or "")
    values = context(camera=camera, frame=frame, counter=counter)
    for key, token_value in values.items():
        result = result.replace("{" + key + "}", str(token_value))
    return os.path.normpath(result) if _looks_like_path(result) else result


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.startswith(".")
