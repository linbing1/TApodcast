from dataclasses import dataclass, field


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
    importance: int
    overview: str
    detail: str
    key_people_and_data: str
    impact: str
    link: str


@dataclass
class PodcastScript:
    text: str
