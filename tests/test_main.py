import json
from datetime import date
from unittest.mock import ANY, AsyncMock, patch

import pytest

from main import (
    _build_pipeline_runner,
    download_images_command,
    extract,
    generate_audio,
    run,
    run_cover_only,
    run_pipeline_step,
    run_publish_only,
)
from src.models import (
    AnalyzedArticle,
    ImageAsset,
    PageContent,
    PodcastScript,
    VideoAsset,
)
from src.pipeline import PipelineContext


def test_pipeline_registers_all_publish_stages(tmp_path):
    runner = _build_pipeline_runner(
        PipelineContext("https://example.com/article", str(tmp_path))
    )

    assert runner.step_names == [
        "extract",
        "download-images",
        "generate-audio",
        "video",
        "cover",
        "publish-copy",
    ]


@pytest.mark.asyncio
@patch("main.get_config")
@patch("main.extract_page_content", new_callable=AsyncMock)
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
    assert json.loads((output_dir / "images.json").read_text(encoding="utf-8"))["images"][0]["alt"] == "Team"
    assert json.loads((output_dir / "videos.json").read_text(encoding="utf-8"))["videos"][0]["kind"] == "iframe"
    page = json.loads((output_dir / "page.json").read_text(encoding="utf-8"))
    assert page["title"] == "Arsenal Win"
    mock_extract.assert_awaited_once_with("https://example.com/article", [])


@pytest.mark.asyncio
@patch("main._build_pipeline_runner")
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
    mock_build_runner.return_value.run.assert_awaited_once_with(
        resume=True,
        from_step="download-images",
        to_step="video",
        force_steps={"generate-audio"},
        dry_run=True,
    )


@pytest.mark.asyncio
@patch("main._build_pipeline_runner")
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
@patch("main._build_pipeline_runner")
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
        from_step="video",
        to_step="video",
    )


@pytest.mark.asyncio
@patch("main.get_config")
@patch("main.download_image_assets", new_callable=AsyncMock)
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
@patch("main.generate_tts", new_callable=AsyncMock)
@patch("main.write_script")
@patch("main.analyze_article")
@patch("main.get_config")
async def test_generate_audio_reads_page_and_writes_stage_outputs(
    mock_get_config, mock_analyze, mock_write, mock_tts, tmp_path
):
    mock_get_config.return_value = {
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+25%",
    }
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({
            "url": "https://example.com/article",
            "title": "Arsenal Win",
            "main_text": "Arsenal won the match.",
        }),
        encoding="utf-8",
    )

    analyzed = AnalyzedArticle(
        title_cn="阿森纳胜利",
        title_original="Arsenal Win",
        article_type="新闻报道",
        overview="阿森纳赢下比赛。",
        detail="比赛详情。",
        key_people_and_data="关键数据。",
        impact="后续影响。",
        link="https://example.com/article",
    )
    mock_analyze.return_value = analyzed
    mock_write.return_value = PodcastScript(text="欢迎收听英超每日观察。")
    mock_tts.return_value = (
        str(output_dir / "audio.mp3"),
        str(output_dir / "audio.vtt"),
    )

    result = await generate_audio(str(output_dir))

    assert result == str(output_dir)
    saved_analysis = json.loads(
        (output_dir / "analysis.json").read_text(encoding="utf-8")
    )
    assert saved_analysis["title_cn"] == "阿森纳胜利"
    assert (output_dir / "title.txt").read_text(encoding="utf-8") == "阿森纳胜利"
    assert (output_dir / "script.txt").read_text(encoding="utf-8") == "欢迎收听英超每日观察。"

    article = mock_analyze.call_args.args[0]
    assert article.title == "Arsenal Win"
    assert article.link == "https://example.com/article"
    assert article.full_text == "Arsenal won the match."
    llm = mock_analyze.call_args.args[1]
    mock_write.assert_called_once_with(analyzed, llm, date_str=ANY)
    mock_tts.assert_awaited_once_with(
        mock_write.return_value,
        "zh-CN-YunjianNeural",
        str(output_dir),
        "+25%",
    )


@pytest.mark.asyncio
@patch("main.get_config")
async def test_generate_audio_requires_article_text(mock_get_config, tmp_path):
    mock_get_config.return_value = {
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "tts_voice": "zh-CN-YunjianNeural",
        "tts_rate": "+25%",
    }
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({"title": "Empty", "main_text": ""}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No article text"):
        await generate_audio(str(output_dir))


@patch("main.generate_cover_landscape")
@patch("main.generate_cover")
def test_run_cover_only_passes_cover_options(mock_generate_cover, mock_generate_landscape, tmp_path):
    mock_generate_cover.return_value = str(tmp_path / "cover-v1.png")
    mock_generate_landscape.return_value = str(tmp_path / "cover-v1-landscape.png")

    result = run_cover_only(
        str(tmp_path),
        title="阿森纳签下领袖吉马良斯",
        image_index=6,
        kicker="阿森纳转会 · 深度报道",
        subtitle="一笔重磅转会背后的故事",
        output_name="cover-v1.png",
    )

    assert result == [str(tmp_path / "cover-v1.png"), str(tmp_path / "cover-v1-landscape.png")]
    mock_generate_cover.assert_called_once_with(
        output_dir=str(tmp_path),
        title="阿森纳签下领袖吉马良斯",
        image_index=6,
        kicker="阿森纳转会 · 深度报道",
        subtitle="一笔重磅转会背后的故事",
        output_name="cover-v1.png",
    )
    mock_generate_landscape.assert_called_once_with(
        output_dir=str(tmp_path),
        title="阿森纳签下领袖吉马良斯",
        image_index=6,
        kicker="阿森纳转会 · 深度报道",
        subtitle="一笔重磅转会背后的故事",
        output_name="cover-v1-landscape.png",
    )


@patch("main.generate_cover_landscape")
@patch("main.generate_cover")
def test_run_cover_only_vertical_skips_landscape(mock_generate_cover, mock_generate_landscape, tmp_path):
    mock_generate_cover.return_value = str(tmp_path / "cover.png")

    result = run_cover_only(str(tmp_path), orientation="vertical")

    assert result == [str(tmp_path / "cover.png")]
    mock_generate_landscape.assert_not_called()


@patch("main.generate_publish_copy")
@patch("main.LLMClient")
@patch("main.get_config")
def test_run_publish_only_generates_publish_files(
    mock_get_config,
    mock_llm_class,
    mock_generate_publish_copy,
    tmp_path,
):
    mock_get_config.return_value = {
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
    }
    mock_generate_publish_copy.return_value = {
        "title": "统一的封面和发布标题",
    }
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "00000.jpg").write_bytes(b"jpg")

    result = run_publish_only(str(tmp_path))

    assert result == str(tmp_path / "publish.json")
    assert not frames_dir.exists()
    mock_llm_class.assert_called_once_with(
        "https://llm.example.com/v1",
        "test-key",
        "test-model",
    )
    mock_generate_publish_copy.assert_called_once_with(
        str(tmp_path),
        mock_llm_class.return_value,
    )
