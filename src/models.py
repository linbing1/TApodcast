from dataclasses import dataclass, field


@dataclass
class ImageAsset:
    url: str
    alt: str = ""
    caption: str = ""
    credit: str = ""
    width: int | None = None
    height: int | None = None


@dataclass
class VideoAsset:
    url: str
    kind: str = "video"
    poster: str = ""
    title: str = ""
    width: int | None = None
    height: int | None = None
    duration: str | None = None


@dataclass
class PageContent:
    url: str
    title: str
    main_text: str
    images: list[ImageAsset] = field(default_factory=list)
    videos: list[VideoAsset] = field(default_factory=list)


@dataclass
class ScrapedArticle:
    title: str
    link: str
    full_text: str
    image_paths: list[str] = field(default_factory=list)


@dataclass
class AnalyzedArticle:
    title_cn: str
    title_original: str
    article_type: str
    overview: str
    detail: str
    key_people_and_data: str
    impact: str
    link: str


@dataclass
class PodcastScript:
    text: str
