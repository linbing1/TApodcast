import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.pipeline_definition import (
    _build_pipeline_runner,
    run,
    run_content_audio_pipeline,
    run_pipeline_step,
)
from src.workflow import (
    download_images_command,
    extract,
    generate_audio,
    generate_audio_assets,
    run_cover_only,
    run_publish_only,
    write_script_command,
)
from src.models import ImageAsset, PageContent, PodcastScript, ScrapedArticle, VideoAsset
from src.pipeline import PipelineContext


def test_pipeline_registers_all_publish_stages(tmp_path):
    runner = _build_pipeline_runner(
        PipelineContext("https://example.com/article", str(tmp_path))
    )

    assert runner.step_names == [
        "extract",
        "download-images",
        "analyze-content",
        "write-script",
        "generate-audio",
        "video",
        "cover",
        "publish-copy",
    ]


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.extract_page_content", new_callable=AsyncMock)
async def test_extract_writes_separate_content_outputs(
    mock_extract, mock_get_config, tmp_path
):
    mock_get_config.return_value = {"athletic_cookies": []}
    mock_extract.return_value = PageContent(
        url="https://example.com/article",
        title="Arsenal Win",
        main_text="Arsenal won the match.",
        images=[ImageAsset(url="https://cdn.example.com/image.jpg", alt="Team")],
        videos=[VideoAsset(url="https://video.example.com/embed/1", kind="iframe")],
    )

    output_dir = tmp_path / "extracted"
    result = await extract("https://example.com/article", str(output_dir))

    assert result == str(output_dir)
    assert (output_dir / "text.txt").read_text(encoding="utf-8") == "Arsenal won the match."
    assert json.loads((output_dir / "videos.json").read_text(encoding="utf-8"))["videos"][0]["kind"] == "iframe"
    assert not (output_dir / "images.json").exists()
    page = json.loads((output_dir / "page.json").read_text(encoding="utf-8"))
    assert page["title"] == "Arsenal Win"
    assert page["images"][0]["alt"] == "Team"
    mock_extract.assert_awaited_once_with("https://example.com/article", [])


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.extract_page_content", new_callable=AsyncMock)
async def test_extract_rejects_missing_title(mock_extract, mock_get_config, tmp_path):
    mock_get_config.return_value = {"athletic_cookies": []}
    mock_extract.return_value = PageContent(
        url="https://example.com/article",
        title="",
        main_text="Some article text",
    )

    with pytest.raises(ValueError, match="No article title found"):
        await extract("https://example.com/article", str(tmp_path))


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.extract_page_content", new_callable=AsyncMock)
async def test_extract_rejects_missing_text(mock_extract, mock_get_config, tmp_path):
    mock_get_config.return_value = {"athletic_cookies": []}
    mock_extract.return_value = PageContent(
        url="https://example.com/article",
        title="Article title",
        main_text="",
    )

    with pytest.raises(ValueError, match="No article text found"):
        await extract("https://example.com/article", str(tmp_path))


@pytest.mark.asyncio
@patch("src.pipeline_definition._build_pipeline_runner")
async def test_run_configures_pipeline_runner(mock_build_runner):
    url = "https://www.nytimes.com/athletic/123/article-slug/"
    output_dir = "output/custom/article-slug"
    mock_build_runner.return_value.run = AsyncMock()

    result = await run(
        url,
        output_dir=output_dir,
        resume=True,
        from_step="download-images",
        to_step="video",
        force_steps={"generate-audio"},
        dry_run=True,
    )

    assert result == output_dir
    context = mock_build_runner.call_args.args[0]
    assert context.article_url == url
    assert context.output_dir == output_dir
    assert context.llm_cache_enabled is True
    mock_build_runner.return_value.run.assert_awaited_once_with(
        resume=True,
        from_step="download-images",
        to_step="video",
        force_steps={"generate-audio"},
        dry_run=True,
    )


@pytest.mark.asyncio
@patch("src.pipeline_definition._build_pipeline_runner")
async def test_run_skip_video_stops_after_audio(mock_build_runner):
    url = "https://www.nytimes.com/athletic/123/article-slug/"
    output_dir = f"output/{date.today()}/article-slug"
    mock_build_runner.return_value.run = AsyncMock()

    result = await run(url, skip_video=True)

    assert result == output_dir
    mock_build_runner.return_value.run.assert_awaited_once_with(
        resume=False,
        from_step=None,
        to_step="generate-audio",
        force_steps=None,
        dry_run=False,
    )


@pytest.mark.asyncio
@patch("src.pipeline_definition._build_pipeline_runner")
async def test_run_pipeline_step_uses_article_url_from_page(mock_build_runner, tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({"url": "https://example.com/article"}),
        encoding="utf-8",
    )
    mock_build_runner.return_value.run = AsyncMock()

    result = await run_pipeline_step(
        "video",
        str(output_dir),
        video_title="自定义标题",
    )

    assert result == str(output_dir)
    context = mock_build_runner.call_args.args[0]
    assert context.article_url == "https://example.com/article"
    assert context.video_title == "自定义标题"
    mock_build_runner.return_value.run.assert_awaited_once_with(
        resume=True,
        from_step="video",
        to_step="video",
        force_steps=None,
    )


@pytest.mark.asyncio
@patch("src.pipeline_definition._build_pipeline_runner")
async def test_run_pipeline_step_force_keeps_llm_cache_enabled(
    mock_build_runner, tmp_path
):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({"url": "https://example.com/article"}),
        encoding="utf-8",
    )
    mock_build_runner.return_value.run = AsyncMock()

    await run_pipeline_step("write-script", str(output_dir), force=True)

    context = mock_build_runner.call_args.args[0]
    assert context.llm_cache_enabled is True
    mock_build_runner.return_value.run.assert_awaited_once_with(
        resume=True,
        from_step="write-script",
        to_step="write-script",
        force_steps={"write-script"},
    )


@pytest.mark.asyncio
@patch("src.pipeline_definition._build_pipeline_runner")
async def test_generate_audio_command_runs_audio_stage_only(
    mock_build_runner, tmp_path
):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({"url": "https://example.com/article"}),
        encoding="utf-8",
    )
    mock_build_pipeline = mock_build_runner.return_value
    mock_build_pipeline.run = AsyncMock()

    result = await run_content_audio_pipeline(str(output_dir))

    assert result == str(output_dir)
    mock_build_pipeline.run.assert_awaited_once_with(
        resume=True,
        from_step="generate-audio",
        to_step="generate-audio",
        force_steps=None,
    )


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.download_image_assets", new_callable=AsyncMock)
async def test_download_images_command_reads_manifest_and_writes_results(
    mock_download, mock_get_config, tmp_path
):
    mock_get_config.return_value = {"athletic_cookies": []}
    output_dir = tmp_path / "extracted"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({
            "url": "https://example.com/article",
            "images": [{"url": "https://cdn.example.com/image.jpg", "alt": "Team"}],
            "cover_image_index": 0,
            "cover_image_url": "https://cdn.example.com/cover.jpg",
        }),
        encoding="utf-8",
    )
    mock_download.return_value = [{
        "url": "https://cdn.example.com/image.jpg",
        "local_path": "images/000.jpg",
        "status": "downloaded",
        "error": None,
        "is_cover": True,
    }]

    result = await download_images_command(str(output_dir))

    assert result == str(output_dir)
    records = json.loads((output_dir / "images.json").read_text(encoding="utf-8"))
    assert records["images"][0]["local_path"] == "images/000.jpg"
    cover = json.loads((output_dir / "cover.json").read_text(encoding="utf-8"))
    assert cover == {
        "schema_version": 1,
        "image_index": 0,
        "image_url": "https://cdn.example.com/cover.jpg",
        "local_path": "images/000.jpg",
    }
    mock_download.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.download_image_assets", new_callable=AsyncMock)
async def test_download_images_command_writes_fallback_cover(
    mock_download, mock_get_config, tmp_path
):
    mock_get_config.return_value = {"athletic_cookies": []}
    output_dir = tmp_path / "extracted"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({
            "url": "https://example.com/article",
            "images": [
                {"url": "https://cdn.example.com/lead.jpg"},
                {"url": "https://cdn.example.com/body.jpg"},
            ],
            "cover_image_index": 0,
            "cover_image_url": "https://cdn.example.com/lead.jpg",
        }),
        encoding="utf-8",
    )
    mock_download.return_value = [
        {
            "url": "https://cdn.example.com/lead.jpg",
            "local_path": "images/000.jpg",
            "status": "failed",
            "error": "HTTP 404",
            "is_cover": False,
        },
        {
            "url": "https://cdn.example.com/body.jpg",
            "local_path": "images/001.jpg",
            "status": "downloaded",
            "error": None,
            "is_cover": True,
        },
    ]

    await download_images_command(str(output_dir))

    cover = json.loads((output_dir / "cover.json").read_text(encoding="utf-8"))
    assert cover == {
        "schema_version": 1,
        "image_index": 1,
        "image_url": "https://cdn.example.com/body.jpg",
        "local_path": "images/001.jpg",
    }


@pytest.mark.asyncio
@patch("src.workflow.get_config")
@patch("src.workflow.download_image_assets", new_callable=AsyncMock)
async def test_download_images_command_removes_manifests_when_all_images_fail(
    mock_download, mock_get_config, tmp_path
):
    mock_get_config.return_value = {"athletic_cookies": []}
    output_dir = tmp_path / "extracted"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({
            "url": "https://example.com/article",
            "images": [{"url": "https://cdn.example.com/image.jpg"}],
            "cover_image_index": 0,
            "cover_image_url": "https://cdn.example.com/image.jpg",
        }),
        encoding="utf-8",
    )
    (output_dir / "images.json").write_text("old manifest", encoding="utf-8")
    (output_dir / "cover.json").write_text("old cover", encoding="utf-8")
    mock_download.return_value = [{
        "url": "https://cdn.example.com/image.jpg",
        "local_path": "images/000.jpg",
        "status": "failed",
        "error": "HTTP 404",
        "is_cover": False,
    }]

    with pytest.raises(ValueError, match="Failed to download any images"):
        await download_images_command(str(output_dir))

    assert not (output_dir / "images.json").exists()
    assert not (output_dir / "cover.json").exists()


@pytest.mark.asyncio
@patch("src.workflow._create_llm_client")
@patch("src.workflow.generate_tts", new_callable=AsyncMock)
@patch("src.workflow.generate_image_captions")
@patch("src.workflow.get_config")
async def test_generate_audio_assets_translates_captions_with_llm(
    mock_get_config,
    mock_generate_captions,
    mock_generate_tts,
    mock_create_llm,
    tmp_path,
):
    mock_get_config.return_value = {
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+10%",
    }
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "script.txt").write_text("测试口播稿", encoding="utf-8")
    mock_generate_tts.return_value = (
        str(output_dir / "audio.mp3"),
        str(output_dir / "audio.vtt"),
    )
    llm = object()
    mock_create_llm.return_value = llm

    result = await generate_audio_assets(str(output_dir))

    assert result == str(output_dir)
    mock_create_llm.assert_called_once_with(
        str(output_dir),
        cache_enabled=True,
        usage_callback=None,
    )
    mock_generate_captions.assert_called_once_with(str(output_dir), llm)
    mock_generate_tts.assert_awaited_once()
    assert mock_generate_tts.call_args.args[1:] == (
        "zh-CN-YunjianNeural",
        str(output_dir),
        "+10%",
    )


def test_write_script_command_writes_final_content(tmp_path, caplog):
    caplog.set_level("INFO")
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "analysis.json").write_text("{}", encoding="utf-8")
    analyzed = type("Analyzed", (), {"title_cn": "中文标题"})()
    llm = object()

    with (
        patch("src.workflow._load_source_article") as mock_load_source,
        patch("src.workflow.load_analyzed_article", return_value=analyzed),
        patch("src.workflow._create_llm_client", return_value=llm),
        patch("src.workflow.write_script", return_value=PodcastScript(text="稿件")) as mock_write,
    ):
        mock_load_source.return_value = ScrapedArticle(
            title="测试文章",
            link="https://example.com/article",
            full_text="阿" * 10_000,
        )

        result = write_script_command(str(output_dir))

    assert result == str(output_dir)
    assert mock_write.call_args.args == (analyzed, llm)
    assert mock_write.call_args.kwargs["target_chars"] == 800
    assert (output_dir / "title.txt").read_text(encoding="utf-8") == "中文标题"
    assert (output_dir / "script.txt").read_text(encoding="utf-8") == "稿件"
    assert "target=800 chars, actual=2 chars, delta=-798 chars" in caplog.text


@pytest.mark.asyncio
@patch("src.workflow.get_config")
async def test_generate_audio_requires_final_script(mock_get_config, tmp_path):
    mock_get_config.return_value = {
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+25%",
    }
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Final podcast script"):
        await generate_audio(str(output_dir))


@patch("src.workflow.generate_covers")
def test_run_cover_only_passes_cover_options(mock_generate_covers, tmp_path):
    mock_generate_covers.return_value = [
        str(tmp_path / "cover-v1.png"),
        str(tmp_path / "cover-v1-landscape.png"),
    ]

    result = run_cover_only(
        str(tmp_path),
        title="阿森纳签下领袖吉马良斯",
        image_index=6,
        kicker="阿森纳转会 · 深度报道",
        subtitle="一笔重磅转会背后的故事",
        output_name="cover-v1.png",
    )

    assert result == [str(tmp_path / "cover-v1.png"), str(tmp_path / "cover-v1-landscape.png")]
    mock_generate_covers.assert_called_once_with(
        output_dir=str(tmp_path),
        title="阿森纳签下领袖吉马良斯",
        image_index=6,
        kicker="阿森纳转会 · 深度报道",
        subtitle="一笔重磅转会背后的故事",
        output_name="cover-v1.png",
        orientation="both",
    )


@patch("src.workflow.generate_covers")
def test_run_cover_only_passes_vertical_orientation(mock_generate_covers, tmp_path):
    mock_generate_covers.return_value = [str(tmp_path / "cover.png")]

    result = run_cover_only(str(tmp_path), orientation="vertical")

    assert result == [str(tmp_path / "cover.png")]
    mock_generate_covers.assert_called_once_with(
        output_dir=str(tmp_path),
        title="",
        image_index=None,
        kicker="英超新闻 · 深度报道",
        subtitle="",
        output_name="cover.png",
        orientation="vertical",
    )


@patch("src.workflow.generate_publish_copy")
def test_run_publish_only_generates_publish_files(
    mock_generate_publish_copy,
    tmp_path,
):
    mock_generate_publish_copy.return_value = {
        "title": "统一的封面和发布标题",
    }
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "00000.jpg").write_bytes(b"jpg")

    result = run_publish_only(str(tmp_path))

    assert result == str(tmp_path / "publish.json")
    assert frames_dir.exists()
    mock_generate_publish_copy.assert_called_once_with(str(tmp_path))
