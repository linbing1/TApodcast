from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class AnalyzedArticle(VersionedArtifact):
    title_cn: str = Field(max_length=30)
    title_original: str = ""
    article_type: str = ""
    overview: str = ""
    detail: str = ""
    key_people_and_data: str = ""
    impact: str = ""
    link: str = ""

    @field_validator("title_cn", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> str:
        return str(value or "")[:30]


class PodcastScript(StrictModel):
    text: str


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
