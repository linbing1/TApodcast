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
    assert manifest["schema_version"] == 3
    assert manifest["pipeline_version"] == "4"
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
    assert migrated["schema_version"] == 3
    assert migrated["pipeline_version"] == "4"
    assert migrated["configuration"]["llm_model"] == "test-model"
    assert migrated["prompt_versions"]["analyzer"] == "v1"
    assert migrated["llm_usage"]["api_requests"] == 0


def test_manifest_syncs_llm_usage_summary(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    usage_path = output_dir / "llm-usage.jsonl"
    usage_path.write_text(
        "\n".join([
            json.dumps({
                "event": "api_request",
                "stage": "review-content",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }),
            json.dumps({
                "event": "cache_hit",
                "stage": "review-content",
            }),
            json.dumps({
                "event": "api_request",
                "stage": "finalize-content",
                "prompt_tokens": 80,
                "completion_tokens": 120,
                "total_tokens": 200,
            }),
            json.dumps({
                "event": "budget_exceeded",
                "stage": "generate-audio",
            }),
        ]) + "\n",
        encoding="utf-8",
    )
    store = ManifestStore(
        str(output_dir),
        "https://example.com/article",
        configuration={"llm_max_requests": "2"},
    )

    store.sync_llm_usage(usage_path, 2)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    usage = manifest["llm_usage"]
    assert manifest["configuration"]["llm_max_requests"] == "2"
    assert usage["max_requests"] == 2
    assert usage["api_requests"] == 2
    assert usage["cache_hits"] == 1
    assert usage["prompt_tokens"] == 180
    assert usage["completion_tokens"] == 170
    assert usage["total_tokens"] == 350
    assert usage["remaining_requests"] == 0
    assert usage["budget_exhausted"] is True
    assert usage["stopped_before_stage"] == "generate-audio"
    assert usage["by_stage"]["review-content"] == {
        "api_requests": 1,
        "cache_hits": 1,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }


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
