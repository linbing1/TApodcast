import json
from unittest.mock import ANY, AsyncMock, patch

import pytest

from main import download_images_command, extract, generate_audio
from src.models import (
    AnalyzedArticle,
    ImageAsset,
    PageContent,
    PodcastScript,
    VideoAsset,
)


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
    assert json.loads((output_dir / "images.json").read_text(encoding="utf-8"))[0]["alt"] == "Team"
    assert json.loads((output_dir / "videos.json").read_text(encoding="utf-8"))[0]["kind"] == "iframe"
    page = json.loads((output_dir / "page.json").read_text(encoding="utf-8"))
    assert page["title"] == "Arsenal Win"
    mock_extract.assert_awaited_once_with("https://example.com/article", [])


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
    assert records[0]["local_path"] == "images/000.jpg"
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
async def test_generate_audio_requires_article_text(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text(
        json.dumps({"title": "Empty", "main_text": ""}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No article text"):
        await generate_audio(str(output_dir))
