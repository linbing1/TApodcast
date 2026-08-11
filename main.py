import argparse
import asyncio
import glob
import logging
import os
import re
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


def _safe_title(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()[:40]


def run_video_only(output_dir: str, title: str = "") -> None:
    images_dir = os.path.join(output_dir, "images")
    mp3_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "audio.vtt")

    if not title:
        title_file = os.path.join(output_dir, "title.txt")
        if os.path.exists(title_file):
            title = open(title_file, encoding="utf-8").read().strip()

    image_paths = sorted(glob.glob(os.path.join(images_dir, "*.jpg")))
    if not image_paths:
        raise FileNotFoundError(f"No images found in {images_dir}")
    if not os.path.exists(mp3_path):
        raise FileNotFoundError(f"Audio not found: {mp3_path}")
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Subtitles not found: {srt_path}")

    video_path = os.path.join(output_dir, f"{_safe_title(title) or 'video'}.mp4")
    article_date = date.today().strftime("%Y年%m月%d日")
    logger.info("Assembling video from %s...", output_dir)
    assemble_video(image_paths, mp3_path, srt_path, video_path,
                   title=title, article_date=article_date)
    logger.info("Done! Video: %s", video_path)


async def run(url: str, skip_video: bool = False) -> None:
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
    with open(os.path.join(output_dir, "title.txt"), "w", encoding="utf-8") as f:
        f.write(analyzed.title_cn)

    logger.info("Step 3: Writing podcast script (LLM)...")
    today = date.today()
    speech_date = f"{today.year}年{today.month}月{today.day}日"
    script = write_script(analyzed, llm, date_str=speech_date)
    logger.info("Script: %d chars", len(script.text))

    script_path = os.path.join(output_dir, "script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script.text)
    logger.info("Script saved to %s", script_path)

    logger.info("Step 4: Generating audio with edge-tts...")
    mp3_path, srt_path = await generate_tts(script, config["tts_voice"], output_dir, config["tts_rate"])

    if skip_video:
        logger.info("--skip-video: done. Output: %s", output_dir)
        return

    logger.info("Step 5: Assembling video with ffmpeg...")
    video_path = os.path.join(output_dir, f"{_safe_title(analyzed.title_cn)}.mp4")
    article_date = date.today().strftime("%Y年%m月%d日")
    assemble_video(article.image_paths, mp3_path, srt_path, video_path,
                   title=analyzed.title_cn, article_date=article_date)

    logger.info("Done! Video: %s", video_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Douyin short video from a The Athletic article"
    )
    sub = parser.add_subparsers(dest="cmd")

    full = sub.add_parser("run", help="Full pipeline from URL")
    full.add_argument("--url", required=True, help="The Athletic article URL")
    full.add_argument("--skip-video", action="store_true", help="Stop after TTS, skip video assembly")

    vid = sub.add_parser("video", help="Assemble video from existing output directory")
    vid.add_argument("--dir", required=True, help="Output directory containing images/, audio.mp3, audio.vtt")
    vid.add_argument("--title", default="", help="Override title (reads title.txt if omitted)")

    # Backwards-compatible: no subcommand → treat as 'run'
    parser.add_argument("--url", help=argparse.SUPPRESS)
    parser.add_argument("--skip-video", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.cmd == "video":
        run_video_only(args.dir, title=args.title)
    else:
        if not args.url:
            parser.print_help()
            return
        asyncio.run(run(args.url, skip_video=args.skip_video))


if __name__ == "__main__":
    main()
