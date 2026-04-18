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
    per_image = 4.0

    # Build cycled image list to cover the full audio duration
    n = len(image_paths)
    total_slots = max(1, int(duration / per_image) + 1)
    cycled = [image_paths[i % n] for i in range(total_slots)]

    concat_path = os.path.join(os.path.dirname(output_path), "concat.txt")
    with open(concat_path, "w") as f:
        for path in cycled:
            f.write(f"file '{os.path.abspath(path)}'\n")
            f.write(f"duration {per_image:.3f}\n")
        f.write(f"file '{os.path.abspath(cycled[-1])}'\n")

    # Scale image to fit 1080x1920 with black letterbox; burn subtitles if libass is available
    abs_srt = os.path.abspath(srt_path)
    letterbox = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    )
    has_libass = "subtitles" in subprocess.run(
        ["ffmpeg", "-filters"], capture_output=True, text=True
    ).stdout
    if has_libass:
        force_style = "FontSize=22\\,PrimaryColour=&Hffffff\\,OutlineColour=&H000000\\,Outline=2\\,Alignment=2"
        vf = f"{letterbox},subtitles='{abs_srt}':force_style={force_style}"
    else:
        logger.warning("libass not available — producing video without burned subtitles")
        vf = letterbox

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
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg failed:\n%s", e.stderr.decode(errors="replace"))
        raise
    logger.info("Video saved to %s", output_path)
    return output_path
