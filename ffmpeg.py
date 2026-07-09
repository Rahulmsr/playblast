from __future__ import annotations

import os
import subprocess
import sys

from . import tokens

ZONE_EXPRESSIONS = {
    "top_left": ("x={margin}", "y={top_y}"),
    "top_center": ("x=(w-text_w)/2", "y={top_y}"),
    "top_right": ("x=w-text_w-{margin}", "y={top_y}"),
    "bottom_left": ("x={margin}", "y=h-{bottom_offset}"),
    "bottom_center": ("x=(w-text_w)/2", "y=h-{bottom_offset}"),
    "bottom_right": ("x=w-text_w-{margin}", "y=h-{bottom_offset}"),
}

LINE_SPACING = 4


def encode_sequence(
    ffmpeg_path: str,
    input_pattern: str,
    output_path: str,
    start_frame: int,
    options: dict,
    shot_mask: dict,
    camera: str,
    log,
    audio_clip: dict = None,
) -> str:
    if not ffmpeg_path or not os.path.exists(ffmpeg_path):
        raise RuntimeError("ffmpeg executable was not found. Set it in Settings.")

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    force = bool(options.get("force_overwrite"))
    if os.path.exists(output_path) and not force:
        raise RuntimeError("Output already exists: {0}".format(output_path))

    filters = build_filters(shot_mask, camera, start_frame)
    encoding = str(options.get("encoding", "h264 mp4")).lower()
    command = [
        ffmpeg_path,
        "-y" if force else "-n",
        "-framerate",
        str(int(_playback_fps())),
        "-start_number",
        str(int(start_frame)),
        "-err_detect",
        "ignore_err",
        "-i",
        input_pattern,
    ]

    logo_path = shot_mask.get("logo_path", "")
    has_logo = bool(
        shot_mask.get("use_logo", True)
        and logo_path
        and os.path.exists(tokens.expand(logo_path, camera=camera))
    )
    if has_logo:
        command.extend(["-i", tokens.expand(logo_path, camera=camera)])

    has_audio = bool(
        audio_clip
        and audio_clip.get("path")
        and os.path.exists(audio_clip.get("path"))
        and "sequence" not in encoding
    )
    audio_input_index = 2 if has_logo else 1
    if has_audio:
        command.extend(["-i", audio_clip["path"]])

    if filters:
        if has_logo and has_audio:
            command.extend(["-filter_complex", filters + "[vout]"])
        else:
            command.extend(["-filter_complex" if has_logo else "-vf", filters])

    if has_audio:
        if has_logo and filters:
            command.extend(["-map", "[vout]"])
        else:
            command.extend(["-map", "0:v:0"])
        command.extend(["-map", "{0}:a:0".format(audio_input_index)])
        command.extend(_audio_filter_args(audio_clip))
        command.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
        log(
            "Adding timeline audio: {0}".format(
                audio_clip.get("node", audio_clip["path"])
            )
        )

    if "mov" in encoding:
        command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", output_path])
    elif "sequence" in encoding:
        command.extend(["-compression_level", "4", output_path])
    else:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "medium",
                "-pix_fmt",
                "yuv420p",
                output_path,
            ]
        )

    log("Running ffmpeg encode.")
    log("ffmpeg command: {0}".format(_command_for_log(command)))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    for line in process.stdout or []:
        text = line.strip()
        if text:
            log(text)
    code = process.wait()
    if code:
        signed_code = code - 4294967296 if code > 2147483647 else code
        raise RuntimeError("ffmpeg failed with exit code {0}".format(signed_code))
    return output_path


def _audio_filter_args(audio_clip: dict) -> list[str]:
    duration = max(0.0, float(audio_clip.get("duration") or 0.0))
    trim_start = max(0.0, float(audio_clip.get("trim_start") or 0.0))
    delay = max(0.0, float(audio_clip.get("delay") or 0.0))

    filters = [
        "atrim=start={0}:duration={1}".format(_seconds(trim_start), _seconds(duration)),
        "asetpts=PTS-STARTPTS",
    ]
    if delay > 0.0:
        delay_ms = int(round(delay * 1000.0))
        filters.append("adelay={0}|{0}".format(delay_ms))

    return ["-af", ",".join(filters), "-t", _seconds(duration)]


def _seconds(value: float) -> str:
    return "{0:.6f}".format(float(value)).rstrip("0").rstrip(".") or "0"


def _command_for_log(command: list[str]) -> str:
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(command)
    return " ".join(_quote_arg(arg) for arg in command)


def _quote_arg(value: str) -> str:
    text = str(value)
    if not text or any(char.isspace() for char in text):
        return "'" + text.replace("'", "'''") + "'"
    return text


def build_filters(shot_mask: dict, camera: str, start_frame: int) -> str:
    parts = []
    width_expr = "iw"
    margin = int(shot_mask.get("margin") or 24)
    bar_height = int(shot_mask.get("bar_height") or 48)
    font_size = int(
        (shot_mask.get("font_size") or 24) * float(shot_mask.get("text_scale") or 1.0)
    )

    if shot_mask.get("top_bar"):
        parts.append(
            "drawbox=x=0:y=0:w={0}:h={1}:color={2}@{3}:t=fill".format(
                width_expr,
                bar_height,
                _hex_to_ffmpeg(shot_mask.get("bar_color", "#000000")),
                _clamp(shot_mask.get("bar_alpha", 0.75)),
            )
        )
    if shot_mask.get("bottom_bar"):
        parts.append(
            "drawbox=x=0:y=ih-{0}:w={1}:h={0}:color={2}@{3}:t=fill".format(
                bar_height,
                width_expr,
                _hex_to_ffmpeg(shot_mask.get("bar_color", "#000000")),
                _clamp(shot_mask.get("bar_alpha", 0.75)),
            )
        )

    labels = shot_mask.get("labels", {})
    padding = int(shot_mask.get("counter_padding") or 4)
    for zone, raw_text in labels.items():
        if not raw_text:
            continue
        # text = tokens.expand(raw_text, camera=camera, counter="{n}")
        # text = text.replace("{counter}", "%{n}")
        # text = text.replace("{frame}", "%{n}")
        # text = text.replace("%{n}", "%{eif\\:n\\:d\\:" + str(padding) + "}")

        # 1. Hide the counter/frame tags
        safe_text = raw_text.replace("{counter}", "__FFMPEG_COUNTER__")
        safe_text = safe_text.replace("{frame}", "__FFMPEG_COUNTER__")

        # 2. Expand normal tokens safely
        text = tokens.expand(safe_text, camera=camera)

        # 3. Inject the FFmpeg math (n + start_frame)
        # If n=0 and start_frame=1001, it evaluates to 1001.
        ffmpeg_pad_string = "%{eif:n+" + str(start_frame) + ":d:" + str(padding) + "}"
        text = text.replace("__FFMPEG_COUNTER__", ffmpeg_pad_string)

        lines = _label_lines(text)
        for index, line_text in enumerate(lines):
            x_expr, y_expr = _line_position(
                zone,
                index,
                len(lines),
                margin,
                bar_height,
                font_size,
            )
            parts.append(
                "drawtext={font}text='{text}':{x}:{y}:fontsize={size}:fontcolor={color}@{alpha}:box=0".format(
                    font=_font_arg(shot_mask.get("font_path", "")),
                    text=_escape_drawtext(line_text),
                    x=x_expr,
                    y=y_expr,
                    size=font_size,
                    color=_hex_to_ffmpeg(shot_mask.get("text_color", "#FFFFFF")),
                    alpha=_clamp(shot_mask.get("text_alpha", 1.0)),
                )
            )

    logo_path = shot_mask.get("logo_path", "")
    if (
        shot_mask.get("use_logo", True)
        and logo_path
        and os.path.exists(tokens.expand(logo_path, camera=camera))
    ):
        logo_width = int(shot_mask.get("logo_width") or 120)
        logo_alpha = _clamp(shot_mask.get("logo_alpha", 1.0))
        pos = _logo_position(
            shot_mask.get("logo_position", "top_left"),
            shot_mask.get("logo_vertical_align", "middle"),
            margin,
            bar_height,
        )
        parts.append(
            "[1:v]scale={0}:-1,colorchannelmixer=aa={1}[logo];[0:v]{base}[base];[base][logo]overlay={2}:{3}".format(
                logo_width,
                logo_alpha,
                pos[0],
                pos[1],
                base=",".join(parts) if parts else "null",
            )
        )
        return parts[-1]

    return ",".join(parts)


def _playback_fps() -> int:
    from maya import cmds

    unit = cmds.currentUnit(query=True, time=True)
    return {
        "film": 24,
        "pal": 25,
        "ntsc": 30,
        "show": 48,
        "palf": 50,
        "ntscf": 60,
    }.get(unit, 24)


def _font_arg(path: str) -> str:
    path = tokens.expand(path).replace("\\", "/") if path else _default_font_path()
    if not path:
        return ""
    return "fontfile='{0}':".format(_escape_drawtext(path))


def _default_font_path() -> str:
    for path in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ):
        if os.path.exists(path):
            return path.replace("\\", "/")
    return ""


def _escape_drawtext(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _label_lines(value: str) -> list[str]:
    normalized = str(value or "").replace("\\n", "\n")
    return [line for line in normalized.splitlines() if line]


def _line_position(
    zone: str,
    line_index: int,
    line_count: int,
    margin: int,
    bar_height: int,
    font_size: int,
) -> tuple[str, str]:
    x_expr, _y_expr = ZONE_EXPRESSIONS.get(zone, ZONE_EXPRESSIONS["top_left"])
    line_height = font_size + LINE_SPACING
    block_height = (line_count * font_size) + ((line_count - 1) * LINE_SPACING)

    if zone.startswith("bottom"):
        start_y = "h-{0}".format(
            max(font_size + 2, int((bar_height + block_height) / 2))
        )
        y_expr = "{0}+{1}".format(start_y, line_index * line_height)
    else:
        start_y = str(max(2, int((bar_height - block_height) / 2)))
        y_expr = str(int(start_y) + (line_index * line_height))

    return (
        x_expr.format(margin=margin, top_y=0, bottom_offset=0),
        "y=" + y_expr,
    )


def _hex_to_ffmpeg(value: str) -> str:
    value = str(value or "#FFFFFF").strip()
    if value.startswith("#"):
        return "0x" + value[1:]
    return value


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 1.0


def _logo_position(
    position: str,
    vertical_align: str,
    margin: int,
    bar_height: int,
) -> tuple[str, str]:
    position = str(position or "top_left").lower()
    vertical_align = str(vertical_align or "middle").lower()
    x = str(margin)
    if "right" in position:
        x = "main_w-overlay_w-{0}".format(margin)
    elif "center" in position:
        x = "(main_w-overlay_w)/2"

    if "bottom" in position:
        if vertical_align == "edge":
            y = "main_h-overlay_h"
        else:
            y = "main_h-{0}+({0}-overlay_h)/2".format(bar_height)
    else:
        if vertical_align == "edge":
            y = "0"
        else:
            y = "({0}-overlay_h)/2".format(bar_height)

    return x, y
