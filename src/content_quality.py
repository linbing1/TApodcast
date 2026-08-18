import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError

from src.llm import LLMClient
from src.models import (
    AnalyzedArticle,
    ContentQualityReport,
    ContentReview,
    ContentRevision,
    PodcastScript,
    QualityIssue,
    ScrapedArticle,
)
from src.script_writer import (
    SCRIPT_MAX_CHARS,
    SCRIPT_TARGET_MIN_CHARS,
    fit_script_length,
)


REVIEW_PROMPT_VERSION = "content-reviewer-v2"
REWRITE_PROMPT_VERSION = "content-rewriter-v2"
MAX_REVISIONS = 2

_SCORE_THRESHOLDS = {
    "factual_accuracy": 90,
    "completeness": 85,
    "structure": 80,
    "spoken_style": 80,
    "title_quality": 80,
    "overall": 85,
}
_REQUIRED_OPENING = "欢迎收听英超每日观察，今天是"
_REQUIRED_ENDING = "感谢收听，更多内容请关注英超每日观察。"

_REVIEW_SYSTEM_PROMPT = """你是一位严谨的中文体育内容总编，负责检查短视频播报稿是否忠实、完整、清晰且适合口播。

审校原则：
1. 原文是唯一事实来源。不得用常识补充原文没有的信息。
2. 逐项核对 source_facts，所有 importance=critical 的事实都必须准确覆盖。
3. 检查人物、俱乐部、金额、日期、数字、引语归属、因果关系和不确定性措辞。
4. 区分原文事实、原文观点和未来推测，不得把传闻写成已发生事实。
5. 标题必须准确、有信息量，但不得夸大。
6. 播报稿应按原文逻辑组织，适合自然口播，避免重复和生硬书面语。
7. 待审标题位于输入的 title_cn 字段；播报稿正文不需要、也不应重复标题。不得以“正文没有标题”为理由扣分。
8. 固定节目开头中的当天日期属于节目制作元数据，不是文章事实；不得因为原文未出现该日期而扣事实准确度分。

只返回 JSON 对象，格式如下：
{
  "passed": false,
  "scores": {
    "factual_accuracy": 0,
    "completeness": 0,
    "structure": 0,
    "spoken_style": 0,
    "title_quality": 0,
    "overall": 0
  },
  "issues": [
    {
      "dimension": "factual_accuracy|completeness|structure|spoken_style|title_quality|format",
      "severity": "warning|error|blocker",
      "description": "具体问题",
      "evidence": "原文或稿件中的相关内容",
      "suggestion": "可执行的修改建议",
      "fact_ids": ["F001"]
    }
  ],
  "summary": "简短审校结论"
}

评分必须严格。事实准确度低于90、完整度低于85、总分低于85，或存在 error/blocker 时，passed 必须为 false。"""

_REWRITE_SYSTEM_PROMPT = """你是一位资深中文体育播报稿编辑。请只修复审校报告指出的问题，同时生成新的中文标题和完整播报稿。

必须遵守：
- 原文是唯一事实来源，不得添加原文没有的信息、评论或推测
- 准确覆盖所有 critical source_facts
- 保留人物、俱乐部、金额、日期、数字、引语归属和不确定性措辞
- 开头固定为“欢迎收听英超每日观察，今天是{date_str}，”
- 结尾固定为“感谢收听，更多内容请关注英超每日观察。”
- 全文控制在850-950个汉字，不超过950字
- 使用自然口语和短句，避免重复
- 标题不超过30个汉字，准确表达协议状态和不确定性，不得夸大
- 只返回 JSON 对象：{{"title_cn": "修订后的标题", "script": "修订后的完整播报稿"}}
- 不解释修改过程"""


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    failed_thresholds: tuple[str, ...]


def _parse_json_object(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Failed to parse content review as JSON: {text[:200]}"
        ) from error
    if not isinstance(data, dict):
        raise ValueError("Content review response must be a JSON object")
    return data


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_title(value: object, fallback: str) -> str:
    title = " ".join(str(value or "").split()).strip("\"'“”‘’# ")[:30]
    return title or fallback


def _static_issues(analyzed: AnalyzedArticle, script: str) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if not analyzed.title_cn.strip():
        issues.append(
            QualityIssue(
                dimension="title_quality",
                severity="blocker",
                description="中文标题为空。",
                suggestion="生成准确概括核心事件的中文标题。",
            )
        )
    if not analyzed.source_facts:
        issues.append(
            QualityIssue(
                dimension="completeness",
                severity="blocker",
                description="分析产物缺少可追踪的原文事实清单。",
                suggestion="重新运行 analyze-content，生成 source_facts。",
            )
        )
    elif not any(fact.importance == "critical" for fact in analyzed.source_facts):
        issues.append(
            QualityIssue(
                dimension="completeness",
                severity="blocker",
                description="原文事实清单没有标记任何 critical 事实。",
                suggestion="重新分析文章并标记播报稿必须覆盖的核心事实。",
            )
        )
    if not script.strip():
        issues.append(
            QualityIssue(
                dimension="format",
                severity="blocker",
                description="播报稿为空。",
                suggestion="重新生成播报稿。",
            )
        )
        return issues
    if len(script) > SCRIPT_MAX_CHARS:
        issues.append(
            QualityIssue(
                dimension="format",
                severity="error",
                description=(
                    f"播报稿共 {len(script)} 字，超过 {SCRIPT_MAX_CHARS} 字上限。"
                ),
                suggestion="删除重复背景和次要细节，但保留 critical 事实。",
            )
        )
    elif len(script) < 650:
        issues.append(
            QualityIssue(
                dimension="completeness",
                severity="error",
                description=f"播报稿仅 {len(script)} 字，信息量明显不足。",
                suggestion="补回遗漏的 critical 事实和关键论据。",
            )
        )
    elif len(script) < SCRIPT_TARGET_MIN_CHARS:
        issues.append(
            QualityIssue(
                dimension="completeness",
                severity="warning",
                description=(
                    f"播报稿共 {len(script)} 字，低于 {SCRIPT_TARGET_MIN_CHARS} 字目标。"
                ),
                suggestion="确认核心事实和关键论据均已覆盖。",
            )
        )
    if not script.startswith(_REQUIRED_OPENING):
        issues.append(
            QualityIssue(
                dimension="format",
                severity="error",
                description="播报稿未使用规定的节目开头。",
                suggestion=f"以“{_REQUIRED_OPENING}……”开头。",
            )
        )
    if not script.endswith(_REQUIRED_ENDING):
        issues.append(
            QualityIssue(
                dimension="format",
                severity="error",
                description="播报稿未使用规定的节目结尾。",
                suggestion=f"以“{_REQUIRED_ENDING}”结尾。",
            )
        )
    if "```" in script or script.lstrip().startswith("#"):
        issues.append(
            QualityIssue(
                dimension="format",
                severity="error",
                description="播报稿包含 Markdown 标记。",
                suggestion="删除代码围栏和标题符号，只保留口播正文。",
            )
        )
    return issues


def evaluate_quality_gate(review: ContentReview) -> QualityGateResult:
    failed_thresholds = tuple(
        dimension
        for dimension, threshold in _SCORE_THRESHOLDS.items()
        if getattr(review.scores, dimension) < threshold
    )
    has_blocking_issue = any(
        issue.severity in {"error", "blocker"} for issue in review.issues
    )
    return QualityGateResult(
        passed=not failed_thresholds and not has_blocking_issue,
        failed_thresholds=failed_thresholds,
    )


def review_content(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
    llm: LLMClient,
) -> ContentReview:
    payload = {
        "source": {
            "title": article.title,
            "url": article.link,
            "full_text": article.full_text,
        },
        "analysis": analyzed.model_dump(mode="json"),
        "title_cn": analyzed.title_cn,
        "script": script.text,
    }
    response = llm.complete(
        _REVIEW_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
    )
    data = _parse_json_object(response)
    data.setdefault("passed", False)
    data.setdefault("issues", [])
    data.setdefault("summary", "")
    data["source_sha256"] = _content_hash(article.full_text)
    data["title_sha256"] = _content_hash(analyzed.title_cn)
    data["script_sha256"] = _content_hash(script.text)
    try:
        review = ContentReview.model_validate(data)
    except ValidationError as error:
        raise ValueError(
            f"Invalid content review response: {response[:200]}"
        ) from error

    review.issues.extend(_static_issues(analyzed, script.text))
    gate = evaluate_quality_gate(review)
    review.passed = gate.passed
    if gate.failed_thresholds:
        failed = "、".join(gate.failed_thresholds)
        suffix = f"未达到质量阈值：{failed}。"
        review.summary = f"{review.summary.rstrip()} {suffix}".strip()
    return review


def rewrite_content(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
    review: ContentReview,
    llm: LLMClient,
    *,
    date_str: str,
) -> tuple[str, PodcastScript]:
    payload = {
        "source": {
            "title": article.title,
            "url": article.link,
            "full_text": article.full_text,
        },
        "analysis": analyzed.model_dump(mode="json"),
        "current_script": script.text,
        "review": review.model_dump(mode="json"),
    }
    response = llm.complete(
        _REWRITE_SYSTEM_PROMPT.format(date_str=date_str or "今天"),
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
    )
    data = _parse_json_object(response)
    title = _normalize_title(data.get("title_cn"), analyzed.title_cn)
    script_value = data.get("script") or data.get("script_text")
    if not isinstance(script_value, str) or not script_value.strip():
        raise ValueError(f"Content rewrite response is missing script: {response[:200]}")
    script = PodcastScript(text=fit_script_length(script_value, llm))
    return title, script


def finalize_content(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    initial_script: PodcastScript,
    initial_review: ContentReview,
    llm: LLMClient,
    *,
    date_str: str,
    max_revisions: int = MAX_REVISIONS,
) -> tuple[str, PodcastScript, ContentQualityReport]:
    current_title = analyzed.title_cn
    current_script = initial_script
    current_review = initial_review
    revisions: list[ContentRevision] = []

    if current_review.passed and (
        current_review.source_sha256 != _content_hash(article.full_text)
        or current_review.title_sha256 != _content_hash(current_title)
        or current_review.script_sha256 != _content_hash(current_script.text)
    ):
        current_review = review_content(article, analyzed, current_script, llm)

    for attempt in range(1, max_revisions + 1):
        if current_review.passed:
            break
        current_analysis = analyzed.model_copy(update={"title_cn": current_title})
        current_title, current_script = rewrite_content(
            article,
            current_analysis,
            current_script,
            current_review,
            llm,
            date_str=date_str,
        )
        current_analysis = analyzed.model_copy(update={"title_cn": current_title})
        current_review = review_content(
            article,
            current_analysis,
            current_script,
            llm,
        )
        revisions.append(
            ContentRevision(
                attempt=attempt,
                title=current_title,
                script=current_script.text,
                review=current_review,
            )
        )

    report = ContentQualityReport(
        initial_title=analyzed.title_cn,
        initial_script=initial_script.text,
        initial_review=initial_review,
        revisions=revisions,
        final_title=current_title,
        final_script=current_script.text,
        final_review=current_review,
        passed=current_review.passed,
        max_revisions=max_revisions,
    )
    return current_title, current_script, report
