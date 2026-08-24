from src.llm import LLMClient
from src.models import AnalyzedArticle, PodcastScript

PROMPT_VERSION = "script-writer-v6"

MIN_SCRIPT_CHARS = 500
MAX_SCRIPT_CHARS = 1000
SCRIPT_SOURCE_RATIO = 0.04
SCRIPT_BASE_CHARS = 400

_SYSTEM_PROMPT_TEMPLATE = """你是一位专业的短视频播客主播。请将以下英超新闻分析改写为自然流畅的中文口语播报脚本。

要求：
- 开头固定为："欢迎收听英超每日观察，今天是{date_str}，"
- 结尾固定为："感谢收听，更多内容请关注英超每日观察。"
- 内容只基于给定新闻分析，禁止添加个人评论、推测或原文未提及的信息
- 聚焦最值得播报的核心主题、结果、人物和关键数字；允许省略次要背景和细节
- 不要把比赛比分、转会状态、主要人物或球队讲反
- 按自然的新闻叙事展开，不要为了凑字数添加或重复内容
- 使用口语化表达，避免书面语和长难句
- 语气自然，像在和球迷朋友聊球

仅返回播报脚本文本，不要添加任何其他内容。"""


def count_source_chars(source_text: str) -> int:
    """Count source characters after removing whitespace."""
    return len("".join(source_text.split()))


def calculate_target_script_chars(source_chars: int) -> int:
    """Calculate a bounded linear script-length target from source length."""
    if source_chars < 0:
        raise ValueError("source_chars must be non-negative")
    return max(
        MIN_SCRIPT_CHARS,
        min(
            MAX_SCRIPT_CHARS,
            round(source_chars * SCRIPT_SOURCE_RATIO + SCRIPT_BASE_CHARS),
        ),
    )


def write_script(
    article: AnalyzedArticle,
    llm: LLMClient,
    date_str: str = "",
    target_chars: int | None = None,
) -> PodcastScript:
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(date_str=date_str or "今天")
    length_instruction = ""
    if target_chars is not None:
        if target_chars <= 0:
            raise ValueError("target_chars must be positive")
        length_instruction = (
            f"目标播报稿总长度约为 {target_chars} 字（包含固定开头和结尾）。"
            "这是精炼目标，不要求为了凑足字数扩写，也不需要后续再次调用模型压缩或扩充。\n"
        )
    user_text = (
        f"标题：{article.title_cn}\n"
        f"概述：{article.overview}\n"
        f"详情：{article.detail}\n"
        f"关键人物与数据：{article.key_people_and_data}\n"
        f"影响分析：{article.impact}\n"
        f"{length_instruction}"
        "请直接输出最终可播报的口语稿。"
    )
    text = llm.complete(
        system_prompt,
        user_text,
        stage="write-script",
        prompt_version=PROMPT_VERSION,
    ).strip()
    validate_script(text)
    return PodcastScript(text=text)


def validate_script(text: str) -> None:
    """Reject empty or visibly non-broadcastable LLM responses without another LLM call."""
    errors = []
    if not text:
        errors.append("script is empty")
    if text and not text.startswith("欢迎收听英超每日观察，今天是"):
        errors.append("missing required opening")
    if text and not text.endswith("感谢收听，更多内容请关注英超每日观察。"):
        errors.append("missing required closing")
    if "```" in text:
        errors.append("contains Markdown code fence")
    if errors:
        raise ValueError(f"Invalid podcast script: {', '.join(errors)}")
