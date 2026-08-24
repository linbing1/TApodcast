import asyncio
import logging
import os
import re
import shutil
import subprocess

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException

from src.models import PodcastScript

logger = logging.getLogger(__name__)

_CUE_TIMING_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
# Edge TTS 的词时间轴允许略微超出实际音频结尾，留出容差避免误报。
_TRUNCATION_TOLERANCE_SECONDS = 0.5
_SCRIPT_TAIL_CHARS = 6
_MAX_TTS_ATTEMPTS = 3
_TTS_RETRY_DELAY_SECONDS = 5


class TtsOutputTruncatedError(RuntimeError):
    """Edge TTS 流被提前关闭，音频或字幕没有覆盖完整稿件。"""


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


def probe_audio_duration(path: str) -> float | None:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        logger.warning("Could not probe audio duration for %s: %s", path, exc)
        return None


def _normalize_for_match(text: str) -> str:
    return "".join(char for char in text if char.isalnum())


def _last_cue_end_seconds(srt_text: str) -> float | None:
    last_end: float | None = None
    for match in _CUE_TIMING_RE.finditer(srt_text):
        hours, minutes, seconds, millis = (int(value) for value in match.group(5, 6, 7, 8))
        last_end = hours * 3600 + minutes * 60 + seconds + millis / 1000
    return last_end


def validate_tts_output(script_text: str, srt_text: str, audio_duration: float | None) -> None:
    """校验 TTS 产物覆盖完整稿件，防止静默截断流入视频阶段。"""
    normalized_script = _normalize_for_match(script_text)
    normalized_srt = _normalize_for_match(srt_text)
    if normalized_script and normalized_srt:
        tail = normalized_script[-_SCRIPT_TAIL_CHARS:]
        if tail not in normalized_srt:
            raise TtsOutputTruncatedError(
                f"字幕未覆盖稿件结尾（缺少结尾「{tail}」），TTS 输出疑似被截断"
            )

    last_end = _last_cue_end_seconds(srt_text)
    if audio_duration is not None and last_end is not None:
        if audio_duration + _TRUNCATION_TOLERANCE_SECONDS < last_end:
            raise TtsOutputTruncatedError(
                f"音频时长 {audio_duration:.2f}s 早于最后一条字幕结束时间 {last_end:.2f}s，"
                "TTS 音频流疑似被截断"
            )


def _is_retryable_tts_error(error: Exception) -> bool:
    return isinstance(
        error,
        (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ConnectionError,
            EdgeTTSException,
            TtsOutputTruncatedError,
        ),
    )


def _temporary_output_paths(output_dir: str, attempt: int) -> tuple[str, str]:
    prefix = f".{os.getpid()}.{attempt}"
    return (
        os.path.join(output_dir, f"audio.mp3{prefix}.tmp"),
        os.path.join(output_dir, f"audio.vtt{prefix}.tmp"),
    )


async def generate_tts(script: PodcastScript, voice: str, output_dir: str, rate: str = "+0%") -> tuple[str, str]:
    mp3_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "audio.vtt")
    logger.info(
        "Generating TTS (script=%d chars, voice=%s, rate=%s)",
        len(script.text),
        voice,
        rate,
    )

    for attempt in range(1, _MAX_TTS_ATTEMPTS + 1):
        temporary_mp3_path, temporary_srt_path = _temporary_output_paths(output_dir, attempt)
        try:
            communicate = edge_tts.Communicate(script.text, voice, rate=rate)
            submaker = edge_tts.SubMaker()

            with open(temporary_mp3_path, "wb") as mp3_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        mp3_file.write(chunk["data"])
                    elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                        submaker.feed(chunk)

            srt_content = submaker.get_srt()
            with open(temporary_srt_path, "w", encoding="utf-8") as srt_file:
                srt_file.write(srt_content)

            audio_duration = probe_audio_duration(temporary_mp3_path)
            if audio_duration is None:
                logger.warning(
                    "ffprobe 不可用，跳过 TTS 音频时长校验: %s",
                    temporary_mp3_path,
                )
            validate_tts_output(script.text, srt_content, audio_duration)

            os.replace(temporary_mp3_path, mp3_path)
            os.replace(temporary_srt_path, srt_path)
            subtitle_end = _last_cue_end_seconds(srt_content)
            logger.info(
                "Generated audio (attempt=%d, duration=%s, subtitles_end=%s, audio_bytes=%d): %s; subtitles: %s",
                attempt,
                f"{audio_duration:.2f}s" if audio_duration is not None else "unknown",
                f"{subtitle_end:.2f}s" if subtitle_end is not None else "unknown",
                os.path.getsize(mp3_path),
                mp3_path,
                srt_path,
            )
            return mp3_path, srt_path
        except Exception as error:
            if not _is_retryable_tts_error(error) or attempt == _MAX_TTS_ATTEMPTS:
                raise
            logger.warning(
                "Retryable TTS failure (attempt %d/%d): %s. Retrying in %ds...",
                attempt,
                _MAX_TTS_ATTEMPTS,
                error,
                _TTS_RETRY_DELAY_SECONDS,
            )
            await asyncio.sleep(_TTS_RETRY_DELAY_SECONDS)
        finally:
            for temporary_path in (temporary_mp3_path, temporary_srt_path):
                try:
                    os.remove(temporary_path)
                except FileNotFoundError:
                    pass
