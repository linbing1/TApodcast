import logging
import math
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from typing import Any

from src.frame_renderer import render_frames
from src.media import probe_media
from src.subtitle_renderer import find_cjk_font, write_ass_from_vtt

logger = logging.getLogger(__name__)

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
PER_IMAGE_SECONDS = 5.0

_FFMPEG_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)


def get_audio_duration(mp3_path: str) -> float:
    duration = probe_media(mp3_path).get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"ffprobe did not return an audio duration for {mp3_path}")
    return float(duration)


def _supports_libass(ffmpeg_path: str) -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    filters = f"{result.stdout}\n{result.stderr}"
    return " ass " in filters and " subtitles " in filters


def find_ffmpeg() -> str:
    configured_path = os.environ.get("FFMPEG_BIN")
    candidates = ((configured_path,) if configured_path else ()) + _FFMPEG_CANDIDATES
    regular_ffmpeg = shutil.which("ffmpeg")
    if regular_ffmpeg:
        candidates += (regular_ffmpeg,)

    checked: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        executable = shutil.which(candidate) or candidate
        if executable in checked:
            continue
        checked.append(executable)
        if _supports_libass(executable):
            return executable

    raise RuntimeError(
        "需要支持 libass 的 FFmpeg 才能烧录字幕。"
        "macOS 可运行 `brew install ffmpeg-full`，"
        "或通过 `FFMPEG_BIN` 指定带 ass/subtitles 滤镜的 ffmpeg。"
    )


def _escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ass_filter(ass_path: str, font_path: str | None) -> str:
    filter_value = f"ass=filename='{_escape_filter_value(ass_path)}'"
    if font_path:
        font_dir = os.path.dirname(font_path) or "."
        filter_value += f":fontsdir='{_escape_filter_value(font_dir)}'"
    return filter_value


def _frame_rate(stream: dict[str, Any]) -> float | None:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not value:
        return None
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def validate_video(path: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Video was not created: {path}")
    if os.path.getsize(path) == 0:
        raise ValueError(f"Video is empty: {path}")

    metadata = probe_media(path)
    streams = metadata.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    format_duration = metadata.get("format", {}).get("duration")

    problems: list[str] = []
    if video_stream is None:
        problems.append("缺少视频流")
    else:
        if video_stream.get("codec_name") != "h264":
            problems.append(f"视频编码不是 H.264（实际为 {video_stream.get('codec_name')}）")
        if (
            video_stream.get("width") != VIDEO_WIDTH
            or video_stream.get("height") != VIDEO_HEIGHT
        ):
            problems.append(
                "分辨率不是 1080x1920 "
                f"（实际为 {video_stream.get('width')}x{video_stream.get('height')}）"
            )
        frame_rate = _frame_rate(video_stream)
        if frame_rate is None or not math.isclose(frame_rate, 30.0, abs_tol=0.01):
            problems.append(f"帧率不是 30fps（实际为 {frame_rate}）")

    if audio_stream is None:
        problems.append("缺少音频流")
    elif audio_stream.get("codec_name") != "aac":
        problems.append(f"音频编码不是 AAC（实际为 {audio_stream.get('codec_name')}）")

    try:
        duration = float(format_duration)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        problems.append(f"视频时长无效（实际为 {format_duration}）")

    if problems:
        raise ValueError(f"视频校验失败：{'; '.join(problems)}")


def _temporary_video_path(output_path: str, output_dir: str) -> str:
    prefix = f".{os.path.basename(output_path)}."
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp.mp4",
        dir=output_dir,
    )
    os.close(descriptor)
    return temporary_path


def cleanup_frames(output_dir: str) -> bool:
    frames_dir = os.path.join(output_dir, "frames")
    if not os.path.isdir(frames_dir):
        return False
    shutil.rmtree(frames_dir, ignore_errors=True)
    logger.info("Removed intermediate frames directory: %s", frames_dir)
    return True


def assemble_video(
    image_paths: list[str],
    mp3_path: str,
    srt_path: str,
    output_path: str,
    image_captions: list[str] | None = None,
) -> str:
    duration = get_audio_duration(mp3_path)
    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_path = find_ffmpeg()
    font_path = find_cjk_font()
    if not font_path:
        raise RuntimeError(
            "未找到可用于中文字幕的字体。"
            "请安装 Noto Sans CJK SC，或通过 `CJK_FONT_PATH` 指定字体文件。"
        )

    ass_path = os.path.join(output_dir, "subtitles.ass")
    write_ass_from_vtt(srt_path, ass_path)

    logger.info("Rendering black vertical frames (%dx%d)...", VIDEO_WIDTH, VIDEO_HEIGHT)
    frames_dir, fps = render_frames(
        image_paths=image_paths,
        duration=duration,
        per_image=PER_IMAGE_SECONDS,
        output_dir=output_dir,
        image_captions=image_captions,
        font_path=font_path,
    )

    temporary_output_path = _temporary_video_path(output_path, output_dir)

    cmd = [
        ffmpeg_path,
        "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%05d.jpg"),
        "-i", mp3_path,
        "-vf", _ass_filter(ass_path, font_path),
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-b:v", "4M",
        "-b:a", "192k",
        "-c:a", "aac",
        "-t", f"{duration:.3f}",
        temporary_output_path,
    ]

    logger.info("Running FFmpeg with burned-in ASS subtitles...")
    try:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            logger.error("ffmpeg failed:\n%s", error.stderr or "")
            raise
        validate_video(temporary_output_path)
        os.replace(temporary_output_path, output_path)
    finally:
        if os.path.exists(temporary_output_path):
            os.remove(temporary_output_path)

    cleanup_frames(output_dir)
    logger.info("Video saved to %s", output_path)
    return output_path
