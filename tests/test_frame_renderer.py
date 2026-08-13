from PIL import Image, ImageFont

from src import frame_renderer
from src.frame_renderer import _composite, _draw_image_caption, render_frames


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
    assert fps == 5
    assert [path.name for path in frame_paths] == [
        "00000.jpg", "00001.jpg", "00002.jpg"
    ]

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


def test_render_frames_keeps_caption_mapped_to_each_image(monkeypatch, tmp_path):
    image_paths = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"image-{index}.jpg"
        Image.new("RGB", (800, 600), color=color).save(path)
        image_paths.append(str(path))

    rendered = []

    def fake_composite(image, caption="", font_path=None):
        del image, font_path
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

    assert rendered == ["第一张图注", "第二张图注"]
