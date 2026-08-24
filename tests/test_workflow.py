import json
from unittest.mock import patch

import pytest

from src.workflow import run_video_only


def test_run_video_only_uses_downloaded_manifest_order(tmp_path):
    output_dir = tmp_path / "article"
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True)
    first_image = images_dir / "000.jpg"
    second_image = images_dir / "002.jpg"
    stale_image = images_dir / "999.jpg"
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")
    stale_image.write_bytes(b"stale")
    (output_dir / "images.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "images": [
                    {"local_path": "images/002.jpg", "status": "downloaded"},
                    {"local_path": "images/001.jpg", "status": "failed"},
                    {"local_path": "images/000.jpg", "status": "downloaded"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "audio.mp3").write_bytes(b"audio")
    (output_dir / "audio.vtt").write_text("subtitles", encoding="utf-8")

    with (
        patch("src.workflow.load_image_captions", return_value=["第二张", "第一张"]),
        patch("src.workflow.assemble_video") as mock_assemble,
    ):
        run_video_only(str(output_dir), title="测试视频")

    mock_assemble.assert_called_once_with(
        [str(second_image), str(first_image)],
        str(output_dir / "audio.mp3"),
        str(output_dir / "audio.vtt"),
        str(output_dir / "测试视频.mp4"),
        image_captions=["第二张", "第一张"],
    )


def test_run_video_only_requires_usable_downloaded_images(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "images.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "images": [
                    {"local_path": "images/000.jpg", "status": "downloaded"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="No usable downloaded images"):
        run_video_only(str(output_dir), title="测试视频")
