import logging
import re
from pathlib import Path

from src.artifacts import load_analyzed_article, write_artifact
from src.models import PublishCopy
from src.storage import atomic_write_text

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 30
PUBLISH_TEXT_MAX_LENGTH = 1000
MIN_HASHTAGS = 5
MAX_HASHTAGS = 10

def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _ensure_minimum_hashtags(hashtags: list[str]) -> list[str]:
    result = list(hashtags)
    for fallback in ("英超", "足球新闻", "足球", "英超每日观察", "体育"):
        if fallback not in result:
            result.append(fallback)
        if len(result) >= MIN_HASHTAGS:
            break
    return result[:MAX_HASHTAGS]


def _build_source_material(output_dir: Path) -> dict[str, object]:
    analysis_path = output_dir / "analysis.json"
    script_path = output_dir / "script.txt"
    title_path = output_dir / "title.txt"
    missing = [
        path.name
        for path in (title_path, script_path, analysis_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing publish inputs in {output_dir}: {', '.join(missing)}"
        )

    title = title_path.read_text(encoding="utf-8").strip()
    if not title:
        raise ValueError(f"Title is empty: {title_path}")
    if len(title) > TITLE_MAX_LENGTH:
        raise ValueError(
            f"Title exceeds {TITLE_MAX_LENGTH} characters: {title_path}"
        )
    script = _normalize_text(script_path.read_text(encoding="utf-8"))
    analysis = load_analyzed_article(analysis_path)

    return {
        "title": title,
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
            if getattr(analysis, key, "")
        },
        "script": script,
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
            material.get("title", ""),
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

    title = material.get("title", "")
    description = _local_description(material)
    hashtags = _local_hashtags(material)
    description, description_with_hashtags = _fit_publish_text(description, hashtags)
    result = PublishCopy(
        title=title,
        description=description,
        hashtags=hashtags,
        description_with_hashtags=description_with_hashtags,
    )
    _validate_publish_result(result)
    write_artifact(directory / "publish.json", result)
    atomic_write_text(directory / "publish_title.txt", title)
    atomic_write_text(directory / "publish_description.txt", description_with_hashtags)
    _validate_publish_outputs(directory, result)
    logger.info("Generated publish copy: %s", directory / "publish.json")
    return result.model_dump(exclude={"schema_version"})


def _validate_publish_result(result: PublishCopy) -> None:
    if not result.title or len(result.title) > TITLE_MAX_LENGTH:
        raise ValueError("Publish title is empty or exceeds 30 characters")
    if not result.description:
        raise ValueError("Publish description is empty")
    if not MIN_HASHTAGS <= len(result.hashtags) <= MAX_HASHTAGS:
        raise ValueError("Publish hashtag count must be between 5 and 10")
    if result.description_with_hashtags == "":
        raise ValueError("Publish description with hashtags is empty")


def _validate_publish_outputs(directory: Path, result: PublishCopy) -> None:
    if (directory / "publish_title.txt").read_text(encoding="utf-8") != result.title:
        raise ValueError("publish_title.txt does not match publish.json title")
    if (
        directory / "publish_description.txt"
    ).read_text(encoding="utf-8") != result.description_with_hashtags:
        raise ValueError(
            "publish_description.txt does not match publish.json description"
        )
