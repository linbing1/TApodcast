import logging

from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

logger = logging.getLogger(__name__)

_MAX_SCRIPT_CHARS = 950
PROMPT_VERSION = "script-writer-v1"

_SYSTEM_PROMPT_TEMPLATE = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："欢迎收听英超每日观察，今天是{date_str}，"
- 结尾固定为："感谢收听，更多内容请关注英超每日观察。"
- 全文（包含固定开头和结尾）控制在 850-950 汉字，绝对不要超过 1000 字
- 按约 1.1 倍语速播报，目标总时长控制在 3 分钟以内
- 内容严格来自文章原文，禁止添加任何个人评论、推测或文章中未提及的信息
- 在有限字数内优先保留核心结论、关键论据、数据、人名和最重要的具体细节
- 按原文逻辑顺序展开，不要遗漏重要内容
- 使用口语化表达，避免书面语和长难句
- 语气自然，像在和球迷朋友聊球

仅返回播报脚本文本，不要添加任何其他内容。"""

_COMPRESSION_PROMPT = """请将下面的中文播报稿压缩到不超过 {max_chars} 个汉字（包含开头和结尾）。

要求：
- 保留原稿的固定开头“欢迎收听英超每日观察……”和固定结尾“感谢收听，更多内容请关注英超每日观察。”
- 只保留文章中的核心事实、关键人物、数据和结论，不添加任何新信息
- 保持自然口语表达，删除重复背景、次要例子和冗余修饰
- 只返回压缩后的完整播报稿，不要解释压缩过程

原稿：
{script}
"""

_COMPRESSION_SYSTEM_PROMPT = "你是一位专业的中文播报稿编辑，负责在不改变事实的前提下压缩稿件。"


def write_script(article: AnalyzedArticle, llm: LLMClient, date_str: str = "") -> PodcastScript:
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(date_str=date_str or "今天")
    user_text = (
        f"标题：{article.title_cn}\n"
        f"概述：{article.overview}\n"
        f"详情：{article.detail}\n"
        f"关键人物与数据：{article.key_people_and_data}\n"
        f"影响分析：{article.impact}"
    )
    text = llm.complete(system_prompt, user_text).strip()
    for attempt in range(2):
        if len(text) <= _MAX_SCRIPT_CHARS:
            break
        logger.info(
            "Podcast script has %d chars; compressing (attempt %d/2)",
            len(text),
            attempt + 1,
        )
        text = llm.complete(
            _COMPRESSION_SYSTEM_PROMPT,
            _COMPRESSION_PROMPT.format(max_chars=_MAX_SCRIPT_CHARS, script=text),
        ).strip()
    if len(text) > _MAX_SCRIPT_CHARS:
        raise ValueError(
            f"Generated podcast script is too long: {len(text)} chars "
            f"(maximum {_MAX_SCRIPT_CHARS})"
        )
    return PodcastScript(text=text)
