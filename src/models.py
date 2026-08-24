from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ARTIFACT_SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VersionedArtifact(StrictModel):
    schema_version: Literal[1] = ARTIFACT_SCHEMA_VERSION


class ImageAsset(StrictModel):
    url: str = ""
    alt: str = ""
    caption: str = ""
    credit: str = ""
    width: int | None = None
    height: int | None = None


class VideoAsset(StrictModel):
    url: str
    kind: str = "video"
    poster: str = ""
    title: str = ""
    width: int | None = None
    height: int | None = None
    duration: str | None = None


class PageContent(VersionedArtifact):
    url: str = ""
    title: str = ""
    main_text: str = ""
    images: list[ImageAsset] = Field(default_factory=list)
    videos: list[VideoAsset] = Field(default_factory=list)
    cover_image_index: int | None = None
    cover_image_url: str = ""


class ImageRecord(ImageAsset):
    local_path: str = ""
    status: Literal["pending", "downloaded", "failed"] = "pending"
    error: str | None = None
    is_cover: bool = False


class ImageManifest(VersionedArtifact):
    images: list[ImageRecord] = Field(default_factory=list)


class VideoManifest(VersionedArtifact):
    videos: list[VideoAsset] = Field(default_factory=list)


class CoverManifest(VersionedArtifact):
    image_index: int | None = None
    image_url: str = ""
    local_path: str | None = None


class ScrapedArticle(StrictModel):
    title: str
    link: str
    full_text: str
    image_paths: list[str] = Field(default_factory=list)
    cover_image_path: str | None = None


class SourceFact(StrictModel):
    fact_id: str = Field(pattern=r"^F\d{3}$")
    claim: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    category: str = ""
    importance: Literal["critical", "supporting"] = "supporting"


class AnalyzedArticle(VersionedArtifact):
    title_cn: str = Field(max_length=30)
    title_original: str = ""
    article_type: str = ""
    overview: str = ""
    detail: str = ""
    key_people_and_data: str = ""
    impact: str = ""
    link: str = ""
    source_facts: list[SourceFact] = Field(default_factory=list)

    @field_validator("title_cn", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> str:
        return str(value or "")[:30]


class PodcastScript(StrictModel):
    text: str


class QualityScores(StrictModel):
    factual_accuracy: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    structure: int = Field(ge=0, le=100)
    spoken_style: int = Field(ge=0, le=100)
    title_quality: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class QualityIssue(StrictModel):
    dimension: Literal[
        "factual_accuracy",
        "completeness",
        "structure",
        "spoken_style",
        "title_quality",
        "format",
    ]
    severity: Literal["warning", "error", "blocker"]
    description: str
    evidence: str = ""
    suggestion: str = ""
    fact_ids: list[str] = Field(default_factory=list)


class ContentReview(VersionedArtifact):
    passed: bool
    scores: QualityScores
    issues: list[QualityIssue] = Field(default_factory=list)
    summary: str = ""
    review_mode: Literal["static", "llm"] = "llm"
    risk_level: Literal["low", "high"] = "high"
    risk_reasons: list[str] = Field(default_factory=list)
    source_sha256: str = ""
    title_sha256: str = ""
    script_sha256: str = ""


class ContentRevision(StrictModel):
    attempt: int = Field(ge=1)
    title: str
    script: str
    review: ContentReview


class ContentQualityReport(VersionedArtifact):
    initial_title: str
    initial_script: str
    initial_review: ContentReview
    revisions: list[ContentRevision] = Field(default_factory=list)
    final_title: str
    final_script: str
    final_review: ContentReview
    passed: bool
    max_revisions: int = Field(ge=0)
    revision_budget_used: int = Field(default=0, ge=0)
    revision_budget_remaining: int = Field(default=0, ge=0)
    revision_budget_exhausted: bool = False
    source_sha256: str = ""
    analysis_sha256: str = ""
    initial_script_sha256: str = ""
    review_prompt_version: str = ""
    rewrite_prompt_version: str = ""

    @model_validator(mode="before")
    @classmethod
    def populate_revision_budget(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        revisions = data.get("revisions")
        used = len(revisions) if isinstance(revisions, list) else 0
        max_revisions = data.get("max_revisions", 0)
        if not isinstance(max_revisions, int) or isinstance(max_revisions, bool):
            max_revisions = 0
        data["revision_budget_used"] = used
        data["revision_budget_remaining"] = max(max_revisions - used, 0)
        data["revision_budget_exhausted"] = used >= max_revisions
        return data


class ImageCaptionRecord(StrictModel):
    local_path: str
    caption_original: str = ""
    caption_cn: str = ""


class ImageCaptionManifest(VersionedArtifact):
    captions: list[ImageCaptionRecord] = Field(default_factory=list)


class PublishCopy(VersionedArtifact):
    title: str = Field(max_length=30)
    description: str
    hashtags: list[str] = Field(min_length=5, max_length=10)
    description_with_hashtags: str
