import json
from unittest.mock import MagicMock

from src.content_quality import (
    DETAIL_CONTEXT_MAX_CHARS,
    finalize_content,
    review_content,
)
from src.models import (
    AnalyzedArticle,
    ContentQualityReport,
    ContentReview,
    PodcastScript,
    QualityIssue,
    QualityScores,
    ScrapedArticle,
    SourceFact,
)


OPENING = "欢迎收听英超每日观察，今天是2026年8月18日，"
ENDING = "感谢收听，更多内容请关注英超每日观察。"


def _script(target_length: int = 880) -> PodcastScript:
    body_length = target_length - len(OPENING) - len(ENDING)
    body = ("阿森纳在主场取胜，球队依靠稳定防守和关键进球掌控比赛。" * 40)[
        :body_length
    ]
    return PodcastScript(text=f"{OPENING}{body}{ENDING}")


def _article() -> ScrapedArticle:
    return ScrapedArticle(
        title="Arsenal win",
        link="https://example.com/article",
        full_text="Arsenal won at home with a decisive goal and strong defending.",
    )


def _high_risk_article() -> ScrapedArticle:
    return ScrapedArticle(
        title="Arsenal transfer fee reported",
        link="https://example.com/article",
        full_text="Arsenal are considering a transfer fee of £50 million, according to reports.",
    )


def _analyzed() -> AnalyzedArticle:
    return AnalyzedArticle(
        title_cn="阿森纳主场取胜",
        title_original="Arsenal win",
        article_type="赛后分析",
        overview="阿森纳依靠关键进球取胜。",
        detail="阿森纳在主场控制比赛并完成零封。",
        key_people_and_data="一粒关键进球。",
        impact="球队延续良好状态。",
        link="https://example.com/article",
        source_facts=[
            SourceFact(
                fact_id="F001",
                claim="阿森纳在主场取胜。",
                evidence="Arsenal won at home.",
                category="比赛",
                importance="critical",
            )
        ],
    )


def _review_response(*, overall: int = 92, issues: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "passed": True,
            "scores": {
                "factual_accuracy": 95,
                "completeness": 90,
                "structure": 90,
                "spoken_style": 90,
                "title_quality": 90,
                "overall": overall,
            },
            "issues": issues or [],
            "summary": "事实准确，结构完整。",
        },
        ensure_ascii=False,
    )


def _rewrite_response(
    *,
    title: str = "阿森纳主场力克对手",
    script: str | None = None,
) -> str:
    return json.dumps(
        {"title_cn": title, "script": script or _script().text},
        ensure_ascii=False,
    )


def _failed_review() -> ContentReview:
    return ContentReview(
        passed=False,
        scores=QualityScores(
            factual_accuracy=70,
            completeness=70,
            structure=80,
            spoken_style=80,
            title_quality=80,
            overall=72,
        ),
        issues=[
            QualityIssue(
                dimension="completeness",
                severity="error",
                description="遗漏关键事实。",
                fact_ids=["F001"],
            )
        ],
        summary="需要补充关键事实。",
    )


def test_review_passes_when_scores_and_static_rules_pass():
    llm = MagicMock()
    llm.complete.return_value = _review_response()

    result = review_content(_high_risk_article(), _analyzed(), _script(), llm)

    assert result.passed is True
    assert result.scores.overall == 92
    assert len(result.source_sha256) == 64
    assert len(result.title_sha256) == 64
    assert len(result.script_sha256) == 64
    request = json.loads(llm.complete.call_args.args[1])
    system_prompt = llm.complete.call_args.args[0]
    assert request["source_facts"][0]["fact_id"] == "F001"
    assert request["title_cn"] == "阿森纳主场取胜"
    assert "full_text" not in request["source"]
    assert result.review_mode == "llm"
    assert result.risk_level == "high"
    assert "节目制作元数据" in system_prompt


def test_review_payload_includes_analysis_detail_as_non_authoritative_context():
    detail = "球迷们甚至能对厄德高踢到自己另一只脚导致球滑稽入网的失误发笑。"
    analyzed = _analyzed().model_copy(update={"detail": detail})
    script = PodcastScript(text=f"{OPENING}阿森纳轻松取胜。{detail}{ENDING}")
    llm = MagicMock()
    llm.complete.return_value = _review_response()

    review_content(_high_risk_article(), analyzed, script, llm)

    request = json.loads(llm.complete.call_args.args[1])
    system_prompt = llm.complete.call_args.args[0]
    assert request["analysis_summary"]["detail_context"] == detail
    assert "不是独立证据" in system_prompt
    assert "不能因为稿件内容出现在 detail_context 中就默认正确" in system_prompt
    assert "source_facts/evidence" in system_prompt


def test_rewrite_payload_includes_analysis_detail():
    detail = "球迷们甚至能对厄德高踢到自己另一只脚导致球滑稽入网的失误发笑。"
    analyzed = _analyzed().model_copy(update={"detail": detail})
    llm = MagicMock()
    llm.complete.side_effect = [
        _rewrite_response(),
        _review_response(),
    ]

    finalize_content(
        _high_risk_article(),
        analyzed,
        _script(),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
    )

    rewrite_call = llm.complete.call_args_list[0]
    request = json.loads(rewrite_call.args[1])
    system_prompt = rewrite_call.args[0]
    assert rewrite_call.kwargs["stage"] == "finalize-content"
    assert request["analysis_summary"]["detail_context"] == detail
    assert "不是事实证据" in system_prompt
    assert "与 source_facts 冲突" in system_prompt


def test_review_prompt_prioritizes_source_facts_over_conflicting_detail():
    detail = "孔萨以4000万英镑加盟阿森纳。"
    analyzed = _analyzed().model_copy(update={"detail": detail})
    llm = MagicMock()
    llm.complete.return_value = _review_response()

    review_content(
        _high_risk_article(),
        analyzed,
        _script(),
        llm,
    )

    system_prompt = llm.complete.call_args.args[0]
    assert "source_facts 及其中的 evidence 是唯一的可验证事实依据" in system_prompt
    assert "以 source_facts 为准" in system_prompt


def test_detail_context_is_bounded_for_llm_requests():
    detail = "开头重要细节。" + ("中间分析内容。" * 500) + "结尾重要细节。"
    analyzed = _analyzed().model_copy(update={"detail": detail})
    llm = MagicMock()
    llm.complete.return_value = _review_response()

    review_content(_high_risk_article(), analyzed, _script(), llm)

    request = json.loads(llm.complete.call_args.args[1])
    context = request["analysis_summary"]["detail_context"]
    assert len(context) <= DETAIL_CONTEXT_MAX_CHARS
    assert context.startswith("开头重要细节。")
    assert context.endswith("结尾重要细节。")
    assert "detail_context 已截断" in context


def test_review_rejects_low_scores_even_if_llm_marks_passed():
    llm = MagicMock()
    llm.complete.return_value = _review_response(overall=70)

    result = review_content(_high_risk_article(), _analyzed(), _script(), llm)

    assert result.passed is False
    assert "overall" in result.summary


def test_review_static_rules_reject_invalid_program_format():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    invalid_script = PodcastScript(text="这是一篇没有固定开头和结尾的短稿。")

    result = review_content(_article(), _analyzed(), invalid_script, llm)

    assert result.passed is False
    descriptions = {issue.description for issue in result.issues}
    assert "播报稿未使用规定的节目开头。" in descriptions
    assert "播报稿未使用规定的节目结尾。" in descriptions


def test_finalize_rewrites_and_reviews_until_quality_gate_passes():
    llm = MagicMock()
    revised_script = _script().text
    revised_title = "阿森纳主场力克对手"
    llm.complete.side_effect = [
        _rewrite_response(title=revised_title, script=revised_script),
        _review_response(),
    ]

    final_title, final_script, report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        PodcastScript(text="不合格初稿"),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
    )

    assert final_title == revised_title
    assert final_script.text == revised_script
    assert report.passed is True
    assert len(report.revisions) == 1
    assert report.revisions[0].review.passed is True
    assert llm.complete.call_count == 2


def test_finalize_uses_static_followup_for_numeric_issue():
    llm = MagicMock()
    article = ScrapedArticle(
        title="Arsenal transfer fee reported",
        link="https://example.com/article",
        full_text="Arsenal are reported to be considering a transfer for £50 million.",
    )
    analyzed = _analyzed().model_copy(update={
        "title_cn": "阿森纳完成5000万英镑转会",
        "article_type": "转会动态",
        "source_facts": [
            SourceFact(
                fact_id="F001",
                claim="阿森纳以5000万英镑完成转会。",
                evidence="Arsenal completed the transfer for £50 million.",
                category="转会",
                importance="critical",
            )
        ],
    })
    initial_script = PodcastScript(text=f"{OPENING}阿森纳完成转会。{ENDING}")
    revised_script = PodcastScript(
        text=f"{OPENING}阿森纳以5000万英镑完成转会。{ENDING}"
    )
    llm.complete.side_effect = [
        _review_response(),
        _rewrite_response(title=analyzed.title_cn, script=revised_script.text),
    ]
    initial_review = review_content(article, analyzed, initial_script, llm)

    final_title, final_script, report = finalize_content(
        article,
        analyzed,
        initial_script,
        initial_review,
        llm,
        date_str="2026年8月18日",
    )

    assert final_title == analyzed.title_cn
    assert final_script.text == revised_script.text
    assert report.passed is True
    assert report.final_review.review_mode == "static"
    assert report.final_review.risk_level == "high"
    assert "未再次调用 LLM" in report.final_review.summary
    assert llm.complete.call_count == 2
    assert llm.complete.call_args_list[-1].kwargs["stage"] == "finalize-content"


def test_finalize_keeps_llm_followup_when_numeric_review_score_fails():
    llm = MagicMock()
    article = ScrapedArticle(
        title="Arsenal transfer fee reported",
        link="https://example.com/article",
        full_text="Arsenal are reported to be considering a transfer for £50 million.",
    )
    analyzed = _analyzed().model_copy(update={
        "title_cn": "阿森纳规划夏窗阵容",
        "article_type": "转会动态",
        "source_facts": [
            SourceFact(
                fact_id="F001",
                claim="据报道，阿森纳正考虑一笔5000万英镑的转会。",
                evidence="Arsenal are reported to be considering a £50 million transfer.",
                category="转会",
                importance="critical",
            )
        ],
    })
    initial_script = PodcastScript(
        text=f"{OPENING}据报道，阿森纳正考虑一笔转会。{ENDING}"
    )
    initial_review = ContentReview(
        passed=False,
        scores=QualityScores(
            factual_accuracy=70,
            completeness=90,
            structure=90,
            spoken_style=90,
            title_quality=90,
            overall=80,
        ),
        issues=[
            QualityIssue(
                dimension="factual_accuracy",
                severity="error",
                description="F001 的数字、金额或比例未在播报稿中保持一致。",
                evidence="据报道，阿森纳正考虑一笔5000万英镑的转会。",
                suggestion="保留原文中的数字、金额或比例，不要改写或省略。",
                fact_ids=["F001"],
            )
        ],
        review_mode="llm",
        risk_level="high",
        source_sha256="source",
        title_sha256="title",
        script_sha256="script",
    )
    revised_script = PodcastScript(
        text=f"{OPENING}据报道，阿森纳正考虑一笔5000万英镑的转会。{ENDING}"
    )
    llm.complete.side_effect = [
        _rewrite_response(
            title=analyzed.title_cn,
            script=revised_script.text,
        ),
        _review_response(),
    ]

    _, _, report = finalize_content(
        article,
        analyzed,
        initial_script,
        initial_review,
        llm,
        date_str="2026年8月18日",
    )

    assert report.final_review.review_mode == "llm"
    assert llm.complete.call_count == 2
    assert llm.complete.call_args_list[-1].kwargs["stage"] == "review-content"


def test_finalize_preserves_review_history_when_gate_never_passes():
    llm = MagicMock()
    revised_script = _script().text
    failing_response = _review_response(
        issues=[
            {
                "dimension": "factual_accuracy",
                "severity": "error",
                "description": "数字与原文不一致。",
                "evidence": "错误数字",
                "suggestion": "按原文修正。",
                "fact_ids": ["F001"],
            }
        ]
    )
    llm.complete.side_effect = [
        _rewrite_response(script=revised_script),
        failing_response,
        _rewrite_response(script=revised_script),
        failing_response,
    ]

    _, _, report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        PodcastScript(text="不合格初稿"),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
        max_revisions=2,
    )

    assert report.passed is False
    assert len(report.revisions) == 2
    assert all(not revision.review.passed for revision in report.revisions)


def test_finalize_rechecks_a_stale_passing_review():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    stale_review = ContentReview(
        passed=True,
        scores=QualityScores(
            factual_accuracy=95,
            completeness=90,
            structure=90,
            spoken_style=90,
            title_quality=90,
            overall=92,
        ),
        summary="旧审校报告",
        source_sha256="old-source",
        script_sha256="old-script",
    )

    final_title, final_script, report = finalize_content(
        _article(),
        _analyzed(),
        _script(),
        stale_review,
        llm,
        date_str="2026年8月18日",
    )

    assert report.passed is True
    assert final_title == _analyzed().title_cn
    assert final_script.text == _script().text
    assert report.final_review.script_sha256 != "old-script"
    llm.complete.assert_not_called()
    assert report.final_review.review_mode == "static"


def test_low_risk_article_uses_static_gate_without_llm():
    llm = MagicMock()

    result = review_content(_article(), _analyzed(), _script(), llm)

    assert result.passed is True
    assert result.review_mode == "static"
    assert result.risk_level == "low"
    llm.complete.assert_not_called()


def test_static_gate_does_not_reject_script_length():
    llm = MagicMock()
    short_script = PodcastScript(
        text=f"{OPENING}阿森纳在主场取胜。{ENDING}"
    )

    result = review_content(_article(), _analyzed(), short_script, llm)

    assert result.passed is True
    assert result.review_mode == "static"
    llm.complete.assert_not_called()


def test_month_name_does_not_trigger_high_risk_review():
    llm = MagicMock()
    article = _article().model_copy(update={"full_text": "Arsenal won at home in May."})

    result = review_content(article, _analyzed(), _script(), llm)

    assert result.review_mode == "static"
    llm.complete.assert_not_called()


def test_background_risk_words_do_not_trigger_llm_review():
    llm = MagicMock()
    article = _article().model_copy(update={
        "full_text": (
            "Arsenal won at home. The report also mentioned an old transfer fee, "
            "a referee decision and a previous injury in the background."
        )
    })

    result = review_content(article, _analyzed(), _script(), llm)

    assert result.review_mode == "static"
    assert result.risk_level == "low"
    llm.complete.assert_not_called()


def test_confirmed_transfer_with_fee_uses_static_review():
    llm = MagicMock()
    article = ScrapedArticle(
        title="Arsenal complete £50 million transfer",
        link="https://example.com/article",
        full_text="Arsenal completed the transfer for £50 million.",
    )
    analyzed = _analyzed().model_copy(update={
        "title_cn": "阿森纳完成5000万英镑转会",
        "article_type": "转会动态",
        "source_facts": [
            SourceFact(
                fact_id="F001",
                claim="阿森纳以5000万英镑完成转会。",
                evidence="Arsenal completed the transfer for £50 million.",
                category="转会",
                importance="critical",
            )
        ],
    })
    script = PodcastScript(
        text=f"{OPENING}阿森纳以5000万英镑完成转会。{ENDING}"
    )

    result = review_content(article, analyzed, script, llm)

    assert result.review_mode == "static"
    assert result.risk_level == "low"
    llm.complete.assert_not_called()


def test_supporting_uncertain_transfer_does_not_trigger_llm_review():
    llm = MagicMock()
    analyzed = _analyzed().model_copy(update={
        "source_facts": [
            *_analyzed().source_facts,
            SourceFact(
                fact_id="F002",
                claim="阿森纳据报道可能在夏窗考虑另一笔转会。",
                evidence="Arsenal could consider another summer transfer.",
                category="转会",
                importance="supporting",
            ),
        ]
    })

    result = review_content(_article(), analyzed, _script(), llm)

    assert result.review_mode == "static"
    assert result.risk_level == "low"
    llm.complete.assert_not_called()


def test_critical_uncertain_transfer_still_uses_llm_review():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    article = ScrapedArticle(
        title="Arsenal summer squad planning",
        link="https://example.com/article",
        full_text="Arsenal are reported to be considering a £50 million transfer.",
    )
    analyzed = _analyzed().model_copy(update={
        "title_cn": "阿森纳规划夏窗阵容",
        "article_type": "转会动态",
        "source_facts": [
            SourceFact(
                fact_id="F001",
                claim="据报道，阿森纳正考虑一笔5000万英镑的转会。",
                evidence="Arsenal are reported to be considering a £50 million transfer.",
                category="转会",
                importance="critical",
            )
        ],
    })
    script = PodcastScript(
        text=f"{OPENING}据报道，阿森纳正考虑一笔5000万英镑的转会。{ENDING}"
    )

    result = review_content(article, analyzed, script, llm)

    assert result.review_mode == "llm"
    assert result.risk_level == "high"
    assert result.risk_reasons == ["critical事实涉及未确认交易或合同（F001）"]
    llm.complete.assert_called_once()


def test_critical_legal_dispute_still_uses_llm_review():
    llm = MagicMock()
    llm.complete.return_value = _review_response()
    article = ScrapedArticle(
        title="Club governance update",
        link="https://example.com/article",
        full_text="The club is facing a fraud investigation.",
    )
    analyzed = _analyzed().model_copy(update={
        "title_cn": "俱乐部治理进展",
        "article_type": "新闻报道",
        "source_facts": [
            SourceFact(
                fact_id="F001",
                claim="俱乐部正面临欺诈调查。",
                evidence="The club is facing a fraud investigation.",
                category="法律",
                importance="critical",
            )
        ],
    })
    script = PodcastScript(
        text=f"{OPENING}俱乐部正面临欺诈调查。{ENDING}"
    )

    result = review_content(article, analyzed, script, llm)

    assert result.review_mode == "llm"
    assert result.risk_reasons == ["critical事实涉及法律或调查争议（F001）"]
    llm.complete.assert_called_once()


def test_missing_fact_ids_do_not_trigger_an_automatic_rewrite():
    llm = MagicMock()
    analyzed = _analyzed().model_copy(update={"source_facts": []})
    initial_review = review_content(_article(), analyzed, _script(), llm)

    finalize_content(
        _article(),
        analyzed,
        _script(),
        initial_review,
        llm,
        date_str="2026年8月18日",
    )

    llm.complete.assert_not_called()


def test_default_finalize_performs_at_most_one_revision():
    llm = MagicMock()
    revised_script = _script().text
    failing_response = _review_response(
        issues=[
            {
                "dimension": "factual_accuracy",
                "severity": "error",
                "description": "数字与原文不一致。",
                "evidence": "错误数字",
                "suggestion": "按原文修正。",
                "fact_ids": ["F001"],
            }
        ]
    )
    llm.complete.side_effect = [
        _rewrite_response(script=revised_script),
        failing_response,
    ]

    _, _, report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        PodcastScript(text="不合格初稿"),
        _failed_review(),
        llm,
        date_str="2026年8月18日",
    )

    assert report.passed is False
    assert len(report.revisions) == 1
    assert llm.complete.call_count == 2


def test_finalize_reuses_persisted_revision_budget():
    llm = MagicMock()
    failing_response = _review_response(
        issues=[
            {
                "dimension": "factual_accuracy",
                "severity": "error",
                "description": "数字与原文不一致。",
                "evidence": "错误数字",
                "suggestion": "按原文修正。",
                "fact_ids": ["F001"],
            }
        ]
    )
    llm.complete.side_effect = [
        _rewrite_response(script=_script().text),
        failing_response,
    ]
    initial_script = PodcastScript(text="不合格初稿")
    initial_review = _failed_review()

    _, _, first_report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        initial_script,
        initial_review,
        llm,
        date_str="2026年8月18日",
    )
    persisted_report = ContentQualityReport.model_validate(
        first_report.model_dump(mode="json")
    )
    second_llm = MagicMock()

    final_title, final_script, second_report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        initial_script,
        initial_review,
        second_llm,
        date_str="2026年8月18日",
        previous_report=persisted_report,
    )

    assert second_report.passed is False
    assert second_report.revision_budget_used == 1
    assert second_report.revision_budget_remaining == 0
    assert second_report.revision_budget_exhausted is True
    assert len(second_report.revisions) == 1
    assert final_title == first_report.final_title
    assert final_script.text == first_report.final_script
    second_llm.complete.assert_not_called()


def test_finalize_resets_revision_budget_when_inputs_change():
    first_llm = MagicMock()
    first_llm.complete.side_effect = [
        _rewrite_response(script=_script().text),
        _review_response(
            issues=[
                {
                    "dimension": "factual_accuracy",
                    "severity": "error",
                    "description": "数字与原文不一致。",
                    "evidence": "错误数字",
                    "suggestion": "按原文修正。",
                    "fact_ids": ["F001"],
                }
            ]
        ),
    ]
    _, _, previous_report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        PodcastScript(text="第一份不合格初稿"),
        _failed_review(),
        first_llm,
        date_str="2026年8月18日",
    )
    second_llm = MagicMock()
    second_llm.complete.side_effect = [
        _rewrite_response(script=_script().text),
        _review_response(),
    ]

    _, _, report = finalize_content(
        _high_risk_article(),
        _analyzed(),
        PodcastScript(text="第二份已经修改的初稿"),
        _failed_review(),
        second_llm,
        date_str="2026年8月18日",
        previous_report=previous_report,
    )

    assert report.passed is True
    assert report.revision_budget_used == 1
    assert report.revision_budget_remaining == 0
    assert len(report.revisions) == 1
    assert second_llm.complete.call_count == 2
