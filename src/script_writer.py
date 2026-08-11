import logging

from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："欢迎收听英超每日观察，今天是{date_str}，"
- 结尾固定为："感谢收听，更多内容请关注英超每日观察。"
- 正文约 450-550 汉字（不含固定开头结尾），目标总时长约 2 分钟
- 内容严格来自文章原文，禁止添加任何个人评论、推测或文章中未提及的信息
- 保留原文中所有重要论据、数据、直接引语、人名和具体细节
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
        f"影响分析：{article.impact}"
    )
    response = llm.complete(system_prompt, user_text)
    return PodcastScript(text=response.strip())
