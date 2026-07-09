from __future__ import annotations

import os

from maya import cmds, mel

from . import tokens

DEFAULT_CAMERAS = {"front", "persp", "side", "top"}
LEGACY_PROJECT_DIRECTORIES = {"{project}/playblast", "{project}/playblasts"}


RESOLUTION_PRESETS = {
    "HD 540": (960, 540),
    "HD 720": (1280, 720),
    "HD 1080": (1920, 1080),
    "Square 1080": (1080, 1080),
    "UHD 4K": (3840, 2160),
    "Custom": None,
}


def cameras(include_defaults: bool = False) -> list[str]:
    result = []
    for shape in cmds.ls(type="camera", long=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        if not parents:
            continue
        camera = parents[0]
        if not include_defaults and camera in DEFAULT_CAMERAS:
            continue
        result.append(camera)
    return sorted(set(result))


def active_camera() -> str:
    panel = cmds.getPanel(withFocus=True)
    if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
        try:
            return cmds.modelPanel(panel, query=True, camera=True)
        except Exception:
            pass
    cams = cameras(include_defaults=False) or cameras(include_defaults=True)
    return cams[0] if cams else ""


def frame_range(mode: str, start_frame: int, end_frame: int) -> tuple[int, int]:
    mode = str(mode or "").lower()
    if mode == "selected":
        selected = selected_time_slider_range()
        if selected:
            return selected
        return (
            int(cmds.playbackOptions(query=True, minTime=True)),
            int(cmds.playbackOptions(query=True, maxTime=True)),
        )
    if mode == "animation":
        return (
            int(cmds.playbackOptions(query=True, animationStartTime=True)),
            int(cmds.playbackOptions(query=True, animationEndTime=True)),
        )
    if mode == "playback":
        return (
            int(cmds.playbackOptions(query=True, minTime=True)),
            int(cmds.playbackOptions(query=True, maxTime=True)),
        )
    if mode == "render":
        return (
            int(cmds.getAttr("defaultRenderGlobals.startFrame")),
            int(cmds.getAttr("defaultRenderGlobals.endFrame")),
        )
    return int(start_frame), int(end_frame)


def timeline_sound() -> str:
    """Return the sound node assigned to Maya's playback slider."""
    try:
        playback_slider = mel.eval("$tmp=$gPlayBackSlider")
        sound = cmds.timeControl(playback_slider, query=True, sound=True)
        if sound:
            return sound
    except Exception:
        pass

    sounds = cmds.ls(type="audio") or []
    return sounds[0] if sounds else ""


def selected_time_slider_range():
    """Return the highlighted playback-slider range, if Maya has one selected."""
    try:
        playback_slider = mel.eval("$tmp=$gPlayBackSlider")
        if not cmds.timeControl(playback_slider, query=True, rangeVisible=True):
            return None
        range_values = cmds.timeControl(playback_slider, query=True, rangeArray=True)
    except Exception:
        return None

    if not range_values or len(range_values) < 2:
        return None
    start = int(round(float(range_values[0])))
    end = int(round(float(range_values[1]))) - 1
    if end < start:
        end = start
    return start, end


def _resolve_audio_path(path: str) -> str:
    audio_path = os.path.expanduser(os.path.expandvars(str(path or "")))
    if not audio_path:
        return ""
    candidates = [audio_path]
    if not os.path.isabs(audio_path):
        try:
            candidates.append(cmds.workspace(expandName=audio_path))
        except Exception:
            pass
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if os.path.exists(normalized):
            return normalized
    return ""


def _sound_time(sound: str, name: str) -> float:
    try:
        return float(cmds.sound(sound, query=True, **{name: True}))
    except Exception:
        pass
    try:
        attr = sound + "." + name
        if cmds.objExists(attr):
            return float(cmds.getAttr(attr))
    except Exception:
        pass
    return 0.0


def timeline_audio_clip(start_frame: int, end_frame: int) -> dict:
    sound = timeline_sound()
    if not sound:
        return {}

    try:
        audio_path = cmds.sound(sound, query=True, file=True)
    except Exception:
        audio_path = (
            cmds.getAttr(sound + ".filename")
            if cmds.objExists(sound + ".filename")
            else ""
        )
    audio_path = _resolve_audio_path(audio_path)
    if not audio_path:
        return {}

    sound_offset = _sound_time(sound, "offset")
    source_start = _sound_time(sound, "sourceStart")

    fps = playback_fps()
    duration = max(0.0, ((int(end_frame) - int(start_frame)) + 1) / float(fps))
    frame_delta = float(start_frame) - sound_offset
    trim_start = (source_start / float(fps)) + max(0.0, frame_delta / float(fps))
    delay = max(0.0, -frame_delta / float(fps))

    return {
        "node": sound,
        "path": audio_path,
        "trim_start": trim_start,
        "delay": delay,
        "duration": duration,
    }


def capture_sequence(options: dict, temp_dir: str, log) -> tuple[str, int, int]:
    camera = options.get("camera") or active_camera()
    start, end = frame_range(
        options.get("frame_range"),
        options.get("start_frame", 1),
        options.get("end_frame", 100),
    )
    width = int(options.get("width") or 960)
    height = int(options.get("height") or 540)
    step = max(1, int(options.get("step") or 1))

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    frame_pattern = os.path.join(temp_dir, "capture")
    log(
        "Capturing frames: {0} to {1} on {2}".format(
            start, end, camera or "active camera"
        )
    )
    kwargs = {
        "format": "image",
        "filename": frame_pattern,
        "sequenceTime": False,
        "clearCache": True,
        "viewer": False,
        "showOrnaments": bool(options.get("show_ornaments")),
        "offScreen": True,
        "framePadding": 4,
        "percent": 100,
        "compression": "png",
        "widthHeight": (width, height),
        "startTime": start,
        "endTime": end,
    }
    # if camera:
    #     kwargs["camera"] = camera

    previous_frame = cmds.currentTime(query=True)
    try:
        if step == 1:
            cmds.playblast(**kwargs)
        else:
            for frame in range(start, end + 1, step):
                cmds.currentTime(frame, edit=True)
                per_frame = dict(kwargs)
                per_frame["startTime"] = frame
                per_frame["endTime"] = frame
                cmds.playblast(**per_frame)
    finally:
        cmds.currentTime(previous_frame, edit=True)

    return os.path.join(temp_dir, "capture.%04d.png"), start, end


def output_directory(options: dict, camera: str = "") -> str:
    directory = str(options.get("directory", "") or "").strip()
    if is_legacy_project_directory(directory):
        directory = "{scene_dir}"
    return tokens.expand(directory or "{scene_dir}", camera=camera)


def output_path(options: dict, camera: str = "") -> str:
    directory = output_directory(options, camera=camera)
    filename = tokens.expand(options.get("filename", ""), camera=camera)
    if not os.path.splitext(filename)[1]:
        filename += (
            ".mp4" if "mp4" in str(options.get("encoding", "")).lower() else ".mov"
        )
    return os.path.normpath(os.path.join(directory, filename))


def _normalized_template(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def is_legacy_project_directory(value: str) -> bool:
    return _normalized_template(value) in LEGACY_PROJECT_DIRECTORIES


def playback_fps() -> int:
    unit = cmds.currentUnit(query=True, time=True)
    return {
        "film": 24,
        "pal": 25,
        "ntsc": 30,
        "show": 48,
        "palf": 50,
        "ntscf": 60,
    }.get(unit, 24)
