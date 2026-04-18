import logging
import os
import subprocess

logger = logging.getLogger(__name__)


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


def assemble_video(
    image_paths: list[str],
    mp3_path: str,
    srt_path: str,
    output_path: str,
) -> str:
    duration = get_audio_duration(mp3_path)
    n = len(image_paths)
    per_image = duration / n

    concat_path = os.path.join(os.path.dirname(output_path), "concat.txt")
    with open(concat_path, "w") as f:
        for path in image_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")
            f.write(f"duration {per_image:.3f}\n")
        f.write(f"file '{os.path.abspath(image_paths[-1])}'\n")

    # Scale image to fill 1080x1920 (crop center), burn subtitles
    abs_srt = os.path.abspath(srt_path)
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles='{abs_srt}':force_style="
        "'FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_path,
        "-i", mp3_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    logger.info("Running ffmpeg to assemble video...")
    subprocess.run(cmd, check=True, capture_output=True)
    logger.info("Video saved to %s", output_path)
    return output_path
