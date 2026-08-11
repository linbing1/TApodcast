import logging
import os
import shutil
import subprocess

from src.frame_renderer import render_frames
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
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp3_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


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


def assemble_video(
    image_paths: list[str],
    mp3_path: str,
    srt_path: str,
    output_path: str,
    title: str = "",
    article_date: str = "",
) -> str:
    del title, article_date

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
        srt_path=srt_path,
        title="",
        article_date="",
        output_dir=output_dir,
        img_top=0,
        lead_in=0.0,
    )

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
        output_path,
    ]

    logger.info("Running FFmpeg with burned-in ASS subtitles...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        logger.error("ffmpeg failed:\n%s", error.stderr or "")
        raise
    logger.info("Video saved to %s", output_path)
    return output_path
