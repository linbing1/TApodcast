import argparse
import asyncio
import glob
import json
import logging
import os
import re
from dataclasses import asdict
from datetime import date
from urllib.parse import urlparse

from src.analyzer import analyze_article
from src.config import get_config
from src.cover_renderer import generate_cover
from src.llm import LLMClient
from src.models import ImageAsset, ScrapedArticle
from src.script_writer import write_script
from src.scraper import download_images as download_image_assets
from src.scraper import extract_page_content, scrape_article
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


def run_cover_only(
    output_dir: str,
    title: str = "",
    image_index: int | None = None,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    output_name: str = "cover.png",
) -> str:
    logger.info("Generating cover from %s...", output_dir)
    cover_path = generate_cover(
        output_dir=output_dir,
        title=title,
        image_index=image_index,
        kicker=kicker,
        subtitle=subtitle,
        output_name=output_name,
    )
    logger.info("Done! Cover: %s", cover_path)
    return cover_path


async def run(url: str, skip_video: bool = False) -> None:
    config = get_config()
    slug = _article_slug(url)
    output_dir = os.path.join("output", str(date.today()), slug)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Output directory: %s", output_dir)

    logger.info("Step 1: Extracting article content and downloading images...")
    article = await scrape_article(url, config["athletic_cookies"], output_dir)
    logger.info("Scraped %d chars text, %d images", len(article.full_text), len(article.image_paths))

    llm = LLMClient(config["llm_base_url"], config["llm_api_key"], config["llm_model"])

    logger.info("Step 2.1: Analyzing article with LLM...")
    analyzed = analyze_article(article, llm)
    logger.info("Analysis complete: %s", analyzed.title_cn)
    with open(os.path.join(output_dir, "title.txt"), "w", encoding="utf-8") as f:
        f.write(analyzed.title_cn)

    logger.info("Step 2.2: Writing podcast script with LLM...")
    today = date.today()
    speech_date = f"{today.year}年{today.month}月{today.day}日"
    script = write_script(analyzed, llm, date_str=speech_date)
    logger.info("Script: %d chars", len(script.text))

    script_path = os.path.join(output_dir, "script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script.text)
    logger.info("Script saved to %s", script_path)

    logger.info("Step 2.3: Generating audio and VTT subtitles with edge-tts...")
    mp3_path, srt_path = await generate_tts(script, config["tts_voice"], output_dir, config["tts_rate"])

    if skip_video:
        logger.info("--skip-video: done. Output: %s", output_dir)
        return

    logger.info("Step 3: Assembling the vertical video with burned-in subtitles...")
    video_path = os.path.join(output_dir, f"{_safe_title(analyzed.title_cn)}.mp4")
    article_date = date.today().strftime("%Y年%m月%d日")
    assemble_video(article.image_paths, mp3_path, srt_path, video_path,
                   title=analyzed.title_cn, article_date=article_date)

    logger.info("Done! Video: %s", video_path)


async def extract(url: str, output_dir: str = "") -> str:
    config = get_config()
    if not output_dir:
        output_dir = os.path.join("output", str(date.today()), _article_slug(url))
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Extracting page content: %s", url)

    content = await extract_page_content(url, config["athletic_cookies"])
    content_data = asdict(content)
    with open(os.path.join(output_dir, "page.json"), "w", encoding="utf-8") as f:
        json.dump(content_data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, "text.txt"), "w", encoding="utf-8") as f:
        f.write(content.main_text)
    with open(os.path.join(output_dir, "images.json"), "w", encoding="utf-8") as f:
        json.dump(content_data["images"], f, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, "videos.json"), "w", encoding="utf-8") as f:
        json.dump(content_data["videos"], f, ensure_ascii=False, indent=2)

    logger.info(
        "Extracted %d chars, %d images, %d videos",
        len(content.main_text), len(content.images), len(content.videos),
    )
    logger.info("Extraction output: %s", output_dir)
    return output_dir


async def download_images_command(output_dir: str) -> str:
    config = get_config()
    page_path = os.path.join(output_dir, "page.json")
    if not os.path.exists(page_path):
        raise FileNotFoundError(f"Page manifest not found: {page_path}")

    with open(page_path, encoding="utf-8") as f:
        page_data = json.load(f)
    images = [
        ImageAsset(
            url=item["url"],
            alt=item.get("alt", ""),
            caption=item.get("caption", ""),
            credit=item.get("credit", ""),
            width=item.get("width"),
            height=item.get("height"),
        )
        for item in page_data.get("images", [])
    ]
    if not images:
        raise ValueError(f"No images listed in page manifest: {page_path}")

    records = await download_image_assets(
        images,
        output_dir,
        referer=page_data.get("url", ""),
        cookies=config["athletic_cookies"],
        cover_image_index=page_data.get("cover_image_index"),
    )
    with open(os.path.join(output_dir, "images.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    downloaded = sum(record["status"] == "downloaded" for record in records)
    logger.info("Image download result: %d/%d succeeded", downloaded, len(records))
    logger.info("Image output: %s", os.path.join(output_dir, "images"))
    return output_dir


async def generate_audio(output_dir: str) -> str:
    config = get_config()
    page_path = os.path.join(output_dir, "page.json")
    if not os.path.exists(page_path):
        raise FileNotFoundError(f"Page manifest not found: {page_path}")

    with open(page_path, encoding="utf-8") as f:
        page_data = json.load(f)

    main_text = page_data.get("main_text", "").strip()
    if not main_text:
        raise ValueError(f"No article text found in page manifest: {page_path}")

    article = ScrapedArticle(
        title=page_data.get("title", "").strip(),
        link=page_data.get("url", ""),
        full_text=main_text,
    )
    llm = LLMClient(config["llm_base_url"], config["llm_api_key"], config["llm_model"])

    logger.info("Step 2.1: Analyzing article with LLM...")
    analyzed = analyze_article(article, llm)
    with open(os.path.join(output_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(analyzed), f, ensure_ascii=False, indent=2)
    with open(os.path.join(output_dir, "title.txt"), "w", encoding="utf-8") as f:
        f.write(analyzed.title_cn)

    logger.info("Step 2.2: Writing podcast script with LLM...")
    today = date.today()
    speech_date = f"{today.year}年{today.month}月{today.day}日"
    script = write_script(analyzed, llm, date_str=speech_date)
    with open(os.path.join(output_dir, "script.txt"), "w", encoding="utf-8") as f:
        f.write(script.text)

    logger.info("Step 2.3: Generating audio with edge-tts...")
    mp3_path, vtt_path = await generate_tts(
        script,
        config["tts_voice"],
        output_dir,
        config["tts_rate"],
    )
    logger.info("Audio output: %s; subtitles: %s", mp3_path, vtt_path)
    return output_dir


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

    cover = sub.add_parser("cover", help="Generate a Douyin cover from existing images")
    cover.add_argument("--dir", required=True, help="Output directory containing images/")
    cover.add_argument("--title", default="", help="Cover title (reads title.txt if omitted)")
    cover.add_argument("--image-index", type=int, default=None, help="Override the image index selected during extraction")
    cover.add_argument("--kicker", default="英超新闻 · 深度报道", help="Small label above the title")
    cover.add_argument("--subtitle", default="", help="Optional supporting line below the title")
    cover.add_argument("--output", default="cover.png", help="Output filename inside --dir")

    ext = sub.add_parser("extract", help="Extract article text, images, and videos")
    ext.add_argument("--url", required=True, help="The Athletic article URL")
    ext.add_argument("--dir", default="", help="Output directory (defaults to output/date/article-slug)")

    dl = sub.add_parser("download-images", help="Download images from an extracted page manifest")
    dl.add_argument("--dir", required=True, help="Directory containing page.json")

    audio = sub.add_parser(
        "generate-audio",
        help="Analyze an extracted article and generate podcast audio",
    )
    audio.add_argument("--dir", required=True, help="Directory containing page.json")

    # Backwards-compatible: no subcommand → treat as 'run'
    parser.add_argument("--url", help=argparse.SUPPRESS)
    parser.add_argument("--skip-video", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.cmd == "video":
        run_video_only(args.dir, title=args.title)
    elif args.cmd == "cover":
        run_cover_only(
            args.dir,
            title=args.title,
            image_index=args.image_index,
            kicker=args.kicker,
            subtitle=args.subtitle,
            output_name=args.output,
        )
    elif args.cmd == "extract":
        asyncio.run(extract(args.url, output_dir=args.dir))
    elif args.cmd == "download-images":
        asyncio.run(download_images_command(args.dir))
    elif args.cmd == "generate-audio":
        asyncio.run(generate_audio(args.dir))
    else:
        if not args.url:
            parser.print_help()
            return
        asyncio.run(run(args.url, skip_video=args.skip_video))


if __name__ == "__main__":
    main()
