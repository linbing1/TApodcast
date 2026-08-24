import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 3
PIPELINE_VERSION = "5"
MANIFEST_FILENAME = "manifest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_path(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(b"file\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    digest.update(b"directory\0")
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with child.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def fingerprint_paths(
    output_dir: Path,
    relative_paths: list[str],
) -> dict[str, str]:
    return {
        relative_path: hash_path(output_dir / relative_path)
        for relative_path in relative_paths
    }


@dataclass
class StepRecord:
    status: str = "pending"
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StepRecord":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class LLMUsageSummary:
    max_requests: int | None = None
    api_requests: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    remaining_requests: int | None = None
    budget_exhausted: bool = False
    stopped_before_stage: str | None = None
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "LLMUsageSummary":
        if not isinstance(data, dict):
            return cls()
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class RunManifest:
    article_url: str
    output_dir: str
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    pipeline_version: str = PIPELINE_VERSION
    configuration: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    llm_usage: LLMUsageSummary = field(default_factory=LLMUsageSummary)
    steps: dict[str, StepRecord] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "RunManifest":
        data = _migrate_manifest(data)
        schema_version = data.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported manifest schema version: {schema_version}; "
                f"expected {SCHEMA_VERSION}"
            )
        steps = {
            name: StepRecord.from_dict(record)
            for name, record in data.get("steps", {}).items()
            if isinstance(record, dict)
        }
        return cls(
            article_url=str(data.get("article_url", "")),
            output_dir=str(data.get("output_dir", "")),
            schema_version=schema_version,
            created_at=str(data.get("created_at", _utc_now())),
            updated_at=str(data.get("updated_at", _utc_now())),
            pipeline_version=str(data.get("pipeline_version", PIPELINE_VERSION)),
            configuration=dict(data.get("configuration", {})),
            prompt_versions=dict(data.get("prompt_versions", {})),
            llm_usage=LLMUsageSummary.from_dict(data.get("llm_usage", {})),
            steps=steps,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _migrate_manifest(data: dict) -> dict:
    migrated = dict(data)
    version = int(migrated.get("schema_version", 1))
    if version == 1:
        migrated.setdefault("pipeline_version", PIPELINE_VERSION)
        migrated.setdefault("configuration", {})
        migrated.setdefault("prompt_versions", {})
        migrated["schema_version"] = 2
        version = 2
    if version == 2:
        migrated.setdefault("llm_usage", {})
        migrated["schema_version"] = 3
        version = 3
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported manifest schema version: {version}; expected {SCHEMA_VERSION}"
        )
    return migrated


class ManifestStore:
    def __init__(
        self,
        output_dir: str,
        article_url: str,
        configuration: dict[str, str] | None = None,
        prompt_versions: dict[str, str] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / MANIFEST_FILENAME
        self.manifest = self._load(article_url)
        self.manifest.pipeline_version = PIPELINE_VERSION
        self.manifest.configuration.update(configuration or {})
        self.manifest.prompt_versions.update(prompt_versions or {})
        configured_budget = self.manifest.configuration.get("llm_max_requests")
        try:
            max_requests = int(configured_budget) if configured_budget is not None else None
        except (TypeError, ValueError):
            max_requests = None
        if max_requests is not None and max_requests > 0:
            self._set_llm_budget(max_requests)

    def _load(self, article_url: str) -> RunManifest:
        if not self.path.exists():
            return RunManifest(
                article_url=article_url,
                output_dir=str(self.output_dir.resolve()),
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid pipeline manifest: {self.path}") from error
        if not isinstance(data, dict):
            raise ValueError(f"Pipeline manifest must be a JSON object: {self.path}")
        manifest = RunManifest.from_dict(data)
        if article_url and manifest.article_url and manifest.article_url != article_url:
            raise ValueError(
                "Output directory belongs to a different article: "
                f"{manifest.article_url}"
            )
        if article_url and not manifest.article_url:
            manifest.article_url = article_url
        return manifest

    def _save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest.updated_at = _utc_now()
        temporary_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary_path.write_text(
            json.dumps(self.manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)

    def _set_llm_budget(self, max_requests: int) -> None:
        summary = self.manifest.llm_usage
        summary.max_requests = max_requests
        summary.remaining_requests = max(max_requests - summary.api_requests, 0)
        summary.budget_exhausted = summary.api_requests >= max_requests

    def sync_llm_usage(
        self,
        usage_path: str | Path,
        max_requests: int,
    ) -> None:
        path = Path(usage_path)
        records: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)

        summary = LLMUsageSummary(max_requests=max_requests)
        for record in records:
            event = record.get("event")
            stage = str(record.get("stage") or "unknown")
            if event == "budget_exceeded":
                summary.stopped_before_stage = stage
                continue
            if event not in {"api_request", "cache_hit"}:
                continue

            stage_usage = summary.by_stage.setdefault(
                stage,
                {
                    "api_requests": 0,
                    "cache_hits": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            )
            if event == "api_request":
                summary.api_requests += 1
                stage_usage["api_requests"] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = record.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        setattr(summary, key, getattr(summary, key) + value)
                        stage_usage[key] += value
            else:
                summary.cache_hits += 1
                stage_usage["cache_hits"] += 1

        summary.remaining_requests = max(max_requests - summary.api_requests, 0)
        summary.budget_exhausted = summary.api_requests >= max_requests
        summary.updated_at = _utc_now()
        self.manifest.llm_usage = summary
        self.manifest.configuration["llm_max_requests"] = str(max_requests)
        self._save()

    def get_step(self, name: str) -> StepRecord:
        return self.manifest.steps.setdefault(name, StepRecord())

    def can_skip(self, name: str, inputs: dict[str, str]) -> bool:
        record = self.manifest.steps.get(name)
        if not record or record.status != "completed" or record.inputs != inputs:
            return False
        if not record.outputs:
            return False
        for relative_path, expected_hash in record.outputs.items():
            path = self.output_dir / relative_path
            if not path.exists() or hash_path(path) != expected_hash:
                return False
        return True

    def mark_running(self, name: str, inputs: dict[str, str]) -> None:
        record = self.get_step(name)
        record.status = "running"
        record.attempts += 1
        record.started_at = _utc_now()
        record.completed_at = None
        record.duration_seconds = None
        record.inputs = inputs
        record.outputs = {}
        record.error = None
        self._save()

    def mark_completed(
        self,
        name: str,
        outputs: dict[str, str],
        duration_seconds: float,
    ) -> None:
        record = self.get_step(name)
        record.status = "completed"
        record.completed_at = _utc_now()
        record.duration_seconds = round(duration_seconds, 3)
        record.outputs = outputs
        record.error = None
        self._save()

    def mark_failed(self, name: str, error: Exception, duration_seconds: float) -> None:
        record = self.get_step(name)
        record.status = "failed"
        record.completed_at = _utc_now()
        record.duration_seconds = round(duration_seconds, 3)
        record.error = f"{type(error).__name__}: {error}"
        self._save()
