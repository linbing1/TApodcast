import json
import logging
import re
from pathlib import Path

from src.artifacts import load_analyzed_article, load_page_content, write_artifact
from src.llm import LLMClient
from src.llm_json import loads as loads_llm_json
from src.models import PublishCopy
from src.storage import atomic_write_text

logger = logging.getLogger(__name__)
PROMPT_VERSION = "publish-copy-v1"

TITLE_MAX_LENGTH = 30
PUBLISH_TEXT_MAX_LENGTH = 1000
MIN_HASHTAGS = 3
MAX_HASHTAGS = 6
MAX_HASHTAG_LENGTH = 30

_SYSTEM_PROMPT = """你是一位擅长体育内容运营的抖音编辑，负责为英超新闻视频生成发布文案。

请根据文章分析和中文口播稿，返回严格的 JSON 对象：
{
  "title": "抖音作品标题",
  "description": "作品简介正文",
  "hashtags": ["英超", "切尔西", "足球新闻"]
}

要求：
- title 必须原样返回输入中的 cover_title，保证抖音作品标题和封面标题完全一致；
- description 用自然的中文概括视频内容，突出核心事件、人物和看点，控制在80至220字；
- hashtags 生成3至6个与文章直接相关的话题，只返回话题名称，不要带 #，不要重复，不要编造不存在的球队或人物；
- 不要在 JSON 之外输出解释、Markdown 或代码围栏。"""


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_response(response: str) -> dict[str, object]:
    try:
        data = loads_llm_json(response)
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse publish copy response: {response[:200]}") from error
    if not isinstance(data, dict):
        raise ValueError("Publish copy response must be a JSON object")
    return data


def _normalize_title(value: object) -> str:
    title = _normalize_text(value).strip("\"'“”‘’")
    title = title.replace("#", "")
    return title[:TITLE_MAX_LENGTH]


def _normalize_hashtags(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []

    hashtags: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        tag = _normalize_text(candidate).lstrip("#").strip("，,。.!！？、")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        hashtags.append(tag[:MAX_HASHTAG_LENGTH])
        if len(hashtags) >= MAX_HASHTAGS:
            break
    return hashtags


def _ensure_minimum_hashtags(hashtags: list[str]) -> list[str]:
    result = list(hashtags)
    for fallback in ("英超", "足球新闻", "英超每日观察"):
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
            for key in ("title_cn", "overview", "detail", "key_people_and_data", "impact")
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


_TOPIC_ALIASES = (
    (("Arsenal", "阿森纳"), "阿森纳"),
    (("Manchester City", "Man City", "曼城"), "曼城"),
    (("Manchester United", "Man United", "曼联"), "曼联"),
    (("Liverpool", "利物浦"), "利物浦"),
    (("Chelsea", "切尔西"), "切尔西"),
    (("Tottenham", "Spurs", "热刺"), "热刺"),
    (("Barcelona", "巴塞罗那", "巴萨"), "巴萨"),
    (("Real Madrid", "皇家马德里", "皇马"), "皇马"),
    (("Aston Villa", "阿斯顿维拉", "维拉"), "阿斯顿维拉"),
)


def _local_hashtags(material: dict[str, object]) -> list[str]:
    analysis = material.get("analysis")
    analysis_text = ""
    if isinstance(analysis, dict):
        analysis_text = " ".join(str(value) for value in analysis.values())
    haystack = " ".join(
        str(value)
        for value in (
            material.get("cover_title", ""),
            material.get("original_title", ""),
            analysis_text,
        )
    ).lower()
    hashtags: list[str] = []
    for aliases, hashtag in _TOPIC_ALIASES:
        if any(alias.lower() in haystack for alias in aliases):
            hashtags.append(hashtag)
    if isinstance(analysis, dict):
        article_type = str(analysis.get("article_type", ""))
        if "转会" in article_type or "transfer" in haystack:
            hashtags.append("英超转会")
        elif "战术" in article_type or "tactic" in haystack:
            hashtags.append("英超战术")
        elif "赛后" in article_type or "match" in haystack:
            hashtags.append("比赛分析")
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
    llm: LLMClient | None = None,
) -> dict[str, object]:
    """Generate Douyin title, description, and hashtags for an article output."""
    directory = Path(output_dir)
    material = _build_source_material(directory)
    data: dict[str, object] = {}
    if llm is not None:
        response = llm.complete(
            _SYSTEM_PROMPT,
            json.dumps(material, ensure_ascii=False),
            json_mode=True,
            stage="publish-copy",
            prompt_version=PROMPT_VERSION,
        )
        data = _parse_response(response)

    title = _normalize_title(material.get("cover_title"))
    if not title:
        analysis = material.get("analysis")
        analysis_title = analysis.get("title_cn") if isinstance(analysis, dict) else ""
        title = _normalize_title(
            data.get("title")
            or data.get("publish_title")
            or analysis_title
            or material.get("original_title")
        )
    if not title:
        raise ValueError("No publish title found in article outputs")

    description = _normalize_text(data.get("description")) if llm is not None else _local_description(material)
    hashtags = (
        _ensure_minimum_hashtags(_normalize_hashtags(data.get("hashtags")))
        if llm is not None
        else _local_hashtags(material)
    )
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
