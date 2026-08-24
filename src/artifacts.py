from pathlib import Path

from src.models import (
    AnalyzedArticle,
    ContentQualityReport,
    ContentReview,
    CoverManifest,
    ImageCaptionManifest,
    ImageManifest,
    PageContent,
    PublishCopy,
    VideoManifest,
)
from src.storage import atomic_write_json, read_json


def load_page_content(path: str | Path) -> PageContent:
    return PageContent.model_validate(read_json(path))


def load_image_manifest(path: str | Path) -> ImageManifest:
    data = read_json(path)
    if isinstance(data, list):
        data = {"images": data}
    return ImageManifest.model_validate(data)


def load_video_manifest(path: str | Path) -> VideoManifest:
    data = read_json(path)
    if isinstance(data, list):
        data = {"videos": data}
    return VideoManifest.model_validate(data)


def load_cover_manifest(path: str | Path) -> CoverManifest:
    return CoverManifest.model_validate(read_json(path))


def load_analyzed_article(path: str | Path) -> AnalyzedArticle:
    return AnalyzedArticle.model_validate(read_json(path))


def load_content_review(path: str | Path) -> ContentReview:
    return ContentReview.model_validate(read_json(path))


def load_content_quality_report(path: str | Path) -> ContentQualityReport:
    return ContentQualityReport.model_validate(read_json(path))


def load_image_caption_manifest(path: str | Path) -> ImageCaptionManifest:
    data = read_json(path)
    if isinstance(data, list):
        data = {"captions": data}
    return ImageCaptionManifest.model_validate(data)


def load_publish_copy(path: str | Path) -> PublishCopy:
    return PublishCopy.model_validate(read_json(path))


def write_artifact(path: str | Path, artifact) -> Path:
    return atomic_write_json(path, artifact)
