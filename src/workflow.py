import glob
import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.analyzer import analyze_article
from src.artifacts import load_analyzed_article, load_page_content, write_artifact
from src.config import get_config
from src.cover_renderer import generate_cover, generate_cover_landscape
from src.doctor import format_doctor_report, run_doctor_checks
from src.image_captioner import generate_image_captions, load_image_captions
from src.llm import LLMClient
from src.models import (
    CoverManifest,
    ImageManifest,
    ImageRecord,
    PodcastScript,
    ScrapedArticle,
    VideoManifest,
)
from src.paths import default_output_dir, safe_title
from src.publish_copy import generate_publish_copy
from src.script_writer import calculate_target_script_chars, count_source_chars, write_script
from src.scraper import download_images as download_image_assets
from src.scraper import extract_page_content
from src.storage import atomic_write_text
from src.tts_generator import generate_tts
from src.video_assembler import assemble_video, cleanup_frames

logger = logging.getLogger(__name__)


def run_video_only(output_dir: str, title: str = "") -> None:
    images_dir = os.path.join(output_dir, "images")
    mp3_path = os.path.join(output_dir, "audio.mp3")
    srt_path = os.path.join(output_dir, "audio.vtt")

    if not title:
        title_file = os.path.join(output_dir, "title.txt")
        if os.path.exists(title_file):
            title = Path(title_file).read_text(encoding="utf-8").strip()

    image_paths = sorted(glob.glob(os.path.join(images_dir, "*.jpg")))
    if not image_paths:
        raise FileNotFoundError(f"No images found in {images_dir}")
    if not os.path.exists(mp3_path):
        raise FileNotFoundError(f"Audio not found: {mp3_path}")
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Subtitles not found: {srt_path}")

    video_path = os.path.join(output_dir, f"{safe_title(title) or 'video'}.mp4")
    image_captions = load_image_captions(output_dir, image_paths)
    logger.info("Assembling video from %s...", output_dir)
    assemble_video(
        image_paths,
        mp3_path,
        srt_path,
        video_path,
        image_captions=image_captions,
    )
    logger.info("Done! Video: %s", video_path)


def run_cover_only(
    output_dir: str,
    title: str = "",
    image_index: int | None = None,
    kicker: str = "英超新闻 · 深度报道",
    subtitle: str = "",
    output_name: str = "cover.png",
    orientation: str = "both",
) -> list[str]:
    logger.info("Generating cover from %s...", output_dir)
    cover_paths: list[str] = []
    if orientation in ("both", "vertical"):
        cover_paths.append(
            generate_cover(
                output_dir=output_dir,
                title=title,
                image_index=image_index,
                kicker=kicker,
                subtitle=subtitle,
                output_name=output_name,
            )
        )
    if orientation in ("both", "landscape"):
        landscape_name = f"{Path(output_name).stem}-landscape.png"
        cover_paths.append(
            generate_cover_landscape(
                output_dir=output_dir,
                title=title,
                image_index=image_index,
                kicker=kicker,
                subtitle=subtitle,
                output_name=landscape_name,
            )
        )
    for cover_path in cover_paths:
        logger.info("Done! Cover: %s", cover_path)
    return cover_paths


def run_publish_only(output_dir: str) -> str:
    logger.info("Generating Douyin publish copy from %s...", output_dir)
    result = generate_publish_copy(output_dir)
    logger.info("Publish title: %s", result["title"])
    logger.info("Publish copy saved to %s", os.path.join(output_dir, "publish.json"))
    return os.path.join(output_dir, "publish.json")


def run_cleanup_only(output_dir: str) -> None:
    logger.info("Cleaning leftover intermediate frames in %s...", output_dir)
    if cleanup_frames(output_dir):
        logger.info("Done! Frames directory removed.")
    else:
        logger.info("No frames directory found, nothing to clean.")


async def run_doctor(
    output_dir: str = "output",
    online: bool = False,
    article_url: str = "",
) -> bool:
    report = await run_doctor_checks(
        output_dir=output_dir,
        online=online,
        article_url=article_url,
    )
    print(format_doctor_report(report))
    return report.passed


async def extract(url: str, output_dir: str = "") -> str:
    config = get_config()
    if not output_dir:
        output_dir = default_output_dir(url)
    logger.info("Extracting page content: %s", url)

    content = await extract_page_content(url, config["athletic_cookies"])
    title = content.title.strip()
    main_text = content.main_text.strip()
    if not title:
        raise ValueError(f"No article title found: {url}")
    if not main_text:
        raise ValueError(f"No article text found: {url}")
    if len(main_text) < 300:
        logger.warning(
            "Extracted article text is unusually short (%d chars): %s",
            len(main_text),
            url,
        )

    os.makedirs(output_dir, exist_ok=True)
    write_artifact(os.path.join(output_dir, "page.json"), content)
    atomic_write_text(os.path.join(output_dir, "text.txt"), main_text)
    write_artifact(
        os.path.join(output_dir, "videos.json"),
        VideoManifest(videos=content.videos),
    )

    logger.info(
        "Extracted %d chars, %d images, %d videos",
        len(content.main_text),
        len(content.images),
        len(content.videos),
    )
    logger.info("Extraction output: %s", output_dir)
    return output_dir


async def download_images_command(output_dir: str) -> str:
    config = get_config()
    page_path = os.path.join(output_dir, "page.json")
    if not os.path.exists(page_path):
        raise FileNotFoundError(f"Page manifest not found: {page_path}")

    page = load_page_content(page_path)
    images = page.images
    if not images:
        raise ValueError(f"No images listed in page manifest: {page_path}")

    records = await download_image_assets(
        images,
        output_dir,
        referer=page.url,
        cookies=config["athletic_cookies"],
        cover_image_index=page.cover_image_index,
    )
    downloaded = sum(record["status"] == "downloaded" for record in records)
    if downloaded == 0:
        for filename in ("images.json", "cover.json"):
            Path(output_dir, filename).unlink(missing_ok=True)
        raise ValueError(f"Failed to download any images listed in: {page_path}")

    cover_record = next(
        (record for record in records if record.get("is_cover")),
        None,
    )
    if cover_record is None:
        raise ValueError(f"No usable cover image found in: {page_path}")

    write_artifact(
        os.path.join(output_dir, "images.json"),
        ImageManifest(images=[ImageRecord.model_validate(record) for record in records]),
    )

    cover_index = records.index(cover_record)
    cover_local_path = cover_record["local_path"]
    cover_image_url = (
        page.cover_image_url
        if cover_index == page.cover_image_index
        else cover_record["url"]
    )
    write_artifact(
        os.path.join(output_dir, "cover.json"),
        CoverManifest(
            image_index=cover_index,
            image_url=cover_image_url,
            local_path=cover_local_path,
        ),
    )

    logger.info("Image download result: %d/%d succeeded", downloaded, len(records))
    logger.info("Image output: %s", os.path.join(output_dir, "images"))
    return output_dir


async def generate_audio(output_dir: str) -> str:
    await generate_audio_assets(output_dir)
    return output_dir


def _load_source_article(output_dir: str) -> ScrapedArticle:
    page_path = os.path.join(output_dir, "page.json")
    if not os.path.exists(page_path):
        raise FileNotFoundError(f"Page manifest not found: {page_path}")

    page = load_page_content(page_path)
    main_text = page.main_text.strip()
    if not main_text:
        raise ValueError(f"No article text found in page manifest: {page_path}")
    return ScrapedArticle(
        title=page.title.strip(),
        link=page.url,
        full_text=main_text,
    )


def _create_llm_client(
    output_dir: str,
    *,
    cache_enabled: bool = True,
    usage_callback: Callable[[], None] | None = None,
) -> LLMClient:
    config = get_config()
    output_path = Path(output_dir)
    return LLMClient(
        config["llm_base_url"],
        config["llm_api_key"],
        config["llm_model"],
        cache_dir=output_path / ".llm-cache" if cache_enabled else None,
        usage_path=output_path / "llm-usage.jsonl",
        max_requests=config.get("llm_max_requests", 12),
        usage_callback=usage_callback,
    )


def _speech_date() -> str:
    today = date.today()
    return f"{today.year}年{today.month}月{today.day}日"


def analyze_content(
    output_dir: str,
    *,
    cache_enabled: bool = True,
    usage_callback: Callable[[], None] | None = None,
) -> str:
    article = _load_source_article(output_dir)
    llm = _create_llm_client(
        output_dir,
        cache_enabled=cache_enabled,
        usage_callback=usage_callback,
    )

    logger.info("Summarizing article for a short news video...")
    analyzed = analyze_article(article, llm)
    write_artifact(os.path.join(output_dir, "analysis.json"), analyzed)
    logger.info("Analysis output: %s", os.path.join(output_dir, "analysis.json"))
    return output_dir


def write_script_command(
    output_dir: str,
    *,
    cache_enabled: bool = True,
    usage_callback: Callable[[], None] | None = None,
) -> str:
    analysis_path = os.path.join(output_dir, "analysis.json")
    if not os.path.exists(analysis_path):
        raise FileNotFoundError(f"Article analysis not found: {analysis_path}")
    source_article = _load_source_article(output_dir)
    analyzed = load_analyzed_article(analysis_path)
    source_chars = count_source_chars(source_article.full_text)
    target_chars = calculate_target_script_chars(source_chars)
    llm = _create_llm_client(
        output_dir,
        cache_enabled=cache_enabled,
        usage_callback=usage_callback,
    )

    logger.info(
        "Writing final podcast script (source=%d chars, target=%d chars)...",
        source_chars,
        target_chars,
    )
    script = write_script(
        analyzed,
        llm,
        date_str=_speech_date(),
        target_chars=target_chars,
    )
    actual_script_chars = count_source_chars(script.text)
    logger.info(
        "Generated podcast script (target=%d chars, actual=%d chars, delta=%+d chars)",
        target_chars,
        actual_script_chars,
        actual_script_chars - target_chars,
    )
    title = analyzed.title_cn.strip()
    if not title:
        raise ValueError("Article analysis did not provide a Chinese title")
    atomic_write_text(os.path.join(output_dir, "title.txt"), title)
    atomic_write_text(os.path.join(output_dir, "script.txt"), script.text)
    logger.info("Content output: %s", os.path.join(output_dir, "script.txt"))
    return output_dir


async def generate_audio_assets(
    output_dir: str,
    *,
    cache_enabled: bool = True,
    usage_callback: Callable[[], None] | None = None,
) -> str:
    config = get_config()
    script_path = Path(output_dir) / "script.txt"
    if not script_path.exists():
        raise FileNotFoundError(f"Final podcast script not found: {script_path}")
    script = PodcastScript(text=script_path.read_text(encoding="utf-8").strip())
    llm = _create_llm_client(
        output_dir,
        cache_enabled=cache_enabled,
        usage_callback=usage_callback,
    )

    logger.info("Translating and shortening image captions with LLM...")
    generate_image_captions(output_dir, llm)

    logger.info("Generating audio with edge-tts...")
    mp3_path, vtt_path = await generate_tts(
        script,
        config["tts_voice"],
        output_dir,
        config["tts_rate"],
    )
    logger.info("Audio output: %s; subtitles: %s", mp3_path, vtt_path)
    return output_dir
