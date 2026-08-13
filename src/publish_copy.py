import json
import logging
from pathlib import Path

from src.llm import LLMClient

logger = logging.getLogger(__name__)

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


def _strip_json_fence(response: str) -> str:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _parse_response(response: str) -> dict[str, object]:
    try:
        data = json.loads(_strip_json_fence(response))
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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _build_source_material(output_dir: Path) -> dict[str, object]:
    page = _load_json(output_dir / "page.json")
    analysis = _load_json(output_dir / "analysis.json")
    script_path = output_dir / "script.txt"
    script = script_path.read_text(encoding="utf-8").strip() if script_path.exists() else ""
    title_path = output_dir / "title.txt"
    cover_title = (
        _normalize_title(title_path.read_text(encoding="utf-8"))
        if title_path.exists()
        else ""
    )
    if not page and not analysis and not script:
        raise FileNotFoundError(
            f"No article material found in {output_dir}; run steps 1 and 2 first"
        )

    return {
        "cover_title": cover_title,
        "original_title": page.get("title", ""),
        "analysis": {
            key: analysis.get(key, "")
            for key in ("title_cn", "overview", "detail", "key_people_and_data", "impact")
            if analysis.get(key)
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


def generate_publish_copy(output_dir: str, llm: LLMClient) -> dict[str, object]:
    """Generate Douyin title, description, and hashtags for an article output."""
    directory = Path(output_dir)
    material = _build_source_material(directory)
    response = llm.complete(
        _SYSTEM_PROMPT,
        json.dumps(material, ensure_ascii=False),
        json_mode=True,
    )
    data = _parse_response(response)

    title = _normalize_title(material.get("cover_title"))
    if not title:
        title = _normalize_title(data.get("title") or data.get("publish_title"))
    if not title:
        raise ValueError("LLM did not return a publish title")

    description = _normalize_text(data.get("description"))
    hashtags = _ensure_minimum_hashtags(_normalize_hashtags(data.get("hashtags")))
    description, description_with_hashtags = _fit_publish_text(description, hashtags)
    result = {
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "description_with_hashtags": description_with_hashtags,
    }

    (directory / "publish.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (directory / "title.txt").write_text(title, encoding="utf-8")
    (directory / "publish_title.txt").write_text(title, encoding="utf-8")
    (directory / "publish_description.txt").write_text(
        description_with_hashtags,
        encoding="utf-8",
    )
    logger.info("Generated publish copy: %s", directory / "publish.json")
    return result
