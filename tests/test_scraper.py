import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image as PILImage

from src.scraper import scrape_article


def _make_pil_mock(width: int = 800, height: int = 600) -> MagicMock:
    """Return a MagicMock that behaves like a PIL Image of the given dimensions."""
    img = MagicMock(spec=PILImage.Image)
    img.size = (width, height)
    img.load = MagicMock()
    img.convert.return_value = img
    img.save = MagicMock()
    return img


class TestScrapeArticle:
    @pytest.mark.asyncio
    @patch("src.scraper.PILImage")
    @patch("src.scraper.httpx.AsyncClient")
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_returns_scraped_article(self, mock_pw, mock_extract, mock_httpx_cls, mock_pil, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = (
            "Arsenal vs City match report",
            "Arsenal Win",
            ["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        )
        mock_client = AsyncMock()
        mock_httpx_cls.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()
        mock_response.content = b"fake-image-data"
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response
        mock_pil.open.return_value = _make_pil_mock(800, 600)

        article = await scrape_article(
            "https://example.com/article", cookies=[], output_dir=str(tmp_path)
        )

        assert article.full_text == "Arsenal vs City match report"
        assert article.title == "Arsenal Win"
        assert len(article.image_paths) == 2

    @pytest.mark.asyncio
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_raises_if_no_images(self, mock_pw, mock_extract, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = ("Some text", "Title", [])

        with pytest.raises(ValueError, match="No images found"):
            await scrape_article(
                "https://example.com/article", cookies=[], output_dir=str(tmp_path)
            )

    @pytest.mark.asyncio
    @patch("src.scraper.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.scraper.PILImage")
    @patch("src.scraper.httpx.AsyncClient")
    @patch("src.scraper._extract_page_data", new_callable=AsyncMock)
    @patch("src.scraper.async_playwright")
    async def test_skips_failed_image_downloads(self, mock_pw, mock_extract, mock_httpx_cls, mock_pil, mock_sleep, tmp_path):
        _setup_playwright_mock(mock_pw)
        mock_extract.return_value = (
            "text", "Title",
            ["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        )
        mock_client = AsyncMock()
        mock_httpx_cls.return_value.__aenter__.return_value = mock_client
        ok_resp = AsyncMock()
        ok_resp.content = b"data"
        ok_resp.raise_for_status = MagicMock()
        # img1 succeeds, img2 always raises
        mock_client.get.side_effect = [
            ok_resp,
            Exception("network error"), Exception("network error"), Exception("network error"),
        ]
        mock_pil.open.return_value = _make_pil_mock(800, 600)

        article = await scrape_article(
            "https://example.com/article", cookies=[], output_dir=str(tmp_path)
        )
        assert len(article.image_paths) == 1


def _setup_playwright_mock(mock_pw):
    mock_instance = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_pw.return_value.__aenter__.return_value = mock_instance
    mock_instance.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
