import json
from dataclasses import dataclass
from pathlib import Path

from src.cover_renderer import validate_cover
from src.manifest import RunManifest
from src.models import PublishCopy
from src.paths import safe_title
from src.storage import read_json
from src.video_assembler import validate_video

PIPELINE_STEPS = (
    "extract",
    "download-images",
    "analyze-content",
    "write-script",
    "generate-audio",
    "video",
    "cover",
    "publish-copy",
)


@dataclass(frozen=True)
class VerifyResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class VerifyReport:
    checks: list[VerifyResult]

    @property
    def passed(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


def _result(name: str, status: str, detail: str) -> VerifyResult:
    return VerifyResult(name=name, status=status, detail=detail)


def _load_manifest(output_dir: Path) -> tuple[RunManifest | None, VerifyResult]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return None, _result("Manifest", "fail", f"Missing {manifest_path.name}")
    try:
        manifest = RunManifest.from_dict(read_json(manifest_path))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return None, _result("Manifest", "fail", str(error))
    return manifest, _result("Manifest", "pass", "manifest.json is valid")


def _check_pipeline_steps(manifest: RunManifest | None) -> VerifyResult:
    if manifest is None:
        return _result(
            "Pipeline stages",
            "fail",
            "Cannot inspect stages without manifest.json",
        )

    incomplete = [
        f"{name}={manifest.steps[name].status if name in manifest.steps else 'missing'}"
        for name in PIPELINE_STEPS
        if name not in manifest.steps or manifest.steps[name].status != "completed"
    ]
    if incomplete:
        return _result(
            "Pipeline stages",
            "fail",
            "Incomplete stages: " + ", ".join(incomplete),
        )
    return _result("Pipeline stages", "pass", "All 8 stages completed")


def _check_required_files(output_dir: Path) -> VerifyResult:
    required_files = (
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
    )
    missing = [name for name in required_files if not (output_dir / name).is_file()]
    if not (output_dir / "images").is_dir():
        missing.append("images/")
    if missing:
        return _result("Required outputs", "fail", "Missing: " + ", ".join(missing))

    empty = [
        name
        for name in required_files
        if (output_dir / name).stat().st_size == 0
    ]
    if empty:
        return _result("Required outputs", "fail", "Empty: " + ", ".join(empty))
    return _result("Required outputs", "pass", "All expected artifacts are present")


def _video_output_path(output_dir: Path) -> Path:
    title = (output_dir / "title.txt").read_text(encoding="utf-8").strip()
    return output_dir / f"{safe_title(title) or 'video'}.mp4"


def _check_video(output_dir: Path) -> VerifyResult:
    try:
        validate_video(str(_video_output_path(output_dir)))
    except (OSError, RuntimeError, ValueError) as error:
        return _result("Video", "fail", str(error))
    return _result("Video", "pass", "MP4 format and media parameters are valid")


def _check_covers(output_dir: Path) -> VerifyResult:
    try:
        validate_cover(str(output_dir / "cover.png"), (1080, 1920))
        validate_cover(str(output_dir / "cover-landscape.png"), (1920, 1080))
    except (OSError, ValueError) as error:
        return _result("Covers", "fail", str(error))
    return _result("Covers", "pass", "Vertical and landscape covers are valid")


def _check_publish_outputs(output_dir: Path) -> VerifyResult:
    try:
        publish = PublishCopy.model_validate(read_json(output_dir / "publish.json"))
        title = (output_dir / "title.txt").read_text(encoding="utf-8").strip()
        publish_title = (output_dir / "publish_title.txt").read_text(encoding="utf-8")
        publish_description = (
            output_dir / "publish_description.txt"
        ).read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _result("Publish outputs", "fail", str(error))

    if publish.title != title or publish_title != title:
        return _result(
            "Publish outputs",
            "fail",
            "publish.json, publish_title.txt, and title.txt do not match",
        )
    if publish_description != publish.description_with_hashtags:
        return _result(
            "Publish outputs",
            "fail",
            "publish_description.txt does not match publish.json",
        )
    return _result(
        "Publish outputs",
        "pass",
        "Title, description, and hashtags are consistent",
    )


def _check_intermediate_cleanup(output_dir: Path) -> VerifyResult:
    if (output_dir / "frames").exists():
        return _result(
            "Intermediate cleanup",
            "fail",
            "frames/ remains; run `main.py cleanup --dir ...` before delivery",
        )
    return _result("Intermediate cleanup", "pass", "No frames/ directory remains")


def verify_output_dir(output_dir: str) -> VerifyReport:
    directory = Path(output_dir).expanduser().resolve()
    manifest, manifest_result = _load_manifest(directory)
    required_outputs = _check_required_files(directory)
    checks = [
        manifest_result,
        _check_pipeline_steps(manifest),
        required_outputs,
    ]
    if required_outputs.status == "pass":
        checks.extend(
            [
                _check_video(directory),
                _check_covers(directory),
                _check_publish_outputs(directory),
            ]
        )
    else:
        checks.extend(
            [
                _result("Video", "fail", "Skipped because required outputs are missing"),
                _result("Covers", "fail", "Skipped because required outputs are missing"),
                _result(
                    "Publish outputs",
                    "fail",
                    "Skipped because required outputs are missing",
                ),
            ]
        )
    checks.append(_check_intermediate_cleanup(directory))
    return VerifyReport(checks)


def format_verify_report(report: VerifyReport) -> str:
    lines = [
        f"[{check.status.upper()}] {check.name}: {check.detail}"
        for check in report.checks
    ]
    passed = sum(check.status == "pass" for check in report.checks)
    failed = sum(check.status == "fail" for check in report.checks)
    lines.append(f"Summary: {passed} passed, {failed} failed")
    return "\n".join(lines)
