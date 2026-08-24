import hashlib
import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from src.llm import LLMClient
from src.llm_json import loads as loads_llm_json
from src.models import (
    AnalyzedArticle,
    ContentQualityReport,
    ContentReview,
    ContentRevision,
    PodcastScript,
    QualityIssue,
    QualityScores,
    ScrapedArticle,
)


REVIEW_PROMPT_VERSION = "content-reviewer-v6"
REWRITE_PROMPT_VERSION = "content-rewriter-v6"
MAX_REVISIONS = 1
DETAIL_CONTEXT_MAX_CHARS = 1600

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
_FACT_CONNECTORS = (
    "在",
    "的",
    "了",
    "将",
    "与",
    "和",
    "并",
    "是",
    "被",
    "向",
    "对",
    "从",
    "到",
    "为",
    "于",
    "也",
    "还",
    "已",
    "中",
    "其",
    "后",
    "前",
    "当",
    "由",
)
_UNCERTAINTY_MARKERS = (
    "可能",
    "或许",
    "预计",
    "有意",
    "考虑",
    "接近",
    "报价",
    "谈判",
    "讨论",
    "兴趣",
    "寻求",
    "探索",
    "计划",
    "有望",
    "未最终确定",
    "尚未达成",
    "传闻",
    "据报道",
    "据称",
    "据悉",
    "尚未",
    "未确认",
    "potential",
    "reported",
    "rumor",
    "rumour",
    "could",
    "may",
    "likely",
    "interested",
    "interest",
    "in talks",
    "negotiation",
    "negotiations",
    "bid",
    "offer",
    "set to",
)
_TRANSACTION_PATTERN = re.compile(
    r"转会|签约|续约|租借|报价|谈判|合同|解约|出售|收购|投资|股权|所有权|"
    r"年薪|工资|身价|费用|"
    r"\b(?:transfer\w*|contract\w*|loan|bid|offer|negotiat\w*|sale|sell|sold|"
    r"investment|stake|takeover|acquisition|salary|wage|fee)\b",
    re.I,
)
_LEGAL_PATTERN = re.compile(
    r"调查|诉讼|起诉|指控|法院|犯罪|欺诈|歧视|虐待|"
    r"\b(?:investigation|lawsuit|legal action|allegation|charged|court|fraud|"
    r"discrimination|abuse)\b",
    re.I,
)
_DISCIPLINE_PATTERN = re.compile(
    r"停赛|禁赛|纪律处分|处罚|上诉|红牌争议|腐败|操纵|违规|"
    r"\b(?:suspension|banned?|disciplinary|appeal|overturn\w*|corrupt\w*|"
    r"misconduct|sanction)\b",
    re.I,
)
_SEVERE_HARM_PATTERN = re.compile(
    r"死亡|去世|事故|住院|手术|赛季报销|长期缺阵|重伤|严重伤病|"
    r"十字韧带|昏迷|"
    r"\b(?:died|death|accident|hospitali[sz]\w*|surgery|season-ending|"
    r"long-term injury|serious injury|acl)\b",
    re.I,
)

_REVIEW_SYSTEM_PROMPT = """你是一位严谨的中文体育内容总编，负责检查短视频播报稿是否忠实、完整、清晰且适合口播。

审校原则：
1. source_facts 及其中的 evidence 是唯一的可验证事实依据。analysis_summary.detail_context 是前一步 LLM 生成的分析上下文，不是独立证据，只用于理解文章叙事，且可能被截断。不能因为稿件内容出现在 detail_context 中就默认正确；稿件中的具体事例、引语、数字或因果关系必须能由 source_facts/evidence 支持。detail_context 与 source_facts 冲突时，以 source_facts 为准；source_facts/evidence 都无法支持的内容必须指出。不得用常识补充 source_facts 没有的信息。
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
- analysis_summary.detail_context 只是前一步 LLM 生成的上下文，不是事实证据；修订时只能保留与 source_facts/evidence 一致的具体事例和细节。若 detail_context 与 source_facts 冲突，以 source_facts 为准；不得添加 source_facts/evidence 都没有的信息
- 准确覆盖所有 critical source_facts
- 保留人物、俱乐部、金额、日期、数字、引语归属和不确定性措辞
- 开头固定为“欢迎收听英超每日观察，今天是{date_str}，”
- 结尾固定为“感谢收听，更多内容请关注英超每日观察。”
- 使用自然口语和短句，避免重复
- 标题不超过30个汉字，准确表达协议状态和不确定性，不得夸大
- 只返回 JSON 对象：{{"title_cn": "修订后的标题", "script": "修订后的完整播报稿"}}
- 不解释修改过程"""


@dataclass(frozen=True)
class QualityGateResult:
    passed: bool
    failed_thresholds: tuple[str, ...]


def _parse_json_object(response: str) -> dict:
    try:
        data = loads_llm_json(response)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Failed to parse content review as JSON: {response[:200]}"
        ) from error
    if not isinstance(data, dict):
        raise ValueError("Content review response must be a JSON object")
    return data


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_hash(analyzed: AnalyzedArticle) -> str:
    payload = json.dumps(
        analyzed.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _content_hash(payload)


def _normalize_title(value: object, fallback: str) -> str:
    title = " ".join(str(value or "").split()).strip("\"'“”‘’# ")[:30]
    return title or fallback


def _detail_context(value: str) -> str:
    value = value.strip()
    if len(value) <= DETAIL_CONTEXT_MAX_CHARS:
        return value
    marker = "\n[…detail_context 已截断…]\n"
    available = DETAIL_CONTEXT_MAX_CHARS - len(marker)
    head_length = max(1, available * 2 // 3)
    tail_length = max(1, available - head_length)
    return f"{value[:head_length]}{marker}{value[-tail_length:]}"


def _normalize_match_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff%£€$¥]+", "", value.lower())


def _fact_segments(claim: str) -> list[str]:
    connector_pattern = "|".join(map(re.escape, _FACT_CONNECTORS))
    raw_segments = re.split(rf"(?:{connector_pattern}|[^0-9a-z\u4e00-\u9fff]+)+", claim.lower())
    return [segment for segment in raw_segments if len(segment) >= 2]


def _segment_covered(segment: str, script: str) -> bool:
    if segment in script:
        return True
    if len(segment) < 4:
        return False
    bigrams = [segment[index : index + 2] for index in range(len(segment) - 1)]
    matched = sum(bigram in script for bigram in bigrams)
    return matched >= max(1, round(len(bigrams) * 0.3))


def _fact_is_covered(claim: str, script: str) -> bool:
    normalized_claim = _normalize_match_text(claim)
    if not normalized_claim:
        return True
    if normalized_claim in script:
        return True
    segments = _fact_segments(claim)
    if not segments:
        return True
    covered = sum(_segment_covered(segment, script) for segment in segments)
    return covered >= max(1, (len(segments) + 1) // 2)


def _numeric_markers(value: str) -> set[str]:
    return {
        marker.lower().replace(",", "")
        for marker in re.findall(
            r"(?:[£€$¥]\s*)?\d+(?:,\d{3})*(?:\.\d+)?(?:%|万|亿|m|bn|million|billion)?",
            value.lower(),
        )
    }


def _has_uncertainty_marker(value: str) -> bool:
    normalized = value.lower()
    for marker in _UNCERTAINTY_MARKERS:
        if marker == "may":
            for match in re.finditer(r"\bmay\b", normalized):
                following = normalized[match.end() :].lstrip()
                preceding = normalized[: match.start()].rstrip()
                if re.match(r"\d{1,4}\b", following):
                    continue
                if re.search(r"\b(?:in|on|by|during|from|until)$", preceding):
                    continue
                return True
            continue
        if marker.isascii() and any(character.isalpha() for character in marker):
            if re.search(rf"\b{re.escape(marker)}\b", normalized, re.I):
                return True
        elif marker in normalized:
            return True
    return False


def assess_article_risk(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
) -> tuple[str, ...]:
    reasons: list[str] = []
    title_material = f"{article.title} {analyzed.title_cn}"
    if _TRANSACTION_PATTERN.search(title_material) and _has_uncertainty_marker(
        title_material
    ):
        reasons.append("标题涉及未确认交易或合同")
    if _LEGAL_PATTERN.search(title_material):
        reasons.append("标题涉及法律或调查争议")
    if _DISCIPLINE_PATTERN.search(title_material):
        reasons.append("标题涉及纪律或处罚争议")
    if _SEVERE_HARM_PATTERN.search(title_material):
        reasons.append("标题涉及严重伤害或事故")

    for fact in analyzed.source_facts:
        if fact.importance != "critical":
            continue
        fact_material = f"{fact.category} {fact.claim}"
        suffix = f"（{fact.fact_id}）"
        if _TRANSACTION_PATTERN.search(fact_material) and _has_uncertainty_marker(
            fact.claim
        ):
            reasons.append(f"critical事实涉及未确认交易或合同{suffix}")
        if _LEGAL_PATTERN.search(fact_material):
            reasons.append(f"critical事实涉及法律或调查争议{suffix}")
        if _DISCIPLINE_PATTERN.search(fact_material):
            reasons.append(f"critical事实涉及纪律或处罚争议{suffix}")
        if _SEVERE_HARM_PATTERN.search(fact_material):
            reasons.append(f"critical事实涉及严重伤害或事故{suffix}")
    return tuple(dict.fromkeys(reasons))


def _static_issues(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: str,
) -> list[QualityIssue]:
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
    else:
        normalized_script = _normalize_match_text(script)
        critical_ids = {
            fact.fact_id for fact in analyzed.source_facts if fact.importance == "critical"
        }
        for fact in analyzed.source_facts:
            if _fact_is_covered(fact.claim, normalized_script):
                missing_numbers = _numeric_markers(fact.claim) - _numeric_markers(script)
                if missing_numbers:
                    issues.append(
                        QualityIssue(
                            dimension="factual_accuracy",
                            severity="error" if fact.fact_id in critical_ids else "warning",
                            description=(
                                f"{fact.fact_id} 的数字、金额或比例未在播报稿中保持一致。"
                            ),
                            evidence=fact.claim,
                            suggestion="保留原文中的数字、金额或比例，不要改写或省略。",
                            fact_ids=[fact.fact_id],
                        )
                    )
                if fact.importance == "critical" and _has_uncertainty_marker(fact.claim):
                    if not _has_uncertainty_marker(script):
                        issues.append(
                            QualityIssue(
                                dimension="factual_accuracy",
                                severity="error",
                                description=f"{fact.fact_id} 的不确定性语气在播报稿中丢失。",
                                evidence=fact.claim,
                                suggestion="保留可能、据报道、尚未确认等不确定性表达。",
                                fact_ids=[fact.fact_id],
                            )
                        )
            elif fact.importance == "critical":
                issues.append(
                    QualityIssue(
                        dimension="completeness",
                        severity="error",
                        description=f"{fact.fact_id} 这条 critical 原文事实没有被播报稿充分覆盖。",
                        evidence=fact.claim,
                        suggestion="补回该事实的核心人物、事件、数字和状态。",
                        fact_ids=[fact.fact_id],
                    )
                )
            else:
                issues.append(
                    QualityIssue(
                        dimension="completeness",
                        severity="warning",
                        description=f"{fact.fact_id} 这条 supporting 原文事实可能未被覆盖。",
                        evidence=fact.claim,
                        suggestion="如内容需要，补充该背景事实。",
                        fact_ids=[fact.fact_id],
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


def _static_scores(issues: list[QualityIssue]) -> QualityScores:
    values = {
        "factual_accuracy": 100,
        "completeness": 100,
        "structure": 100,
        "spoken_style": 100,
        "title_quality": 100,
        "overall": 100,
    }
    for issue in issues:
        if issue.severity == "warning":
            continue
        score = 0 if issue.severity == "blocker" else 70
        if issue.dimension in values:
            values[issue.dimension] = min(values[issue.dimension], score)
        values["overall"] = min(values["overall"], score)
    return QualityScores(**values)


def _build_static_review(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
    risk_reasons: tuple[str, ...],
) -> ContentReview:
    issues = _static_issues(article, analyzed, script.text)
    review = ContentReview(
        passed=False,
        scores=_static_scores(issues),
        issues=issues,
        summary="低风险文章使用本地事实与格式门禁，未调用 LLM 审校。",
        review_mode="static",
        risk_level="low",
        risk_reasons=list(risk_reasons),
        source_sha256=_content_hash(article.full_text),
        title_sha256=_content_hash(analyzed.title_cn),
        script_sha256=_content_hash(script.text),
    )
    gate = evaluate_quality_gate(review)
    review.passed = gate.passed
    if gate.failed_thresholds:
        failed = "、".join(gate.failed_thresholds)
        review.summary = f"{review.summary} 未达到质量阈值：{failed}。"
    if not issues:
        review.summary = f"{review.summary} 本地检查通过。"
    return review


def _should_auto_rewrite(
    review: ContentReview,
    analyzed: AnalyzedArticle,
) -> bool:
    critical_ids = {
        fact.fact_id for fact in analyzed.source_facts if fact.importance == "critical"
    }
    for issue in review.issues:
        if issue.severity not in {"error", "blocker"}:
            continue
        if issue.dimension == "factual_accuracy":
            return True
        if issue.dimension == "completeness" and critical_ids.intersection(
            issue.fact_ids
        ):
            return True
    return False


def _static_rewrite_issues(
    review: ContentReview,
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
) -> list[QualityIssue] | None:
    if any(
        getattr(review.scores, dimension) < threshold
        for dimension, threshold in _SCORE_THRESHOLDS.items()
    ):
        return None
    static_issues = _static_issues(article, analyzed, script.text)
    numeric_issues = [
        issue
        for issue in static_issues
        if (
            issue.dimension == "factual_accuracy"
            and "数字、金额或比例" in issue.description
        )
    ]
    numeric_issue_keys = {
        json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for issue in numeric_issues
    }
    blocking_issues = [
        issue for issue in review.issues if issue.severity in {"error", "blocker"}
    ]
    if not blocking_issues or not numeric_issues:
        return None
    if any(
        json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        not in numeric_issue_keys
        for issue in blocking_issues
    ):
        return None
    return numeric_issues


def _build_static_followup_review(
    previous_review: ContentReview,
    previous_static_issues: list[QualityIssue],
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
) -> ContentReview:
    previous_static_issue_keys = {
        json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for issue in previous_static_issues
    }
    preserved_issues = [
        issue
        for issue in previous_review.issues
        if json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        not in previous_static_issue_keys
    ]
    followup = previous_review.model_copy(
        update={
            "passed": False,
            "issues": [*preserved_issues, *_static_issues(article, analyzed, script.text)],
            "summary": (
                f"{previous_review.summary.rstrip()} "
                "修订后已通过本地规则复核，未再次调用 LLM。"
            ).strip(),
            "review_mode": "static",
            "source_sha256": _content_hash(article.full_text),
            "title_sha256": _content_hash(analyzed.title_cn),
            "script_sha256": _content_hash(script.text),
        }
    )
    gate = evaluate_quality_gate(followup)
    followup.passed = gate.passed
    if gate.failed_thresholds:
        failed = "、".join(gate.failed_thresholds)
        followup.summary = f"{followup.summary} 未达到质量阈值：{failed}。"
    return followup


def _can_resume_quality_report(
    report: ContentQualityReport,
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    initial_script: PodcastScript,
) -> bool:
    return (
        report.source_sha256 == _content_hash(article.full_text)
        and report.analysis_sha256 == _analysis_hash(analyzed)
        and report.initial_script_sha256 == _content_hash(initial_script.text)
        and report.review_prompt_version == REVIEW_PROMPT_VERSION
        and report.rewrite_prompt_version == REWRITE_PROMPT_VERSION
    )


def review_content(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    script: PodcastScript,
    llm: LLMClient,
) -> ContentReview:
    risk_reasons = assess_article_risk(article, analyzed)
    if not risk_reasons:
        return _build_static_review(article, analyzed, script, risk_reasons)

    payload = {
        "source": {
            "title": article.title,
            "url": article.link,
        },
        "source_facts": [fact.model_dump(mode="json") for fact in analyzed.source_facts],
        "analysis_summary": {
            "article_type": analyzed.article_type,
            "overview": analyzed.overview,
            "detail_context": _detail_context(analyzed.detail),
            "key_people_and_data": analyzed.key_people_and_data,
            "impact": analyzed.impact,
        },
        "title_cn": analyzed.title_cn,
        "script": script.text,
    }
    response = llm.complete(
        _REVIEW_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
        stage="review-content",
        prompt_version=REVIEW_PROMPT_VERSION,
    )
    data = _parse_json_object(response)
    data.setdefault("passed", False)
    data.setdefault("issues", [])
    data.setdefault("summary", "")
    data["review_mode"] = "llm"
    data["risk_level"] = "high"
    data["risk_reasons"] = list(risk_reasons)
    data["source_sha256"] = _content_hash(article.full_text)
    data["title_sha256"] = _content_hash(analyzed.title_cn)
    data["script_sha256"] = _content_hash(script.text)
    try:
        review = ContentReview.model_validate(data)
    except ValidationError as error:
        raise ValueError(
            f"Invalid content review response: {response[:200]}"
        ) from error

    review.issues.extend(_static_issues(article, analyzed, script.text))
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
        },
        "source_facts": [fact.model_dump(mode="json") for fact in analyzed.source_facts],
        "analysis_summary": {
            "article_type": analyzed.article_type,
            "overview": analyzed.overview,
            "detail_context": _detail_context(analyzed.detail),
            "key_people_and_data": analyzed.key_people_and_data,
            "impact": analyzed.impact,
        },
        "current_script": script.text,
        "review": review.model_dump(mode="json"),
    }
    response = llm.complete(
        _REWRITE_SYSTEM_PROMPT.format(date_str=date_str or "今天"),
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
        stage="finalize-content",
        prompt_version=REWRITE_PROMPT_VERSION,
    )
    data = _parse_json_object(response)
    title = _normalize_title(data.get("title_cn"), analyzed.title_cn)
    script_value = data.get("script") or data.get("script_text")
    if not isinstance(script_value, str) or not script_value.strip():
        raise ValueError(f"Content rewrite response is missing script: {response[:200]}")
    return title, PodcastScript(text=script_value.strip())


def finalize_content(
    article: ScrapedArticle,
    analyzed: AnalyzedArticle,
    initial_script: PodcastScript,
    initial_review: ContentReview,
    llm: LLMClient,
    *,
    date_str: str,
    max_revisions: int | None = None,
    previous_report: ContentQualityReport | None = None,
) -> tuple[str, PodcastScript, ContentQualityReport]:
    resume_previous = previous_report is not None and _can_resume_quality_report(
        previous_report,
        article,
        analyzed,
        initial_script,
    )
    if resume_previous:
        current_title = previous_report.final_title
        current_script = PodcastScript(text=previous_report.final_script)
        current_review = previous_report.final_review
        revisions = list(previous_report.revisions)
        report_initial_title = previous_report.initial_title
        report_initial_script = previous_report.initial_script
        report_initial_review = previous_report.initial_review
        revision_limit = (
            previous_report.max_revisions
            if max_revisions is None
            else max(max_revisions, len(revisions))
        )
    else:
        current_title = analyzed.title_cn
        current_script = initial_script
        current_review = initial_review
        revisions = []
        report_initial_title = analyzed.title_cn
        report_initial_script = initial_script.text
        report_initial_review = initial_review
        revision_limit = MAX_REVISIONS if max_revisions is None else max_revisions

    if not resume_previous and current_review.passed and (
        current_review.source_sha256 != _content_hash(article.full_text)
        or current_review.title_sha256 != _content_hash(current_title)
        or current_review.script_sha256 != _content_hash(current_script.text)
    ):
        current_review = review_content(article, analyzed, current_script, llm)

    for attempt in range(len(revisions) + 1, revision_limit + 1):
        if current_review.passed or not _should_auto_rewrite(current_review, analyzed):
            break
        current_analysis = analyzed.model_copy(update={"title_cn": current_title})
        previous_static_issues = _static_rewrite_issues(
            current_review,
            article,
            current_analysis,
            current_script,
        )
        current_title, current_script = rewrite_content(
            article,
            current_analysis,
            current_script,
            current_review,
            llm,
            date_str=date_str,
        )
        current_analysis = analyzed.model_copy(update={"title_cn": current_title})
        if previous_static_issues is not None:
            current_review = _build_static_followup_review(
                current_review,
                previous_static_issues,
                article,
                current_analysis,
                current_script,
            )
        else:
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
        initial_title=report_initial_title,
        initial_script=report_initial_script,
        initial_review=report_initial_review,
        revisions=revisions,
        final_title=current_title,
        final_script=current_script.text,
        final_review=current_review,
        passed=current_review.passed,
        max_revisions=revision_limit,
        source_sha256=_content_hash(article.full_text),
        analysis_sha256=_analysis_hash(analyzed),
        initial_script_sha256=_content_hash(initial_script.text),
        review_prompt_version=REVIEW_PROMPT_VERSION,
        rewrite_prompt_version=REWRITE_PROMPT_VERSION,
    )
    return current_title, current_script, report
