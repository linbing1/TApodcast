import json

import pytest

from src.pipeline import PipelineContext, PipelineRunner, PipelineStep


def _paths(*values):
    return lambda _: list(values)


@pytest.mark.asyncio
async def test_pipeline_runs_steps_and_resume_skips_unchanged_outputs(tmp_path):
    output_dir = tmp_path / "article"
    calls = []

    async def extract(context):
        calls.append("extract")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "page.json").write_text("page", encoding="utf-8")

    async def analyze(context):
        calls.append("analyze")
        (output_dir / "audio.mp3").write_text("audio", encoding="utf-8")

    steps = [
        PipelineStep("extract", extract, _paths(), _paths("page.json")),
        PipelineStep(
            "analyze",
            analyze,
            _paths("page.json"),
            _paths("audio.mp3"),
        ),
    ]
    context = PipelineContext("https://example.com/article", str(output_dir))

    first = await PipelineRunner(context, steps).run()
    second = await PipelineRunner(context, steps).run(resume=True)

    assert [result.status for result in first] == ["completed", "completed"]
    assert [result.status for result in second] == ["skipped", "skipped"]
    assert calls == ["extract", "analyze"]


@pytest.mark.asyncio
async def test_forced_upstream_change_reruns_dependent_step(tmp_path):
    output_dir = tmp_path / "article"
    page_content = ["version-one"]
    calls = []

    async def extract(context):
        calls.append("extract")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "page.json").write_text(page_content[0], encoding="utf-8")

    async def analyze(context):
        calls.append("analyze")
        source = (output_dir / "page.json").read_text(encoding="utf-8")
        (output_dir / "analysis.json").write_text(source, encoding="utf-8")

    steps = [
        PipelineStep("extract", extract, _paths(), _paths("page.json")),
        PipelineStep(
            "analyze",
            analyze,
            _paths("page.json"),
            _paths("analysis.json"),
        ),
    ]
    context = PipelineContext("https://example.com/article", str(output_dir))
    await PipelineRunner(context, steps).run()

    page_content[0] = "version-two"
    result = await PipelineRunner(context, steps).run(
        resume=True,
        force_steps={"extract"},
    )

    assert [item.status for item in result] == ["completed", "completed"]
    assert calls == ["extract", "analyze", "extract", "analyze"]
    assert (output_dir / "analysis.json").read_text(encoding="utf-8") == "version-two"


@pytest.mark.asyncio
async def test_prompt_version_change_reruns_only_dependent_step(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text("page", encoding="utf-8")
    calls = []

    async def analyze(context):
        calls.append(context.prompt_versions["analyzer"])
        (output_dir / "analysis.json").write_text("analysis", encoding="utf-8")

    steps = [
        PipelineStep(
            "analyze",
            analyze,
            _paths("page.json"),
            _paths("analysis.json"),
            configuration_keys=("llm_model",),
            prompt_keys=("analyzer",),
        )
    ]
    first_context = PipelineContext(
        "https://example.com/article",
        str(output_dir),
        configuration={"llm_model": "model-a"},
        prompt_versions={"analyzer": "v1"},
    )
    await PipelineRunner(first_context, steps).run()

    unchanged = await PipelineRunner(first_context, steps).run(resume=True)
    changed_context = PipelineContext(
        "https://example.com/article",
        str(output_dir),
        configuration={"llm_model": "model-a"},
        prompt_versions={"analyzer": "v2"},
    )
    changed = await PipelineRunner(changed_context, steps).run(resume=True)

    assert unchanged[0].status == "skipped"
    assert changed[0].status == "completed"
    assert calls == ["v1", "v2"]


@pytest.mark.asyncio
async def test_pipeline_records_failed_step(tmp_path):
    output_dir = tmp_path / "article"

    async def fail(context):
        raise RuntimeError("service unavailable")

    context = PipelineContext("https://example.com/article", str(output_dir))
    runner = PipelineRunner(
        context,
        [PipelineStep("extract", fail, _paths(), _paths("page.json"))],
    )

    with pytest.raises(RuntimeError, match="service unavailable"):
        await runner.run()

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    record = manifest["steps"]["extract"]
    assert record["status"] == "failed"
    assert record["attempts"] == 1
    assert "service unavailable" in record["error"]


@pytest.mark.asyncio
async def test_pipeline_dry_run_plans_without_writing_files(tmp_path):
    output_dir = tmp_path / "article"
    called = False

    async def extract(context):
        nonlocal called
        called = True

    steps = [
        PipelineStep("extract", extract, _paths(), _paths("page.json")),
        PipelineStep(
            "analyze",
            extract,
            _paths("page.json"),
            _paths("analysis.json"),
        ),
    ]
    context = PipelineContext("https://example.com/article", str(output_dir))

    result = await PipelineRunner(context, steps).run(dry_run=True)

    assert [item.status for item in result] == ["planned", "planned"]
    assert not called
    assert not output_dir.exists()


@pytest.mark.asyncio
async def test_pipeline_limits_execution_range(tmp_path):
    output_dir = tmp_path / "article"
    output_dir.mkdir()
    (output_dir / "page.json").write_text("page", encoding="utf-8")
    calls = []

    async def analyze(context):
        calls.append("analyze")
        (output_dir / "analysis.json").write_text("analysis", encoding="utf-8")

    async def render(context):
        calls.append("render")
        (output_dir / "video.mp4").write_text("video", encoding="utf-8")

    steps = [
        PipelineStep("extract", analyze, _paths(), _paths("page.json")),
        PipelineStep(
            "analyze",
            analyze,
            _paths("page.json"),
            _paths("analysis.json"),
        ),
        PipelineStep(
            "render",
            render,
            _paths("analysis.json"),
            _paths("video.mp4"),
        ),
    ]
    context = PipelineContext("https://example.com/article", str(output_dir))

    result = await PipelineRunner(context, steps).run(
        from_step="analyze",
        to_step="render",
    )

    assert [item.name for item in result] == ["analyze", "render"]
    assert calls == ["analyze", "render"]
