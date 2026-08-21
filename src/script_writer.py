import json

from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

PROMPT_VERSION = "script-writer-v4"

_SYSTEM_PROMPT_TEMPLATE = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："欢迎收听英超每日观察，今天是{date_str}，"
- 结尾固定为："感谢收听，更多内容请关注英超每日观察。"
- 内容严格来自文章原文，禁止添加任何个人评论、推测或文章中未提及的信息
- 优先保留核心结论、关键论据、数据、人名和最重要的具体细节
- 按原文逻辑顺序展开，不要遗漏重要内容
- 使用口语化表达，避免书面语和长难句
- 语气自然，像在和球迷朋友聊球

仅返回播报脚本文本，不要添加任何其他内容。"""


def write_script(article: AnalyzedArticle, llm: LLMClient, date_str: str = "") -> PodcastScript:
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(date_str=date_str or "今天")
    user_text = (
        f"标题：{article.title_cn}\n"
        f"概述：{article.overview}\n"
        f"详情：{article.detail}\n"
        f"关键人物与数据：{article.key_people_and_data}\n"
        f"影响分析：{article.impact}\n"
        "必须覆盖的原文事实清单：\n"
        f"{json.dumps([fact.model_dump() for fact in article.source_facts], ensure_ascii=False)}"
    )
    text = llm.complete(
        system_prompt,
        user_text,
        stage="write-script",
        prompt_version=PROMPT_VERSION,
    ).strip()
    return PodcastScript(text=text)
