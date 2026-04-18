import logging

from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："今天的英超快报——"
- 结尾固定为："更多内容关注每日英超快报"
- 正文约 200-250 汉字（不含固定开头结尾）
- 使用口语化表达，避免书面语和长难句
- 保留最重要的事实、数据和人名
- 语气自然，像在和球迷朋友聊球

仅返回播报脚本文本，不要添加任何其他内容。"""


def write_script(article: AnalyzedArticle, llm: LLMClient) -> PodcastScript:
    user_text = (
        f"标题：{article.title_cn}\n"
        f"概述：{article.overview}\n"
        f"详情：{article.detail}\n"
        f"关键人物与数据：{article.key_people_and_data}\n"
        f"影响分析：{article.impact}"
    )
    response = llm.complete(_SYSTEM_PROMPT, user_text)
    return PodcastScript(text=response.strip())
