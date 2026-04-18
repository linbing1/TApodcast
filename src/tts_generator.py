import logging
import os

import edge_tts

from src.models import PodcastScript

logger = logging.getLogger(__name__)


async def generate_tts(script: PodcastScript, voice: str, output_dir: str) -> tuple[str, str]:
    mp3_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "audio.vtt")

    communicate = edge_tts.Communicate(script.text, voice)
    submaker = edge_tts.SubMaker()

    with open(mp3_path, "wb") as mp3_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])

    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(submaker.generate_subs())

    logger.info("Generated audio: %s, subtitles: %s", mp3_path, srt_path)
    return mp3_path, srt_path
