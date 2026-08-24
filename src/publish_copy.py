import logging
import re
from pathlib import Path

from src.artifacts import load_analyzed_article, load_page_content, write_artifact
from src.models import PublishCopy
from src.storage import atomic_write_text

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 30
PUBLISH_TEXT_MAX_LENGTH = 1000
MIN_HASHTAGS = 5
MAX_HASHTAGS = 10

def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_title(value: object) -> str:
    title = _normalize_text(value).strip("\"'“”‘’")
    title = title.replace("#", "")
    return title[:TITLE_MAX_LENGTH]


def _ensure_minimum_hashtags(hashtags: list[str]) -> list[str]:
    result = list(hashtags)
    for fallback in ("英超", "足球新闻", "足球", "英超每日观察", "体育"):
        if fallback not in result:
            result.append(fallback)
        if len(result) >= MIN_HASHTAGS:
            break
    return result[:MAX_HASHTAGS]


def _build_source_material(output_dir: Path) -> dict[str, object]:
    page_path = output_dir / "page.json"
    analysis_path = output_dir / "analysis.json"
    page = load_page_content(page_path) if page_path.exists() else None
    analysis = load_analyzed_article(analysis_path) if analysis_path.exists() else None
    script_path = output_dir / "script.txt"
    script = script_path.read_text(encoding="utf-8").strip() if script_path.exists() else ""
    title_path = output_dir / "title.txt"
    cover_title = (
        _normalize_title(title_path.read_text(encoding="utf-8"))
        if title_path.exists()
        else ""
    )
    if page is None and analysis is None and not script:
        raise FileNotFoundError(
            f"No article material found in {output_dir}; run steps 1 and 2 first"
        )

    return {
        "cover_title": cover_title,
        "original_title": page.title if page else "",
        "analysis": {
            key: getattr(analysis, key, "")
            for key in (
                "title_cn",
                "article_type",
                "overview",
                "detail",
                "key_people_and_data",
                "impact",
            )
            if analysis and getattr(analysis, key, "")
        },
        "script": script[:12000],
    }


def _format_description(description: str, hashtags: list[str]) -> str:
    hashtag_line = " ".join(f"#{tag}" for tag in hashtags)
    if not hashtag_line:
        return description
    return f"{description}\n\n{hashtag_line}" if description else hashtag_line


def _fit_publish_text(description: str, hashtags: list[str]) -> tuple[str, str]:
    hashtag_line = " ".join(f"#{tag}" for tag in hashtags)
    separator = "\n\n" if description and hashtag_line else ""
    description_limit = max(
        0,
        PUBLISH_TEXT_MAX_LENGTH - len(separator) - len(hashtag_line),
    )
    fitted_description = description[:description_limit].rstrip()
    return fitted_description, _format_description(fitted_description, hashtags)


_TEAM_ALIASES = (
    (("Arsenal", "阿森纳"), "阿森纳"),
    (("Manchester City", "Man City", "曼城"), "曼城"),
    (("Bournemouth", "伯恩茅斯"), "伯恩茅斯"),
    (("Manchester United", "Man United", "曼联"), "曼联"),
    (("Liverpool", "利物浦"), "利物浦"),
    (("Chelsea", "切尔西"), "切尔西"),
    (("Tottenham", "Spurs", "热刺"), "热刺"),
    (("Newcastle United", "Newcastle", "纽卡斯尔", "纽卡"), "纽卡斯尔"),
    (("Brentford", "布伦特福德"), "布伦特福德"),
    (("Brighton", "布莱顿"), "布莱顿"),
    (("Crystal Palace", "水晶宫"), "水晶宫"),
    (("Everton", "埃弗顿"), "埃弗顿"),
    (("Fulham", "富勒姆"), "富勒姆"),
    (("Leeds United", "Leeds", "利兹联"), "利兹联"),
    (("Nottingham Forest", "诺丁汉森林"), "诺丁汉森林"),
    (("Sunderland", "桑德兰"), "桑德兰"),
    (("West Ham United", "West Ham", "西汉姆联"), "西汉姆联"),
    (("Wolverhampton", "Wolves", "狼队"), "狼队"),
    (("Burnley", "伯恩利"), "伯恩利"),
    (("Hull City", "Hull", "赫尔城", "胡尔城"), "赫尔城"),
    (("Coventry City", "Coventry", "考文垂"), "考文垂"),
    (("Barcelona", "巴塞罗那", "巴萨"), "巴萨"),
    (("Real Madrid", "皇家马德里", "皇马"), "皇马"),
    (("Aston Villa", "阿斯顿维拉", "维拉"), "阿斯顿维拉"),
)

_DISCOVERY_TOPIC_ALIASES = (
    (("transfer", "转会", "签下", "加盟", "报价"), "英超转会"),
    (("tactic", "formation", "pressing", "战术", "阵型", "逼抢", "低位防守"), "英超战术"),
    (("match", "result", "score", "赛后", "比分", "逆转", "绝杀"), "比赛分析"),
    (("champions league", "欧冠"), "欧冠"),
    (("world cup", "世界杯"), "世界杯"),
    (("ownership", "investment", "takeover", "sale", "股权", "投资", "收购", "出售"), "足球商业"),
    (("injury", "伤病", "受伤", "复出"), "伤病动态"),
    (("profile", "wonderkid", "young star", "新星", "妖星", "球员观察"), "球员观察"),
)


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _matching_hashtags(text: str, aliases_by_hashtag: tuple) -> list[str]:
    haystack = text.lower()
    return [
        hashtag
        for aliases, hashtag in aliases_by_hashtag
        if any(alias.lower() in haystack for alias in aliases)
    ]


def _local_hashtags(material: dict[str, object]) -> list[str]:
    analysis = material.get("analysis")
    primary_analysis_text = ""
    related_analysis_text = ""
    if isinstance(analysis, dict):
        primary_analysis_text = " ".join(
            str(analysis.get(key, ""))
            for key in ("title_cn", "article_type", "overview")
        )
        related_analysis_text = " ".join(
            str(analysis.get(key, ""))
            for key in ("detail", "key_people_and_data", "impact")
        )
    primary_text = " ".join(
        str(value)
        for value in (
            material.get("cover_title", ""),
            material.get("original_title", ""),
            primary_analysis_text,
        )
    )
    related_text = " ".join(
        str(value)
        for value in (
            related_analysis_text,
            material.get("script", ""),
        )
    )
    full_text = f"{primary_text} {related_text}"
    hashtags: list[str] = []
    _append_unique(hashtags, _matching_hashtags(primary_text, _TEAM_ALIASES))
    _append_unique(hashtags, _matching_hashtags(full_text, _DISCOVERY_TOPIC_ALIASES))
    _append_unique(hashtags, ["英超", "足球新闻"])
    _append_unique(hashtags, _matching_hashtags(related_text, _TEAM_ALIASES))
    return _ensure_minimum_hashtags(hashtags)


def _local_description(material: dict[str, object]) -> str:
    analysis = material.get("analysis")
    if isinstance(analysis, dict):
        overview = _normalize_text(analysis.get("overview"))
        if overview:
            return overview
    script = _normalize_text(material.get("script"))
    script = re.sub(r"^欢迎收听英超每日观察，今天是[^，。]*，", "", script)
    script = script.replace("感谢收听，更多内容请关注英超每日观察。", "").strip()
    return script


def generate_publish_copy(
    output_dir: str,
) -> dict[str, object]:
    """Generate Douyin publish copy locally from existing article outputs."""
    directory = Path(output_dir)
    material = _build_source_material(directory)

    title = _normalize_title(material.get("cover_title"))
    if not title:
        analysis = material.get("analysis")
        analysis_title = analysis.get("title_cn") if isinstance(analysis, dict) else ""
        title = _normalize_title(
            analysis_title
            or material.get("original_title")
        )
    if not title:
        raise ValueError("No publish title found in article outputs")

    description = _local_description(material)
    hashtags = _local_hashtags(material)
    description, description_with_hashtags = _fit_publish_text(description, hashtags)
    result = PublishCopy(
        title=title,
        description=description,
        hashtags=hashtags,
        description_with_hashtags=description_with_hashtags,
    )
    write_artifact(directory / "publish.json", result)
    atomic_write_text(directory / "title.txt", title)
    atomic_write_text(directory / "publish_title.txt", title)
    atomic_write_text(directory / "publish_description.txt", description_with_hashtags)
    logger.info("Generated publish copy: %s", directory / "publish.json")
    return result.model_dump(exclude={"schema_version"})
