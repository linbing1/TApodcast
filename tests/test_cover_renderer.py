from datetime import date
from pathlib import Path

from PIL import Image

from src import cover_renderer


def test_format_cover_date():
    assert cover_renderer._format_cover_date(date(2026, 8, 11)) == "2026.08.11"


def test_generate_cover_reads_title_and_writes_vertical_png(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    Image.new("RGB", (1200, 800), "#164d75").save(image_dir / "000.jpg")
    Image.new("RGB", (800, 1200), "#875522").save(image_dir / "001.jpg")
    (tmp_path / "title.txt").write_text("枪手签下领袖吉马良斯", encoding="utf-8")
    (tmp_path / "page.json").write_text(
        '{"cover_image_index": 1, "cover_image_url": "https://example.com/001.jpg"}',
        encoding="utf-8",
    )

    font = ImageFontForTest()
    monkeypatch.setattr(cover_renderer, "find_cjk_font", lambda: str(font.path))
    monkeypatch.setattr(cover_renderer.ImageFont, "truetype", lambda *args, **kwargs: font.font)

    output = cover_renderer.generate_cover(
        str(tmp_path),
        kicker="转会专题",
        subtitle="一笔重磅转会背后的故事",
    )

    assert output == str(tmp_path / "cover.png")
    assert Path(output).exists()
    assert Image.open(output).size == (1080, 1920)


class ImageFontForTest:
    def __init__(self):
        from PIL import ImageFont

        self.path = Path("/tmp/test-cover-font.otf")
        self.font = ImageFont.load_default()
