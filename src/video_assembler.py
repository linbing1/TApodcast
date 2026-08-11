import logging
import os
import subprocess

from src.frame_renderer import render_frames

logger = logging.getLogger(__name__)

_VIDEO_W = 1080
_VIDEO_H = 1920
_TAIL_SECS = 2
_PER_IMAGE = 5.0


def get_audio_duration(mp3_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp3_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _image_top(img_path: str) -> int:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            img_path,
        ],
        capture_output=True, text=True,
    )
    try:
        w, h = map(int, result.stdout.strip().split(","))
        scale = min(_VIDEO_W / w, _VIDEO_H / h)
        scaled_h = int(h * scale)
        return (_VIDEO_H - scaled_h) // 2
    except Exception:
        return 600


def assemble_video(
    image_paths: list[str],
    mp3_path: str,
    srt_path: str,
    output_path: str,
    title: str = "",
    article_date: str = "",
) -> str:
    _LEAD_IN = 1.0
    duration = get_audio_duration(mp3_path)
    total_duration = _LEAD_IN + duration + _TAIL_SECS
    output_dir = os.path.dirname(output_path)

    img_top = _image_top(image_paths[0])
    logger.info("Image top y=%d (video %dx%d)", img_top, _VIDEO_W, _VIDEO_H)

    logger.info("Rendering frames with Pillow (blurred background + subtitles)...")
    frames_dir, fps = render_frames(
        image_paths=image_paths,
        duration=total_duration,
        per_image=_PER_IMAGE,
        srt_path=srt_path,
        title=title,
        article_date=article_date,
        output_dir=output_dir,
        img_top=img_top,
        lead_in=_LEAD_IN,
    )

    adelay_ms = int(_LEAD_IN * 1000)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%05d.jpg"),
        "-i", mp3_path,
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-b:v", "4M", "-b:a", "192k", "-c:a", "aac",
        "-af", f"adelay={adelay_ms}:all=1",
        "-t", f"{total_duration:.3f}",
        output_path,
    ]

    logger.info("Running ffmpeg to assemble video...")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg failed:\n%s", e.stderr.decode(errors="replace"))
        raise
    logger.info("Video saved to %s", output_path)
    return output_path
