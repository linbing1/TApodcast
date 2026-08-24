import json
from unittest.mock import patch

from src.cli import build_parser
from src.verifier import format_verify_report, verify_output_dir


def _write_manifest(output_dir, statuses=None):
    statuses = statuses or {}
    steps = {
        name: {"status": statuses.get(name, "completed")}
        for name in (
            "extract",
            "download-images",
            "analyze-content",
            "write-script",
            "generate-audio",
            "video",
            "cover",
            "publish-copy",
        )
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "article_url": "https://example.com/article",
                "output_dir": str(output_dir),
                "steps": steps,
            }
        ),
        encoding="utf-8",
    )


def _write_required_outputs(output_dir):
    for name in (
        "page.json",
        "text.txt",
        "videos.json",
        "images.json",
        "cover.json",
        "analysis.json",
        "title.txt",
        "script.txt",
        "image_captions.json",
        "audio.mp3",
        "audio.vtt",
        "subtitles.ass",
        "cover.png",
        "cover-landscape.png",
        "publish.json",
        "publish_title.txt",
        "publish_description.txt",
    ):
        content = "{}" if name.endswith(".json") else "content"
        (output_dir / name).write_text(content, encoding="utf-8")
    (output_dir / "title.txt").write_text("测试标题", encoding="utf-8")
    (output_dir / "publish_title.txt").write_text("测试标题", encoding="utf-8")
    (output_dir / "publish_description.txt").write_text(
        "简介\n\n#英超",
        encoding="utf-8",
    )
    (output_dir / "images").mkdir()


def test_verify_passes_completed_outputs_without_writing(tmp_path):
    _write_manifest(tmp_path)
    _write_required_outputs(tmp_path)
    before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "manifest.json", tmp_path / "title.txt")
    }

    with (
        patch("src.verifier.validate_video"),
        patch("src.verifier.validate_cover"),
        patch(
            "src.verifier.read_json",
            side_effect=lambda path: (
                {"schema_version": 1, "title": "测试标题", "description": "简介", "hashtags": ["英超"] * 5, "description_with_hashtags": "简介\n\n#英超"}
                if str(path).endswith("publish.json")
                else json.loads(path.read_text(encoding="utf-8"))
            ),
        ),
    ):
        report = verify_output_dir(str(tmp_path))

    assert report.passed
    assert all(check.status == "pass" for check in report.checks)
    assert before["manifest.json"] == (tmp_path / "manifest.json").read_bytes()
    assert before["title.txt"] == (tmp_path / "title.txt").read_bytes()


def test_verify_reports_incomplete_stage_and_missing_outputs(tmp_path):
    _write_manifest(tmp_path, {"cover": "failed"})

    report = verify_output_dir(str(tmp_path))
    text = format_verify_report(report)

    assert not report.passed
    assert "cover=failed" in text
    assert "Missing:" in text
    assert "Summary:" in text


def test_verify_fails_when_frames_remain(tmp_path):
    _write_manifest(tmp_path)
    _write_required_outputs(tmp_path)
    (tmp_path / "frames").mkdir()

    with (
        patch("src.verifier.validate_video"),
        patch("src.verifier.validate_cover"),
        patch(
            "src.verifier.read_json",
            side_effect=lambda path: (
                {"schema_version": 1, "title": "测试标题", "description": "简介", "hashtags": ["英超"] * 5, "description_with_hashtags": "简介\n\n#英超"}
                if str(path).endswith("publish.json")
                else json.loads(path.read_text(encoding="utf-8"))
            ),
        ),
    ):
        report = verify_output_dir(str(tmp_path))

    cleanup_check = next(check for check in report.checks if check.name == "Intermediate cleanup")
    assert cleanup_check.status == "fail"


def test_cli_registers_verify_command():
    args = build_parser().parse_args(["verify", "--dir", "/tmp/article"])

    assert args.cmd == "verify"
    assert args.dir == "/tmp/article"
