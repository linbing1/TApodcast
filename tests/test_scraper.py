from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image as PILImage

from src.models import ImageAsset, PageContent
from src.scraper import (
    _clean_main_text,
    _extract_jsonld_images,
    _merge_images,
    _select_cover_image,
    _split_caption_credit,
    download_images,
)


def _make_pil_mock(width: int = 800, height: int = 600) -> MagicMock:
    """Return a MagicMock that behaves like a PIL Image of the given dimensions."""
    img = MagicMock(spec=PILImage.Image)
    img.size = (width, height)
    img.load = MagicMock()
    img.convert.return_value = img
    img.save = MagicMock()
    return img


def test_clean_main_text_removes_related_reading_block():
    text = """First paragraph.

WHAT YOU SHOULD READ NEXT
Related headline one
Related headline two

Second paragraph."""

    assert _clean_main_text(text) == "First paragraph.\n\nSecond paragraph."


def test_extract_jsonld_images_keeps_one_crop_and_metadata():
    raw_script = """{
        "@type": "NewsArticle",
        "image": [
            {
                "@type": "ImageObject",
                "contentUrl": "https://cdn.example.com/lead.jpg?width=1200&height=675&fit=cover",
                "width": "1200",
                "height": "675",
                "caption": "Xabi Alonso gives instructions to Cole Palmer",
                "alternateName": "Xabi Alonso and Cole Palmer in Sydney",
                "creditText": "Robbie Stephenson - PA Images via Getty Images"
            },
            {
                "@type": "ImageObject",
                "contentUrl": "https://cdn.example.com/lead.jpg?width=1200&height=900&fit=cover"
            }
        ],
        "thumbnailUrl": "https://cdn.example.com/lead.jpg"
    }"""

    images = _extract_jsonld_images([raw_script], "https://example.com/article")

    assert images == [ImageAsset(
        url="https://cdn.example.com/lead.jpg?width=1200&height=675&fit=cover",
        alt="Xabi Alonso and Cole Palmer in Sydney",
        caption="Xabi Alonso gives instructions to Cole Palmer",
        credit="Robbie Stephenson - PA Images via Getty Images",
        width=1200,
        height=675,
    )]


def test_merge_images_prefers_jsonld_order_and_enriches_metadata():
    jsonld = ImageAsset(
        url="https://cdn.example.com/lead.jpg?width=1200&height=675&fit=cover",
        caption="Lead caption",
        credit="Photo credit",
    )
    dom = ImageAsset(
        url="https://cdn.example.com/lead.jpg?width=800",
        alt="Lead alt text",
        width=800,
        height=450,
    )

    assert _merge_images([jsonld], [dom]) == [ImageAsset(
        url=jsonld.url,
        alt="Lead alt text",
        caption="Lead caption",
        credit="Photo credit",
        width=800,
        height=450,
    )]


def test_select_cover_image_prefers_metadata_over_positional_match():
    images = [
        ImageAsset(url="https://cdn.example.com/lead.jpg?width=1200&height=675"),
        ImageAsset(url="https://cdn.example.com/body.jpg"),
    ]

    assert _select_cover_image(
        images,
        "https://cdn.example.com/lead.jpg?width=1080&height=630&fit=cover",
        "https://cdn.example.com/body.jpg",
    ) == (0, "https://cdn.example.com/lead.jpg?width=1080&height=630&fit=cover")


def test_select_cover_image_falls_back_to_positional_match():
    images = [
        ImageAsset(url="https://cdn.example.com/lead.jpg"),
        ImageAsset(url="https://cdn.example.com/body.jpg"),
    ]

    assert _select_cover_image(
        images,
        "https://cdn.example.com/missing.jpg",
        "https://cdn.example.com/body.jpg",
    ) == (1, "https://cdn.example.com/body.jpg")


def test_split_caption_credit_separates_parenthesized_photo_source():
    caption, credit = _split_caption_credit(
        "Jeff Bezos founded Amazon from his garage in 1994 "
        "(Julien De Rosa/AFP via Getty Images)"
    )

    assert caption == "Jeff Bezos founded Amazon from his garage in 1994"
    assert credit == "Julien De Rosa/AFP via Getty Images"


@pytest.mark.asyncio
@patch("src.scraper.PILImage")
@patch("src.scraper.httpx.AsyncClient")
async def test_download_images_returns_local_manifest(
    mock_httpx_cls, mock_pil, tmp_path
):
    mock_client = AsyncMock()
    mock_httpx_cls.return_value.__aenter__.return_value = mock_client
    mock_response = AsyncMock()
    mock_response.content = b"fake-image-data"
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response
    mock_pil.open.return_value = _make_pil_mock(800, 600)

    records = await download_images(
        [ImageAsset(url="https://cdn.example.com/image.jpg", alt="Team")],
        str(tmp_path),
        referer="https://example.com/article",
        cookies=[{"name": "sid", "value": "abc"}],
        cover_image_index=0,
    )

    assert records == [{
        "url": "https://cdn.example.com/image.jpg",
        "local_path": "images/000.jpg",
        "status": "downloaded",
        "error": None,
        "alt": "Team",
        "caption": "",
        "credit": "",
        "width": None,
        "height": None,
        "is_cover": True,
    }]
    headers = mock_client.get.call_args.kwargs["headers"]
    assert headers["Referer"] == "https://example.com/article"
    assert headers["Cookie"] == "sid=abc"
