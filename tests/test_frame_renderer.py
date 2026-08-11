from PIL import Image

from src.frame_renderer import _composite, render_frames


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
