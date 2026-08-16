from datetime import date
from pathlib import Path

from PIL import Image
from PIL import ImageDraw

from src import cover_renderer


def _draw():
    canvas = Image.new("RGB", (cover_renderer.COVER_WIDTH, cover_renderer.COVER_HEIGHT))
    return ImageDraw.Draw(canvas)


def _assert_lines_fit(lines, draw, font):
    assert all(
        cover_renderer._title_width(draw, line, font) <= cover_renderer.MAX_TITLE_WIDTH
        for line in lines
    )


def test_format_cover_date():
    assert cover_renderer._format_cover_date(date(2026, 8, 11)) == "2026.08.11"


def test_split_title_keeps_each_line_inside_safe_width():
    draw = _draw()
    font = ImageFontForTest().font

    lines = cover_renderer._split_title(
        "刘易斯-斯凯利心属阿森纳，球迷深情呼唤留下" * 10,
        draw,
        font,
    )

    assert len(lines) >= 2
    _assert_lines_fit(lines, draw, font)


def test_split_title_wraps_explicit_lines():
    draw = _draw()
    font = ImageFontForTest().font

    lines = cover_renderer._split_title("第一行很长很长很长\n第二行也很长很长", draw, font)

    assert len(lines) >= 2
    _assert_lines_fit(lines, draw, font)


def test_split_title_prefers_semantic_break_after_phrase(monkeypatch):
    draw = _draw()

    class SizedFont:
        size = 96

    def fake_text_width(draw, text, font, stroke_width=0):
        return len(text) * 50

    monkeypatch.setattr(cover_renderer, "_text_width", fake_text_width)

    lines = cover_renderer._split_title(
        "刘易斯-斯凯利心属阿森纳，球迷深情呼唤留下",
        draw,
        SizedFont(),
    )

    assert lines == ["刘易斯-斯凯利心属阿森纳，", "球迷深情呼唤留下"]
    assert "心属阿森纳" in lines[0]
    assert all(not line.startswith(("，", "。", "！", "？")) for line in lines)


def test_fit_title_prefers_two_lines_with_smaller_font(monkeypatch):
    draw = _draw()
    loaded_sizes = []

    class SizedFont:
        def __init__(self, size):
            self.size = size

    def fake_load_font(size):
        loaded_sizes.append(size)
        return SizedFont(size)

    def fake_text_width(draw, text, font, stroke_width=0):
        return len(text) * font.size

    monkeypatch.setattr(cover_renderer, "_load_font", fake_load_font)
    monkeypatch.setattr(cover_renderer, "_text_width", fake_text_width)

    font, lines = cover_renderer._fit_title("一二三四五六七八九十" * 2, draw)

    assert font.size < cover_renderer.TITLE_FONT_SIZE
    assert len(lines) == 2
    assert loaded_sizes[0] == cover_renderer.TITLE_FONT_SIZE


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


def test_generate_cover_prefers_shared_title_file(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    Image.new("RGB", (1200, 800), "#164d75").save(image_dir / "000.jpg")
    (tmp_path / "title.txt").write_text("统一的封面和发布标题", encoding="utf-8")
    (tmp_path / "publish_title.txt").write_text("旧的发布标题", encoding="utf-8")

    captured = {}

    def fake_render_cover(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(cover_renderer, "render_cover", fake_render_cover)

    cover_renderer.generate_cover(str(tmp_path))

    assert captured["title"] == "统一的封面和发布标题"


def test_generate_cover_landscape_writes_horizontal_png(tmp_path, monkeypatch):
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

    output = cover_renderer.generate_cover_landscape(str(tmp_path))

    assert output == str(tmp_path / "cover-landscape.png")
    assert Path(output).exists()
    assert Image.open(output).size == (1920, 1080)


def test_generate_cover_landscape_uses_same_inputs_as_vertical(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    Image.new("RGB", (1200, 800), "#164d75").save(image_dir / "000.jpg")
    (tmp_path / "title.txt").write_text("统一的封面标题", encoding="utf-8")

    captured = {}

    def fake_render_cover_landscape(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(cover_renderer, "render_cover_landscape", fake_render_cover_landscape)

    cover_renderer.generate_cover_landscape(
        str(tmp_path),
        image_index=0,
        kicker="英超转会",
        output_name="wide.png",
    )

    assert captured["title"] == "统一的封面标题"
    assert captured["image_path"] == str(image_dir / "000.jpg")
    assert captured["kicker"] == "英超转会"
    assert captured["output_path"] == str(tmp_path / "wide.png")


class ImageFontForTest:
    def __init__(self):
        from PIL import ImageFont

        self.path = Path("/tmp/test-cover-font.otf")
        self.font = ImageFont.load_default()
