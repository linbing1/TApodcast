import json

import pytest

from src.manifest import ManifestStore, fingerprint_paths


def test_manifest_records_completed_step_and_reloads(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "input.txt").write_text("input", encoding="utf-8")
    (output_dir / "output.txt").write_text("output", encoding="utf-8")

    store = ManifestStore(str(output_dir), "https://example.com/article")
    inputs = fingerprint_paths(output_dir, ["input.txt"])
    outputs = fingerprint_paths(output_dir, ["output.txt"])
    store.mark_running("analyze", inputs)
    store.mark_completed("analyze", outputs, 1.23456)

    reloaded = ManifestStore(str(output_dir), "https://example.com/article")
    record = reloaded.get_step("analyze")
    assert record.status == "completed"
    assert record.attempts == 1
    assert record.duration_seconds == 1.235
    assert reloaded.can_skip("analyze", inputs)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["article_url"] == "https://example.com/article"


def test_manifest_migrates_schema_v1(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "article_url": "https://example.com/article",
            "output_dir": str(output_dir),
            "steps": {},
        }),
        encoding="utf-8",
    )

    store = ManifestStore(
        str(output_dir),
        "https://example.com/article",
        configuration={"llm_model": "test-model"},
        prompt_versions={"analyzer": "v1"},
    )
    store.mark_running("extract", {})

    migrated = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["configuration"]["llm_model"] == "test-model"
    assert migrated["prompt_versions"]["analyzer"] == "v1"


def test_manifest_detects_changed_output(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "output.txt").write_text("original", encoding="utf-8")

    store = ManifestStore(str(output_dir), "https://example.com/article")
    outputs = fingerprint_paths(output_dir, ["output.txt"])
    store.mark_running("render", {})
    store.mark_completed("render", outputs, 0.1)

    (output_dir / "output.txt").write_text("changed", encoding="utf-8")

    assert not store.can_skip("render", {})


def test_manifest_rejects_different_article_for_same_directory(tmp_path):
    output_dir = tmp_path / "article"
    store = ManifestStore(str(output_dir), "https://example.com/first")
    store.mark_running("extract", {})

    with pytest.raises(ValueError, match="different article"):
        ManifestStore(str(output_dir), "https://example.com/second")
