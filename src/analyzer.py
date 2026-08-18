import json
import logging

from pydantic import ValidationError

from src.llm import LLMClient
from src.models import AnalyzedArticle, ScrapedArticle

logger = logging.getLogger(__name__)

_ANALYZED_FIELDS = set(AnalyzedArticle.model_fields) - {"schema_version"}
_REQUIRED_ANALYZED_FIELDS = _ANALYZED_FIELDS - {"source_facts"}
_TITLE_MAX_LENGTH = 30
PROMPT_VERSION = "analyzer-v2"
_TEXT_FIELDS = {
    "title_original",
    "article_type",
    "overview",
    "detail",
    "key_people_and_data",
    "impact",
    "link",
}

_SYSTEM_PROMPT = """你是一位资深英超足球记者和分析师。请对以下英超文章进行深度中文分析。

核心原则：尽量保留原文的丰富内容，不要过度精简。读者希望通过你的分析获取接近原文的信息量，而不仅仅是摘要。

返回一个 JSON 对象，包含：
- title_cn: 适合抖音作品和封面的中文标题，不超过30个汉字；准确概括核心事件并突出人物、冲突或悬念，要有吸引力但不夸大、不虚构，不使用“震惊”“速看”等空洞标题党词语
- title_original: 英文原标题
- article_type: 文章类型（深度分析/新闻报道/战术解读/转会动态/赛后分析）
- overview: 3-5 句话概述核心论点，包含关键结论和背景（中文）
- detail: 深度转述原文内容，要求：（1）保留原文中所有重要论据、数据、直接引语、战术细节和具体事例；（2）按原文逻辑结构组织，不要遗漏关键段落；（3）深度分析类 800-1200 字，普通新闻 400-600 字（中文）
- key_people_and_data: 涉及的关键人物和数据，列出所有被提及的人名、具体数据和统计（中文）
- impact: 影响分析与展望，包含短期和中长期影响（中文）
- link: 原文链接
- source_facts: 可供后续审校逐项核对的事实清单，数组中每项包含：
  - fact_id: 从 F001 开始连续编号
  - claim: 忠实转述的中文事实，不加入推测
  - evidence: 支撑该事实的原文短句或关键措辞
  - category: 人物/转会/比赛/数据/引语/背景/影响之一
  - importance: critical 或 supporting；播报稿必须覆盖所有 critical 事实

重要格式要求：
- 仅返回 JSON 对象，不要添加任何其他文字"""


def _parse_response(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {text[:200]}") from e
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(
            text for item in value if (text := _normalize_text(item))
        )
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _normalize_text(item)
            if text:
                parts.append(f"{key}：{text}")
        return "；".join(parts)
    return str(value).strip()


def _normalize_source_facts(value: object) -> object:
    if isinstance(value, dict):
        value = value.get("facts") or value.get("items") or value.get("source_facts")
    if not isinstance(value, list):
        return value
    facts = []
    for item in value:
        if not isinstance(item, dict):
            facts.append(item)
            continue
        normalized = dict(item)
        for field in ("fact_id", "claim", "evidence", "category", "importance"):
            if field in normalized:
                normalized[field] = _normalize_text(normalized[field])
        facts.append(normalized)
    return facts


def analyze_article(article: ScrapedArticle, llm: LLMClient) -> AnalyzedArticle:
    user_text = f"Title: {article.title}\nLink: {article.link}\nContent:\n{article.full_text}"
    response = llm.complete(_SYSTEM_PROMPT, user_text, json_mode=True)
    data = _parse_response(response)
    filtered = {k: v for k, v in data.items() if k in _ANALYZED_FIELDS}
    for field in _TEXT_FIELDS & filtered.keys():
        filtered[field] = _normalize_text(filtered[field])
    if "source_facts" in filtered:
        filtered["source_facts"] = _normalize_source_facts(
            filtered["source_facts"]
        )
    if "title_cn" in filtered:
        filtered["title_cn"] = " ".join(str(filtered["title_cn"]).split()).strip(
            "\"'“”‘’# "
        )[:_TITLE_MAX_LENGTH]
    filtered.setdefault("link", article.link)
    missing = _REQUIRED_ANALYZED_FIELDS - set(filtered)
    if missing:
        raise ValueError(f"LLM response missing required fields {missing}: {response[:200]}")
    if not filtered.get("source_facts"):
        raise ValueError(f"LLM response missing source facts: {response[:200]}")
    try:
        analyzed = AnalyzedArticle(**filtered)
    except ValidationError as e:
        raise ValueError(f"Invalid analyzed article response: {response[:200]}") from e
    fact_ids = [fact.fact_id for fact in analyzed.source_facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("LLM response contains duplicate source fact IDs")
    if not any(fact.importance == "critical" for fact in analyzed.source_facts):
        raise ValueError("LLM response contains no critical source facts")
    return analyzed
