import json
from unittest.mock import AsyncMock, patch

import pytest

from main import download_images_command, extract
from src.models import ImageAsset, PageContent, VideoAsset


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
