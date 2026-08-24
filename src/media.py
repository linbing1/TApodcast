import json
import os
import shutil
import subprocess
from typing import Any


def find_ffprobe() -> str | None:
    configured = os.environ.get("FFPROBE_BIN")
    candidates = ((configured,) if configured else ()) + ("ffprobe",)
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def probe_media(path: str) -> dict[str, Any]:
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise RuntimeError(
            "需要 ffprobe 才能校验媒体文件。请安装 FFmpeg，"
            "或通过 `FFPROBE_BIN` 指定 ffprobe。"
        )

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(result.stdout)
    if not isinstance(metadata, dict):
        raise ValueError(f"ffprobe returned invalid metadata for {path}")
    return metadata
