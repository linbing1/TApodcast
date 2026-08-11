from PIL import Image

from src.frame_renderer import _composite, _parse_subtitles, render_frames


def test_composite_returns_vertical_canvas():
    image = Image.new("RGB", (800, 600), color="red")

    result = _composite(image)

    assert result.size == (1080, 1920)


def test_parse_subtitles_reads_timestamped_entries(tmp_path):
    subtitle_path = tmp_path / "audio.vtt"
    subtitle_path.write_text(
        "1\n00:00:00,100 --> 00:00:01,200\nhello <b>world</b>\n\n",
        encoding="utf-8",
    )

    result = _parse_subtitles(str(subtitle_path))

    assert result == [(0.1, 1.2, "hello world")]


def test_render_frames_creates_numbered_jpegs(tmp_path):
    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (800, 600), color="blue").save(image_path)
    subtitle_path = tmp_path / "audio.vtt"
    subtitle_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n",
        encoding="utf-8",
    )

    frames_dir, fps = render_frames(
        image_paths=[str(image_path)],
        duration=0.4,
        per_image=1.0,
        srt_path=str(subtitle_path),
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
    assert Image.open(frame_paths[0]).size == (1080, 1920)
