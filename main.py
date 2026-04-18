import argparse
import asyncio
import logging
import os
from datetime import date
from urllib.parse import urlparse

from src.analyzer import analyze_article
from src.config import get_config
from src.llm import LLMClient
from src.script_writer import write_script
from src.scraper import scrape_article
from src.tts_generator import generate_tts
from src.video_assembler import assemble_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _article_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    slug = parts[-1] if parts else "article"
    return slug[:60]


async def run(url: str) -> None:
    config = get_config()
    slug = _article_slug(url)
    output_dir = os.path.join("output", str(date.today()), slug)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Output directory: %s", output_dir)

    logger.info("Step 1: Scraping article and images...")
    article = await scrape_article(url, config["athletic_cookies"], output_dir)
    logger.info("Scraped %d chars text, %d images", len(article.full_text), len(article.image_paths))

    llm = LLMClient(config["llm_base_url"], config["llm_api_key"], config["llm_model"])

    logger.info("Step 2: Analyzing article (LLM)...")
    analyzed = analyze_article(article, llm)
    logger.info("Analysis complete: %s", analyzed.title_cn)

    logger.info("Step 3: Writing podcast script (LLM)...")
    script = write_script(analyzed, llm)
    logger.info("Script: %d chars", len(script.text))

    logger.info("Step 4: Generating audio with edge-tts...")
    mp3_path, srt_path = await generate_tts(script, config["tts_voice"], output_dir, config["tts_rate"])

    logger.info("Step 5: Assembling video with ffmpeg...")
    video_path = os.path.join(output_dir, "video.mp4")
    assemble_video(article.image_paths, mp3_path, srt_path, video_path)

    logger.info("Done! Video: %s", video_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Douyin short video from a The Athletic article"
    )
    parser.add_argument("--url", required=True, help="The Athletic article URL")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
