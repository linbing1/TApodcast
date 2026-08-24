import argparse
import asyncio
import glob
import logging
import os
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from src.analyzer import PROMPT_VERSION as ANALYZER_PROMPT_VERSION
from src.analyzer import analyze_article
from src.artifacts import (
    load_analyzed_article,
    load_page_content,
    write_artifact,
)
from src.config import get_config, get_llm_max_requests
from src.cover_renderer import generate_cover, generate_cover_landscape
from src.doctor import format_doctor_report, run_doctor_checks
from src.image_captioner import PROMPT_VERSION as IMAGE_CAPTION_PROMPT_VERSION
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
from src.pipeline import PipelineContext, PipelineRunner, PipelineStep
from src.publish_copy import PROMPT_VERSION as PUBLISH_PROMPT_VERSION
from src.publish_copy import generate_publish_copy
from src.script_writer import (
    PROMPT_VERSION as SCRIPT_PROMPT_VERSION,
    calculate_target_script_chars,
    count_source_chars,
    write_script,
)
from src.scraper import download_images as download_image_assets
from src.scraper import extract_page_content
from src.storage import atomic_write_text
from src.tts_generator import generate_tts
from src.video_assembler import assemble_video, cleanup_frames

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PIPELINE_STEP_NAMES = (
    "extract",
    "download-images",
    "analyze-content",
    "write-script",
    "generate-audio",
    "video",
    "cover",
    "publish-copy",
)


def _article_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    slug = parts[-1] if parts else "article"
    return slug[:60]


def _safe_title(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()[:40]


def _default_output_dir(url: str) -> str:
    return os.path.join("output", str(date.today()), _article_slug(url))


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
    image_captions = load_image_captions(output_dir, image_paths)
    logger.info("Assembling video from %s...", output_dir)
    assemble_video(image_paths, mp3_path, srt_path, video_path,
                   image_captions=image_captions)
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
        cover_paths.append(generate_cover(
            output_dir=output_dir,
            title=title,
            image_index=image_index,
            kicker=kicker,
            subtitle=subtitle,
            output_name=output_name,
        ))
    if orientation in ("both", "landscape"):
        landscape_name = f"{Path(output_name).stem}-landscape.png"
        cover_paths.append(generate_cover_landscape(
            output_dir=output_dir,
            title=title,
            image_index=image_index,
            kicker=kicker,
            subtitle=subtitle,
            output_name=landscape_name,
        ))
    for cover_path in cover_paths:
        logger.info("Done! Cover: %s", cover_path)
    return cover_paths


def run_publish_only(output_dir: str) -> str:
    logger.info("Generating Douyin publish copy from %s...", output_dir)
    result = generate_publish_copy(output_dir)
    logger.info("Publish title: %s", result["title"])
    logger.info("Publish copy saved to %s", os.path.join(output_dir, "publish.json"))
    cleanup_frames(output_dir)
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


async def run(
    url: str,
    skip_video: bool = False,
    output_dir: str = "",
    resume: bool | None = None,
    from_step: str | None = None,
    to_step: str | None = None,
    force_steps: set[str] | None = None,
    dry_run: bool = False,
) -> str:
    output_dir = output_dir or _default_output_dir(url)
    if resume is None:
        resume = (Path(output_dir) / "manifest.json").exists()
    logger.info("Output directory: %s", output_dir)

    if skip_video:
        if to_step == "video":
            raise ValueError("--skip-video cannot be combined with --to video")
        to_step = to_step or "generate-audio"

    context = PipelineContext(
        article_url=url,
        output_dir=output_dir,
        configuration=_pipeline_configuration(),
        prompt_versions=_prompt_versions(),
    )
    runner = _build_pipeline_runner(context)
    await runner.run(
        resume=resume,
        from_step=from_step,
        to_step=to_step,
        force_steps=force_steps,
        dry_run=dry_run,
    )
    logger.info("Done! Output: %s", output_dir)
    return output_dir


async def extract(url: str, output_dir: str = "") -> str:
    config = get_config()
    if not output_dir:
        output_dir = _default_output_dir(url)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Extracting page content: %s", url)

    content = await extract_page_content(url, config["athletic_cookies"])
    write_artifact(os.path.join(output_dir, "page.json"), content)
    atomic_write_text(os.path.join(output_dir, "text.txt"), content.main_text)
    write_artifact(
        os.path.join(output_dir, "images.json"),
        ImageManifest(
            images=[ImageRecord(**image.model_dump()) for image in content.images]
        ),
    )
    write_artifact(
        os.path.join(output_dir, "videos.json"),
        VideoManifest(videos=content.videos),
    )

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
    write_artifact(
        os.path.join(output_dir, "images.json"),
        ImageManifest(images=[ImageRecord.model_validate(record) for record in records]),
    )

    cover_index = page.cover_image_index
    cover_local_path = None
    if isinstance(cover_index, int) and 0 <= cover_index < len(records):
        cover_record = records[cover_index]
        if cover_record["status"] == "downloaded":
            cover_local_path = cover_record["local_path"]
    write_artifact(
        os.path.join(output_dir, "cover.json"),
        CoverManifest(
            image_index=cover_index,
            image_url=page.cover_image_url,
            local_path=cover_local_path,
        ),
    )

    downloaded = sum(record["status"] == "downloaded" for record in records)
    if downloaded == 0:
        raise ValueError(f"Failed to download any images listed in: {page_path}")
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
    title = analyzed.title_cn.strip()
    if not title:
        raise ValueError("Article analysis did not provide a Chinese title")
    atomic_write_text(os.path.join(output_dir, "title.txt"), title)
    atomic_write_text(os.path.join(output_dir, "script.txt"), script.text)
    for filename in (
        "script-draft.txt",
        "content-review.json",
        "content-quality.json",
        "title-candidate.txt",
        "script-candidate.txt",
    ):
        (Path(output_dir) / filename).unlink(missing_ok=True)
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


def _static_paths(*relative_paths: str):
    def resolve_paths(_: PipelineContext) -> list[str]:
        return list(relative_paths)

    return resolve_paths


async def _pipeline_extract(context: PipelineContext) -> None:
    await extract(context.article_url, output_dir=context.output_dir)


async def _pipeline_download_images(context: PipelineContext) -> None:
    await download_images_command(context.output_dir)


def _pipeline_analyze_content(context: PipelineContext) -> None:
    analyze_content(
        context.output_dir,
        cache_enabled=context.llm_cache_enabled,
        usage_callback=context.llm_usage_callback,
    )


def _pipeline_write_script(context: PipelineContext) -> None:
    write_script_command(
        context.output_dir,
        cache_enabled=context.llm_cache_enabled,
        usage_callback=context.llm_usage_callback,
    )


async def _pipeline_generate_audio(context: PipelineContext) -> None:
    await generate_audio_assets(
        context.output_dir,
        cache_enabled=context.llm_cache_enabled,
        usage_callback=context.llm_usage_callback,
    )


def _pipeline_video(context: PipelineContext) -> None:
    run_video_only(context.output_dir, title=context.video_title)


def _pipeline_cover(context: PipelineContext) -> None:
    run_cover_only(
        context.output_dir,
        title=context.cover_title,
        image_index=context.cover_image_index,
        kicker=context.cover_kicker,
        subtitle=context.cover_subtitle,
        output_name=context.cover_output_name,
        orientation=context.cover_orientation,
    )


def _pipeline_publish(context: PipelineContext) -> None:
    run_publish_only(context.output_dir)


def _video_output_paths(context: PipelineContext) -> list[str]:
    title = context.video_title
    if not title:
        title_path = Path(context.output_dir) / "title.txt"
        title = title_path.read_text(encoding="utf-8").strip()
    return [f"{_safe_title(title) or 'video'}.mp4", "subtitles.ass"]


def _cover_output_paths(context: PipelineContext) -> list[str]:
    paths = []
    if context.cover_orientation in ("both", "vertical"):
        paths.append(context.cover_output_name)
    if context.cover_orientation in ("both", "landscape"):
        paths.append(f"{Path(context.cover_output_name).stem}-landscape.png")
    return paths


def _pipeline_configuration() -> dict[str, str]:
    return {
        "llm_base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "llm_model": os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        "llm_max_requests": str(get_llm_max_requests()),
        "tts_voice": os.environ.get("TTS_VOICE", "zh-CN-YunjianNeural"),
        "tts_rate": os.environ.get("TTS_RATE", "+10%"),
    }


def _prompt_versions() -> dict[str, str]:
    return {
        "analyzer": ANALYZER_PROMPT_VERSION,
        "image_captioner": IMAGE_CAPTION_PROMPT_VERSION,
        "script_writer": SCRIPT_PROMPT_VERSION,
        "publish_copy": PUBLISH_PROMPT_VERSION,
    }


def _build_pipeline_runner(context: PipelineContext) -> PipelineRunner:
    steps = [
        PipelineStep(
            name="extract",
            action=_pipeline_extract,
            inputs=_static_paths(),
            outputs=_static_paths("page.json", "text.txt", "videos.json"),
        ),
        PipelineStep(
            name="download-images",
            action=_pipeline_download_images,
            inputs=_static_paths("page.json"),
            outputs=_static_paths("images.json", "cover.json", "images"),
        ),
        PipelineStep(
            name="analyze-content",
            action=_pipeline_analyze_content,
            inputs=_static_paths("page.json"),
            outputs=_static_paths("analysis.json"),
            configuration_keys=("llm_base_url", "llm_model"),
            prompt_keys=("analyzer",),
        ),
        PipelineStep(
            name="write-script",
            action=_pipeline_write_script,
            inputs=_static_paths("page.json", "analysis.json"),
            outputs=_static_paths("title.txt", "script.txt"),
            configuration_keys=("llm_base_url", "llm_model"),
            prompt_keys=("script_writer",),
        ),
        PipelineStep(
            name="generate-audio",
            action=_pipeline_generate_audio,
            inputs=_static_paths("images.json", "script.txt"),
            outputs=_static_paths(
                "image_captions.json",
                "audio.mp3",
                "audio.vtt",
            ),
            configuration_keys=(
                "llm_base_url",
                "llm_model",
                "tts_voice",
                "tts_rate",
            ),
            prompt_keys=("image_captioner",),
        ),
        PipelineStep(
            name="video",
            action=_pipeline_video,
            inputs=_static_paths(
                "images",
                "image_captions.json",
                "title.txt",
                "audio.mp3",
                "audio.vtt",
            ),
            outputs=_video_output_paths,
        ),
        PipelineStep(
            name="cover",
            action=_pipeline_cover,
            inputs=_static_paths("images", "cover.json", "title.txt"),
            outputs=_cover_output_paths,
        ),
        PipelineStep(
            name="publish-copy",
            action=_pipeline_publish,
            inputs=_static_paths("page.json", "analysis.json", "script.txt", "title.txt"),
            outputs=_static_paths(
                "publish.json",
                "publish_title.txt",
                "publish_description.txt",
            ),
        ),
    ]
    return PipelineRunner(context, steps)


def _article_url_from_output(output_dir: str) -> str:
    page_path = Path(output_dir) / "page.json"
    if not page_path.exists():
        return ""
    return load_page_content(page_path).url


async def run_pipeline_step(
    step_name: str,
    output_dir: str,
    *,
    article_url: str = "",
    video_title: str = "",
    cover_title: str = "",
    cover_image_index: int | None = None,
    cover_kicker: str = "英超新闻 · 深度报道",
    cover_subtitle: str = "",
    cover_output_name: str = "cover.png",
    cover_orientation: str = "both",
    resume: bool = True,
    force: bool = False,
) -> str:
    if step_name not in PIPELINE_STEP_NAMES:
        raise ValueError(f"Unknown pipeline step: {step_name}")
    if step_name == "extract":
        if not article_url:
            raise ValueError("The extract step requires an article URL")
        output_dir = output_dir or _default_output_dir(article_url)
    resolved_url = article_url or _article_url_from_output(output_dir)
    context = PipelineContext(
        article_url=resolved_url,
        output_dir=output_dir,
        video_title=video_title,
        cover_title=cover_title,
        cover_image_index=cover_image_index,
        cover_kicker=cover_kicker,
        cover_subtitle=cover_subtitle,
        cover_output_name=cover_output_name,
        cover_orientation=cover_orientation,
        configuration=_pipeline_configuration(),
        prompt_versions=_prompt_versions(),
    )
    runner = _build_pipeline_runner(context)
    await runner.run(
        resume=resume,
        from_step=step_name,
        to_step=step_name,
        force_steps={step_name} if force else None,
    )
    return output_dir


async def run_content_audio_pipeline(output_dir: str, *, force: bool = False) -> str:
    return await run_pipeline_step("generate-audio", output_dir, force=force)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Douyin short video from a The Athletic article"
    )
    sub = parser.add_subparsers(dest="cmd")

    full = sub.add_parser("run", help="Full pipeline from URL")
    full.add_argument("--url", required=True, help="The Athletic article URL")
    full.add_argument(
        "--dir",
        default="",
        help="Output directory (defaults to output/date/article-slug)",
    )
    full.add_argument("--skip-video", action="store_true", help="Stop after TTS, skip video assembly")
    resume_group = full.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        help="Skip completed steps whose inputs and outputs are unchanged",
    )
    resume_group.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Run selected steps even when an existing manifest could skip them",
    )
    full.set_defaults(resume=None)
    full.add_argument(
        "--from",
        dest="from_step",
        choices=PIPELINE_STEP_NAMES,
        help="Start from this pipeline step",
    )
    full.add_argument(
        "--to",
        dest="to_step",
        choices=PIPELINE_STEP_NAMES,
        help="Stop after this pipeline step",
    )
    full.add_argument(
        "--force",
        dest="force_steps",
        action="append",
        choices=PIPELINE_STEP_NAMES,
        default=[],
        help="Force a pipeline step to run; may be repeated",
    )
    full.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which pipeline steps would run without changing files",
    )

    vid = sub.add_parser("video", help="Assemble video from existing output directory")
    vid.add_argument("--dir", required=True, help="Output directory containing images/, audio.mp3, audio.vtt")
    vid.add_argument("--title", default="", help="Override title (reads title.txt if omitted)")
    vid.add_argument("--force", action="store_true", help="Regenerate this stage")

    cover = sub.add_parser("cover", help="Generate a Douyin cover from existing images")
    cover.add_argument("--dir", required=True, help="Output directory containing images/")
    cover.add_argument("--title", default="", help="Cover title (reads title.txt if omitted)")
    cover.add_argument("--image-index", type=int, default=None, help="Override the image index selected during extraction")
    cover.add_argument("--kicker", default="英超新闻 · 深度报道", help="Small label above the title")
    cover.add_argument("--subtitle", default="", help="Optional supporting line below the title")
    cover.add_argument("--output", default="cover.png", help="Output filename inside --dir")
    cover.add_argument(
        "--orientation",
        choices=["both", "vertical", "landscape"],
        default="both",
        help="Generate vertical cover.png, landscape cover-landscape.png, or both",
    )
    cover.add_argument("--force", action="store_true", help="Regenerate this stage")

    publish = sub.add_parser(
        "publish-copy",
        aliases=["publish"],
        help="Generate Douyin title, description, and hashtags",
    )
    publish.add_argument("--dir", required=True, help="Directory containing article outputs")
    publish.add_argument("--force", action="store_true", help="Regenerate this stage")

    ext = sub.add_parser("extract", help="Extract article text, images, and videos")
    ext.add_argument("--url", required=True, help="The Athletic article URL")
    ext.add_argument("--dir", default="", help="Output directory (defaults to output/date/article-slug)")
    ext.add_argument("--force", action="store_true", help="Regenerate this stage")

    dl = sub.add_parser("download-images", help="Download images from an extracted page manifest")
    dl.add_argument("--dir", required=True, help="Directory containing page.json")
    dl.add_argument("--force", action="store_true", help="Regenerate this stage")

    content_commands = {
        "analyze-content": "Summarize the article for a short news video",
        "write-script": "Generate the final title and podcast script",
    }
    for command, help_text in content_commands.items():
        content = sub.add_parser(command, help=help_text)
        content.add_argument("--dir", required=True, help="Article output directory")
        content.add_argument("--force", action="store_true", help="Regenerate this stage")

    audio = sub.add_parser(
        "generate-audio",
        help="Generate image captions and podcast audio from existing content outputs",
    )
    audio.add_argument("--dir", required=True, help="Directory containing images.json and script.txt")
    audio.add_argument("--force", action="store_true", help="Regenerate this stage")

    clean = sub.add_parser(
        "cleanup",
        help="Remove leftover intermediate frames directory",
    )
    clean.add_argument("--dir", required=True, help="Output directory of the article")

    doctor = sub.add_parser(
        "doctor",
        help="Check configuration and runtime dependencies",
    )
    doctor.add_argument(
        "--output-dir",
        default="output",
        help="Output directory or parent path to check for write access and free space",
    )
    doctor.add_argument(
        "--online",
        action="store_true",
        help="Also verify live LLM and TTS connectivity",
    )
    doctor.add_argument(
        "--url",
        default="",
        help="Optionally verify authenticated extraction of a The Athletic article",
    )

    # Backwards-compatible: no subcommand → treat as 'run'
    parser.add_argument("--url", help=argparse.SUPPRESS)
    parser.add_argument("--skip-video", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.cmd == "video":
        asyncio.run(
            run_pipeline_step(
                "video",
                args.dir,
                video_title=args.title,
                force=args.force,
            )
        )
    elif args.cmd == "cover":
        asyncio.run(
            run_pipeline_step(
                "cover",
                args.dir,
                cover_title=args.title,
                cover_image_index=args.image_index,
                cover_kicker=args.kicker,
                cover_subtitle=args.subtitle,
                cover_output_name=args.output,
                cover_orientation=args.orientation,
                force=args.force,
            )
        )
    elif args.cmd in ("publish-copy", "publish"):
        asyncio.run(run_pipeline_step("publish-copy", args.dir, force=args.force))
    elif args.cmd == "cleanup":
        run_cleanup_only(args.dir)
    elif args.cmd == "doctor":
        passed = asyncio.run(
            run_doctor(
                output_dir=args.output_dir,
                online=args.online,
                article_url=args.url,
            )
        )
        if not passed:
            raise SystemExit(1)
    elif args.cmd == "extract":
        asyncio.run(
            run_pipeline_step(
                "extract",
                args.dir,
                article_url=args.url,
                force=args.force,
            )
        )
    elif args.cmd == "download-images":
        asyncio.run(run_pipeline_step("download-images", args.dir, force=args.force))
    elif args.cmd in {
        "analyze-content",
        "write-script",
    }:
        asyncio.run(run_pipeline_step(args.cmd, args.dir, force=args.force))
    elif args.cmd == "generate-audio":
        asyncio.run(run_content_audio_pipeline(args.dir, force=args.force))
    else:
        if not args.url:
            parser.print_help()
            return
        asyncio.run(
            run(
                args.url,
                skip_video=args.skip_video,
                output_dir=getattr(args, "dir", ""),
                resume=getattr(args, "resume", None),
                from_step=getattr(args, "from_step", None),
                to_step=getattr(args, "to_step", None),
                force_steps=set(getattr(args, "force_steps", [])),
                dry_run=getattr(args, "dry_run", False),
            )
        )


if __name__ == "__main__":
    main()
