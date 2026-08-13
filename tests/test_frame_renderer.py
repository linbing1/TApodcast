from PIL import Image, ImageFont

from src import frame_renderer
from src.frame_renderer import (
    _composite,
    _draw_image_caption,
    _image_geometry,
    render_frames,
)


def test_composite_returns_black_vertical_canvas_with_centered_image():
    image = Image.new("RGB", (800, 600), color="red")

    result = _composite(image)

    assert result.size == (1080, 1920)
    assert result.getpixel((0, 0)) == (0, 0, 0)
    assert result.getpixel((1079, 1919)) == (0, 0, 0)
    assert result.getpixel((540, 960))[0] > 200


def test_render_frames_creates_numbered_jpegs_without_text_overlay(tmp_path):
    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (800, 600), color="blue").save(image_path)

    frames_dir, fps = render_frames(
        image_paths=[str(image_path)],
        duration=0.4,
        per_image=1.0,
        srt_path=str(tmp_path / "audio.vtt"),
        title="Title",
        article_date="2026-08-11",
        output_dir=str(tmp_path),
        img_top=600,
    )

    frame_paths = sorted((tmp_path / "frames").glob("*.jpg"))
    assert frames_dir == str(tmp_path / "frames")
    assert fps == 15
    assert len(frame_paths) == 7

    frame = Image.open(frame_paths[0])
    assert frame.size == (1080, 1920)
    assert frame.getpixel((0, 0)) == (0, 0, 0)


def test_composite_draws_right_aligned_caption_relative_to_image(monkeypatch):
    monkeypatch.setattr(
        frame_renderer,
        "_load_caption_font",
        lambda size, font_path=None: ImageFont.load_default(size=32),
    )
    canvas = Image.new("RGB", (1080, 1920), color="black")

    _draw_image_caption(
        canvas,
        "Liverpool owners celebrate",
        (140, 400, 940, 1000),
    )

    caption_bounds = canvas.getbbox()
    assert caption_bounds is not None
    assert caption_bounds[0] > 400
    assert caption_bounds[2] <= 940


def test_draw_image_caption_centers_visible_text_inside_background(monkeypatch):
    calls = {}

    class FakeDraw:
        def textbbox(self, position, text, font):
            del position, text, font
            return (0, 10, 100, 42)

        def rounded_rectangle(self, bounds, **kwargs):
            del kwargs
            calls["box"] = bounds

        def text(self, position, text, **kwargs):
            del text, kwargs
            calls["text"] = position

    monkeypatch.setattr(frame_renderer.ImageDraw, "Draw", lambda *args: FakeDraw())
    font = ImageFont.load_default(size=32)

    _draw_image_caption(
        Image.new("RGB", (1080, 1920), color="black"),
        "测试图注",
        (140, 400, 940, 1000),
        caption_layout=(font, ["测试图注"]),
    )

    box_left, box_top, box_right, box_bottom = calls["box"]
    text_x, text_y = calls["text"]
    visible_bounds = (
        text_x,
        text_y + 10,
        text_x + 100,
        text_y + 42,
    )

    assert visible_bounds[1] - box_top == frame_renderer._CAPTION_VERTICAL_PADDING
    assert box_bottom - visible_bounds[3] == frame_renderer._CAPTION_VERTICAL_PADDING
    assert visible_bounds[2] == box_right - frame_renderer._CAPTION_HORIZONTAL_PADDING


def test_render_frames_keeps_caption_mapped_to_each_image(monkeypatch, tmp_path):
    image_paths = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"image-{index}.jpg"
        Image.new("RGB", (800, 600), color=color).save(path)
        image_paths.append(str(path))

    rendered = []

    def fake_composite(image, caption="", font_path=None, *args):
        del image, font_path, args
        rendered.append(caption)
        return Image.new("RGB", (1080, 1920), color="black")

    monkeypatch.setattr(frame_renderer, "_composite", fake_composite)

    render_frames(
        image_paths=image_paths,
        duration=2.0,
        per_image=1.0,
        srt_path=str(tmp_path / "audio.vtt"),
        title="",
        article_date="",
        output_dir=str(tmp_path),
        image_captions=["第一张图注", "第二张图注"],
    )

    assert rendered[0] == "第一张图注"
    assert set(rendered) == {"第一张图注", "第二张图注"}
    assert rendered.index("第一张图注") < rendered.index("第二张图注")


def test_image_geometry_applies_smooth_zoom_and_directional_pan():
    start = _image_geometry(1200, 675, 0.0, motion_index=0)
    end = _image_geometry(1200, 675, 1.0, motion_index=0)

    assert end[2] - end[0] > start[2] - start[0]
    assert end[3] - end[1] > start[3] - start[1]
    assert end[0] < start[0]


def test_composite_keeps_canvas_size_during_ken_burns_motion():
    image = Image.new("RGB", (1200, 675), color="red")

    start = _composite(image, progress=0.0)
    end = _composite(image, progress=1.0)

    assert start.size == (1080, 1920)
    assert end.size == (1080, 1920)
    assert start.getpixel((0, 0)) == (0, 0, 0)
