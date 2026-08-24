import json

from pydantic import ValidationError

from src.llm import LLMClient
from src.llm_json import loads as loads_llm_json
from src.models import AnalyzedArticle, ScrapedArticle

_ANALYZED_FIELDS = set(AnalyzedArticle.model_fields) - {"schema_version"}
_REQUIRED_ANALYZED_FIELDS = _ANALYZED_FIELDS
_TITLE_MAX_LENGTH = 30
PROMPT_VERSION = "analyzer-v5"
_TEXT_FIELDS = {
    "title_original",
    "article_type",
    "overview",
    "detail",
    "key_people_and_data",
    "impact",
    "link",
}

_SYSTEM_PROMPT = """你是一位英超新闻编辑。请为一条即将发布到抖音的中文英超新闻视频整理简明、可靠的中文内容上下文。

核心原则：聚焦最值得播报的新闻主题、比赛结果、转会进展、关键人物和数字。可以省略次要背景和细节；不要补充原文没有的信息，也不要把主要事实、比分、转会状态或人物关系讲反。

返回一个 JSON 对象，包含：
- title_cn: 用于视频封面、视频文件和抖音发布的中文标题，不超过30个汉字。标题必须让球迷产生“想点开看看发生了什么”的兴趣，而不是平铺直叙地复述文章原标题。优先从原文中提炼一个明确的新闻钩子：意外结果、关键转折、潜在影响、人物选择、转会悬念、战术问题或冲突；尽量采用“核心事件 + 为什么值得关注”的结构，也可以使用有依据的疑问或悬念表达。标题要具体、有画面感、有信息量，至少包含核心人物/球队/事件中的关键元素；吸引力必须来自原文事实，不能夸大、虚构、故意制造错误悬念，不使用“震惊”“速看”“太意外了”等空洞标题党词语
- title_original: 英文原标题
- article_type: 文章类型（深度分析/新闻报道/战术解读/转会动态/赛后分析）
- overview: 2-4 句话概述最重要的事件、结果和背景（中文）
- detail: 用 300-600 个汉字按新闻叙事整理核心信息，优先保留影响理解主题的事实、关键细节和引语；不需要覆盖全文
- key_people_and_data: 与主题直接相关的人物、球队、数字和时间点（中文）
- impact: 这条新闻对球队、联赛或后续事件最直接的影响；原文没有明确影响时留空（中文）
- link: 原文链接

重要格式要求：
- 仅返回 JSON 对象，不要添加任何其他文字"""


def _parse_response(response: str) -> dict:
    try:
        data = loads_llm_json(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {response[:200]}") from e
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


def analyze_article(article: ScrapedArticle, llm: LLMClient) -> AnalyzedArticle:
    user_text = f"Title: {article.title}\nLink: {article.link}\nContent:\n{article.full_text}"
    response = llm.complete(
        _SYSTEM_PROMPT,
        user_text,
        json_mode=True,
        stage="analyze-content",
        prompt_version=PROMPT_VERSION,
    )
    data = _parse_response(response)
    filtered = {k: v for k, v in data.items() if k in _ANALYZED_FIELDS}
    for field in _TEXT_FIELDS & filtered.keys():
        filtered[field] = _normalize_text(filtered[field])
    if "title_cn" in filtered:
        filtered["title_cn"] = " ".join(str(filtered["title_cn"]).split()).strip(
            "\"'“”‘’# "
        )[:_TITLE_MAX_LENGTH]
    filtered.setdefault("link", article.link)
    missing = _REQUIRED_ANALYZED_FIELDS - set(filtered)
    if missing:
        raise ValueError(f"LLM response missing required fields {missing}: {response[:200]}")
    try:
        analyzed = AnalyzedArticle(**filtered)
    except ValidationError as e:
        raise ValueError(f"Invalid analyzed article response: {response[:200]}") from e
    return analyzed
