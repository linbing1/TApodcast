import os
from pathlib import Path

from src.analyzer import PROMPT_VERSION as ANALYZER_PROMPT_VERSION
from src.artifacts import load_page_content
from src.config import get_llm_max_requests
from src.paths import default_output_dir, safe_title
from src.pipeline import PipelineContext, PipelineRunner, PipelineStep
from src.script_writer import PROMPT_VERSION as SCRIPT_PROMPT_VERSION
from src.workflow import (
    analyze_content,
    download_images_command,
    extract,
    generate_audio_assets,
    run_cover_only,
    run_publish_only,
    run_video_only,
    logger,
    write_script_command,
)

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
    await generate_audio_assets(context.output_dir)


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
    return [f"{safe_title(title) or 'video'}.mp4", "subtitles.ass"]


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
        "script_writer": SCRIPT_PROMPT_VERSION,
    }


def _build_pipeline_runner(context: PipelineContext) -> PipelineRunner:
    steps = [
        PipelineStep(
            name="extract",
            action=_pipeline_extract,
            inputs=_static_paths(),
            outputs=_static_paths(
                "page.json",
                "text.txt",
                "videos.json",
            ),
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
                "tts_voice",
                "tts_rate",
            ),
        ),
        PipelineStep(
            name="video",
            action=_pipeline_video,
            inputs=_static_paths(
                "images",
                "images.json",
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
            inputs=_static_paths("images.json", "cover.json", "title.txt"),
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


def _build_pipeline_context(
    article_url: str,
    output_dir: str,
    *,
    video_title: str = "",
    cover_title: str = "",
    cover_image_index: int | None = None,
    cover_kicker: str = "英超新闻 · 深度报道",
    cover_subtitle: str = "",
    cover_output_name: str = "cover.png",
    cover_orientation: str = "both",
) -> PipelineContext:
    return PipelineContext(
        article_url=article_url,
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
    output_dir = output_dir or default_output_dir(url)
    if resume is None:
        resume = (Path(output_dir) / "manifest.json").exists()
    logger.info("Output directory: %s", output_dir)

    if skip_video:
        if to_step == "video":
            raise ValueError("--skip-video cannot be combined with --to video")
        to_step = to_step or "generate-audio"

    context = _build_pipeline_context(url, output_dir)
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
        output_dir = output_dir or default_output_dir(article_url)
    resolved_url = article_url or _article_url_from_output(output_dir)
    context = _build_pipeline_context(
        resolved_url,
        output_dir,
        video_title=video_title,
        cover_title=cover_title,
        cover_image_index=cover_image_index,
        cover_kicker=cover_kicker,
        cover_subtitle=cover_subtitle,
        cover_output_name=cover_output_name,
        cover_orientation=cover_orientation,
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
